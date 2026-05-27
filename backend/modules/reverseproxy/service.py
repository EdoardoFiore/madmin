"""
Reverse Proxy Module - Service Layer

Renders nginx configs from DB state, writes them to disk under madmin-* prefix,
manages access lists (htpasswd + IP rules), and drives certbot for Let's Encrypt.
"""
import os
import re
import subprocess
import logging
import ipaddress
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import (
    RevproxyHost, RevproxyHostDomain,
    RevproxyAccessList, RevproxyAccessListAuth, RevproxyAccessListRule,
    RevproxyCertificate,
)

logger = logging.getLogger(__name__)

# --- Paths ---
NGINX_SITES_AVAILABLE = Path("/etc/nginx/sites-available")
NGINX_SITES_ENABLED = Path("/etc/nginx/sites-enabled")
MADMIN_REVPROXY_DIR = Path("/etc/nginx/madmin-revproxy")
HTPASSWD_DIR = MADMIN_REVPROXY_DIR / "htpasswd"
SNIPPETS_DIR = MADMIN_REVPROXY_DIR / "snippets"
ACME_WEBROOT = Path("/var/www/madmin-acme")
SENTINEL_DIR = Path("/etc/madmin/reverseproxy")
SENTINEL_FILE = SENTINEL_DIR / ".disabled-due-to-conflict"
LETSENCRYPT_LIVE = Path("/etc/letsencrypt/live")
RENEWAL_HOOK = Path("/etc/letsencrypt/renewal-hooks/deploy/madmin-revproxy-reload.sh")

FILE_PREFIX = "madmin-"
PROXY_FILE_PREFIX = "madmin-proxy-"
ACME_FILE = "madmin-acme.conf"

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_jinja = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
    keep_trailing_newline=True,
)


# ============================================================================
# Sentinel (conflict marker)
# ============================================================================

def is_blocked() -> Tuple[bool, str]:
    """Return (True, reason) if the module is blocked by a port conflict."""
    if SENTINEL_FILE.exists():
        try:
            return True, SENTINEL_FILE.read_text().strip()
        except Exception:
            return True, "Conflitto porte 80/443 (dettagli non leggibili)"
    return False, ""


def write_sentinel(reason: str) -> None:
    SENTINEL_DIR.mkdir(parents=True, exist_ok=True)
    SENTINEL_FILE.write_text(reason)


def clear_sentinel() -> None:
    try:
        SENTINEL_FILE.unlink()
    except FileNotFoundError:
        pass


# ============================================================================
# Preflight (port conflict check)
# ============================================================================

def _port_in_spec(port_spec: str, target: int) -> bool:
    """True if `target` is in port_spec like '80', '80,443', '80:90'."""
    if not port_spec:
        return False
    for chunk in str(port_spec).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            try:
                lo, hi = chunk.split(":", 1)
                if int(lo) <= target <= int(hi):
                    return True
            except ValueError:
                continue
        else:
            try:
                if int(chunk) == target:
                    return True
            except ValueError:
                continue
    return False


async def _check_dnat_conflicts(session: AsyncSession) -> List[str]:
    """DB DNAT rules on 80/443 that would collide with the module."""
    from core.firewall.models import MachineFirewallRule

    conflicts: List[str] = []
    result = await session.execute(
        select(MachineFirewallRule).where(
            MachineFirewallRule.enabled == True,  # noqa: E712
            MachineFirewallRule.chain == "PREROUTING",
            MachineFirewallRule.action == "DNAT",
        )
    )
    for rule in result.scalars().all():
        for p in (80, 443):
            if _port_in_spec(rule.port or "", p):
                conflicts.append(
                    f"Regola firewall DNAT (id {rule.id}) usa la porta {p} "
                    f"in PREROUTING → {rule.to_destination or '?'}"
                )
                break
    return conflicts


def _check_nginx_conflicts() -> List[str]:
    """Parse `nginx -T` to find non-madmin listen 80/443 directives."""
    conflicts: List[str] = []
    try:
        result = subprocess.run(
            ["nginx", "-T"], capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            # nginx not running or config broken — not a conflict per se
            return conflicts
        text = result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return conflicts

    current_file = "<unknown>"
    for raw in text.splitlines():
        line = raw.strip()
        # `# configuration file /etc/nginx/sites-enabled/foo.conf:`
        m = re.match(r"#\s*configuration file\s+(\S+):", line)
        if m:
            current_file = m.group(1)
            continue
        # Skip files managed by this module
        fname = Path(current_file).name
        if fname.startswith(FILE_PREFIX):
            continue
        if "/madmin-revproxy/" in current_file:
            continue
        # Match `listen 80 ...;` or `listen [::]:80 ...;` (also ssl on 443)
        lm = re.match(r"listen\s+(?:\[::\]:)?(\d+)\b", line)
        if not lm:
            continue
        port = int(lm.group(1))
        if port in (80, 443):
            conflicts.append(
                f"nginx ascolta su porta {port} in '{current_file}' (vhost non gestito dal modulo)"
            )
    return conflicts


def _check_listening_processes() -> List[str]:
    """Warning-level: non-nginx processes bound to 80/443."""
    warnings: List[str] = []
    try:
        result = subprocess.run(
            ["ss", "-ltnpH"], capture_output=True, text=True, timeout=5
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return warnings
    if result.returncode != 0:
        return warnings
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local = parts[3]
        m = re.search(r":(\d+)$", local)
        if not m:
            continue
        port = int(m.group(1))
        if port not in (80, 443):
            continue
        users = " ".join(parts[5:]) if len(parts) > 5 else ""
        if "nginx" in users:
            continue
        warnings.append(f"Processo non-nginx in ascolto su porta {port}: {users or '?'}")
    return warnings


async def preflight_check(session: AsyncSession) -> Dict[str, Any]:
    """Return {ok, conflicts:[{type,detail}], warnings:[...]}."""
    conflicts: List[Dict[str, str]] = []

    for d in await _check_dnat_conflicts(session):
        conflicts.append({"type": "firewall_dnat", "detail": d})

    for d in _check_nginx_conflicts():
        conflicts.append({"type": "nginx_listen", "detail": d})

    warnings = [
        {"type": "process_listen", "detail": d} for d in _check_listening_processes()
    ]
    return {"ok": len(conflicts) == 0, "conflicts": conflicts, "warnings": warnings}


# ============================================================================
# Rendering
# ============================================================================

def _serialize_acl(acl: Optional[RevproxyAccessList]) -> Optional[Dict[str, Any]]:
    if acl is None:
        return None
    return {
        "id": str(acl.id),
        "name": acl.name,
        "satisfy_any": acl.satisfy_any,
        "pass_auth_to_upstream": acl.pass_auth_to_upstream,
        "auths": [{"id": str(a.id), "username": a.username} for a in acl.auths],
        "rules": sorted(
            [{"action": r.action, "subject": r.subject, "order": r.order} for r in acl.rules],
            key=lambda r: r["order"],
        ),
    }


def render_host_vhost(
    host: RevproxyHost,
    domains: List[RevproxyHostDomain],
    acl: Optional[RevproxyAccessList],
    cert: Optional[RevproxyCertificate],
) -> str:
    """Render the full :80 (+ :443 if cert) vhost for a host."""
    host_view = {
        "id": str(host.id),
        "name": host.name,
        "forward_scheme": host.forward_scheme,
        "forward_host": host.forward_host,
        "forward_port": host.forward_port,
        "force_https": host.force_https,
        "http2_support": host.http2_support,
        "block_exploits": host.block_exploits,
        "caching_enabled": host.caching_enabled,
        "websockets_support": host.websockets_support,
        "custom_nginx_config": host.custom_nginx_config or "",
    }

    proxy_block = _jinja.get_template("proxy_block.conf.j2").render(
        host=host_view, acl=_serialize_acl(acl)
    )
    return _jinja.get_template("proxy_host.conf.j2").render(
        host=host_view,
        domains=[d.domain for d in domains],
        cert=(
            {"cert_path": cert.cert_path, "key_path": cert.key_path}
            if cert and cert.cert_path
            else None
        ),
        proxy_block=proxy_block,
    )


def render_access_list_snippet(acl: RevproxyAccessList) -> str:
    return _jinja.get_template("access_list.conf.j2").render(
        acl=_serialize_acl(acl)
    )


def render_acme_vhost() -> str:
    return _jinja.get_template("acme_challenge.conf.j2").render()


# ============================================================================
# nginx control
# ============================================================================

def nginx_test() -> Tuple[bool, str]:
    try:
        r = subprocess.run(
            ["nginx", "-t"], capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            return True, r.stderr.strip() or "ok"
        return False, (r.stderr or r.stdout).strip()
    except Exception as e:
        return False, str(e)


def nginx_reload() -> Tuple[bool, str]:
    ok, msg = nginx_test()
    if not ok:
        return False, f"nginx -t failed: {msg}"
    try:
        r = subprocess.run(
            ["systemctl", "reload", "nginx"], capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            return True, "reloaded"
        return False, (r.stderr or r.stdout).strip()
    except Exception as e:
        return False, str(e)


# ============================================================================
# Host apply / remove
# ============================================================================

def _host_conf_paths(host_id) -> Tuple[Path, Path]:
    fname = f"{PROXY_FILE_PREFIX}{host_id}.conf"
    return NGINX_SITES_AVAILABLE / fname, NGINX_SITES_ENABLED / fname


async def _load_host_full(session: AsyncSession, host_id) -> Optional[RevproxyHost]:
    result = await session.execute(
        select(RevproxyHost)
        .where(RevproxyHost.id == host_id)
        .options(
            selectinload(RevproxyHost.domains),
            selectinload(RevproxyHost.certificate),
        )
    )
    return result.scalar_one_or_none()


async def _load_acl_full(session: AsyncSession, acl_id) -> Optional[RevproxyAccessList]:
    if acl_id is None:
        return None
    result = await session.execute(
        select(RevproxyAccessList)
        .where(RevproxyAccessList.id == acl_id)
        .options(
            selectinload(RevproxyAccessList.auths),
            selectinload(RevproxyAccessList.rules),
        )
    )
    return result.scalar_one_or_none()


async def apply_host(session: AsyncSession, host_id) -> Tuple[bool, str]:
    """Render and install the vhost for a host; reload nginx."""
    host = await _load_host_full(session, host_id)
    if host is None:
        return False, "Host non trovato"

    avail, enabled = _host_conf_paths(host.id)

    if not host.enabled:
        # Treat disabled as remove
        return await remove_host(host.id)

    acl = await _load_acl_full(session, host.access_list_id)
    config = render_host_vhost(host, host.domains, acl, host.certificate)

    NGINX_SITES_AVAILABLE.mkdir(parents=True, exist_ok=True)
    NGINX_SITES_ENABLED.mkdir(parents=True, exist_ok=True)
    avail.write_text(config)

    if not enabled.exists():
        try:
            enabled.symlink_to(avail)
        except FileExistsError:
            pass

    ok, msg = nginx_reload()
    if not ok:
        # Rollback: remove files
        for p in (enabled, avail):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        return False, f"nginx reload fallito: {msg}"
    return True, "applied"


async def remove_host(host_id) -> Tuple[bool, str]:
    avail, enabled = _host_conf_paths(host_id)
    for p in (enabled, avail):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    ok, msg = nginx_reload()
    if not ok:
        return False, f"nginx reload fallito: {msg}"
    return True, "removed"


# ============================================================================
# Access list apply / remove
# ============================================================================

def _acl_snippet_path(acl_id) -> Path:
    return SNIPPETS_DIR / f"acl-{acl_id}.conf"


def _htpasswd_path(acl_id) -> Path:
    return HTPASSWD_DIR / f"{acl_id}"


def write_htpasswd(acl_id, users: List[Tuple[str, str]]) -> None:
    """Write the htpasswd file. `users` = [(username, bcrypt_hash), ...]."""
    HTPASSWD_DIR.mkdir(parents=True, exist_ok=True)
    path = _htpasswd_path(acl_id)
    lines = [f"{u}:{h}" for u, h in users]
    path.write_text("\n".join(lines) + ("\n" if lines else ""))
    os.chmod(path, 0o640)


def hash_password(plain: str) -> str:
    """Hash plain password using `htpasswd -nbB`. Returns the hash portion only."""
    r = subprocess.run(
        ["htpasswd", "-nbB", "x", plain],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        raise RuntimeError(f"htpasswd failed: {r.stderr.strip()}")
    out = r.stdout.strip()
    # Format: "x:$2y$...". Strip the dummy username.
    if ":" in out:
        return out.split(":", 1)[1]
    return out


async def apply_access_list(session: AsyncSession, acl_id) -> Tuple[bool, str]:
    acl = await _load_acl_full(session, acl_id)
    if acl is None:
        return False, "Access list non trovata"

    SNIPPETS_DIR.mkdir(parents=True, exist_ok=True)
    snippet = render_access_list_snippet(acl)
    _acl_snippet_path(acl.id).write_text(snippet)

    users = [(a.username, a.password_hash) for a in acl.auths]
    write_htpasswd(acl.id, users)

    # Reapply hosts that use this acl (so any toggle change is reflected)
    result = await session.execute(
        select(RevproxyHost.id).where(RevproxyHost.access_list_id == acl.id)
    )
    affected = [row[0] for row in result.all()]
    for hid in affected:
        ok, msg = await apply_host(session, hid)
        if not ok:
            return False, f"apply_host({hid}) fallito: {msg}"

    if not affected:
        ok, msg = nginx_reload()
        if not ok:
            return False, msg
    return True, "applied"


async def remove_access_list(session: AsyncSession, acl_id) -> Tuple[bool, str]:
    for p in (_acl_snippet_path(acl_id), _htpasswd_path(acl_id)):
        try:
            p.unlink()
        except FileNotFoundError:
            pass

    # Reapply hosts that had it assigned (their access_list_id will be None now)
    # Caller is responsible for clearing FK before calling.
    return nginx_reload()


# ============================================================================
# Certificates (Let's Encrypt via certbot --webroot)
# ============================================================================

def cert_name(host_id) -> str:
    return f"madmin-{host_id}"


def issue_certificate(
    host_id, primary_domain: str, san_domains: List[str], email: Optional[str] = None
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Request (or expand) a Let's Encrypt cert for the given domains via HTTP-01.

    Returns (ok, message, cert_info). cert_info has cert_path/key_path/expires_at.
    """
    ACME_WEBROOT.mkdir(parents=True, exist_ok=True)
    name = cert_name(host_id)

    args = [
        "certbot", "certonly",
        "--webroot", "-w", str(ACME_WEBROOT),
        "--cert-name", name,
        "--non-interactive", "--agree-tos",
        "--expand", "--keep-until-expiring",
    ]
    if email:
        args += ["--email", email]
    else:
        args += ["--register-unsafely-without-email"]
    args += ["-d", primary_domain]
    for d in san_domains or []:
        if d and d != primary_domain:
            args += ["-d", d]

    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        return False, "certbot non installato", None
    except subprocess.TimeoutExpired:
        return False, "certbot timeout", None

    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip()[-2000:], None

    live_dir = LETSENCRYPT_LIVE / name
    cert_path = live_dir / "fullchain.pem"
    key_path = live_dir / "privkey.pem"
    if not cert_path.exists() or not key_path.exists():
        return False, f"Certbot ok ma file mancanti in {live_dir}", None

    info = {
        "cert_path": str(cert_path),
        "key_path": str(key_path),
        "expires_at": _read_cert_expiry(cert_path),
        "issued_at": datetime.utcnow(),
    }
    return True, "issued", info


def revoke_certificate(host_id) -> Tuple[bool, str]:
    name = cert_name(host_id)
    live = LETSENCRYPT_LIVE / name / "fullchain.pem"
    if not live.exists():
        return True, "no cert"
    try:
        r = subprocess.run(
            ["certbot", "revoke", "--non-interactive",
             "--cert-path", str(live), "--reason", "cessationofoperation"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            return False, (r.stderr or r.stdout).strip()[-2000:]
        subprocess.run(
            ["certbot", "delete", "--non-interactive", "--cert-name", name],
            capture_output=True, text=True, timeout=30,
        )
        return True, "revoked"
    except Exception as e:
        return False, str(e)


def _read_cert_expiry(cert_path: Path) -> Optional[datetime]:
    try:
        r = subprocess.run(
            ["openssl", "x509", "-enddate", "-noout", "-in", str(cert_path)],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return None
        # notAfter=Aug 12 04:54:00 2026 GMT
        m = re.match(r"notAfter=(.+)", r.stdout.strip())
        if not m:
            return None
        return datetime.strptime(m.group(1), "%b %d %H:%M:%S %Y %Z")
    except Exception:
        return None


# ============================================================================
# Validation helpers
# ============================================================================

DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$"
)


def normalize_domain(domain: str) -> str:
    d = (domain or "").strip().lower().rstrip(".")
    return d


def is_valid_domain(domain: str) -> bool:
    d = normalize_domain(domain)
    return bool(DOMAIN_RE.match(d))


def is_valid_subject(subject: str) -> bool:
    try:
        ipaddress.ip_network(subject, strict=False)
        return True
    except ValueError:
        return False


def is_valid_forward_host(host: str) -> bool:
    h = (host or "").strip()
    if not h:
        return False
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        pass
    return bool(re.match(r"^[a-zA-Z0-9._-]+$", h)) and len(h) <= 253

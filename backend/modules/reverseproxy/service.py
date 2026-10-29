"""
Reverse Proxy Module - Service Layer

Renders nginx configs from DB state into a dedicated nginx instance
(nginx-revproxy.service, separate from the dashboard nginx),
manages access lists (htpasswd + IP rules), and drives certbot for Let's Encrypt.
"""
import os
import re
import gzip
import shutil
import subprocess
import logging
import ipaddress
from pathlib import Path
from collections import deque
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any

from cryptography import x509

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
# The module runs its own nginx instance, separate from the one serving the
# MADMIN dashboard: a broken proxy config can never take the admin UI down.
SERVICE_NAME = "nginx-revproxy"
NGINX_BIN = "/usr/sbin/nginx"
NGINX_DIR = Path("/etc/nginx-revproxy")
NGINX_CONF = NGINX_DIR / "nginx.conf"
SITES_DIR = NGINX_DIR / "sites"
HTPASSWD_DIR = NGINX_DIR / "htpasswd"
SNIPPETS_DIR = NGINX_DIR / "snippets"
NGINX_LOG_DIR = Path("/var/log/nginx-revproxy")
NGINX_TEMP_DIR = Path("/var/lib/nginx-revproxy")
NGINX_PID_FILE = Path("/run/nginx-revproxy.pid")
SYSTEMD_UNIT = Path(f"/etc/systemd/system/{SERVICE_NAME}.service")
LOGROTATE_FILE = Path(f"/etc/logrotate.d/{SERVICE_NAME}")
ACME_WEBROOT = Path("/var/www/madmin-acme")
SENTINEL_DIR = Path("/etc/madmin/reverseproxy")
SENTINEL_FILE = SENTINEL_DIR / ".disabled-due-to-conflict"
LETSENCRYPT_LIVE = Path("/etc/letsencrypt/live")
RENEWAL_HOOK = Path("/etc/letsencrypt/renewal-hooks/deploy/madmin-revproxy-reload.sh")

# Layout used before the dedicated instance: vhosts lived in the dashboard nginx
LEGACY_SITES_DIRS = (Path("/etc/nginx/sites-enabled"), Path("/etc/nginx/sites-available"))
LEGACY_REVPROXY_DIR = Path("/etc/nginx/madmin-revproxy")

PROXY_FILE_PREFIX = "madmin-proxy-"
ACME_FILE = "madmin-acme.conf"

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_jinja = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
    keep_trailing_newline=True,
)

# Directives that must never appear in user-supplied nginx snippets because they
# allow traffic hijacking, auth bypass, file-system access, or code execution.
_BLOCKED_NGINX_DIRECTIVES = frozenset({
    # Code execution (Lua / Perl)
    "access_by_lua", "access_by_lua_block", "access_by_lua_file",
    "content_by_lua", "content_by_lua_block", "content_by_lua_file",
    "rewrite_by_lua", "rewrite_by_lua_block", "rewrite_by_lua_file",
    "header_filter_by_lua", "header_filter_by_lua_block",
    "body_filter_by_lua", "body_filter_by_lua_block",
    "log_by_lua", "log_by_lua_block",
    "balancer_by_lua", "ssl_certificate_by_lua",
    "perl", "perl_set", "perl_require",
    # File / module inclusion
    "include", "load_module",
    # Traffic hijacking (upstream redirection)
    "proxy_pass", "fastcgi_pass", "uwsgi_pass", "scgi_pass", "grpc_pass",
    # Auth bypass
    "auth_request", "auth_request_set", "auth_basic_user_file",
    # IP spoofing
    "set_real_ip_from", "real_ip_header",
    # Arbitrary redirect / access-control bypass
    "return", "allow", "deny",
    # File-system access change
    "alias", "root",
})


def validate_custom_nginx_config(snippet: str) -> None:
    """Raise ValueError if snippet contains a blocked nginx directive."""
    if not snippet:
        return
    # Strip line comments before extracting directive names.
    cleaned = re.sub(r'#[^\n]*', '', snippet)
    for token in re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', cleaned):
        if token.lower() in _BLOCKED_NGINX_DIRECTIVES:
            raise ValueError(f"Directive '{token}' is not allowed in custom nginx config")


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
    """Parse `nginx -T` of the system nginx (the one serving the MADMIN
    dashboard) for listen 80/443 directives: those ports belong to the
    dedicated reverse proxy instance."""
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
        # Skip files of the legacy layout: migrate_legacy_layout() removes them
        fname = Path(current_file).name
        if fname.startswith(PROXY_FILE_PREFIX) or fname == ACME_FILE:
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


def _instance_pids() -> set:
    """PIDs of the dedicated nginx instance (master + its workers)."""
    try:
        master = int(NGINX_PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return set()
    pids = {master}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            # /proc/<pid>/stat: "pid (comm) state ppid ..."
            ppid = int((proc / "stat").read_text().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        if ppid == master:
            pids.add(int(proc.name))
    return pids


def _check_listening_processes() -> List[str]:
    """Warning-level: processes other than the dedicated instance bound to 80/443."""
    warnings: List[str] = []
    try:
        result = subprocess.run(
            ["ss", "-ltnpH"], capture_output=True, text=True, timeout=5
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return warnings
    if result.returncode != 0:
        return warnings
    own = _instance_pids()
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
        pids = {int(x) for x in re.findall(r"pid=(\d+)", users)}
        if pids and pids <= own:
            continue
        warnings.append(f"Processo in ascolto su porta {port}: {users or '?'}")
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
        logs={k: str(host_log_path(host.id, k)) for k in LOG_TYPES},
    )


def render_access_list_snippet(acl: RevproxyAccessList) -> str:
    return _jinja.get_template("access_list.conf.j2").render(
        acl=_serialize_acl(acl)
    )


def render_acme_vhost() -> str:
    return _jinja.get_template("acme_challenge.conf.j2").render()


def _instance_context() -> Dict[str, str]:
    return {
        "service": SERVICE_NAME,
        "nginx_bin": NGINX_BIN,
        "conf": str(NGINX_CONF),
        "sites_dir": str(SITES_DIR),
        "log_dir": str(NGINX_LOG_DIR),
        "temp_dir": str(NGINX_TEMP_DIR),
        "pid_file": str(NGINX_PID_FILE),
    }


def render_nginx_conf() -> str:
    return _jinja.get_template("nginx.conf.j2").render(**_instance_context())


# ============================================================================
# Dedicated nginx instance (systemd unit, main config, log rotation)
# ============================================================================

def _systemctl(*args: str) -> Tuple[bool, str]:
    try:
        r = subprocess.run(
            ["systemctl", *args], capture_output=True, text=True, timeout=30
        )
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except Exception as e:
        return False, str(e)


def _write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def render_renewal_hook() -> str:
    return (
        "#!/bin/sh\n"
        "# Installed by MADMIN reverseproxy module\n"
        f"systemctl reload {SERVICE_NAME}.service\n"
    )


def install_instance() -> None:
    """Create directories, main config, systemd unit, logrotate policy and
    certbot deploy hook for the dedicated instance and enable it at boot.
    Idempotent; does not start it. Runs on every startup too, so installs
    upgraded from the shared layout get their renewal hook repointed from the
    system nginx to the instance."""
    for d in (NGINX_DIR, SITES_DIR, SNIPPETS_DIR, HTPASSWD_DIR,
              NGINX_LOG_DIR, NGINX_TEMP_DIR, ACME_WEBROOT, SENTINEL_DIR):
        d.mkdir(parents=True, exist_ok=True)
    os.chmod(HTPASSWD_DIR, 0o755)

    _write_if_changed(NGINX_CONF, render_nginx_conf())
    _write_if_changed(SITES_DIR / ACME_FILE, render_acme_vhost())

    ctx = _instance_context()
    _write_if_changed(LOGROTATE_FILE, _jinja.get_template("logrotate.j2").render(**ctx))
    if _write_if_changed(SYSTEMD_UNIT, _jinja.get_template("nginx-revproxy.service.j2").render(**ctx)):
        _systemctl("daemon-reload")
    _systemctl("enable", f"{SERVICE_NAME}.service")

    _write_if_changed(RENEWAL_HOOK, render_renewal_hook())
    os.chmod(RENEWAL_HOOK, 0o755)


def uninstall_instance() -> None:
    """Stop and remove the dedicated instance. Logs are kept for logrotate."""
    _systemctl("disable", "--now", f"{SERVICE_NAME}.service")
    for f in (SYSTEMD_UNIT, LOGROTATE_FILE):
        try:
            f.unlink()
        except FileNotFoundError:
            pass
    _systemctl("daemon-reload")
    shutil.rmtree(NGINX_DIR, ignore_errors=True)
    shutil.rmtree(NGINX_TEMP_DIR, ignore_errors=True)


def migrate_legacy_layout() -> bool:
    """Remove vhosts/snippets left in the system nginx by the pre-instance
    layout and reload it so ports 80/443 are freed. Returns True if anything
    was removed. Configs are regenerated from the DB by sync_all()."""
    removed = False
    for d in LEGACY_SITES_DIRS:
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.name.startswith(PROXY_FILE_PREFIX) or f.name == ACME_FILE:
                try:
                    f.unlink()
                    removed = True
                except OSError as e:
                    logger.warning("Legacy cleanup: cannot remove %s: %s", f, e)
    if LEGACY_REVPROXY_DIR.exists():
        shutil.rmtree(LEGACY_REVPROXY_DIR, ignore_errors=True)
        removed = True

    if removed:
        try:
            r = subprocess.run(["nginx", "-t"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                _systemctl("reload", "nginx")
            else:
                logger.warning("Legacy cleanup: system nginx -t failed: %s", r.stderr.strip())
        except Exception as e:
            logger.warning("Legacy cleanup: system nginx reload error: %s", e)
    return removed


def is_active() -> bool:
    ok, _ = _systemctl("is-active", "--quiet", f"{SERVICE_NAME}.service")
    return ok


# ============================================================================
# nginx control (dedicated instance only)
# ============================================================================

def nginx_test() -> Tuple[bool, str]:
    try:
        r = subprocess.run(
            [NGINX_BIN, "-t", "-c", str(NGINX_CONF)],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            return True, r.stderr.strip() or "ok"
        return False, (r.stderr or r.stdout).strip()
    except Exception as e:
        return False, str(e)


def nginx_reload() -> Tuple[bool, str]:
    """Test the config, then reload the instance (or start it if it is down)."""
    ok, msg = nginx_test()
    if not ok:
        return False, f"nginx -t failed: {msg}"
    action = "reload" if is_active() else "start"
    ok, msg = _systemctl(action, f"{SERVICE_NAME}.service")
    if ok:
        return True, "reloaded" if action == "reload" else "started"
    return False, msg


# ============================================================================
# Host apply / remove
# ============================================================================

def _host_conf_path(host_id) -> Path:
    return SITES_DIR / f"{PROXY_FILE_PREFIX}{host_id}.conf"


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

    if not host.enabled:
        # Treat disabled as remove
        return await remove_host(host.id)

    acl = await _load_acl_full(session, host.access_list_id)
    config = render_host_vhost(host, host.domains, acl, host.certificate)

    path = _host_conf_path(host.id)
    SITES_DIR.mkdir(parents=True, exist_ok=True)

    # Snapshot the current on-disk vhost so a config that fails `nginx -t`
    # (e.g. an invalid custom_nginx_config snippet) can be reverted without
    # taking a previously-working host offline.
    prev_config = path.read_text() if path.exists() else None

    path.write_text(config)

    ok, msg = nginx_reload()
    if not ok:
        # `nginx -t` failed, so the broken config was never loaded (reload runs
        # only after a passing test) — the live nginx is unchanged. Restore the
        # on-disk file to its previous good content so it doesn't poison the next
        # reload; if this host had no previous config, remove it entirely.
        if prev_config is not None:
            path.write_text(prev_config)
        else:
            path.unlink(missing_ok=True)
        return False, f"nginx reload fallito: {msg}"
    return True, "applied"


async def sync_all(session: AsyncSession) -> Tuple[bool, str]:
    """Bring every managed file of the instance in line with the DB, then
    reload once (or start the instance if it is down).

    Writes main config, ACME vhost, enabled host vhosts, ACL snippets and
    htpasswd files; removes vhosts/snippets/htpasswd no longer in the DB. If
    `nginx -t` rejects the result, every touched file is restored.
    """
    desired: Dict[Path, str] = {
        NGINX_CONF: render_nginx_conf(),
        SITES_DIR / ACME_FILE: render_acme_vhost(),
    }

    acls = (await session.execute(
        select(RevproxyAccessList).options(
            selectinload(RevproxyAccessList.auths),
            selectinload(RevproxyAccessList.rules),
        )
    )).scalars().all()
    acl_by_id = {acl.id: acl for acl in acls}
    for acl in acls:
        desired[_acl_snippet_path(acl.id)] = render_access_list_snippet(acl)
        desired[_htpasswd_path(acl.id)] = _htpasswd_content(
            [(a.username, a.password_hash) for a in acl.auths]
        )

    hosts = (await session.execute(
        select(RevproxyHost)
        .where(RevproxyHost.enabled == True)  # noqa: E712
        .options(
            selectinload(RevproxyHost.domains),
            selectinload(RevproxyHost.certificate),
        )
    )).scalars().all()
    for host in hosts:
        acl = acl_by_id.get(host.access_list_id)
        desired[_host_conf_path(host.id)] = render_host_vhost(
            host, host.domains, acl, host.certificate
        )

    managed = [f for f in SITES_DIR.glob(f"{PROXY_FILE_PREFIX}*.conf")]
    managed += list(SNIPPETS_DIR.glob("acl-*.conf"))
    managed += [f for f in HTPASSWD_DIR.iterdir() if f.is_file()] if HTPASSWD_DIR.exists() else []

    previous: Dict[Path, Optional[str]] = {}
    for path in managed:
        if path not in desired:
            previous[path] = path.read_text()
            path.unlink()
    for path, content in desired.items():
        current = path.read_text() if path.exists() else None
        if current != content:
            previous[path] = current
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            if path.parent == HTPASSWD_DIR:
                os.chmod(path, 0o644)

    if not previous and is_active():
        return True, "up to date"

    ok, msg = nginx_reload()
    if not ok:
        for path, content in previous.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(content)
        return False, f"nginx reload fallito: {msg}"
    return True, f"{len(previous)} file aggiornati, {msg}"


async def remove_host(host_id) -> Tuple[bool, str]:
    _host_conf_path(host_id).unlink(missing_ok=True)
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


def _htpasswd_content(users: List[Tuple[str, str]]) -> str:
    lines = [f"{u}:{h}" for u, h in users]
    return "\n".join(lines) + ("\n" if lines else "")


def write_htpasswd(acl_id, users: List[Tuple[str, str]]) -> None:
    """Write the htpasswd file. `users` = [(username, bcrypt_hash), ...]."""
    HTPASSWD_DIR.mkdir(parents=True, exist_ok=True)
    path = _htpasswd_path(acl_id)
    path.write_text(_htpasswd_content(users))
    os.chmod(path, 0o644)


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
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        try:
            return cert.not_valid_after_utc.replace(tzinfo=None)
        except AttributeError:
            return cert.not_valid_after  # cryptography < 42
    except Exception:
        return None


# ============================================================================
# Logs (per-host files + nginx global logs, including logrotate archives)
# ============================================================================

LOG_TYPES = ("access", "error")
GLOBAL_LOG_SOURCE = "global"
MAX_LOG_LINES = 2000
_TAIL_BLOCK = 64 * 1024

# nginx `combined` format
_ACCESS_RE = re.compile(
    r'^(?P<ip>\S+) \S+ (?P<user>\S+) \[(?P<time>[^\]]+)\] '
    r'"(?P<request>(?:[^"\\]|\\.)*)" (?P<status>\d{3}) (?P<bytes>\d+|-)'
    r'(?: "(?P<referer>(?:[^"\\]|\\.)*)" "(?P<agent>(?:[^"\\]|\\.)*)")?'
)
_ERROR_RE = re.compile(
    r'^(?P<time>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) \[(?P<level>\w+)\] '
    r'\d+#\d+: (?:\*\d+ )?(?P<message>.*)$'
)
_ERROR_CLIENT_RE = re.compile(r'client: ([^,]+)')
_ERROR_HOST_RE = re.compile(r'host: "([^"]*)"')


def host_log_path(host_id, kind: str) -> Path:
    return NGINX_LOG_DIR / f"{PROXY_FILE_PREFIX}{host_id}.{kind}.log"


def log_base_path(source: str, kind: str) -> Path:
    """Current log file for a source ("global" or a host UUID, already validated)."""
    if source == GLOBAL_LOG_SOURCE:
        return NGINX_LOG_DIR / f"{kind}.log"
    return host_log_path(source, kind)


def _rotated_path(base: Path, index: int) -> Optional[Path]:
    """logrotate naming: base, base.1, base.2.gz, ... (delaycompress)."""
    if index == 0:
        return base
    for candidate in (Path(f"{base}.{index}"), Path(f"{base}.{index}.gz")):
        if candidate.exists():
            return candidate
    return None


def list_log_files(base: Path) -> List[Dict[str, Any]]:
    """Current file plus every rotated archive, newest first."""
    pattern = re.compile(rf"^{re.escape(base.name)}(?:\.(\d+)(\.gz)?)?$")
    files = []
    if base.parent.exists():
        for f in base.parent.iterdir():
            m = pattern.match(f.name)
            if not m or not f.is_file():
                continue
            st = f.stat()
            files.append({
                "index": int(m.group(1) or 0),
                "name": f.name,
                "compressed": bool(m.group(2)),
                "size": st.st_size,
                "modified": datetime.fromtimestamp(st.st_mtime),
            })
    return sorted(files, key=lambda x: x["index"])


def _parse_access_line(line: str) -> Dict[str, Any]:
    m = _ACCESS_RE.match(line)
    if not m:
        return {"raw": line}
    parts = m.group("request").split(" ", 2)
    method, path, protocol = parts if len(parts) == 3 else ("", m.group("request"), "")
    try:
        time = datetime.strptime(m.group("time"), "%d/%b/%Y:%H:%M:%S %z").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        time = m.group("time")
    return {
        "raw": line,
        "time": time,
        "ip": m.group("ip"),
        "user": None if m.group("user") == "-" else m.group("user"),
        "method": method,
        "path": path,
        "protocol": protocol,
        "status": int(m.group("status")),
        "bytes": 0 if m.group("bytes") == "-" else int(m.group("bytes")),
        "referer": None if m.group("referer") in (None, "-") else m.group("referer"),
        "agent": m.group("agent"),
    }


def _parse_error_line(line: str) -> Dict[str, Any]:
    m = _ERROR_RE.match(line)
    if not m:
        return {"raw": line}
    message = m.group("message")
    client = _ERROR_CLIENT_RE.search(message)
    host = _ERROR_HOST_RE.search(message)
    return {
        "raw": line,
        "time": m.group("time").replace("/", "-"),
        "level": m.group("level"),
        "message": message,
        "client": client.group(1) if client else None,
        "host": host.group(1) if host else None,
    }


def _tail_lines(path: Path, count: int) -> List[str]:
    """Last `count` lines of an uncompressed file without reading all of it."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        data = b""
        while pos > 0 and data.count(b"\n") <= count:
            step = min(_TAIL_BLOCK, pos)
            pos -= step
            f.seek(pos)
            data = f.read(step) + data
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[-count:]


def read_log(
    base: Path,
    kind: str,
    index: int = 0,
    lines: int = 500,
    search: str = "",
    status_class: Optional[int] = None,
) -> Dict[str, Any]:
    """Return the last `lines` matching entries of a log file, newest first.

    Filters (`search`, case-insensitive substring; `status_class`, 2..5 for
    access logs) are applied before the limit, so a filtered read scans the
    whole file. Blocking: call from a worker thread.
    """
    path = _rotated_path(base, index)
    if path is None or not path.exists():
        return {"file": None, "exists": False, "entries": [], "truncated": False}

    parse = _parse_access_line if kind == "access" else _parse_error_line
    needle = search.lower()
    filtered = bool(needle) or status_class is not None
    compressed = path.suffix == ".gz"

    if not filtered and not compressed:
        raw = _tail_lines(path, lines + 1)
        truncated = len(raw) > lines
        entries = [parse(l) for l in raw[-lines:] if l]
    else:
        window: deque = deque(maxlen=lines)
        matched = 0
        opener = gzip.open if compressed else open
        with opener(path, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or (needle and needle not in line.lower()):
                    continue
                entry = parse(line)
                if status_class is not None and entry.get("status", 0) // 100 != status_class:
                    continue
                window.append(entry)
                matched += 1
        entries = list(window)
        truncated = matched > lines

    entries.reverse()
    return {"file": path.name, "exists": True, "entries": entries, "truncated": truncated}


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

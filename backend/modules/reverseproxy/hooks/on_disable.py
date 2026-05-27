"""
Reverse Proxy Module - on_disable Hook

Removes every nginx vhost/snippet file prefixed with `madmin-`, the htpasswd
files, the renewal-hook script and the conflict sentinel. Reloads nginx.
Does NOT touch /etc/letsencrypt/live/* (irrecoverable, see manifest).
"""
import shutil
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

NGINX_SITES_AVAILABLE = Path("/etc/nginx/sites-available")
NGINX_SITES_ENABLED = Path("/etc/nginx/sites-enabled")
MADMIN_REVPROXY_DIR = Path("/etc/nginx/madmin-revproxy")
HTPASSWD_DIR = MADMIN_REVPROXY_DIR / "htpasswd"
SNIPPETS_DIR = MADMIN_REVPROXY_DIR / "snippets"
RENEWAL_HOOK = Path("/etc/letsencrypt/renewal-hooks/deploy/madmin-revproxy-reload.sh")
SENTINEL_DIR = Path("/etc/madmin/reverseproxy")

FILE_PREFIX = "madmin-"


def _unlink_madmin_files(directory: Path) -> int:
    if not directory.exists():
        return 0
    removed = 0
    for f in directory.iterdir():
        if not f.name.startswith(FILE_PREFIX):
            continue
        try:
            if f.is_symlink() or f.is_file():
                f.unlink()
                removed += 1
        except Exception as e:
            logger.warning("Failed to unlink %s: %s", f, e)
    return removed


async def run():
    logger.info("Reverse Proxy on_disable: start")

    # 1) Remove madmin-* vhosts (enabled first, then available)
    n_en = _unlink_madmin_files(NGINX_SITES_ENABLED)
    n_av = _unlink_madmin_files(NGINX_SITES_AVAILABLE)
    logger.info("Removed %d enabled and %d available madmin-* vhosts", n_en, n_av)

    # 2) Empty htpasswd and snippets directories
    for d in (HTPASSWD_DIR, SNIPPETS_DIR):
        if not d.exists():
            continue
        for f in d.iterdir():
            try:
                if f.is_file():
                    f.unlink()
            except Exception as e:
                logger.warning("Failed to remove %s: %s", f, e)

    # 3) Renewal hook
    try:
        RENEWAL_HOOK.unlink()
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("Failed to remove renewal hook: %s", e)

    # 4) Sentinel
    try:
        for f in SENTINEL_DIR.glob(".*"):
            f.unlink()
    except Exception as e:
        logger.warning("Failed to clean sentinel: %s", e)

    # 5) Reload nginx (best effort — if it fails, log but don't abort)
    try:
        r = subprocess.run(["nginx", "-t"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            subprocess.run(["systemctl", "reload", "nginx"], capture_output=True, text=True, timeout=15)
        else:
            logger.warning("nginx -t failed during on_disable: %s", r.stderr.strip())
    except Exception as e:
        logger.warning("nginx reload error during on_disable: %s", e)

    # 6) Remove MOD_REVPROXY_INPUT chain and its rules
    try:
        from core.firewall import iptables as core_iptables
        chain = "MOD_REVPROXY_INPUT"
        core_iptables.remove_jump_rule("INPUT", chain, "filter")
        core_iptables.flush_chain(chain, "filter")
        core_iptables.delete_chain(chain, "filter")
        logger.info("Reverse Proxy on_disable: firewall chain %s removed", chain)
    except Exception as e:
        logger.warning("Reverse Proxy on_disable: firewall cleanup error: %s", e)

    logger.info("Reverse Proxy on_disable: complete")
    return True

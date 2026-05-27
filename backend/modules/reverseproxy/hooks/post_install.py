"""
Reverse Proxy Module - Post Install Hook

- Verifies that no other service/rule occupies ports 80/443.
- Creates working dirs (madmin-revproxy, ACME webroot).
- Installs the ACME catch-all vhost.
- Whitelists nginx for systemd control.
- Opens 80/443 on MOD_REVPROXY_INPUT.
- Idempotent: regenerates all DB-tracked vhosts on re-enable.
"""
import os
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

NGINX_SITES_AVAILABLE = Path("/etc/nginx/sites-available")
NGINX_SITES_ENABLED = Path("/etc/nginx/sites-enabled")
ACME_FILE = "madmin-acme.conf"


async def run():
    logger.info("Reverse Proxy post-install: start")

    from modules.reverseproxy import service as svc
    from core.database import async_session_maker
    from core.services.service import SystemdService
    from core.firewall import iptables as fw

    # 1) Preflight: port conflicts
    async with async_session_maker() as session:
        preflight = await svc.preflight_check(session)

    if not preflight["ok"]:
        details = "; ".join(c["detail"] for c in preflight["conflicts"])
        reason = f"Porte 80/443 in conflitto: {details}"
        logger.error("Reverse Proxy post-install: %s", reason)
        svc.write_sentinel(reason)
        return False

    svc.clear_sentinel()

    # 2) Working directories
    for d in (
        svc.MADMIN_REVPROXY_DIR,
        svc.HTPASSWD_DIR,
        svc.SNIPPETS_DIR,
        svc.ACME_WEBROOT,
        svc.SENTINEL_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
    os.chmod(svc.HTPASSWD_DIR, 0o750)
    logger.info("Reverse Proxy post-install: directories ready")

    # 3) Install ACME catch-all vhost (idempotent)
    NGINX_SITES_AVAILABLE.mkdir(parents=True, exist_ok=True)
    NGINX_SITES_ENABLED.mkdir(parents=True, exist_ok=True)
    acme_available = NGINX_SITES_AVAILABLE / ACME_FILE
    acme_enabled = NGINX_SITES_ENABLED / ACME_FILE
    acme_available.write_text(svc.render_acme_vhost())
    if not acme_enabled.exists():
        try:
            acme_enabled.symlink_to(acme_available)
        except FileExistsError:
            pass

    # 4) Whitelist nginx for systemd control
    if "nginx.service" not in SystemdService.ALLOWED_SERVICES:
        SystemdService.ALLOWED_SERVICES.append("nginx.service")

    # 5) Open 80/443 on MOD_REVPROXY_INPUT (the chain itself is created by the
    #    module loader from manifest.firewall_chains).
    try:
        for port in (80, 443):
            fw.add_rule(
                table="filter",
                chain="MOD_REVPROXY_INPUT",
                action="ACCEPT",
                protocol="tcp",
                port=str(port),
                comment=f"madmin-revproxy:{port}",
            )
    except Exception as e:
        logger.warning("Reverse Proxy post-install: firewall rules error: %s", e)

    # 6) Install certbot deploy-hook so nginx reloads after every renewal
    try:
        hook_dir = svc.RENEWAL_HOOK.parent
        hook_dir.mkdir(parents=True, exist_ok=True)
        svc.RENEWAL_HOOK.write_text(
            "#!/bin/sh\n"
            "# Installed by MADMIN reverseproxy module\n"
            "nginx -t && systemctl reload nginx\n"
        )
        os.chmod(svc.RENEWAL_HOOK, 0o755)
    except Exception as e:
        logger.warning("Reverse Proxy post-install: cert renewal hook error: %s", e)

    # 7) Re-render any existing DB-tracked vhosts (re-enable case)
    try:
        from sqlalchemy import select
        from modules.reverseproxy.models import RevproxyHost, RevproxyAccessList

        async with async_session_maker() as session:
            hosts = (await session.execute(select(RevproxyHost.id))).scalars().all()
            acls = (await session.execute(select(RevproxyAccessList.id))).scalars().all()
            for acl_id in acls:
                ok, msg = await svc.apply_access_list(session, acl_id)
                if not ok:
                    logger.warning("apply_access_list(%s) failed: %s", acl_id, msg)
            for hid in hosts:
                ok, msg = await svc.apply_host(session, hid)
                if not ok:
                    logger.warning("apply_host(%s) failed: %s", hid, msg)
    except Exception as e:
        logger.warning("Reverse Proxy post-install: re-render error: %s", e)

    # 8) Reload nginx (apply ACME vhost at minimum)
    ok, msg = svc.nginx_reload()
    if not ok:
        logger.error("Reverse Proxy post-install: nginx reload failed: %s", msg)
        return False

    logger.info("Reverse Proxy post-install: complete")
    return True

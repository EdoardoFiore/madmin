"""
Reverse Proxy Module - on_disable Hook

Stops and removes the dedicated nginx instance (systemd unit, logrotate policy,
/etc/nginx-revproxy with vhosts, snippets and htpasswd files), removes any
leftover of the old shared layout from the system nginx, the renewal-hook
script and the conflict sentinel. Logs in /var/log/nginx-revproxy are kept.
Does NOT touch /etc/letsencrypt/live/* (irrecoverable, see manifest).
"""
import logging

logger = logging.getLogger(__name__)


async def run():
    logger.info("Reverse Proxy on_disable: start")

    from modules.reverseproxy import service as svc

    # 1) Dedicated instance
    try:
        svc.uninstall_instance()
        logger.info("Reverse Proxy on_disable: instance %s removed", svc.SERVICE_NAME)
    except Exception as e:
        logger.warning("Reverse Proxy on_disable: instance removal error: %s", e)

    # 2) Old shared layout (system nginx), if still present
    try:
        svc.migrate_legacy_layout()
    except Exception as e:
        logger.warning("Reverse Proxy on_disable: legacy cleanup error: %s", e)

    # 3) Renewal hook
    try:
        svc.RENEWAL_HOOK.unlink()
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("Failed to remove renewal hook: %s", e)

    # 4) Sentinel
    try:
        for f in svc.SENTINEL_DIR.glob(".*"):
            f.unlink()
    except Exception as e:
        logger.warning("Failed to clean sentinel: %s", e)

    # 5) Remove MOD_REVPROXY_INPUT chain and its rules
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

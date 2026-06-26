"""
OpenVPN on_startup hook.

Restores instances that were UP before the last restart (desired-state
reconciliation). Reuses OpenVPNService.bring_instance_up so the firewall state
matches the /start endpoint exactly. Idempotent: skips instances already active.

Also starts a daily background loop that auto-renews each server instance's CRL
before it expires. The server config uses `crl-verify`, so an expired CRL makes
OpenVPN reject every TLS handshake — clients silently can no longer connect even
though the daemon stays up. easy-rsa's default CRL validity is only 180 days.
"""
import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger("hook_on_startup")

# Daily check interval for the CRL renewal loop.
_CRL_CHECK_INTERVAL_SECONDS = 86400

# Guard so repeated module (re)loads don't spawn multiple renewal loops.
_crl_loop_started = False


async def _renew_all_crls():
    """Renew the CRL of every server instance that is close to expiry."""
    from core.database import async_session_maker
    from modules.openvpn.models import OvpnInstance
    from modules.openvpn.service import OpenVPNService

    async with async_session_maker() as session:
        result = await session.execute(
            select(OvpnInstance).where(OvpnInstance.direction == "server")
        )
        instances = result.scalars().all()

    renewed = 0
    for instance in instances:
        try:
            # Blocking subprocess work (openssl/easyrsa/systemctl) off the loop.
            if await asyncio.to_thread(OpenVPNService.renew_crl_if_needed, instance.id):
                renewed += 1
                logger.info(f"Auto-renewed CRL for OpenVPN instance {instance.name} ({instance.id})")
        except Exception as e:
            logger.error(f"CRL auto-renewal failed for {instance.name} ({instance.id}): {e}", exc_info=True)

    if renewed:
        logger.info(f"OpenVPN CRL renewal: {renewed} instance(s) renewed")


async def _crl_renewal_loop():
    """Check CRL expiry daily, renewing any instance within the threshold window."""
    while True:
        try:
            await _renew_all_crls()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"OpenVPN CRL renewal loop error: {e}", exc_info=True)
        await asyncio.sleep(_CRL_CHECK_INTERVAL_SECONDS)


async def run(session: AsyncSession):
    """Bring up all OpenVPN instances marked enabled=True."""
    global _crl_loop_started
    from modules.openvpn.models import OvpnInstance
    from modules.openvpn.service import OpenVPNService

    result = await session.execute(
        select(OvpnInstance).where(OvpnInstance.enabled == True)  # noqa: E712
    )
    instances = result.scalars().all()

    restored = 0
    for instance in instances:
        try:
            # Idempotent: skip if already active
            if instance.direction == "client":
                already_up = OpenVPNService.get_client_instance_status(instance.id)
            else:
                already_up = OpenVPNService.get_instance_status(instance.id)
            if already_up:
                instance.status = "running"
                continue

            if await OpenVPNService.bring_instance_up(instance, session):
                instance.status = "running"
                restored += 1
                logger.info(f"Restored OpenVPN instance {instance.name} ({instance.id})")
            else:
                logger.error(f"Failed to restore OpenVPN instance {instance.name} ({instance.id})")
        except Exception as e:
            logger.error(f"Error restoring OpenVPN instance {instance.name}: {e}", exc_info=True)

    await session.commit()
    logger.info(f"OpenVPN on_startup: {restored} instance(s) restored ({len(instances)} enabled)")

    # Start the daily CRL auto-renewal loop once. The first iteration also
    # upgrades any legacy 180-day CRL to the long validity window immediately.
    if not _crl_loop_started:
        _crl_loop_started = True
        asyncio.create_task(_crl_renewal_loop())
        logger.info("OpenVPN CRL auto-renewal loop started (daily)")

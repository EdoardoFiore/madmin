"""
strongSwan post_restore hook.

Regenerates all swanctl.conf files from DB data.
Uses existing StrongSwanService.generate_tunnel_config() — no code duplication.
"""
import logging
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger("hook_post_restore")

SWANCTL_CONF_DIR = Path("/etc/swanctl/conf.d")


async def run(session: AsyncSession):
    """Regenerate strongSwan configs from imported DB data."""
    from modules.strongswan.models import IpsecTunnel, IpsecChildSA
    from modules.strongswan.service import StrongSwanService
    
    logger.info("Running strongSwan post_restore hook")
    
    SWANCTL_CONF_DIR.mkdir(parents=True, exist_ok=True)
    
    service = StrongSwanService()
    
    # Get all tunnels
    result = await session.execute(select(IpsecTunnel))
    tunnels = result.scalars().all()
    
    for tunnel in tunnels:
        # Get child SAs for this tunnel
        children_result = await session.execute(
            select(IpsecChildSA).where(IpsecChildSA.tunnel_id == tunnel.id)
        )
        children = children_result.scalars().all()
        
        child_sas = [
            {
                "name": child.name,
                "local_ts": child.local_ts,
                "remote_ts": child.remote_ts,
                "esp_proposal": child.esp_proposal,
                "esp_lifetime": child.esp_lifetime,
                "start_action": child.start_action,
                "close_action": child.close_action
            }
            for child in children
        ]
        
        # Generate config using existing function
        config = service.generate_tunnel_config(
            tunnel_id=tunnel.id,
            name=tunnel.name,
            ike_version=tunnel.ike_version,
            local_address=tunnel.local_address,
            remote_address=tunnel.remote_address,
            local_id=tunnel.local_id,
            remote_id=tunnel.remote_id,
            auth_method=tunnel.auth_method,
            ike_proposal=tunnel.ike_proposal,
            ike_lifetime=tunnel.ike_lifetime,
            dpd_action=tunnel.dpd_action,
            dpd_delay=tunnel.dpd_delay,
            nat_traversal=tunnel.nat_traversal,
            child_sas=child_sas
        )
        
        # Write config file
        config_path = SWANCTL_CONF_DIR / f"madmin_{tunnel.name}.conf"
        config_path.write_text(config)
        
        logger.info(f"Regenerated config for tunnel {tunnel.name}")
    
    logger.info(f"strongSwan post_restore complete: {len(tunnels)} tunnels regenerated")

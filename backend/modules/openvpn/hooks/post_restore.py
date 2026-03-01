"""
OpenVPN post_restore hook.

Regenerates all server.conf files and CCD entries from DB data.
Uses existing OpenVPNService functions — no code duplication.
"""
import logging
import asyncio
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger("hook_post_restore")


async def run(session: AsyncSession):
    """Regenerate OpenVPN configs from imported DB data."""
    from modules.openvpn.models import OvpnInstance, OvpnClient
    from modules.openvpn.service import OpenVPNService
    
    logger.info("Running OpenVPN post_restore hook")
    
    # Get all instances from DB
    result = await session.execute(select(OvpnInstance))
    instances = result.scalars().all()
    
    for instance in instances:
        instance_dir = OpenVPNService.get_instance_dir(instance.id)
        
        # Ensure directories exist
        instance_dir.mkdir(parents=True, exist_ok=True)
        ccd_dir = instance_dir / "ccd"
        ccd_dir.mkdir(exist_ok=True)
        
        from modules.openvpn.service import OPENVPN_BASE_DIR
        
        # Generate server config
        config_content = OpenVPNService.create_server_config(instance)
        config_path = OPENVPN_BASE_DIR / f"{instance.id}.conf"
        config_path.write_text(config_content)
        logger.info(f"Regenerated {instance.id}.conf for instance {instance.name}")
        
        # Regenerate CCD files for all clients with allocated IPs
        clients_result = await session.execute(
            select(OvpnClient).where(OvpnClient.instance_id == instance.id)
        )
        clients = clients_result.scalars().all()
        
        for client in clients:
            if client.allocated_ip:
                OpenVPNService.create_ccd_file(
                    instance.id, client.name, client.allocated_ip
                )
    
    logger.info(f"OpenVPN post_restore complete: {len(instances)} instances regenerated")

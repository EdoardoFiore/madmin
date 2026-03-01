"""
WireGuard post_restore hook.

Regenerates all WireGuard .conf files from DB data.
Uses existing WireGuardService functions — no code duplication.
"""
import logging
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger("hook_post_restore")

WG_CONFIG_DIR = Path("/etc/wireguard")


async def run(session: AsyncSession):
    """Regenerate WireGuard configs from imported DB data."""
    from modules.wireguard.models import WgInstance, WgClient
    from modules.wireguard.service import WireGuardService
    
    logger.info("Running WireGuard post_restore hook")
    
    WG_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    # Get all instances
    result = await session.execute(select(WgInstance))
    instances = result.scalars().all()
    
    for instance in instances:
        # Generate server [Interface] section
        config = WireGuardService.create_server_config(
            interface=instance.interface,
            port=instance.port,
            private_key=instance.private_key,
            address=instance.address
        )
        
        # Add [Peer] sections for all clients
        clients_result = await session.execute(
            select(WgClient).where(WgClient.instance_id == instance.id)
        )
        clients = clients_result.scalars().all()
        
        for client in clients:
            if not client.enabled:
                continue
            
            peer_section = f"\n[Peer]\n"
            peer_section += f"# {client.name}\n"
            peer_section += f"PublicKey = {client.public_key}\n"
            
            if client.preshared_key:
                peer_section += f"PresharedKey = {client.preshared_key}\n"
            
            peer_section += f"AllowedIPs = {client.allocated_ip}/32\n"
            config += peer_section
        
        # Write config file
        config_path = WG_CONFIG_DIR / f"{instance.interface}.conf"
        config_path.write_text(config)
        config_path.chmod(0o600)
        
        logger.info(f"Regenerated {instance.interface}.conf with {len(clients)} peers")
    
    logger.info(f"WireGuard post_restore complete: {len(instances)} instances regenerated")

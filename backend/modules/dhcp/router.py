"""
DHCP Module - API Router

FastAPI endpoints for DHCP server management.
"""
import logging
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from core.database import get_session
from core.auth.models import User
from core.auth.dependencies import require_permission

from .models import (
    DhcpSubnet, DhcpHost, DhcpOption,
    DhcpSubnetCreate, DhcpSubnetRead, DhcpSubnetUpdate,
    DhcpHostCreate, DhcpHostRead, DhcpHostUpdate,
    DhcpOptionCreate, DhcpOptionRead,
    DhcpLeaseInfo, DhcpServiceStatus
)
from .service import dhcp_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
#  SYSTEM / SERVICE
# ============================================================

@router.get("/status", response_model=DhcpServiceStatus)
async def get_status(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.view"))
):
    """Get DHCP service status and statistics."""
    svc = dhcp_service.get_service_status()

    # Count subnets
    result = await session.execute(select(func.count(DhcpSubnet.id)))
    total_subnets = result.scalar() or 0

    # Count hosts
    result = await session.execute(select(func.count(DhcpHost.id)))
    total_hosts = result.scalar() or 0

    # Count active leases
    leases = dhcp_service.parse_leases()
    total_leases = len(leases)

    # Validate config
    config_valid = None
    try:
        valid, _ = dhcp_service.validate_config()
        config_valid = valid
    except:
        pass

    return DhcpServiceStatus(
        running=svc["running"],
        enabled=svc["enabled"],
        uptime=svc.get("uptime"),
        total_subnets=total_subnets,
        total_hosts=total_hosts,
        total_leases=total_leases,
        config_valid=config_valid
    )


@router.get("/interfaces")
async def get_interfaces(
    _user: User = Depends(require_permission("dhcp.view"))
):
    """List available network interfaces."""
    interfaces = dhcp_service.get_physical_interfaces()
    return {"interfaces": interfaces}


@router.post("/apply")
async def apply_config(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.manage"))
):
    """Generate config, validate, and restart service."""
    success, message = await dhcp_service.apply_config(session)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )
    return {"message": message}


@router.post("/start")
async def start_service(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.manage"))
):
    """Start DHCP service (applies config first)."""
    # Check for enabled subnets
    result = await session.execute(
        select(func.count(DhcpSubnet.id)).where(DhcpSubnet.enabled == True)
    )
    if (result.scalar() or 0) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossibile avviare: nessuna subnet abilitata configurata"
        )

    # Apply config before starting
    success, message = await dhcp_service.apply_config(session)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )
    return {"message": message}


@router.post("/stop")
async def stop_service(
    _user: User = Depends(require_permission("dhcp.manage"))
):
    """Stop DHCP service."""
    success, message = dhcp_service.stop_service()
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )
    return {"message": message}


@router.post("/restart")
async def restart_service(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.manage"))
):
    """Restart DHCP service (re-applies config)."""
    # Check for enabled subnets
    result = await session.execute(
        select(func.count(DhcpSubnet.id)).where(DhcpSubnet.enabled == True)
    )
    if (result.scalar() or 0) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossibile riavviare: nessuna subnet abilitata configurata"
        )

    # Apply config before restarting
    success, message = await dhcp_service.apply_config(session)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )
    return {"message": message}


@router.get("/config/preview")
async def preview_config(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.manage"))
):
    """Preview the generated dhcpd.conf without applying."""
    config = await dhcp_service.generate_config(session)
    return {"config": config}


@router.get("/config/validate")
async def validate_config(
    _user: User = Depends(require_permission("dhcp.manage"))
):
    """Validate current dhcpd.conf syntax."""
    valid, message = dhcp_service.validate_config()
    return {"valid": valid, "message": message}


# ============================================================
#  SUBNETS
# ============================================================

@router.get("/subnets", response_model=List[DhcpSubnetRead])
async def list_subnets(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.view"))
):
    """List all DHCP subnets."""
    result = await session.execute(select(DhcpSubnet))
    subnets = result.scalars().all()

    # Get active leases for enrichment
    all_leases = dhcp_service.parse_leases()

    response = []
    for subnet in subnets:
        # Count hosts
        host_result = await session.execute(
            select(func.count(DhcpHost.id)).where(
                DhcpHost.subnet_id == subnet.id
            )
        )
        host_count = host_result.scalar() or 0

        # Count leases in this subnet
        subnet_leases = dhcp_service.get_leases_for_subnet(subnet.network)
        active_leases = len(subnet_leases)

        response.append(DhcpSubnetRead(
            id=subnet.id,
            name=subnet.name,
            network=subnet.network,
            range_start=subnet.range_start,
            range_end=subnet.range_end,
            gateway=subnet.gateway,
            dns_servers=subnet.dns_servers,
            domain_name=subnet.domain_name,
            interface=subnet.interface,
            lease_time=subnet.lease_time,
            max_lease_time=subnet.max_lease_time,
            enabled=subnet.enabled,
            created_at=subnet.created_at,
            host_count=host_count,
            active_leases=active_leases
        ))

    return response


@router.post("/subnets", response_model=DhcpSubnetRead,
             status_code=status.HTTP_201_CREATED)
async def create_subnet(
    data: DhcpSubnetCreate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.manage"))
):
    """Create a new DHCP subnet."""
    # Validate IP range
    valid, msg = dhcp_service.validate_ip_range(
        data.range_start, data.range_end, data.network
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg
        )

    # Validate gateway in subnet
    if not dhcp_service.validate_ip_in_subnet(data.gateway, data.network):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Gateway {data.gateway} is not in subnet {data.network}"
        )

    subnet = DhcpSubnet(**data.dict())
    session.add(subnet)
    await session.commit()
    await session.refresh(subnet)

    return DhcpSubnetRead(
        **subnet.dict(),
        host_count=0,
        active_leases=0
    )


@router.get("/subnets/{subnet_id}", response_model=DhcpSubnetRead)
async def get_subnet(
    subnet_id: UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.view"))
):
    """Get a single subnet by ID."""
    result = await session.execute(
        select(DhcpSubnet).where(DhcpSubnet.id == subnet_id)
    )
    subnet = result.scalar_one_or_none()
    if not subnet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subnet not found"
        )

    # Count hosts
    host_result = await session.execute(
        select(func.count(DhcpHost.id)).where(
            DhcpHost.subnet_id == subnet.id
        )
    )
    host_count = host_result.scalar() or 0

    # Count leases
    subnet_leases = dhcp_service.get_leases_for_subnet(subnet.network)

    return DhcpSubnetRead(
        **subnet.dict(),
        host_count=host_count,
        active_leases=len(subnet_leases)
    )


@router.patch("/subnets/{subnet_id}", response_model=DhcpSubnetRead)
async def update_subnet(
    subnet_id: UUID,
    data: DhcpSubnetUpdate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.manage"))
):
    """Update a subnet."""
    result = await session.execute(
        select(DhcpSubnet).where(DhcpSubnet.id == subnet_id)
    )
    subnet = result.scalar_one_or_none()
    if not subnet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subnet not found"
        )

    update_data = data.dict(exclude_unset=True)

    # If range or network changed, validate
    new_network = update_data.get("network", subnet.network)
    new_start = update_data.get("range_start", subnet.range_start)
    new_end = update_data.get("range_end", subnet.range_end)

    if "range_start" in update_data or "range_end" in update_data:
        valid, msg = dhcp_service.validate_ip_range(
            new_start, new_end, new_network
        )
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=msg
            )

    if "gateway" in update_data:
        if not dhcp_service.validate_ip_in_subnet(
            update_data["gateway"], new_network
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Gateway is not in subnet"
            )

    for key, value in update_data.items():
        setattr(subnet, key, value)

    session.add(subnet)
    await session.commit()
    await session.refresh(subnet)

    host_result = await session.execute(
        select(func.count(DhcpHost.id)).where(
            DhcpHost.subnet_id == subnet.id
        )
    )
    host_count = host_result.scalar() or 0
    subnet_leases = dhcp_service.get_leases_for_subnet(subnet.network)

    return DhcpSubnetRead(
        **subnet.dict(),
        host_count=host_count,
        active_leases=len(subnet_leases)
    )


@router.delete("/subnets/{subnet_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def delete_subnet(
    subnet_id: UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.manage"))
):
    """Delete a subnet and its hosts/options."""
    result = await session.execute(
        select(DhcpSubnet).where(DhcpSubnet.id == subnet_id)
    )
    subnet = result.scalar_one_or_none()
    if not subnet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subnet not found"
        )

    await session.delete(subnet)
    await session.commit()


# ============================================================
#  HOSTS (RESERVATIONS)
# ============================================================

@router.get("/subnets/{subnet_id}/hosts", response_model=List[DhcpHostRead])
async def list_hosts(
    subnet_id: UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.view"))
):
    """List static reservations for a subnet."""
    # Verify subnet exists
    result = await session.execute(
        select(DhcpSubnet).where(DhcpSubnet.id == subnet_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subnet not found"
        )

    result = await session.execute(
        select(DhcpHost).where(DhcpHost.subnet_id == subnet_id)
    )
    return result.scalars().all()


@router.post("/subnets/{subnet_id}/hosts", response_model=DhcpHostRead,
             status_code=status.HTTP_201_CREATED)
async def create_host(
    subnet_id: UUID,
    data: DhcpHostCreate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.reservations"))
):
    """Create a static reservation."""
    # Verify subnet exists
    result = await session.execute(
        select(DhcpSubnet).where(DhcpSubnet.id == subnet_id)
    )
    subnet = result.scalar_one_or_none()
    if not subnet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subnet not found"
        )

    # Validate MAC format
    if not dhcp_service.validate_mac_address(data.mac_address):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid MAC address format (expected AA:BB:CC:DD:EE:FF)"
        )

    # Validate IP in subnet
    if not dhcp_service.validate_ip_in_subnet(
        data.ip_address, subnet.network
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"IP {data.ip_address} is not in subnet {subnet.network}"
        )

    # Check for duplicate MAC or IP in this subnet
    result = await session.execute(
        select(DhcpHost).where(
            DhcpHost.subnet_id == subnet_id,
            DhcpHost.mac_address == data.mac_address.lower()
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MAC address already reserved in this subnet"
        )

    result = await session.execute(
        select(DhcpHost).where(
            DhcpHost.subnet_id == subnet_id,
            DhcpHost.ip_address == data.ip_address
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="IP address already reserved in this subnet"
        )

    host = DhcpHost(
        subnet_id=subnet_id,
        hostname=data.hostname,
        mac_address=data.mac_address.lower(),
        ip_address=data.ip_address,
        description=data.description
    )
    session.add(host)
    await session.commit()
    await session.refresh(host)

    return host


@router.patch("/subnets/{subnet_id}/hosts/{host_id}",
              response_model=DhcpHostRead)
async def update_host(
    subnet_id: UUID,
    host_id: UUID,
    data: DhcpHostUpdate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.reservations"))
):
    """Update a static reservation."""
    result = await session.execute(
        select(DhcpHost).where(
            DhcpHost.id == host_id,
            DhcpHost.subnet_id == subnet_id
        )
    )
    host = result.scalar_one_or_none()
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found"
        )

    update_data = data.dict(exclude_unset=True)

    # Validate MAC if changed
    if "mac_address" in update_data:
        if not dhcp_service.validate_mac_address(update_data["mac_address"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid MAC address format"
            )
        update_data["mac_address"] = update_data["mac_address"].lower()

    # Validate IP if changed
    if "ip_address" in update_data:
        result = await session.execute(
            select(DhcpSubnet).where(DhcpSubnet.id == subnet_id)
        )
        subnet = result.scalar_one_or_none()
        if subnet and not dhcp_service.validate_ip_in_subnet(
            update_data["ip_address"], subnet.network
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="IP is not in subnet"
            )

    for key, value in update_data.items():
        setattr(host, key, value)

    session.add(host)
    await session.commit()
    await session.refresh(host)

    return host


@router.delete("/subnets/{subnet_id}/hosts/{host_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def delete_host(
    subnet_id: UUID,
    host_id: UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.reservations"))
):
    """Delete a static reservation."""
    result = await session.execute(
        select(DhcpHost).where(
            DhcpHost.id == host_id,
            DhcpHost.subnet_id == subnet_id
        )
    )
    host = result.scalar_one_or_none()
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found"
        )

    await session.delete(host)
    await session.commit()


# ============================================================
#  LEASES
# ============================================================

@router.get("/leases", response_model=List[DhcpLeaseInfo])
async def list_leases(
    _user: User = Depends(require_permission("dhcp.view"))
):
    """List all active DHCP leases."""
    return dhcp_service.parse_leases()


@router.get("/subnets/{subnet_id}/leases",
            response_model=List[DhcpLeaseInfo])
async def list_subnet_leases(
    subnet_id: UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.view"))
):
    """List active leases for a specific subnet."""
    result = await session.execute(
        select(DhcpSubnet).where(DhcpSubnet.id == subnet_id)
    )
    subnet = result.scalar_one_or_none()
    if not subnet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subnet not found"
        )

    return dhcp_service.get_leases_for_subnet(subnet.network)


# ============================================================
#  OPTIONS
# ============================================================

@router.get("/options", response_model=List[DhcpOptionRead])
async def list_options(
    subnet_id: Optional[UUID] = None,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.view"))
):
    """
    List DHCP options.
    If subnet_id is provided, returns options for that subnet.
    If not, returns global options.
    """
    if subnet_id:
        result = await session.execute(
            select(DhcpOption).where(DhcpOption.subnet_id == subnet_id)
        )
    else:
        result = await session.execute(
            select(DhcpOption).where(DhcpOption.subnet_id == None)
        )
    return result.scalars().all()


@router.post("/options", response_model=DhcpOptionRead,
             status_code=status.HTTP_201_CREATED)
async def create_option(
    data: DhcpOptionCreate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.manage"))
):
    """Create a DHCP option (global or per-subnet)."""
    if data.subnet_id:
        result = await session.execute(
            select(DhcpSubnet).where(DhcpSubnet.id == data.subnet_id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subnet not found"
            )

    option = DhcpOption(**data.dict())
    session.add(option)
    await session.commit()
    await session.refresh(option)

    return option


@router.delete("/options/{option_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def delete_option(
    option_id: UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dhcp.manage"))
):
    """Delete a DHCP option."""
    result = await session.execute(
        select(DhcpOption).where(DhcpOption.id == option_id)
    )
    option = result.scalar_one_or_none()
    if not option:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Option not found"
        )

    await session.delete(option)
    await session.commit()

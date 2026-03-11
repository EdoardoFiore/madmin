"""
DNS Module - API Router

FastAPI endpoints for DNS server management.
"""
import json
import logging
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from sqlalchemy.orm import selectinload

from core.database import get_session
from core.auth.dependencies import require_permission
from core.auth.models import User

from .models import (
    DnsSettings, DnsSettingsUpdate,
    DnsZone, DnsZoneCreate, DnsZoneRead, DnsZoneUpdate,
    DnsRecord, DnsRecordCreate, DnsRecordRead, DnsRecordUpdate,
    DnsForwarder, DnsForwarderCreate, DnsForwarderRead, DnsForwarderUpdate,
)
from .service import dns_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
#  SERVICE STATUS & CONTROL
# ============================================================

@router.get("/status")
async def get_status(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.view")),
):
    """Get DNS service status and statistics."""
    svc_status = dns_service.get_service_status()
    stats = await dns_service.get_statistics(session)
    settings = await dns_service.get_or_create_settings(session)

    return {
        **svc_status,
        **stats,
        "mode": settings.mode,
    }


@router.post("/apply")
async def apply_config(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.manage")),
):
    """Generate config, validate, apply firewall, restart bind9."""
    success, msg = await dns_service.apply_config(session)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"message": msg}


@router.post("/start")
async def start_service(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.manage")),
):
    """Start bind9 (applies config first)."""
    # Write & validate config before starting
    ok, msg = await dns_service.write_all_configs(session)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    valid, msg = dns_service.validate_config()
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    dns_service.apply_firewall_rules()

    ok, msg = dns_service.start_service()
    if not ok:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)
    return {"message": "Servizio DNS avviato"}


@router.post("/stop")
async def stop_service(
    _user: User = Depends(require_permission("dns.manage")),
):
    """Stop bind9."""
    ok, msg = dns_service.stop_service()
    if not ok:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)
    return {"message": "Servizio DNS arrestato"}


@router.post("/restart")
async def restart_service(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.manage")),
):
    """Restart bind9 (re-applies config)."""
    success, msg = await dns_service.apply_config(session)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"message": "Servizio DNS riavviato"}


@router.get("/interfaces")
async def get_interfaces(
    _user: User = Depends(require_permission("dns.view")),
):
    """List available network interfaces for listening."""
    return dns_service.get_physical_interfaces()


# ============================================================
#  SETTINGS
# ============================================================

@router.get("/settings")
async def get_settings(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.view")),
):
    """Get global DNS settings."""
    settings = await dns_service.get_or_create_settings(session)
    return {
        "id": str(settings.id),
        "mode": settings.mode,
        "listen_interfaces": settings.listen_interfaces,
        "system_forwarders": settings.system_forwarders,
        "allow_query": settings.allow_query,
        "dnssec_validation": settings.dnssec_validation,
    }


@router.put("/settings")
async def update_settings(
    data: DnsSettingsUpdate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.manage")),
):
    """Update global DNS settings."""
    # Validate mode
    valid_modes = {"recursive", "forward_only", "non_recursive"}
    if data.mode and data.mode not in valid_modes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Modalità non valida. Valide: {', '.join(valid_modes)}"
        )

    settings = await dns_service.update_settings(session, data.dict(exclude_unset=True))
    return {
        "id": str(settings.id),
        "mode": settings.mode,
        "listen_interfaces": settings.listen_interfaces,
        "system_forwarders": settings.system_forwarders,
        "allow_query": settings.allow_query,
        "dnssec_validation": settings.dnssec_validation,
    }


# ============================================================
#  ZONES
# ============================================================

@router.get("/zones")
async def list_zones(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.view")),
):
    """List all DNS zones with record count."""
    result = await session.execute(
        select(DnsZone).options(selectinload(DnsZone.records)).order_by(DnsZone.name)
    )
    zones = result.scalars().all()

    return [
        {
            "id": str(z.id),
            "name": z.name,
            "zone_type": z.zone_type,
            "enabled": z.enabled,
            "ttl_default": z.ttl_default,
            "forward_servers": z.forward_servers,
            "description": z.description,
            "created_at": z.created_at.isoformat(),
            "record_count": len(z.records),
        }
        for z in zones
    ]


@router.post("/zones", status_code=status.HTTP_201_CREATED)
async def create_zone(
    data: DnsZoneCreate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.zones")),
):
    """Create a new DNS zone."""
    # Validate name
    valid, msg = dns_service.validate_zone_name(data.name)
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    # Check uniqueness
    existing = await session.execute(
        select(DnsZone).where(DnsZone.name == data.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La zona '{data.name}' esiste già"
        )

    # Validate zone type
    if data.zone_type not in ("master", "forward", "stub"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tipo zona non valido. Validi: master, forward, stub"
        )

    zone = DnsZone(**data.dict())
    session.add(zone)
    await session.commit()
    await session.refresh(zone)

    return {
        "id": str(zone.id),
        "name": zone.name,
        "zone_type": zone.zone_type,
        "enabled": zone.enabled,
        "description": zone.description,
        "created_at": zone.created_at.isoformat(),
        "record_count": 0,
    }


@router.get("/zones/{zone_id}")
async def get_zone(
    zone_id: UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.view")),
):
    """Get a zone with all its records."""
    result = await session.execute(
        select(DnsZone).where(DnsZone.id == zone_id)
            .options(selectinload(DnsZone.records))
    )
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zona non trovata")

    return {
        "id": str(zone.id),
        "name": zone.name,
        "zone_type": zone.zone_type,
        "enabled": zone.enabled,
        "ttl_default": zone.ttl_default,
        "soa_refresh": zone.soa_refresh,
        "soa_retry": zone.soa_retry,
        "soa_expire": zone.soa_expire,
        "soa_minimum": zone.soa_minimum,
        "forward_servers": zone.forward_servers,
        "description": zone.description,
        "created_at": zone.created_at.isoformat(),
        "records": [
            {
                "id": str(r.id),
                "record_type": r.record_type,
                "name": r.name,
                "value": r.value,
                "ttl": r.ttl,
                "priority": r.priority,
                "weight": r.weight,
                "port": r.port,
                "created_at": r.created_at.isoformat(),
            }
            for r in zone.records
        ],
    }


@router.patch("/zones/{zone_id}")
async def update_zone(
    zone_id: UUID,
    data: DnsZoneUpdate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.zones")),
):
    """Update a DNS zone."""
    result = await session.execute(select(DnsZone).where(DnsZone.id == zone_id))
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zona non trovata")

    update_data = data.dict(exclude_unset=True)

    if "name" in update_data:
        valid, msg = dns_service.validate_zone_name(update_data["name"])
        if not valid:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    for key, value in update_data.items():
        setattr(zone, key, value)

    session.add(zone)
    await session.commit()
    await session.refresh(zone)

    return {"message": "Zona aggiornata", "id": str(zone.id)}


@router.delete("/zones/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_zone(
    zone_id: UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.zones")),
):
    """Delete a DNS zone and all its records."""
    result = await session.execute(select(DnsZone).where(DnsZone.id == zone_id))
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zona non trovata")

    await session.delete(zone)
    await session.commit()


# ============================================================
#  RECORDS
# ============================================================

@router.get("/zones/{zone_id}/records")
async def list_records(
    zone_id: UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.view")),
):
    """List all records in a zone."""
    result = await session.execute(
        select(DnsRecord).where(DnsRecord.zone_id == zone_id).order_by(DnsRecord.name)
    )
    records = result.scalars().all()

    return [
        {
            "id": str(r.id),
            "zone_id": str(r.zone_id),
            "record_type": r.record_type,
            "name": r.name,
            "value": r.value,
            "ttl": r.ttl,
            "priority": r.priority,
            "weight": r.weight,
            "port": r.port,
            "created_at": r.created_at.isoformat(),
        }
        for r in records
    ]


@router.post("/zones/{zone_id}/records", status_code=status.HTTP_201_CREATED)
async def create_record(
    zone_id: UUID,
    data: DnsRecordCreate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.records")),
):
    """Create a DNS record in a zone."""
    # Verify zone exists
    result = await session.execute(select(DnsZone).where(DnsZone.id == zone_id))
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zona non trovata")

    if zone.zone_type != "master":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="I record si possono aggiungere solo a zone di tipo master"
        )

    # Validate record
    valid, msg = dns_service.validate_record(data.record_type, data.name, data.value)
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    record = DnsRecord(zone_id=zone_id, **data.dict())
    session.add(record)
    await session.commit()
    await session.refresh(record)

    return {
        "id": str(record.id),
        "zone_id": str(record.zone_id),
        "record_type": record.record_type,
        "name": record.name,
        "value": record.value,
        "ttl": record.ttl,
        "priority": record.priority,
        "weight": record.weight,
        "port": record.port,
        "created_at": record.created_at.isoformat(),
    }


@router.patch("/records/{record_id}")
async def update_record(
    record_id: UUID,
    data: DnsRecordUpdate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.records")),
):
    """Update a DNS record."""
    result = await session.execute(select(DnsRecord).where(DnsRecord.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record non trovato")

    update_data = data.dict(exclude_unset=True)

    # Validate if type or value changed
    new_type = update_data.get("record_type", record.record_type)
    new_name = update_data.get("name", record.name)
    new_value = update_data.get("value", record.value)
    valid, msg = dns_service.validate_record(new_type, new_name, new_value)
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    for key, value in update_data.items():
        setattr(record, key, value)

    session.add(record)
    await session.commit()
    return {"message": "Record aggiornato", "id": str(record.id)}


@router.delete("/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(
    record_id: UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.records")),
):
    """Delete a DNS record."""
    result = await session.execute(select(DnsRecord).where(DnsRecord.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record non trovato")

    await session.delete(record)
    await session.commit()


# ============================================================
#  FORWARDERS
# ============================================================

@router.get("/forwarders")
async def list_forwarders(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.view")),
):
    """List conditional forwarders."""
    result = await session.execute(
        select(DnsForwarder).order_by(DnsForwarder.domain)
    )
    items = result.scalars().all()

    return [
        {
            "id": str(f.id),
            "domain": f.domain,
            "servers": f.servers,
            "enabled": f.enabled,
            "description": f.description,
            "created_at": f.created_at.isoformat(),
        }
        for f in items
    ]


@router.post("/forwarders", status_code=status.HTTP_201_CREATED)
async def create_forwarder(
    data: DnsForwarderCreate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.manage")),
):
    """Create a conditional forwarder."""
    valid, msg = dns_service.validate_zone_name(data.domain)
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    # Parse/validate servers JSON
    try:
        servers = json.loads(data.servers)
        if not isinstance(servers, list) or not servers:
            raise ValueError()
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="servers deve essere un array JSON di indirizzi IP"
        )

    fwd = DnsForwarder(**data.dict())
    session.add(fwd)
    await session.commit()
    await session.refresh(fwd)

    return {
        "id": str(fwd.id),
        "domain": fwd.domain,
        "servers": fwd.servers,
        "enabled": fwd.enabled,
        "description": fwd.description,
        "created_at": fwd.created_at.isoformat(),
    }


@router.patch("/forwarders/{fwd_id}")
async def update_forwarder(
    fwd_id: UUID,
    data: DnsForwarderUpdate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.manage")),
):
    """Update a conditional forwarder."""
    result = await session.execute(select(DnsForwarder).where(DnsForwarder.id == fwd_id))
    fwd = result.scalar_one_or_none()
    if not fwd:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Forwarder non trovato")

    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(fwd, key, value)

    session.add(fwd)
    await session.commit()
    return {"message": "Forwarder aggiornato", "id": str(fwd.id)}


@router.delete("/forwarders/{fwd_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_forwarder(
    fwd_id: UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.manage")),
):
    """Delete a conditional forwarder."""
    result = await session.execute(select(DnsForwarder).where(DnsForwarder.id == fwd_id))
    fwd = result.scalar_one_or_none()
    if not fwd:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Forwarder non trovato")

    await session.delete(fwd)
    await session.commit()


# ============================================================
#  DNS TEST
# ============================================================

class DnsTestRequest(BaseModel):
    domain: str
    record_type: str = "A"


@router.post("/test")
async def test_dns_query(
    data: DnsTestRequest,
    _user: User = Depends(require_permission("dns.view")),
):
    """Test a DNS query against the local server."""
    return dns_service.test_query(data.domain, data.record_type)

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
)
from .service import dns_service
from core.network.service import NetworkService

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
    # Persist desired state: service should be running (restored on app startup)
    settings = await dns_service.get_or_create_settings(session)
    settings.service_enabled = True
    await session.commit()
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
    # Persist desired state: service should be running (restored on app startup)
    settings = await dns_service.get_or_create_settings(session)
    settings.service_enabled = True
    await session.commit()
    return {"message": "Servizio DNS avviato"}


@router.post("/stop")
async def stop_service(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.manage")),
):
    """Stop bind9."""
    ok, msg = dns_service.stop_service()
    if not ok:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)
    # Persist desired state: must stay DOWN across restarts
    settings = await dns_service.get_or_create_settings(session)
    settings.service_enabled = False
    await session.commit()
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
    # Persist desired state: service should be running (restored on app startup)
    settings = await dns_service.get_or_create_settings(session)
    settings.service_enabled = True
    await session.commit()
    return {"message": "Servizio DNS riavviato"}


@router.get("/interfaces")
async def get_interfaces(
    _user: User = Depends(require_permission("dns.view")),
):
    """List available network interfaces for listening."""
    return NetworkService.get_interfaces()


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

    # Auto-apply: rewrite named.conf.options + reload
    apply_ok, apply_msg = await dns_service.apply_settings_only(session)

    return {
        "id": str(settings.id),
        "mode": settings.mode,
        "listen_interfaces": settings.listen_interfaces,
        "system_forwarders": settings.system_forwarders,
        "allow_query": settings.allow_query,
        "dnssec_validation": settings.dnssec_validation,
        "applied": apply_ok,
        "apply_message": apply_msg,
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

    # Validate zone type and forward servers
    if data.zone_type not in ("master", "forward", "stub"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tipo zona non valido. Validi: master, forward, stub"
        )
        
    if data.zone_type in ("forward", "stub"):
        if not data.forward_servers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="I server DNS remoti sono obbligatori per le zone forward/stub"
            )
        try:
            servers = json.loads(data.forward_servers)
            if not isinstance(servers, list) or not servers:
                raise ValueError()
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="servers deve essere un array JSON valido di indirizzi IP"
            )

    zone = DnsZone(**data.dict())
    session.add(zone)
    await session.commit()
    await session.refresh(zone)

    # Auto-apply: write zone file + update named.conf.local + reload
    apply_ok, apply_msg = await dns_service.apply_single_zone(session, zone)

    return {
        "id": str(zone.id),
        "name": zone.name,
        "zone_type": zone.zone_type,
        "enabled": zone.enabled,
        "description": zone.description,
        "created_at": zone.created_at.isoformat(),
        "record_count": 0,
        "applied": apply_ok,
        "apply_message": apply_msg,
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
            
    # Validate forward servers if changing zone type or servers
    new_type = update_data.get("zone_type", zone.zone_type)
    if new_type in ("forward", "stub"):
        new_servers = update_data.get("forward_servers", zone.forward_servers)
        if not new_servers:
             raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="I server DNS remoti sono obbligatori per le zone forward/stub"
            )
        try:
            servers = json.loads(new_servers)
            if not isinstance(servers, list) or not servers:
                 raise ValueError()
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="servers deve essere un array JSON valido di indirizzi IP"
            )

    for key, value in update_data.items():
        setattr(zone, key, value)

    session.add(zone)
    await session.commit()
    await session.refresh(zone)

    # Auto-apply: update zone file + reload
    apply_ok, apply_msg = await dns_service.apply_single_zone(session, zone)

    return {
        "message": "Zona aggiornata",
        "id": str(zone.id),
        "applied": apply_ok,
        "apply_message": apply_msg,
    }


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

    zone_name = zone.name
    await session.delete(zone)
    await session.commit()

    # Auto-apply: remove zone file + update named.conf.local + reload
    await dns_service.remove_zone_files(zone_name, session)


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
    """Create a DNS record in a zone (with pre-commit zone validation)."""
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

    # Basic record validation
    valid, msg = dns_service.validate_record(data.record_type, data.name, data.value)
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    # Add record to session WITHOUT committing
    record = DnsRecord(zone_id=zone_id, **data.dict())
    session.add(record)
    await session.flush()  # sends to DB but keeps transaction open

    # Validate zone with temp file (includes the new record via flushed session)
    valid, validation_msg = await dns_service.validate_zone_temp(session, zone)
    if not valid:
        # Zone invalid → rollback the record, return error
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Record non valido per la zona: {validation_msg}"
        )

    # Zone valid → commit and apply
    await session.commit()
    await session.refresh(record)

    # Auto-apply: rewrite zone file, reload
    apply_ok, apply_msg = await dns_service.apply_single_zone(session, zone)

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
        "applied": apply_ok,
        "apply_message": apply_msg,
    }


@router.patch("/records/{record_id}")
async def update_record(
    record_id: UUID,
    data: DnsRecordUpdate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("dns.records")),
):
    """Update a DNS record (with pre-commit zone validation)."""
    result = await session.execute(select(DnsRecord).where(DnsRecord.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record non trovato")

    update_data = data.dict(exclude_unset=True)

    # Basic record validation
    new_type = update_data.get("record_type", record.record_type)
    new_name = update_data.get("name", record.name)
    new_value = update_data.get("value", record.value)
    valid, msg = dns_service.validate_record(new_type, new_name, new_value)
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    for key, value in update_data.items():
        setattr(record, key, value)

    session.add(record)
    await session.flush()  # sends to DB but keeps transaction open

    # Validate zone with temp file (includes updated record)
    zone_result = await session.execute(select(DnsZone).where(DnsZone.id == record.zone_id))
    zone = zone_result.scalar_one_or_none()
    if zone and zone.zone_type == "master":
        valid, validation_msg = await dns_service.validate_zone_temp(session, zone)
        if not valid:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Record non valido per la zona: {validation_msg}"
            )

    # Zone valid → commit and apply
    await session.commit()

    apply_ok, apply_msg = False, "Zona non trovata"
    if zone:
        apply_ok, apply_msg = await dns_service.apply_single_zone(session, zone)

    return {
        "message": "Record aggiornato",
        "id": str(record.id),
        "applied": apply_ok,
        "apply_message": apply_msg,
    }


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

    zone_id = record.zone_id
    await session.delete(record)
    await session.commit()

    # Auto-apply: rewrite the parent zone + reload
    zone_result = await session.execute(select(DnsZone).where(DnsZone.id == zone_id))
    zone = zone_result.scalar_one_or_none()
    if zone:
        apply_ok, apply_msg = await dns_service.apply_single_zone(session, zone)
        if not apply_ok:
            logger.warning(f"apply_single_zone after record delete failed: {apply_msg}")


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

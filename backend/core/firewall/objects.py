"""
MADMIN Firewall Objects Service

CRUD and resolution for FirewallObject aliases.

Resolution rules:
  host/network  → single inline value
  range         → nft set (two IPs expanded to range syntax)
  fqdn          → resolved to IPs at apply time (DNS lookup)
  group         → flat union of member objects (recursive)
  service       → (protocol, port) tuple inline
  service_group → flat union of member service objects
"""
import logging
import re
import socket
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
import uuid

from .models import FirewallObject, FirewallObjectType

logger = logging.getLogger(__name__)


def nft_set_name(obj: FirewallObject) -> str:
    """Build deterministic nft set name for a multi-value object.  Max 31 chars."""
    sanitized = re.sub(r'[^A-Z0-9_]', '_', obj.name.upper())[:20]
    return f"FWOBJ_{sanitized}"


def _is_multi_value(obj: FirewallObject) -> bool:
    return obj.type in (
        FirewallObjectType.RANGE,
        FirewallObjectType.FQDN,
        FirewallObjectType.GROUP,
        FirewallObjectType.SERVICE_GROUP,
    )


class FirewallObjectService:

    @staticmethod
    async def get_all(session: AsyncSession) -> List[FirewallObject]:
        result = await session.execute(
            select(FirewallObject).order_by(FirewallObject.name)
        )
        return result.scalars().all()

    @staticmethod
    async def get_by_id(
        session: AsyncSession, obj_id: uuid.UUID
    ) -> Optional[FirewallObject]:
        result = await session.execute(
            select(FirewallObject).where(FirewallObject.id == obj_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_ids(
        session: AsyncSession, ids
    ) -> Dict[uuid.UUID, FirewallObject]:
        if not ids:
            return {}
        result = await session.execute(
            select(FirewallObject).where(FirewallObject.id.in_(ids))
        )
        return {obj.id: obj for obj in result.scalars().all()}

    @staticmethod
    async def create(
        session: AsyncSession, data: dict
    ) -> FirewallObject:
        obj = FirewallObject(
            name=data["name"],
            type=FirewallObjectType(data["type"]),
            value=data.get("value"),
            members=data.get("members"),
            comment=data.get("comment"),
            color=data.get("color"),
        )
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        logger.info(f"Created firewall object '{obj.name}' ({obj.type})")
        return obj

    @staticmethod
    async def update(
        session: AsyncSession, obj_id: uuid.UUID, data: dict
    ) -> Optional[FirewallObject]:
        result = await session.execute(
            select(FirewallObject).where(FirewallObject.id == obj_id)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            return None
        for k, v in data.items():
            if v is not None and hasattr(obj, k):
                setattr(obj, k, v)
        obj.updated_at = datetime.utcnow()
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    @staticmethod
    async def delete(session: AsyncSession, obj_id: uuid.UUID) -> bool:
        result = await session.execute(
            select(FirewallObject).where(FirewallObject.id == obj_id)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            return False
        await session.delete(obj)
        await session.flush()
        logger.info(f"Deleted firewall object '{obj.name}'")
        return True

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    @staticmethod
    async def resolve_address(
        session: AsyncSession,
        obj: FirewallObject,
        cache: Optional[Dict[uuid.UUID, FirewallObject]] = None,
        _depth: int = 0,
    ) -> List[str]:
        """
        Resolve an address object to a flat list of IP strings / CIDRs.
        Returns [] on error or unsupported type.
        GROUP resolution is recursive (max depth 8).
        """
        if _depth > 8:
            logger.warning(f"Max recursion depth for object group '{obj.name}'")
            return []

        if obj.type == FirewallObjectType.HOST:
            return [obj.value] if obj.value else []

        if obj.type == FirewallObjectType.NETWORK:
            return [obj.value] if obj.value else []

        if obj.type == FirewallObjectType.RANGE:
            # nftables range syntax: "10.0.0.1-10.0.0.50"
            # Returned as single string so nft can interpret it in a set element.
            return [obj.value] if obj.value else []

        if obj.type == FirewallObjectType.FQDN:
            try:
                infos = socket.getaddrinfo(obj.value, None, socket.AF_INET)
                ips = list({info[4][0] for info in infos})
                return ips
            except Exception as e:
                logger.warning(f"FQDN resolution failed for '{obj.value}': {e}")
                return []

        if obj.type == FirewallObjectType.GROUP:
            members = obj.members or []
            result: List[str] = []
            member_ids = []
            for m in members:
                try:
                    member_ids.append(uuid.UUID(str(m)))
                except ValueError:
                    continue

            if cache is None:
                resolved_members = await FirewallObjectService.get_by_ids(
                    session, member_ids
                )
            else:
                resolved_members = {
                    mid: cache[mid] for mid in member_ids if mid in cache
                }
                missing = [mid for mid in member_ids if mid not in cache]
                if missing:
                    extra = await FirewallObjectService.get_by_ids(session, missing)
                    resolved_members.update(extra)

            for mid in member_ids:
                member = resolved_members.get(mid)
                if member:
                    result.extend(
                        await FirewallObjectService.resolve_address(
                            session, member, cache, _depth + 1
                        )
                    )
            return result

        return []

    @staticmethod
    async def resolve_service(
        session: AsyncSession,
        obj: FirewallObject,
        cache: Optional[Dict[uuid.UUID, FirewallObject]] = None,
        _depth: int = 0,
    ) -> List[Tuple[Optional[str], Optional[str]]]:
        """
        Resolve a service object to a list of (protocol, port) tuples.
        Service value format: "tcp/443", "udp/53", "tcp/80-8080", "tcp/80,443"
        """
        if _depth > 8:
            return []

        if obj.type == FirewallObjectType.SERVICE:
            if not obj.value:
                return [(None, None)]
            parts = obj.value.split("/", 1)
            if len(parts) == 2:
                return [(parts[0].lower(), parts[1])]
            return [(None, obj.value)]

        if obj.type == FirewallObjectType.SERVICE_GROUP:
            members = obj.members or []
            result = []
            member_ids = []
            for m in members:
                try:
                    member_ids.append(uuid.UUID(str(m)))
                except ValueError:
                    continue

            if cache is None:
                resolved = await FirewallObjectService.get_by_ids(session, member_ids)
            else:
                resolved = {
                    mid: cache[mid] for mid in member_ids if mid in cache
                }
                missing = [mid for mid in member_ids if mid not in cache]
                if missing:
                    extra = await FirewallObjectService.get_by_ids(session, missing)
                    resolved.update(extra)

            for mid in member_ids:
                member = resolved.get(mid)
                if member:
                    result.extend(
                        await FirewallObjectService.resolve_service(
                            session, member, cache, _depth + 1
                        )
                    )
            return result

        return []

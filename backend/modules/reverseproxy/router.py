"""
Reverse Proxy Module - API Router

CRUD for hosts and access lists, certificate issuance, preflight check
and nginx service status.
"""
import asyncio
import logging
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload

from core.database import get_session
from core.auth.dependencies import require_permission
from core.auth.models import User
from core.services.service import SystemdService

from .models import (
    RevproxyHost, RevproxyHostDomain,
    RevproxyAccessList, RevproxyAccessListAuth, RevproxyAccessListRule,
    RevproxyCertificate,
    RevproxyHostCreate, RevproxyHostUpdate, RevproxyHostRead,
    RevproxyAccessListCreate, RevproxyAccessListUpdate, RevproxyAccessListRead,
    RevproxyAccessListAuthRead, RevproxyAccessListRuleRead,
    RevproxyHostDomainRead, RevproxyCertificateRead,
)
from . import service as svc

logger = logging.getLogger(__name__)
router = APIRouter()


def _apply_chain_rules() -> None:
    """Apply port 80/443 ACCEPT rules to MOD_REVPROXY_INPUT.

    Called at module import time so rules are re-applied on every app
    startup — AFTER the orchestrator calls create_chain (which does NOT
    flush an existing chain), preserving these rules.
    """
    try:
        from core.firewall import iptables as core_iptables
        chain = "MOD_REVPROXY_INPUT"
        core_iptables.create_or_flush_chain(chain, "filter")
        core_iptables.run_safe("filter", [
            "-A", chain, "-p", "tcp", "--dport", "80",
            "-j", "ACCEPT", "-m", "comment", "--comment", "madmin-revproxy:80",
        ])
        core_iptables.run_safe("filter", [
            "-A", chain, "-p", "tcp", "--dport", "443",
            "-j", "ACCEPT", "-m", "comment", "--comment", "madmin-revproxy:443",
        ])
        logger.info("Reverse Proxy: firewall rules applied to %s (80, 443)", chain)
    except Exception as e:
        logger.warning("Reverse Proxy: could not apply firewall rules at import: %s", e)


_apply_chain_rules()


# ============================================================================
# Helpers
# ============================================================================

def _block_if_disabled():
    """Return HTTPException 503 if the module is blocked by a port conflict."""
    blocked, reason = svc.is_blocked()
    if blocked:
        raise HTTPException(
            status_code=503,
            detail=f"Modulo Reverse Proxy bloccato: {reason}",
        )


def _to_host_read(host: RevproxyHost) -> RevproxyHostRead:
    cert = host.certificate
    return RevproxyHostRead(
        id=host.id,
        name=host.name,
        forward_scheme=host.forward_scheme,
        forward_host=host.forward_host,
        forward_port=host.forward_port,
        access_list_id=host.access_list_id,
        force_https=host.force_https,
        http2_support=host.http2_support,
        block_exploits=host.block_exploits,
        caching_enabled=host.caching_enabled,
        websockets_support=host.websockets_support,
        custom_nginx_config=host.custom_nginx_config or "",
        enabled=host.enabled,
        created_at=host.created_at,
        updated_at=host.updated_at,
        domains=[RevproxyHostDomainRead(id=d.id, domain=d.domain) for d in host.domains],
        certificate=(
            RevproxyCertificateRead(
                id=cert.id,
                provider=cert.provider,
                domain=cert.domain,
                san_domains=cert.san_domains,
                expires_at=cert.expires_at,
                last_renewal_status=cert.last_renewal_status,
                auto_renew=cert.auto_renew,
            )
            if cert
            else None
        ),
    )


async def _load_host(db: AsyncSession, host_id: uuid.UUID) -> RevproxyHost:
    result = await db.execute(
        select(RevproxyHost)
        .where(RevproxyHost.id == host_id)
        .options(
            selectinload(RevproxyHost.domains),
            selectinload(RevproxyHost.certificate),
        )
    )
    host = result.scalar_one_or_none()
    if not host:
        raise HTTPException(status_code=404, detail="Host non trovato")
    return host


async def _check_domain_uniqueness(
    db: AsyncSession, domains: List[str], exclude_host_id: Optional[uuid.UUID] = None
) -> None:
    for d in domains:
        if not svc.is_valid_domain(d):
            raise HTTPException(status_code=400, detail=f"Dominio non valido: {d}")
    q = select(RevproxyHostDomain).where(RevproxyHostDomain.domain.in_(domains))
    if exclude_host_id is not None:
        q = q.where(RevproxyHostDomain.host_id != exclude_host_id)
    result = await db.execute(q)
    existing = result.scalars().all()
    if existing:
        names = ", ".join(sorted({e.domain for e in existing}))
        raise HTTPException(
            status_code=400, detail=f"Dominio/i già utilizzati: {names}"
        )


# ============================================================================
# Preflight + Service status
# ============================================================================

@router.get("/preflight")
async def preflight(
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("reverseproxy.view")),
):
    """Check whether ports 80/443 are free for the module."""
    return await svc.preflight_check(db)


@router.get("/service/status")
async def service_status(
    _user: User = Depends(require_permission("reverseproxy.view")),
):
    blocked, reason = svc.is_blocked()
    status = SystemdService.get_status("nginx")
    return {**status, "blocked": blocked, "block_reason": reason}


@router.post("/service/reload")
async def service_reload(
    _user: User = Depends(require_permission("reverseproxy.manage")),
):
    _block_if_disabled()
    ok, msg = svc.nginx_reload()
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"ok": True, "message": msg}


# ============================================================================
# Hosts
# ============================================================================

@router.get("/hosts", response_model=List[RevproxyHostRead])
async def list_hosts(
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("reverseproxy.view")),
):
    result = await db.execute(
        select(RevproxyHost).options(
            selectinload(RevproxyHost.domains),
            selectinload(RevproxyHost.certificate),
        )
    )
    return [_to_host_read(h) for h in result.scalars().all()]


@router.post("/hosts", response_model=RevproxyHostRead)
async def create_host(
    data: RevproxyHostCreate,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("reverseproxy.manage")),
):
    _block_if_disabled()
    if not data.domains:
        raise HTTPException(status_code=400, detail="Almeno un dominio è richiesto")
    if data.forward_scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="forward_scheme non valido")
    if not (1 <= data.forward_port <= 65535):
        raise HTTPException(status_code=400, detail="forward_port fuori range")
    if not svc.is_valid_forward_host(data.forward_host):
        raise HTTPException(status_code=400, detail="forward_host non valido")
    domains_norm = [svc.normalize_domain(d) for d in data.domains]
    await _check_domain_uniqueness(db, domains_norm)
    if data.access_list_id is not None:
        acl = (await db.execute(
            select(RevproxyAccessList).where(RevproxyAccessList.id == data.access_list_id)
        )).scalar_one_or_none()
        if not acl:
            raise HTTPException(status_code=404, detail="Access list non trovata")

    host = RevproxyHost(
        name=data.name,
        forward_scheme=data.forward_scheme,
        forward_host=data.forward_host.strip(),
        forward_port=data.forward_port,
        access_list_id=data.access_list_id,
        force_https=data.force_https,
        http2_support=data.http2_support,
        block_exploits=data.block_exploits,
        caching_enabled=data.caching_enabled,
        websockets_support=data.websockets_support,
        custom_nginx_config=data.custom_nginx_config or "",
    )
    db.add(host)
    await db.flush()
    for d in domains_norm:
        db.add(RevproxyHostDomain(host_id=host.id, domain=d))
    await db.commit()

    ok, msg = await svc.apply_host(db, host.id)
    if not ok:
        logger.error(f"apply_host failed for {host.id}: {msg}")
        raise HTTPException(status_code=500, detail=f"Configurazione nginx fallita: {msg}")

    return _to_host_read(await _load_host(db, host.id))


@router.get("/hosts/{host_id}", response_model=RevproxyHostRead)
async def get_host(
    host_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("reverseproxy.view")),
):
    return _to_host_read(await _load_host(db, host_id))


@router.patch("/hosts/{host_id}", response_model=RevproxyHostRead)
async def update_host(
    host_id: uuid.UUID,
    data: RevproxyHostUpdate,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("reverseproxy.manage")),
):
    _block_if_disabled()
    host = await _load_host(db, host_id)

    if data.domains is not None:
        domains_norm = [svc.normalize_domain(d) for d in data.domains]
        if not domains_norm:
            raise HTTPException(status_code=400, detail="Almeno un dominio è richiesto")
        await _check_domain_uniqueness(db, domains_norm, exclude_host_id=host.id)
        # Replace domain rows
        await db.execute(
            delete(RevproxyHostDomain).where(RevproxyHostDomain.host_id == host.id)
        )
        for d in domains_norm:
            db.add(RevproxyHostDomain(host_id=host.id, domain=d))

    if data.forward_scheme is not None:
        if data.forward_scheme not in ("http", "https"):
            raise HTTPException(status_code=400, detail="forward_scheme non valido")
        host.forward_scheme = data.forward_scheme
    if data.forward_host is not None:
        if not svc.is_valid_forward_host(data.forward_host):
            raise HTTPException(status_code=400, detail="forward_host non valido")
        host.forward_host = data.forward_host.strip()
    if data.forward_port is not None:
        if not (1 <= data.forward_port <= 65535):
            raise HTTPException(status_code=400, detail="forward_port fuori range")
        host.forward_port = data.forward_port
    if data.access_list_id is not None:
        # Allow nulling by passing all-zero UUID? Use explicit field or treat None separately.
        # PATCH with explicit null is not distinguishable from omitted in Pydantic v1.
        # So: pass any UUID = set; to clear, use DELETE /hosts/{id}/access-list (separate endpoint).
        acl = (await db.execute(
            select(RevproxyAccessList).where(RevproxyAccessList.id == data.access_list_id)
        )).scalar_one_or_none()
        if not acl:
            raise HTTPException(status_code=404, detail="Access list non trovata")
        host.access_list_id = data.access_list_id
    for field in (
        "name", "force_https", "http2_support", "block_exploits",
        "caching_enabled", "websockets_support", "custom_nginx_config", "enabled",
    ):
        v = getattr(data, field)
        if v is not None:
            setattr(host, field, v)

    from datetime import datetime
    host.updated_at = datetime.utcnow()
    await db.commit()

    ok, msg = await svc.apply_host(db, host.id)
    if not ok:
        raise HTTPException(status_code=500, detail=f"Configurazione nginx fallita: {msg}")

    return _to_host_read(await _load_host(db, host.id))


@router.delete("/hosts/{host_id}/access-list", response_model=RevproxyHostRead)
async def clear_host_access_list(
    host_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("reverseproxy.manage")),
):
    _block_if_disabled()
    host = await _load_host(db, host_id)
    host.access_list_id = None
    await db.commit()
    ok, msg = await svc.apply_host(db, host.id)
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return _to_host_read(await _load_host(db, host.id))


@router.delete("/hosts/{host_id}")
async def delete_host(
    host_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("reverseproxy.manage")),
):
    host = await _load_host(db, host_id)
    # Best-effort revoke cert
    if host.certificate:
        svc.revoke_certificate(host.id)
    await db.delete(host)
    await db.commit()
    await svc.remove_host(host_id)
    return {"ok": True}


@router.post("/hosts/{host_id}/enable", response_model=RevproxyHostRead)
async def enable_host(
    host_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("reverseproxy.manage")),
):
    _block_if_disabled()
    host = await _load_host(db, host_id)
    host.enabled = True
    await db.commit()
    ok, msg = await svc.apply_host(db, host.id)
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return _to_host_read(await _load_host(db, host.id))


@router.post("/hosts/{host_id}/disable", response_model=RevproxyHostRead)
async def disable_host(
    host_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("reverseproxy.manage")),
):
    _block_if_disabled()
    host = await _load_host(db, host_id)
    host.enabled = False
    await db.commit()
    await svc.remove_host(host.id)
    return _to_host_read(await _load_host(db, host.id))


# ============================================================================
# Certificates
# ============================================================================

@router.post("/hosts/{host_id}/certificate", response_model=RevproxyCertificateRead)
async def issue_host_certificate(
    host_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("reverseproxy.certs")),
):
    _block_if_disabled()
    host = await _load_host(db, host_id)
    if not host.domains:
        raise HTTPException(status_code=400, detail="Host senza domini")

    primary = host.domains[0].domain
    sans = [d.domain for d in host.domains[1:]]
    # certbot is a blocking subprocess (up to ~180s) — run in thread pool
    # to avoid blocking the entire FastAPI event loop
    loop = asyncio.get_event_loop()
    ok, msg, info = await loop.run_in_executor(
        None, lambda: svc.issue_certificate(host.id, primary, sans)
    )
    if not ok:
        raise HTTPException(status_code=500, detail=f"certbot ha fallito: {msg}")

    cert = host.certificate
    if cert is None:
        cert = RevproxyCertificate(
            host_id=host.id,
            provider="letsencrypt",
            domain=primary,
            san_domains=sans,
            cert_path=info["cert_path"],
            key_path=info["key_path"],
            issued_at=info["issued_at"],
            expires_at=info["expires_at"],
            last_renewal_status="issued",
            auto_renew=True,
        )
        db.add(cert)
    else:
        cert.provider = "letsencrypt"
        cert.domain = primary
        cert.san_domains = sans
        cert.cert_path = info["cert_path"]
        cert.key_path = info["key_path"]
        cert.issued_at = info["issued_at"]
        cert.expires_at = info["expires_at"]
        cert.last_renewal_status = "issued"

    await db.commit()
    apply_ok, apply_msg = await svc.apply_host(db, host.id)
    if not apply_ok:
        raise HTTPException(status_code=500, detail=f"nginx reload fallito: {apply_msg}")

    return RevproxyCertificateRead(
        id=cert.id,
        provider=cert.provider,
        domain=cert.domain,
        san_domains=cert.san_domains,
        expires_at=cert.expires_at,
        last_renewal_status=cert.last_renewal_status,
        auto_renew=cert.auto_renew,
    )


@router.delete("/hosts/{host_id}/certificate")
async def revoke_host_certificate(
    host_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("reverseproxy.certs")),
):
    _block_if_disabled()
    host = await _load_host(db, host_id)
    if not host.certificate:
        raise HTTPException(status_code=404, detail="Nessun certificato")
    svc.revoke_certificate(host.id)
    await db.delete(host.certificate)
    # If force_https was on, drop it so vhost still works HTTP-only
    host.force_https = False
    await db.commit()
    await svc.apply_host(db, host.id)
    return {"ok": True}


# ============================================================================
# Access lists
# ============================================================================

async def _load_acl(db: AsyncSession, acl_id: uuid.UUID) -> RevproxyAccessList:
    result = await db.execute(
        select(RevproxyAccessList)
        .where(RevproxyAccessList.id == acl_id)
        .options(
            selectinload(RevproxyAccessList.auths),
            selectinload(RevproxyAccessList.rules),
        )
    )
    acl = result.scalar_one_or_none()
    if not acl:
        raise HTTPException(status_code=404, detail="Access list non trovata")
    return acl


def _to_acl_read(acl: RevproxyAccessList, hosts_count: int = 0) -> RevproxyAccessListRead:
    return RevproxyAccessListRead(
        id=acl.id,
        name=acl.name,
        satisfy_any=acl.satisfy_any,
        pass_auth_to_upstream=acl.pass_auth_to_upstream,
        auths=[RevproxyAccessListAuthRead(id=a.id, username=a.username) for a in acl.auths],
        rules=sorted(
            [RevproxyAccessListRuleRead(id=r.id, action=r.action, subject=r.subject, order=r.order)
             for r in acl.rules],
            key=lambda r: r.order,
        ),
        hosts_count=hosts_count,
    )


@router.get("/access_lists", response_model=List[RevproxyAccessListRead])
async def list_access_lists(
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("reverseproxy.view")),
):
    result = await db.execute(
        select(RevproxyAccessList).options(
            selectinload(RevproxyAccessList.auths),
            selectinload(RevproxyAccessList.rules),
        )
    )
    acls = result.scalars().all()
    count_result = await db.execute(
        select(RevproxyHost.access_list_id, func.count(RevproxyHost.id))
        .where(RevproxyHost.access_list_id.is_not(None))
        .group_by(RevproxyHost.access_list_id)
    )
    counts = dict(count_result.all())
    return [_to_acl_read(a, counts.get(a.id, 0)) for a in acls]


@router.post("/access_lists", response_model=RevproxyAccessListRead)
async def create_access_list(
    data: RevproxyAccessListCreate,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("reverseproxy.access_lists")),
):
    _block_if_disabled()
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="Nome richiesto")
    existing = (await db.execute(
        select(RevproxyAccessList).where(RevproxyAccessList.name == data.name)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Nome già esistente")
    for r in data.rules:
        if r.action not in ("allow", "deny"):
            raise HTTPException(status_code=400, detail="Action deve essere allow/deny")
        if not svc.is_valid_subject(r.subject):
            raise HTTPException(status_code=400, detail=f"IP/CIDR non valido: {r.subject}")

    acl = RevproxyAccessList(
        name=data.name.strip(),
        satisfy_any=data.satisfy_any,
        pass_auth_to_upstream=data.pass_auth_to_upstream,
    )
    db.add(acl)
    await db.flush()

    for a in data.auths:
        if not a.username or not a.password:
            raise HTTPException(status_code=400, detail="Username e password richiesti")
        db.add(RevproxyAccessListAuth(
            access_list_id=acl.id,
            username=a.username.strip(),
            password_hash=svc.hash_password(a.password),
        ))
    for r in data.rules:
        db.add(RevproxyAccessListRule(
            access_list_id=acl.id, action=r.action, subject=r.subject, order=r.order,
        ))
    await db.commit()

    ok, msg = await svc.apply_access_list(db, acl.id)
    if not ok:
        raise HTTPException(status_code=500, detail=msg)

    return _to_acl_read(await _load_acl(db, acl.id))


@router.get("/access_lists/{acl_id}", response_model=RevproxyAccessListRead)
async def get_access_list(
    acl_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("reverseproxy.view")),
):
    acl = await _load_acl(db, acl_id)
    count = (await db.execute(
        select(func.count(RevproxyHost.id)).where(RevproxyHost.access_list_id == acl.id)
    )).scalar() or 0
    return _to_acl_read(acl, count)


@router.patch("/access_lists/{acl_id}", response_model=RevproxyAccessListRead)
async def update_access_list(
    acl_id: uuid.UUID,
    data: RevproxyAccessListUpdate,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("reverseproxy.access_lists")),
):
    _block_if_disabled()
    acl = await _load_acl(db, acl_id)

    if data.name is not None:
        new = data.name.strip()
        if not new:
            raise HTTPException(status_code=400, detail="Nome richiesto")
        if new != acl.name:
            existing = (await db.execute(
                select(RevproxyAccessList).where(RevproxyAccessList.name == new)
            )).scalar_one_or_none()
            if existing:
                raise HTTPException(status_code=400, detail="Nome già esistente")
            acl.name = new
    if data.satisfy_any is not None:
        acl.satisfy_any = data.satisfy_any
    if data.pass_auth_to_upstream is not None:
        acl.pass_auth_to_upstream = data.pass_auth_to_upstream

    if data.auths is not None:
        await db.execute(
            delete(RevproxyAccessListAuth).where(RevproxyAccessListAuth.access_list_id == acl.id)
        )
        for a in data.auths:
            if not a.username or not a.password:
                raise HTTPException(status_code=400, detail="Username e password richiesti")
            db.add(RevproxyAccessListAuth(
                access_list_id=acl.id,
                username=a.username.strip(),
                password_hash=svc.hash_password(a.password),
            ))

    if data.rules is not None:
        for r in data.rules:
            if r.action not in ("allow", "deny"):
                raise HTTPException(status_code=400, detail="Action deve essere allow/deny")
            if not svc.is_valid_subject(r.subject):
                raise HTTPException(status_code=400, detail=f"IP/CIDR non valido: {r.subject}")
        await db.execute(
            delete(RevproxyAccessListRule).where(RevproxyAccessListRule.access_list_id == acl.id)
        )
        for r in data.rules:
            db.add(RevproxyAccessListRule(
                access_list_id=acl.id, action=r.action, subject=r.subject, order=r.order,
            ))

    from datetime import datetime
    acl.updated_at = datetime.utcnow()
    await db.commit()

    ok, msg = await svc.apply_access_list(db, acl.id)
    if not ok:
        raise HTTPException(status_code=500, detail=msg)

    fresh = await _load_acl(db, acl.id)
    count = (await db.execute(
        select(func.count(RevproxyHost.id)).where(RevproxyHost.access_list_id == acl.id)
    )).scalar() or 0
    return _to_acl_read(fresh, count)


@router.delete("/access_lists/{acl_id}")
async def delete_access_list(
    acl_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("reverseproxy.access_lists")),
):
    acl = await _load_acl(db, acl_id)
    # Detach from hosts
    result = await db.execute(
        select(RevproxyHost).where(RevproxyHost.access_list_id == acl.id)
    )
    affected_hosts = list(result.scalars().all())
    for h in affected_hosts:
        h.access_list_id = None

    await db.delete(acl)
    await db.commit()

    await svc.remove_access_list(db, acl_id)
    for h in affected_hosts:
        await svc.apply_host(db, h.id)
    return {"ok": True}

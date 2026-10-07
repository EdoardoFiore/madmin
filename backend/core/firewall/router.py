"""
MADMIN Firewall Router

API endpoints for machine firewall management.
"""
import asyncio
import ipaddress
import logging
import subprocess
from typing import List, Optional
import json
import re
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status, File, UploadFile
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel
import uuid
from pydantic import ValidationError, field_validator

from core.database import get_session
from core.http import get_client_ip
from config import get_settings
from core.network.utils import get_default_interface
from core.auth.dependencies import require_permission, get_current_user
from core.auth.models import User
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta

from .models import (
    MachineFirewallRule,
    MachineFirewallRuleCreate,
    MachineFirewallRuleUpdate,
    MachineFirewallRuleResponse,
    RuleOrderUpdate,
    RuleCounter,
    RuleCounterResponse, RuleTrafficSample,
    ForwardSection, ForwardSectionResponse,
    NatPool, NatPoolCreate, NatPoolUpdate, NatPoolResponse,
    ModuleChainResponse,
    RuleAddressRefResponse,
    AddressObject,
    AddressGroup,
    AddressGroupMember,
    FirewallRuleAddress,
    AddressObjectCreate,
    AddressObjectUpdate,
    AddressObjectResponse,
    AddressGroupCreate,
    AddressGroupUpdate,
    AddressGroupResponse,
    AddressGroupMemberResponse,
    ADDRESS_OBJECT_TYPES,
)
from .orchestrator import (
    firewall_orchestrator, dnat_forward_fields, policy_nat_fields, policy_nat_target, hairpin_masq_fields,
    redirect_input_fields, dnat_input_fields, effective_to_destination, section_key,
    IMPLICIT_DENY_COMMENT,
)
from .iptables import IptablesError
from . import flowmatch
from .protected_ports import validate_protected_port_collision, port_specs_overlap
from . import addresses, geoip, natpool

logger = logging.getLogger(__name__)

settings = get_settings()

router = APIRouter(prefix="/api/firewall", tags=["Firewall"])


# Hook (chain) in cui ciascun match/azione è valido per netfilter.
# Denylist applicata DOPO la validazione table/chain/action: blocca solo le
# combinazioni note-incompatibili, lasciando passare quelle non elencate.
_IN_IFACE_VALID = {"PREROUTING", "INPUT", "FORWARD", "POSTROUTING"}
_OUT_IFACE_VALID = {"POSTROUTING", "OUTPUT", "FORWARD"}
_NAT_TARGET_HOOK = {
    "DNAT": {"PREROUTING", "OUTPUT"},
    "REDIRECT": {"PREROUTING", "OUTPUT"},
    "SNAT": {"POSTROUTING"},
    "MASQUERADE": {"POSTROUTING"},
}

# Chain e azioni valide per tabella (GW_EXCEPTIONS è la chain virtuale filter).
_TABLE_CHAINS = {
    "filter": ("INPUT", "OUTPUT", "FORWARD", "GW_EXCEPTIONS"),
    "nat": ("PREROUTING", "POSTROUTING", "OUTPUT"),
    "mangle": ("PREROUTING", "INPUT", "FORWARD", "OUTPUT", "POSTROUTING"),
    "raw": ("PREROUTING", "OUTPUT"),
}
_TABLE_ACTIONS = {
    "filter": ("ACCEPT", "DROP", "REJECT", "LOG", "RETURN"),
    "nat": ("SNAT", "DNAT", "MASQUERADE", "REDIRECT", "ACCEPT", "RETURN"),
    "mangle": ("MARK", "TOS", "TTL", "ACCEPT", "RETURN"),
    "raw": ("NOTRACK", "ACCEPT", "RETURN"),
}

# Fields the duplicate port-forward check depends on (enabled included: re-
# enabling a rule disabled because it duplicated another must not resurrect it)
_DUP_CHECK_FIELDS = {
    "table_name", "chain", "action", "protocol", "port", "in_interface",
    "source", "destination", "source_refs", "destination_refs", "enabled",
}


async def _validate_rule_payload(
    session: AsyncSession,
    rule: dict,
    *,
    exclude_rule_id: Optional[uuid.UUID] = None,
    touched: Optional[set] = None,
    has_source_refs: bool = False,
    has_destination_refs: bool = False,
) -> None:
    """
    Everything a rule must satisfy beyond its field grammar, for the state the
    rule ends up in: create passes the new rule, PATCH the existing one merged
    with the update, import each imported rule. One function so that no path
    skips a check (import used to skip them all, protected ports included).

    touched: the fields this request writes (PATCH). The port/protocol trap and
    the duplicate port-forward check only run when the write touches what they
    depend on, so toggling `enabled` on a legacy row keeps working. None means
    every field (create, import).
    Raises HTTPException(400).
    """
    from core.provisioning.service import MANAGED_NAT_SENTINEL

    table = rule.get("table_name") or "filter"
    chain = rule.get("chain")
    action = rule.get("action")

    # The managed-LAN NAT rule is recognised by this comment: a copy would be
    # locked against editing and deletion like the real one
    if rule.get("comment") == MANAGED_NAT_SENTINEL:
        raise HTTPException(status_code=400, detail="Commento riservato alla regola NAT della LAN gestita")

    _validate_rule_constraints(table, chain, action, rule.get("in_interface"), rule.get("out_interface"))

    if touched is None or {"port", "protocol"} & touched:
        _validate_port_protocol(rule.get("protocol"), rule.get("port"))

    if rule.get("policy_nat") and not (table == "filter" and chain == "FORWARD"):
        raise HTTPException(status_code=400, detail="policy_nat è disponibile solo su regole filter/FORWARD.")
    if (rule.get("policy_nat") and action != "ACCEPT"
            and (touched is None or {"policy_nat", "action"} & touched)):
        raise HTTPException(status_code=400, detail="Il NAT si applica solo alle policy che accettano il traffico.")

    # Where a policy's NAT applies: its outgoing interface, or the
    # default-route interface when it names none (see build_ruleset)
    nat_checks = touched is None or {"to_source", "nat_pool_id", "out_interface", "policy_nat", "enabled"} & touched
    nat_out = rule.get("out_interface")
    if table == "filter" and rule.get("policy_nat") and nat_checks and not nat_out:
        nat_out = await asyncio.to_thread(get_default_interface)

    to_source = rule.get("to_source")
    if to_source:
        if table == "filter":
            # A policy's NAT address: SNAT toward one address of the machine
            if not (chain == "FORWARD" and rule.get("policy_nat")):
                raise HTTPException(status_code=400, detail="L'IP di uscita richiede una policy FORWARD con NAT attivo.")
            if not natpool.is_single_ipv4(to_source):
                raise HTTPException(status_code=400, detail="L'IP di uscita di una policy è un singolo indirizzo IPv4.")
            if nat_checks:
                addrs = await asyncio.to_thread(natpool.interface_addresses)
                if not natpool.nat_ip_is_local(to_source, nat_out, addrs):
                    if rule.get("out_interface"):
                        where = f"non è configurato sull'interfaccia {nat_out}"
                    elif nat_out:
                        where = (f"non è sull'interfaccia {nat_out}: senza interfaccia di uscita il NAT "
                                 f"si applica solo verso {nat_out}, scegli l'interfaccia di uscita")
                    else:
                        where = "non è configurato su nessuna interfaccia"
                    raise HTTPException(
                        status_code=400,
                        detail=f"L'indirizzo {to_source} {where}: le risposte non tornerebbero.",
                    )
        elif not (table == "nat" and action == "SNAT"):
            raise HTTPException(status_code=400, detail="to_source è disponibile solo su SNAT in nat/POSTROUTING o sul NAT delle policy.")

    pool_id = rule.get("nat_pool_id")
    if pool_id:
        if to_source:
            raise HTTPException(status_code=400, detail="Indicare un IP di uscita oppure un IP pool, non entrambi.")
        if not ((table == "filter" and chain == "FORWARD" and rule.get("policy_nat"))
                or (table == "nat" and action == "SNAT")):
            raise HTTPException(status_code=400, detail="Un IP pool si usa sul NAT di una policy FORWARD o su una regola SNAT.")
        pool = await session.get(NatPool, _uuid(pool_id))
        if not pool:
            raise HTTPException(status_code=400, detail="IP pool non trovato")
        if pool.type == "one_to_one":
            _validate_one_to_one_source(pool, rule.get("source"), has_source_refs)
        if table == "filter" and nat_checks and pool.arp_reply and nat_out:
            # the pool's addresses live on the interface of their subnet: the
            # NAT must leave through that one
            from core.network.service import NetworkService
            devs, _ = natpool.describe(pool, [], await asyncio.to_thread(NetworkService.get_interfaces))
            if devs and not all(natpool.iface_matches(nat_out, d) for d in devs):
                hint = "" if rule.get("out_interface") else " (senza interfaccia di uscita il NAT si applica solo verso " + nat_out + ")"
                raise HTTPException(
                    status_code=400,
                    detail=f"Gli indirizzi del pool '{pool.name}' sono su {', '.join(devs)}, "
                           f"il NAT di questa policy esce da {nat_out}{hint}.",
                )
    elif table == "nat" and action == "SNAT" and not to_source:
        raise HTTPException(status_code=400, detail="Una regola SNAT richiede l'indirizzo di uscita (to_source) o un IP pool.")

    obj_id = rule.get("to_destination_object_id")
    if obj_id and not (table == "nat" and action == "DNAT"):
        raise HTTPException(
            status_code=400,
            detail="to_destination_object_id è disponibile solo su regole DNAT in nat/PREROUTING o nat/OUTPUT."
        )
    effective_dest = rule.get("to_destination")
    if obj_id:
        from types import SimpleNamespace
        obj_value = await _validate_dnat_target_object(session, str(obj_id))
        effective_dest = effective_to_destination(
            SimpleNamespace(to_destination_port=rule.get("to_destination_port")), obj_value
        )

    if rule.get("hairpin") and not (
        table == "nat" and chain == "PREROUTING" and action == "DNAT" and effective_dest
    ):
        raise HTTPException(
            status_code=400,
            detail="hairpin è disponibile solo su regole DNAT in nat/PREROUTING con destinazione interna."
        )

    if (table == "nat" and chain == "PREROUTING" and action in ("DNAT", "REDIRECT")
            and rule.get("enabled", True)
            and (touched is None or _DUP_CHECK_FIELDS & touched)):
        await _validate_duplicate_port_forward(
            session,
            exclude_rule_id=exclude_rule_id,
            action=action,
            protocol=rule.get("protocol"),
            port=rule.get("port"),
            in_interface=rule.get("in_interface"),
            source=rule.get("source"),
            destination=rule.get("destination"),
            has_source_refs=has_source_refs,
            has_destination_refs=has_destination_refs,
        )

    try:
        await validate_protected_port_collision(
            session,
            table_name=table,
            action=action,
            chain=chain,
            protocol=rule.get("protocol"),
            port=rule.get("port"),
            to_destination=effective_dest,
            to_ports=rule.get("to_ports"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))



def _validate_one_to_one_source(pool, source: Optional[str], has_source_refs: bool) -> None:
    """NETMAP keeps the host part: the source must be a subnet of the pool's size."""
    _, _, pool_net = natpool.parse_pool(pool.type, pool.value)
    net = None
    if source and not has_source_refs:
        try:
            net = ipaddress.IPv4Network(source, strict=False)
        except ValueError:
            net = None
    if net is None or net.prefixlen != pool_net.prefixlen:
        raise HTTPException(
            status_code=400,
            detail=f"Il pool one-to-one '{pool.name}' ({pool.value}) richiede come sorgente una "
                   f"subnet /{pool_net.prefixlen} scritta nella regola: ogni host esce con l'indirizzo "
                   f"corrispondente del pool.",
        )


def _uuid(value) -> uuid.UUID:
    """Parse a UUID, raising HTTP 400 on bad input."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"ID non valido: {value}")


async def _validate_rule_refs(session: AsyncSession, *ref_lists) -> None:
    """Validate object/group references attached to a rule direction: each must
    name exactly one existing, enabled object or group."""
    for refs in ref_lists:
        if not refs:
            continue
        for ref in refs:
            oid = getattr(ref, "object_id", None)
            gid = getattr(ref, "group_id", None)
            if bool(oid) == bool(gid):
                raise HTTPException(
                    status_code=400,
                    detail="Ogni riferimento deve indicare un oggetto OPPURE un gruppo."
                )
            if oid:
                o = await session.get(AddressObject, _uuid(oid))
                if not o:
                    raise HTTPException(status_code=400, detail=f"Oggetto indirizzo non trovato: {oid}")
                if not o.enabled:
                    raise HTTPException(status_code=400, detail=f"Oggetto indirizzo disabilitato: {o.name}")
            else:
                g = await session.get(AddressGroup, _uuid(gid))
                if not g:
                    raise HTTPException(status_code=400, detail=f"Gruppo indirizzi non trovato: {gid}")
                if not g.enabled:
                    raise HTTPException(status_code=400, detail=f"Gruppo indirizzi disabilitato: {g.name}")


async def _rule_refs_map(session: AsyncSession, rule_ids) -> dict:
    """Return {(rule_id, direction): [RuleAddressRefResponse, ...]} for the rules."""
    if not rule_ids:
        return {}
    res = await session.execute(
        select(FirewallRuleAddress)
        .where(FirewallRuleAddress.rule_id.in_(rule_ids))
        .order_by(FirewallRuleAddress.order)
    )
    refs = res.scalars().all()
    if not refs:
        return {}
    obj_ids = {r.object_id for r in refs if r.object_id}
    grp_ids = {r.group_id for r in refs if r.group_id}
    objs, grps = {}, {}
    if obj_ids:
        ores = await session.execute(select(AddressObject).where(AddressObject.id.in_(obj_ids)))
        objs = {o.id: o for o in ores.scalars().all()}
    if grp_ids:
        gres = await session.execute(select(AddressGroup).where(AddressGroup.id.in_(grp_ids)))
        grps = {g.id: g for g in gres.scalars().all()}
    out: dict = {}
    for r in refs:
        if r.object_id and r.object_id in objs:
            o = objs[r.object_id]
            item = RuleAddressRefResponse(
                object_id=str(o.id), name=o.name, kind="object", type=o.type,
                value=o.value,
                resolved_ips=json.loads(o.resolved_ips) if o.resolved_ips else None,
            )
        elif r.group_id and r.group_id in grps:
            g = grps[r.group_id]
            item = RuleAddressRefResponse(group_id=str(g.id), name=g.name, kind="group")
        else:
            continue
        out.setdefault((r.rule_id, r.direction), []).append(item)
    return out


def _validate_rule_constraints(table: str, chain: str, action: str,
                               in_interface: Optional[str],
                               out_interface: Optional[str]) -> None:
    """Reject rules whose table/chain/action/interface combination is invalid for netfilter."""
    if table not in _TABLE_CHAINS:
        raise HTTPException(
            status_code=400,
            detail=f"Tabella non valida: deve essere una tra {', '.join(_TABLE_CHAINS.keys())}."
        )
    if chain not in _TABLE_CHAINS[table]:
        raise HTTPException(
            status_code=400,
            detail=f"Catena {chain} non valida per la tabella {table}: "
                   f"disponibili {', '.join(_TABLE_CHAINS[table])}."
        )
    if action not in _TABLE_ACTIONS[table]:
        raise HTTPException(
            status_code=400,
            detail=f"Azione {action} non valida per la tabella {table}: "
                   f"disponibili {', '.join(_TABLE_ACTIONS[table])}."
        )
    if in_interface and chain not in _IN_IFACE_VALID:
        raise HTTPException(
            status_code=400,
            detail=f"Interfaccia di ingresso (-i) non valida nella catena {chain}: "
                   f"disponibile solo in PREROUTING, INPUT, FORWARD, POSTROUTING."
        )
    if out_interface and chain not in _OUT_IFACE_VALID:
        raise HTTPException(
            status_code=400,
            detail=f"Interfaccia di uscita (-o) non valida nella catena {chain}: "
                   f"disponibile solo in POSTROUTING, OUTPUT, FORWARD."
        )
    if action in _NAT_TARGET_HOOK and chain not in _NAT_TARGET_HOOK[action]:
        raise HTTPException(
            status_code=400,
            detail=f"Azione {action} non valida nella catena {chain}."
        )


def _validate_port_protocol(protocol: Optional[str], port: Optional[str]) -> None:
    """Reject a port match without a tcp/udp protocol: build_rule_args only
    emits --dport for protocol in (tcp, udp) (iptables.py), so a port stored
    against any other protocol (or none) is silently ignored by the engine —
    the rule ends up matching far more traffic than its port suggests."""
    if port and protocol not in ("tcp", "udp"):
        raise HTTPException(
            status_code=400,
            detail="La porta è applicabile solo con protocollo TCP o UDP: "
                   "impostare il protocollo o rimuovere la porta."
        )


async def _validate_duplicate_port_forward(
    session: AsyncSession,
    *,
    exclude_rule_id: Optional[uuid.UUID],
    action: str,
    protocol: Optional[str],
    port: Optional[str],
    in_interface: Optional[str],
    source: Optional[str],
    destination: Optional[str],
    has_source_refs: bool,
    has_destination_refs: bool,
) -> None:
    """
    Reject a nat/PREROUTING DNAT|REDIRECT that would silently shadow (or be
    shadowed by) another enabled port-forward rule: iptables evaluates in
    order and only the first match wins, so an identical-enough duplicate
    is dead code that never fires.

    A rule using address-object/group refs for source or destination is
    opaque here (its effective match depends on ipset contents resolved at
    apply time) — such rules are skipped entirely rather than risk a false
    positive/negative. Literal comparison is strict string equality, so
    "1.2.3.4" and "1.2.3.4/32" are treated as different (a real, if unusual,
    differentiator) — deliberately conservative: only flag true duplicates.
    """
    if has_source_refs or has_destination_refs:
        return

    query = (
        select(MachineFirewallRule)
        .where(MachineFirewallRule.table_name == "nat")
        .where(MachineFirewallRule.chain == "PREROUTING")
        .where(MachineFirewallRule.action.in_(("DNAT", "REDIRECT")))
        .where(MachineFirewallRule.enabled == True)
    )
    if exclude_rule_id is not None:
        query = query.where(MachineFirewallRule.id != exclude_rule_id)
    candidates = (await session.execute(query)).scalars().all()
    if not candidates:
        return

    other_ids = [c.id for c in candidates]
    refs_res = await session.execute(
        select(FirewallRuleAddress.rule_id).where(FirewallRuleAddress.rule_id.in_(other_ids))
    )
    ids_with_refs = {row[0] for row in refs_res.all()}

    proto_l = (protocol or "").lower()
    src_l = (source or "").strip()
    dst_l = (destination or "").strip()

    for other in candidates:
        if other.id in ids_with_refs:
            continue
        other_proto = (other.protocol or "").lower()
        if proto_l and other_proto and proto_l != other_proto:
            continue
        if not port_specs_overlap(port, other.port):
            continue
        if in_interface and other.in_interface and in_interface != other.in_interface:
            continue
        other_dst = (other.destination or "").strip()
        if dst_l and other_dst and dst_l != other_dst:
            continue
        other_src = (other.source or "").strip()
        if src_l and other_src and src_l != other_src:
            continue
        raise HTTPException(
            status_code=409,
            detail=f"Regola duplicata: confligge con il port forwarding "
                   f"'{other.comment or str(other.id)[:8]}' "
                   f"(porta {other.port or 'tutte'}, protocollo {other.protocol or 'tutti'}). "
                   f"Cambiare porta, protocollo o interfaccia, oppure rimuovere la regola esistente."
        )


async def _validate_dnat_target_object(session: AsyncSession, obj_id: str) -> str:
    """
    Validate a to_destination_object_id and return the referenced object's
    value. Only /32 cidr objects are accepted as a DNAT target:
    --to-destination rewrites to exactly one address, and every companion
    (FORWARD/INPUT/hairpin) embeds the target as a plain -d match, which
    neither a range nor a wider CIDR can be. See orchestrator.effective_to_destination.
    """
    obj = await session.get(AddressObject, _uuid(obj_id))
    if not obj:
        raise HTTPException(status_code=400, detail=f"Oggetto indirizzo non trovato: {obj_id}")
    if not obj.enabled:
        raise HTTPException(status_code=400, detail=f"Oggetto indirizzo disabilitato: {obj.name}")
    if obj.type != "cidr" or not obj.value.endswith("/32"):
        raise HTTPException(
            status_code=400,
            detail=f"La destinazione DNAT può referenziare solo un oggetto indirizzo di tipo "
                   f"CIDR /32 (host singolo): '{obj.name}' non è valido."
        )
    return obj.value


async def _dnat_obj_names_map(session: AsyncSession, rules) -> dict:
    """Return {rule_id: object_name} for rules whose to_destination_object_id
    is set, so responses can show a human name instead of a bare UUID."""
    obj_ids = {r.to_destination_object_id for r in rules if getattr(r, "to_destination_object_id", None)}
    if not obj_ids:
        return {}
    ores = await session.execute(select(AddressObject).where(AddressObject.id.in_(obj_ids)))
    objs = {o.id: o.name for o in ores.scalars().all()}
    return {
        r.id: objs[r.to_destination_object_id]
        for r in rules
        if getattr(r, "to_destination_object_id", None) and r.to_destination_object_id in objs
    }


async def _pool_names_map(session: AsyncSession) -> dict:
    """{pool id: name}, for rules that NAT through a pool."""
    return {p.id: p.name for p in (await session.execute(select(NatPool))).scalars().all()}


def _rule_to_response(rule, refs_map=None, dnat_obj_names=None, pool_names=None) -> MachineFirewallRuleResponse:
    """Convert database model to API response, including resolved address refs."""
    refs_map = refs_map or {}
    dnat_obj_names = dnat_obj_names or {}
    pool_names = pool_names or {}
    return MachineFirewallRuleResponse(
        id=str(rule.id),
        chain=rule.chain,
        action=rule.action,
        protocol=rule.protocol,
        source=rule.source,
        destination=rule.destination,
        source_refs=refs_map.get((rule.id, "source"), []),
        destination_refs=refs_map.get((rule.id, "destination"), []),
        port=rule.port,
        in_interface=rule.in_interface,
        out_interface=rule.out_interface,
        state=rule.state,
        limit_rate=rule.limit_rate,
        limit_burst=rule.limit_burst,
        to_destination=rule.to_destination,
        to_destination_object_id=str(rule.to_destination_object_id) if rule.to_destination_object_id else None,
        to_destination_object_name=dnat_obj_names.get(rule.id),
        to_destination_port=rule.to_destination_port,
        to_source=rule.to_source,
        nat_pool_id=str(rule.nat_pool_id) if rule.nat_pool_id else None,
        nat_pool_name=pool_names.get(rule.nat_pool_id),
        to_ports=rule.to_ports,
        log_prefix=rule.log_prefix,
        log_level=rule.log_level,
        reject_with=rule.reject_with,
        comment=rule.comment,
        table_name=rule.table_name,
        order=rule.order,
        enabled=rule.enabled,
        policy_nat=rule.policy_nat,
        hairpin=rule.hairpin,
        created_at=rule.created_at,
        updated_at=rule.updated_at
    )


def _auto_nat_response(policy, default_if: Optional[str] = None, position: int = 0,
                       pools: Optional[dict] = None) -> MachineFirewallRuleResponse:
    """Build the read-only synthetic POSTROUTING row mirroring a policy_nat
    companion (MASQUERADE or SNAT, see policy_nat_target). The real companion
    matches by conntrack mark, not by flow (see policy_nat_fields) — no single
    protocol/port/source/destination value represents it, so those stay None;
    the comment identifies the owning policy instead. default_if mirrors
    apply_rules' fallback to the default-route interface when the policy sets
    none. position: the policy's place in evaluation order."""
    fields = policy_nat_fields(policy)
    out_if = fields["out_interface"] or default_if
    try:
        nat_action, nat_args = policy_nat_target(policy, pools)
    except ValueError:
        nat_action, nat_args = "SNAT", {}
    pool = (pools or {}).get(policy.nat_pool_id) if policy.nat_pool_id else None
    return MachineFirewallRuleResponse(
        id=f"auto-nat-{policy.id}",
        chain="POSTROUTING",
        action=nat_action,
        protocol=None,
        source=None,
        destination=None,
        port=None,
        in_interface=None,  # -i does not exist in POSTROUTING
        out_interface=out_if,
        state=None,
        limit_rate=None,
        limit_burst=None,
        to_destination=None,
        to_source=nat_args.get("to_source") or nat_args.get("netmap_to"),
        nat_pool_id=str(pool.id) if pool else None,
        nat_pool_name=pool.name if pool else None,
        to_ports=None,
        log_prefix=None,
        log_level=None,
        reject_with=None,
        comment=f"→ NAT (connmark) per policy: {policy.comment or str(policy.id)[:8]}",
        table_name="nat",
        order=900_000 + position,  # after user POSTROUTING rules, in policy order
        enabled=True,
        auto_generated=True,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _auto_hairpin_nat_response(dnat, to_destination: Optional[str] = None) -> MachineFirewallRuleResponse:
    """Build the read-only synthetic POSTROUTING MASQUERADE row mirroring a
    DNAT's hairpin-NAT companion. The real companion is emitted once per LAN
    subnet (topology-resolved at apply time) so no single `source` value can
    represent it here — the comment carries the context instead.

    to_destination: resolved via firewall_orchestrator.resolve_dnat_targets()
    by the caller (falls back to dnat.to_destination when not given)."""
    fields = hairpin_masq_fields(dnat, to_destination)
    label = to_destination if to_destination is not None else dnat.to_destination
    return MachineFirewallRuleResponse(
        id=f"auto-hairpin-{dnat.id}",
        chain="POSTROUTING",
        action="MASQUERADE",
        protocol=fields["protocol"],
        source=None,
        destination=fields["destination"],
        port=fields["port"],
        in_interface=None,  # -i does not exist in POSTROUTING
        out_interface=None,
        state=None,
        limit_rate=None,
        limit_burst=None,
        to_destination=None,
        to_source=None,
        to_ports=None,
        log_prefix=None,
        log_level=None,
        reject_with=None,
        comment=f"→ hairpin {label}",
        table_name="nat",
        order=999_998,  # companions sit after user POSTROUTING rules
        enabled=True,
        auto_generated=True,
        created_at=dnat.created_at,
        updated_at=dnat.updated_at,
    )


def _auto_hairpin_forward_response(dnat, to_destination: Optional[str] = None) -> MachineFirewallRuleResponse:
    """Build the read-only synthetic FORWARD ACCEPT row mirroring a hairpin
    DNAT's LAN-side forward companion. apply_rules emits one such ACCEPT per
    LAN subnet (source=<subnet>) for LAN-originated reflected traffic — the
    DNAT's own FORWARD companion (_auto_forward_response) carries -i <wan> and
    never matches it. Like the hairpin MASQUERADE row, source collapses to None
    (no single subnet represents it); the comment carries the context. Shares
    hairpin_masq_fields with apply_rules so destination/port stay in sync."""
    fields = hairpin_masq_fields(dnat, to_destination)
    label = to_destination if to_destination is not None else dnat.to_destination
    return MachineFirewallRuleResponse(
        id=f"auto-hairpin-fwd-{dnat.id}",
        chain="FORWARD",
        action="ACCEPT",
        protocol=fields["protocol"],
        source=None,
        destination=fields["destination"],
        port=fields["port"],
        in_interface=None,
        out_interface=None,
        state=None,
        limit_rate=None,
        limit_burst=None,
        to_destination=None,
        to_source=None,
        to_ports=None,
        log_prefix=None,
        log_level=None,
        reject_with=None,
        comment=f"→ hairpin {label}",
        table_name="filter",
        order=999_998,  # companions sit after user policies, before the implicit deny
        enabled=True,
        auto_generated=True,
        created_at=dnat.created_at,
        updated_at=dnat.updated_at,
    )


def _auto_forward_response(dnat, to_destination: Optional[str] = None, refs_map=None) -> MachineFirewallRuleResponse:
    """Build the read-only synthetic FORWARD ACCEPT row that mirrors a DNAT
    companion. to_destination: resolved via resolve_dnat_targets() by the
    caller (falls back to dnat.to_destination when not given).

    Must mirror the DNAT's own source object/group refs (not just its literal
    `source` column) — apply_rules() already honors them for the real iptables
    rule via eff_map, but this display-only row previously showed the literal
    column, which is None whenever the source is an address object/group.
    """
    refs_map = refs_map or {}
    fields = dnat_forward_fields(dnat, to_destination)
    label = to_destination if to_destination is not None else dnat.to_destination
    source_refs = refs_map.get((dnat.id, "source"), [])
    return MachineFirewallRuleResponse(
        id=f"auto-dnat-{dnat.id}",
        chain="FORWARD",
        action="ACCEPT",
        protocol=fields["protocol"],
        source=None if source_refs else fields["source"],
        source_refs=source_refs,
        destination=fields["destination"],
        port=fields["port"],
        in_interface=fields["in_interface"],
        out_interface=None,
        state=None,
        limit_rate=None,
        limit_burst=None,
        to_destination=None,
        to_source=None,
        to_ports=None,
        log_prefix=None,
        log_level=None,
        reject_with=None,
        comment=f"→ DNAT {label}",
        table_name="filter",
        order=999_998,  # companions sit after user policies, before the implicit deny
        enabled=True,
        auto_generated=True,
        created_at=dnat.created_at,
        updated_at=dnat.updated_at,
    )


def _auto_input_response(rule, fields: dict, label: str) -> MachineFirewallRuleResponse:
    """
    Build the read-only synthetic INPUT ACCEPT row mirroring a REDIRECT or
    DNAT-to-self companion (both deliver to the gateway itself). order=-1 sorts
    it before user INPUT rules, matching real evaluation order (see apply_rules
    — the companion is prepended, not appended, unlike the FORWARD companions).
    Advanced renders auto_generated rows with a lock icon instead of the order
    number, so -1 never surfaces to the user.
    """
    return MachineFirewallRuleResponse(
        id=f"auto-rdr-{rule.id}",
        chain="INPUT",
        action="ACCEPT",
        protocol=fields["protocol"],
        source=fields["source"],
        destination=fields.get("destination"),
        port=fields["port"],
        in_interface=fields["in_interface"],
        out_interface=None,
        state=None,
        limit_rate=None,
        limit_burst=None,
        to_destination=None,
        to_source=None,
        to_ports=None,
        log_prefix=None,
        log_level=None,
        reject_with=None,
        comment=label,
        table_name="filter",
        order=-1,
        enabled=True,
        auto_generated=True,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _implicit_deny_response() -> MachineFirewallRuleResponse:
    """
    Read-only synthetic row for the always-last FORWARD implicit deny appended
    by apply_rules(). Informational only: not a DB rule, cannot be edited (the
    'auto-' id prefix locks it in both views).
    """
    now = datetime.utcnow()
    return MachineFirewallRuleResponse(
        id="auto-implicit-deny",
        chain="FORWARD",
        action="DROP",
        protocol=None,
        source=None,
        destination=None,
        port=None,
        in_interface=None,
        out_interface=None,
        state=None,
        limit_rate=None,
        limit_burst=None,
        to_destination=None,
        to_source=None,
        to_ports=None,
        log_prefix=None,
        log_level=None,
        reject_with=None,
        comment=IMPLICIT_DENY_COMMENT,
        table_name="filter",
        order=999_999,  # always last
        enabled=True,
        auto_generated=True,
        created_at=now,
        updated_at=now,
    )


async def _annotate_sequence_and_shadow(session: AsyncSession, rules, responses) -> None:
    """Evaluation sequence and shadowed/duplicate rules, per filter chain and nat/POSTROUTING."""
    from . import shadow

    sections = (await session.execute(select(ForwardSection))).scalars().all()
    pos = {(x.in_interface, x.out_interface): x.position for x in sections}
    by_id = {str(r.id): resp for r, resp in zip(rules, responses)}
    chains: dict = {}
    for r, resp in zip(rules, responses):
        if r.table_name == "filter" or (r.table_name == "nat" and r.chain == "POSTROUTING"):
            chains.setdefault((r.table_name, r.chain), []).append((r, resp))
    for (table, chain), items in chains.items():
        if chain == "FORWARD":
            items.sort(key=lambda it: (pos.get(section_key(it[0]), len(pos)), it[0].order))
        else:
            items.sort(key=lambda it: it[0].order)
        for i, (_, resp) in enumerate(items, start=1):
            resp.seq = i
        for rid, info in shadow.analyze([resp for _, resp in items], nat=table == "nat").items():
            resp = by_id[rid]
            resp.shadowed_by = info["by"]
            resp.shadowed_by_seq = by_id[info["by"]].seq
            resp.shadow_kind = info["kind"]


def _policy_nat_decision(resp) -> tuple:
    """A policy's NAT in shadow.nat_decision's terms (comparable to an SNAT rule)."""
    if resp.to_source or resp.nat_pool_id:
        return ("SNAT", resp.to_source, resp.nat_pool_id)
    return ("MASQUERADE", None, None)


async def _annotate_nat(rules, responses, default_if: Optional[str], full: bool) -> None:
    """
    For every forward policy with NAT:
    - nat_via: where its NAT applies when it names no outgoing interface
      (the default-route interface: the companion carries -o <it>);
    - nat_warning ip_not_local: its address is no longer on that interface;
    - nat_overridden_by: an enabled nat/POSTROUTING rule of Advanced that
      matches all of its traffic and NATs it differently. Those rules are
      evaluated first, so the policy's NAT never applies: Standard and
      Advanced disagree. Only with the full listing (full=True).
    """
    from types import SimpleNamespace
    from . import shadow
    policies = [(r, resp) for r, resp in zip(rules, responses)
                if r.table_name == "filter" and r.chain == "FORWARD" and r.policy_nat and r.action == "ACCEPT"]
    if not policies:
        return
    addrs = None
    if any(r.to_source for r, _ in policies):
        try:
            addrs = await asyncio.to_thread(natpool.interface_addresses)
        except Exception:
            logger.exception("Interface addresses unavailable for the NAT check")
    advanced = sorted((resp for r, resp in zip(rules, responses)
                       if r.table_name == "nat" and r.chain == "POSTROUTING" and r.enabled),
                      key=lambda x: x.order)
    for rule, resp in policies:
        out = rule.out_interface or default_if
        if not rule.out_interface:
            resp.nat_via = default_if
        if rule.to_source and addrs is not None and not natpool.nat_ip_is_local(rule.to_source, out, addrs):
            resp.nat_warning = "ip_not_local"
        if not (full and rule.enabled):
            continue
        # the policy's traffic as POSTROUTING sees it
        view = SimpleNamespace(**{**resp.model_dump(), "out_interface": out})
        for adv in advanced:
            if shadow.covers(adv, view):
                if shadow.nat_decision(adv) != _policy_nat_decision(resp):
                    resp.nat_overridden_by = adv.id
                    resp.nat_overridden_by_seq = adv.seq
                break


@router.get("/rules", response_model=List[MachineFirewallRuleResponse])
async def list_rules(
    chain: Optional[str] = None,
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session)
):
    """List all firewall rules, optionally filtered by chain."""
    rules = await firewall_orchestrator.get_all_rules(session, chain)
    refs_map = await _rule_refs_map(session, [r.id for r in rules])
    dnat_obj_names = await _dnat_obj_names_map(session, rules)
    pools = {p.id: p for p in (await session.execute(select(NatPool))).scalars().all()}
    pool_names = {pid: p.name for pid, p in pools.items()}
    responses = [_rule_to_response(r, refs_map, dnat_obj_names, pool_names) for r in rules]
    await _annotate_sequence_and_shadow(session, rules, responses)
    default_if = await asyncio.to_thread(get_default_interface)
    await _annotate_nat(rules, responses, default_if, full=chain is None)
    # Surface auto-generated DNAT forward companions on the FORWARD (filter) chain
    if chain in (None, "FORWARD"):
        dnat_rules = await firewall_orchestrator.get_enabled_dnat_rules(session)
        dnat_targets = await firewall_orchestrator.resolve_dnat_targets(session, dnat_rules)
        dnat_refs_map = await _rule_refs_map(session, [d.id for d in dnat_rules])
        responses.extend(
            _auto_forward_response(d, dnat_targets.get(d.id), dnat_refs_map) for d in dnat_rules
        )
        # Hairpin DNATs also emit a LAN-side FORWARD ACCEPT (apply_rules
        # hairpin_forward_lines) that the DNAT's own -i <wan> companion above
        # never covers. Surface it here so the FORWARD listing mirrors the
        # engine — ordered after the DNAT companions, before the implicit deny,
        # exactly as apply_rules appends them.
        hairpin_fwd_rules = await firewall_orchestrator.get_enabled_hairpin_rules(session)
        hairpin_fwd_targets = await firewall_orchestrator.resolve_dnat_targets(session, hairpin_fwd_rules)
        responses.extend(
            _auto_hairpin_forward_response(d, hairpin_fwd_targets.get(d.id)) for d in hairpin_fwd_rules
        )
        responses.append(_implicit_deny_response())
    # Surface auto-generated policy-NAT masquerade companions on the POSTROUTING (nat) chain
    if chain in (None, "POSTROUTING"):
        nat_policies = await firewall_orchestrator.get_enabled_policy_nat_rules(session)
        # In the order apply_rules emits them: the policies' evaluation order
        positions = {
            (s.in_interface, s.out_interface): s.position
            for s in (await session.execute(select(ForwardSection))).scalars().all()
        }
        nat_policies = sorted(nat_policies, key=lambda p: (
            positions.get(section_key(p), len(positions)), p.order))
        responses.extend(_auto_nat_response(p, default_if, i, pools) for i, p in enumerate(nat_policies))
        hairpin_rules = await firewall_orchestrator.get_enabled_hairpin_rules(session)
        hairpin_targets = await firewall_orchestrator.resolve_dnat_targets(session, hairpin_rules)
        responses.extend(_auto_hairpin_nat_response(d, hairpin_targets.get(d.id)) for d in hairpin_rules)
    # Surface auto-generated INPUT ACCEPT companions (REDIRECT / DNAT-to-self)
    if chain in (None, "INPUT"):
        input_companions = await firewall_orchestrator.get_enabled_input_companion_rules(session)
        for r in input_companions["redirect"]:
            fields = redirect_input_fields(r)
            label = f"→ REDIRECT :{fields['port']}" if fields["port"] else "→ REDIRECT"
            responses.append(_auto_input_response(r, fields, label))
        dnat_self_targets = await firewall_orchestrator.resolve_dnat_targets(
            session, input_companions["dnat_self"]
        )
        for r in input_companions["dnat_self"]:
            target = dnat_self_targets.get(r.id)
            fields = dnat_input_fields(r, target)
            responses.append(_auto_input_response(r, fields, f"→ DNAT self {target}"))
    return responses


@router.get("/preview")
async def preview_ruleset(
    rule_id: Optional[str] = None,
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session),
):
    """
    The ruleset an apply would load, in iptables-restore format, without
    changing anything. With rule_id: only the lines of that rule, its
    companions included (DNAT FORWARD accept, hairpin, policy-NAT mark and
    masquerade), all tagged with its id.
    """
    from .iptables import _RESTORE_TABLE_ORDER
    chain_rules, subchains, _rules, _topo = await firewall_orchestrator.build_ruleset(session, side_effects=False)
    chain_rules["filter"].update(subchains)
    lines = []
    for table in _RESTORE_TABLE_ORDER:
        for chain, body in chain_rules.get(table, {}).items():
            for line in body:
                lines.append({"table": table, "chain": chain, "line": line})
    if rule_id:
        lines = [x for x in lines if rule_id in x["line"]]
    text_parts = []
    tables = []
    for table in _RESTORE_TABLE_ORDER:
        chains = chain_rules.get(table, {})
        if not chains:
            continue
        block = [f"*{table}"]
        block.extend(f":{c} - [0:0]" for c in chains)
        table_lines = [x["line"] for x in lines if x["table"] == table]
        block.extend(table_lines)
        block.append("COMMIT")
        text_parts.extend(block)
        # One block per table for the Advanced preview tabs
        tables.append({
            "table": table,
            "chains": len(chains),
            "rules": len(table_lines),
            "text": "\n".join(block) + "\n",
        })
    return {"lines": lines, "tables": tables, "text": "\n".join(text_parts) + "\n"}


@router.get("/sections", response_model=List[ForwardSectionResponse])
async def list_forward_sections(
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session),
):
    """filter/FORWARD interface-pair groups in evaluation order ("" = any)."""
    from sqlalchemy import func
    rows = (await session.execute(
        select(ForwardSection).order_by(ForwardSection.position)
    )).scalars().all()
    counts = {}
    for in_if, out_if, n in (await session.execute(
        select(MachineFirewallRule.in_interface, MachineFirewallRule.out_interface, func.count())
        .where(MachineFirewallRule.table_name == "filter", MachineFirewallRule.chain == "FORWARD")
        .group_by(MachineFirewallRule.in_interface, MachineFirewallRule.out_interface)
    )).all():
        key = (in_if or "", out_if or "")
        counts[key] = counts.get(key, 0) + n
    return [
        ForwardSectionResponse(
            id=str(r.id), in_interface=r.in_interface, out_interface=r.out_interface,
            position=r.position, rule_count=counts.get((r.in_interface, r.out_interface), 0),
        )
        for r in rows
    ]


class SectionOrderUpdate(SQLModel):
    section_ids: List[str]


@router.put("/sections/order")
async def update_forward_section_order(
    data: SectionOrderUpdate,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session),
):
    """
    Reorder the interface-pair groups: the earlier group sees a packet first.
    The list must name every current section exactly once.
    """
    rows = (await session.execute(select(ForwardSection))).scalars().all()
    by_id = {str(r.id): r for r in rows}
    if sorted(data.section_ids) != sorted(by_id):
        raise HTTPException(status_code=400, detail="L'elenco deve contenere ogni gruppo una sola volta")
    for i, sid in enumerate(data.section_ids):
        by_id[sid].position = i
    await session.flush()
    try:
        await firewall_orchestrator.apply_rules(session)
        await session.commit()
    except IptablesError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok"}


@router.get("/counters/history")
async def get_rule_traffic_history(
    hours: int = Query(24, ge=1, le=168),
    buckets: int = Query(24, ge=4, le=96),
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session),
):
    """
    Bytes per rule over the last `hours`, in `buckets` equal slots (oldest
    first), for the sparklines. Rules without traffic in the window are left out.
    """
    since = datetime.utcnow() - timedelta(hours=hours)
    rows = (await session.execute(
        select(RuleTrafficSample.rule_id, RuleTrafficSample.ts, RuleTrafficSample.bytes)
        .where(RuleTrafficSample.ts >= since)
    )).all()
    width = hours * 3600 / buckets
    out: dict = {}
    for rule_id, ts, nbytes in rows:
        idx = min(buckets - 1, int((ts - since).total_seconds() // width))
        series = out.setdefault(str(rule_id), [0] * buckets)
        series[idx] += nbytes
    return {"hours": hours, "buckets": buckets, "series": out}


@router.get("/counters", response_model=List[RuleCounterResponse])
async def get_rule_counters(
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session)
):
    """
    Durable per-rule hit-count/traffic totals (see models.RuleCounter — kernel
    iptables counters are zeroed on every apply, so these accumulate deltas
    across applies/reboots). Snapshots the live kernel state on every call so
    totals are fresh; the Standard view fetches this once on page load
    (fire-and-forget, no polling) and renders it as a per-rule hover popover.
    """
    await firewall_orchestrator.snapshot_counters(session)
    result = await session.execute(select(RuleCounter))
    return [
        RuleCounterResponse(
            rule_id=str(c.rule_id),
            packets=c.packets,
            bytes=c.bytes,
            window_start=c.window_start,
            updated_at=c.updated_at,
        )
        for c in result.scalars().all()
    ]


@router.get("/rules/{rule_id}", response_model=MachineFirewallRuleResponse)
async def get_rule(
    rule_id: str,
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session)
):
    """Get a specific firewall rule by ID."""
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule ID format")
    
    rule = await firewall_orchestrator.get_rule_by_id(session, rule_uuid)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    refs_map = await _rule_refs_map(session, [rule.id])
    dnat_obj_names = await _dnat_obj_names_map(session, [rule])
    return _rule_to_response(rule, refs_map, dnat_obj_names, await _pool_names_map(session))


@router.post("/rules", response_model=MachineFirewallRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(
    rule_data: MachineFirewallRuleCreate,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Create a new firewall rule."""
    await _validate_rule_payload(
        session, rule_data.model_dump(),
        has_source_refs=bool(rule_data.source_refs),
        has_destination_refs=bool(rule_data.destination_refs),
    )
    await _validate_rule_refs(session, rule_data.source_refs, rule_data.destination_refs)

    try:
        rule = await firewall_orchestrator.create_rule(session, rule_data.model_dump())
        await session.commit()
        refs_map = await _rule_refs_map(session, [rule.id])
        dnat_obj_names = await _dnat_obj_names_map(session, [rule])
        return _rule_to_response(rule, refs_map, dnat_obj_names, await _pool_names_map(session))
    except IptablesError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        logger.error(f"Error creating firewall rule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/rules/{rule_id}", response_model=MachineFirewallRuleResponse)
async def update_rule(
    rule_id: str,
    rule_data: MachineFirewallRuleUpdate,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Update an existing firewall rule."""
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule ID format")

    # Filter out None values
    update_data = rule_data.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Validate the resulting state (merge existing rule with the partial update)
    existing = await firewall_orchestrator.get_rule_by_id(session, rule_uuid)
    if not existing:
        raise HTTPException(status_code=404, detail="Rule not found")

    from core.provisioning.service import MANAGED_NAT_SENTINEL
    if existing.comment == MANAGED_NAT_SENTINEL:
        raise HTTPException(
            status_code=403,
            detail="Regola NAT della LAN gestita: non modificabile (necessaria alla navigazione delle VM)."
        )

    # Validate the rule as it will be after the update: table/chain/action
    # were only checked on create, so a PATCH could move a rule anywhere
    merged = {
        field: getattr(existing, field)
        for field in MachineFirewallRuleUpdate.model_fields
        if hasattr(existing, field)
    }
    if merged.get("to_destination_object_id") is not None:
        merged["to_destination_object_id"] = str(merged["to_destination_object_id"])
    merged.update(update_data)
    existing_dirs_res = await session.execute(
        select(FirewallRuleAddress.direction).where(FirewallRuleAddress.rule_id == rule_uuid)
    )
    existing_dirs = {row[0] for row in existing_dirs_res.all()}
    await _validate_rule_payload(
        session, merged,
        exclude_rule_id=rule_uuid,
        touched=set(update_data.keys()),
        has_source_refs=(bool(update_data["source_refs"]) if "source_refs" in update_data
                         else "source" in existing_dirs),
        has_destination_refs=(bool(update_data["destination_refs"]) if "destination_refs" in update_data
                              else "destination" in existing_dirs),
    )
    await _validate_rule_refs(session, rule_data.source_refs, rule_data.destination_refs)

    try:
        rule = await firewall_orchestrator.update_rule(session, rule_uuid, update_data)
        if not rule:
            raise HTTPException(status_code=404, detail="Rule not found")

        await session.commit()

        refs_map = await _rule_refs_map(session, [rule.id])
        dnat_obj_names = await _dnat_obj_names_map(session, [rule])
        return _rule_to_response(rule, refs_map, dnat_obj_names, await _pool_names_map(session))
    except IptablesError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        await session.rollback()
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Error updating firewall rule {rule_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: str,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Delete a firewall rule."""
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule ID format")

    existing = await firewall_orchestrator.get_rule_by_id(session, rule_uuid)
    if existing:
        from core.provisioning.service import MANAGED_NAT_SENTINEL
        if existing.comment == MANAGED_NAT_SENTINEL:
            raise HTTPException(
                status_code=403,
                detail="Regola NAT della LAN gestita: non eliminabile (necessaria alla navigazione delle VM)."
            )

    try:
        success = await firewall_orchestrator.delete_rule(session, rule_uuid)
        if not success:
            raise HTTPException(status_code=404, detail="Rule not found")

        await session.commit()
    except IptablesError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        await session.rollback()
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Error deleting firewall rule {rule_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


class FlushRequest(SQLModel):
    # Preview by default: closing sessions is only done on an explicit confirm
    dry_run: bool = True


async def _rule_views(session: AsyncSession, chain: str, table: str = "filter") -> List[flowmatch.RuleView]:
    """
    Enabled rules of `table`/`chain` in evaluation order (filter FORWARD: groups in
    ForwardSection order, then rule order), with address refs resolved to
    networks. An FQDN object never resolved, or a country list not on disk,
    makes that side "unknown": the matcher then keeps the connection.
    """
    import ipaddress
    from . import geoip

    rules = (await session.execute(
        select(MachineFirewallRule).where(
            MachineFirewallRule.table_name == table,
            MachineFirewallRule.chain == chain,
            MachineFirewallRule.enabled == True,  # noqa: E712
        ).order_by(MachineFirewallRule.order)
    )).scalars().all()
    if table == "filter" and chain == "FORWARD":
        sections = (await session.execute(select(ForwardSection))).scalars().all()
        pos = {(x.in_interface, x.out_interface): x.position for x in sections}
        rules = sorted(rules, key=lambda r: (pos.get(section_key(r), len(pos)), r.order))

    refs = (await session.execute(
        select(FirewallRuleAddress).where(FirewallRuleAddress.rule_id.in_([r.id for r in rules]))
    )).scalars().all() if rules else []
    objects = {o.id: o for o in (await session.execute(select(AddressObject))).scalars().all()}
    members: dict = {}
    for m in (await session.execute(select(AddressGroupMember))).scalars().all():
        if m.member_object_id:
            members.setdefault(m.group_id, []).append(m.member_object_id)

    def obj_nets(obj):
        if obj is None or not obj.enabled:
            return []
        if obj.type == "fqdn":
            ips = json.loads(obj.resolved_ips) if obj.resolved_ips else None
            return None if not ips else [ipaddress.ip_network(ip, strict=False) for ip in ips]
        entries = geoip._read_cached_cidrs(obj.value) if obj.type == "geo" else addresses.resolve_entries(obj.type, obj.value)
        if obj.type == "geo" and not entries:
            return None
        return [ipaddress.ip_network(e, strict=False) for e in entries]

    def side(rule, direction):
        rows = [x for x in refs if x.rule_id == rule.id and x.direction == direction]
        if not rows:
            literal = rule.source if direction == "source" else rule.destination
            return None if not literal else [ipaddress.ip_network(literal, strict=False)]
        nets = []
        for x in rows:
            ids = [x.object_id] if x.object_id else members.get(x.group_id, [])
            for oid in ids:
                n = obj_nets(objects.get(oid))
                if n is None:
                    return "unknown"
                nets.extend(n)
        return nets

    views = []
    for r in rules:
        try:
            src, dst = side(r, "source"), side(r, "destination")
        except ValueError:
            src = dst = "unknown"
        views.append(flowmatch.RuleView(
            id=str(r.id), action=r.action, protocol=r.protocol, port=r.port,
            in_interface=r.in_interface, out_interface=r.out_interface,
            src=src, dst=dst, state=r.state, limited=bool(r.limit_rate),
        ))
    return views


class TraceRequest(SQLModel):
    protocol: str = "tcp"            # tcp | udp | icmp | protocol number
    source: str
    destination: str
    dport: Optional[int] = None
    in_interface: Optional[str] = None
    out_interface: Optional[str] = None

    @field_validator("protocol")
    @classmethod
    def _proto(cls, v):
        v = (v or "").lower()
        if not re.fullmatch(r"tcp|udp|icmp|\d{1,3}", v):
            raise ValueError("Protocollo non valido")
        return v

    @field_validator("source", "destination")
    @classmethod
    def _ip(cls, v):
        import ipaddress
        try:
            return str(ipaddress.IPv4Address(v.strip()))
        except ValueError:
            raise ValueError(f"Indirizzo IPv4 non valido: {v}")

    @field_validator("dport")
    @classmethod
    def _port(cls, v):
        if v is not None and not 1 <= v <= 65535:
            raise ValueError("Porta non valida")
        return v

    @field_validator("in_interface", "out_interface")
    @classmethod
    def _iface(cls, v):
        if v in (None, ""):
            return None
        if not re.fullmatch(r"[A-Za-z0-9._@-]{1,15}", v):
            raise ValueError(f"Interfaccia non valida: {v}")
        return v


async def _seq_map(session: AsyncSession, chain: str, table: str = "filter") -> dict:
    """rule id -> 1-based position in evaluation order (as in GET /rules)."""
    rules = (await session.execute(
        select(MachineFirewallRule).where(
            MachineFirewallRule.table_name == table, MachineFirewallRule.chain == chain,
        )
    )).scalars().all()
    if chain == "FORWARD":
        sections = (await session.execute(select(ForwardSection))).scalars().all()
        pos = {(x.in_interface, x.out_interface): x.position for x in sections}
        rules.sort(key=lambda r: (pos.get(section_key(r), len(pos)), r.order))
    else:
        rules.sort(key=lambda r: r.order)
    return {str(r.id): i for i, r in enumerate(rules, start=1)}


async def _trace_snat(session: AsyncSession, flow, topo, decision: dict) -> dict:
    """
    The address a forwarded connection leaves with. The nat/POSTROUTING rules
    of Advanced come first, in order (the first match decides); then the NAT
    of the policy that accepted the connection (its connection mark).
    kind: none | masquerade | snat | pool | netmap | unknown.
    """
    from .orchestrator import rule_nat_target
    pools = {p.id: p for p in (await session.execute(select(NatPool))).scalars().all()}
    out_dev = topo.dev_for(flow.reply_src)
    try:
        addrs = await asyncio.to_thread(natpool.interface_addresses)
    except Exception:
        addrs = {}

    def describe(action, args, pool):
        if action == "MASQUERADE":
            ips = addrs.get(out_dev) or []
            return {"kind": "masquerade", "ip": ips[0] if ips else None, "interface": out_dev}
        if action == "NETMAP":
            # NETMAP keeps the host part of the source
            net = ipaddress.IPv4Network(args["netmap_to"])
            host = int(ipaddress.IPv4Address(flow.src)) & int(net.hostmask)
            return {"kind": "netmap", "ip": str(net.network_address + host), "pool": pool.name if pool else None}
        return {"kind": "pool" if pool else "snat", "ip": args.get("to_source"),
                "pool": pool.name if pool else None}

    rows = {str(r.id): r for r in (await session.execute(
        select(MachineFirewallRule).where(
            MachineFirewallRule.table_name == "nat", MachineFirewallRule.chain == "POSTROUTING")
    )).scalars().all()}
    seq = await _seq_map(session, "POSTROUTING", table="nat")
    for view in await _rule_views(session, "POSTROUTING", table="nat"):
        m = flowmatch.match(view, flow, "POSTROUTING", topo)
        if m is False:
            continue
        where = {"rule_id": view.id, "seq": seq.get(view.id), "advanced": True}
        if m is None:
            return {"kind": "unknown", **where}
        rule = rows[view.id]
        if rule.action in ("ACCEPT", "RETURN"):
            return {"kind": "none", **where}
        try:
            action, args = rule_nat_target(rule, pools) or (rule.action, {"to_source": rule.to_source})
        except ValueError:
            return {"kind": "unknown", **where}
        return {**describe(action, args, pools.get(rule.nat_pool_id)), **where}

    policy_id = decision.get("rule_id")
    policy = await session.get(MachineFirewallRule, uuid.UUID(policy_id)) if policy_id else None
    if policy is not None and policy.policy_nat:
        try:
            action, args = policy_nat_target(policy, pools)
        except ValueError:
            return {"kind": "unknown", "rule_id": policy_id, "seq": decision.get("seq")}
        return {**describe(action, args, pools.get(policy.nat_pool_id)),
                "rule_id": policy_id, "seq": decision.get("seq")}
    return {"kind": "none"}


@router.post("/trace")
async def trace_packet(
    data: TraceRequest,
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session),
):
    """
    Which rule decides a packet (the first one of a new connection)?

    Simulates the MADMIN rules in engine order: port forwards (nat PREROUTING
    DNAT) rewrite the destination first, then INPUT (to this machine) or
    FORWARD. Interfaces not given are inferred from the routing table.
    Module chains (VPN, IPsec, DNS) run before MADMIN's and are not simulated.
    A forwarded connection that is accepted also gets `snat`: the address it
    leaves with (see _trace_snat).
    """
    import ipaddress
    try:
        topo = await asyncio.to_thread(flowmatch.Topology.from_system) if not settings.mock_iptables else None
    except (OSError, subprocess.SubprocessError, ValueError):
        topo = None
    routes = []
    if data.in_interface:
        routes.append((ipaddress.ip_network(f"{data.source}/32"), data.in_interface))
    if topo is None:
        topo = flowmatch.Topology([], set(), None)
    notes = []

    def flow_for(dst, reply_src):
        return flowmatch.Flow(proto=data.protocol, src=data.source, dst=dst, sport=None,
                              dport=data.dport, reply_src=reply_src)

    # 1. Port forwards: first matching DNAT rewrites the destination
    dnat = None
    pre_topo = flowmatch.Topology(routes + topo.routes, topo.local_ips, topo.default_dev)
    targets = await firewall_orchestrator.resolve_dnat_targets(
        session, await firewall_orchestrator.get_enabled_dnat_rules(session))
    for view in await _rule_views(session, "PREROUTING", table="nat"):
        if view.action not in ("DNAT", "REDIRECT"):
            continue
        m = flowmatch.match(view, flow_for(data.destination, data.destination), "PREROUTING", pre_topo)
        if m is None:
            notes.append("uncertain_dnat")
            break
        if m:
            to = targets.get(uuid.UUID(view.id)) if view.action == "DNAT" else None
            dnat = {"rule_id": view.id, "action": view.action, "to": to}
            break
    # After a DNAT, FORWARD sees the internal target as destination
    reply_src = dnat["to"].split(":")[0] if dnat and dnat.get("to") else data.destination

    # 2. Chain: to this machine (not forwarded elsewhere) or through it
    flow = flow_for(data.destination, reply_src)
    if data.out_interface:
        routes.append((ipaddress.ip_network(f"{reply_src}/32"), data.out_interface))
    ttopo = flowmatch.Topology(routes + topo.routes, topo.local_ips, topo.default_dev)
    # REDIRECT always delivers to this machine, whatever the original destination
    chain = "INPUT" if dnat and dnat["action"] == "REDIRECT" else flowmatch.chain_of(flow, ttopo)
    if not topo.local_ips:
        notes.append("no_topology")

    # 3. Rules in order: the first terminal match decides
    seq = await _seq_map(session, chain)
    steps = []
    decision = None
    for view in await _rule_views(session, chain):
        m = flowmatch.match(view, flow, chain, ttopo)
        steps.append({"rule_id": view.id, "seq": seq.get(view.id), "action": view.action,
                      "result": "match" if m else ("unknown" if m is None else "no")})
        if m is None and view.action in flowmatch.TERMINAL:
            notes.append("uncertain_rule")
        if m and view.action in flowmatch.TERMINAL and not view.limited:
            decision = {"rule_id": view.id, "seq": seq.get(view.id), "action": view.action}
            break
    if decision is None:
        if chain == "FORWARD" and dnat and dnat["action"] == "DNAT":
            decision = {"auto": "dnat_companion", "action": "ACCEPT"}
        elif chain == "FORWARD":
            decision = {"auto": "implicit_deny", "action": "DROP"}
        else:
            decision = {"auto": "chain_policy", "action": "ACCEPT"}
    snat = None
    if chain == "FORWARD" and decision["action"] == "ACCEPT":
        snat = await _trace_snat(session, flow, ttopo, decision)
    return {
        "chain": chain,
        "in_interface": ttopo.dev_for(data.source),
        "out_interface": ttopo.dev_for(reply_src) if chain == "FORWARD" else None,
        "dnat": dnat, "steps": steps, "decision": decision, "snat": snat,
        "notes": sorted(set(notes)),
    }


@router.post("/rules/{rule_id}/flush-conntrack")
async def flush_rule_conntrack(
    rule_id: str,
    request: Request,
    data: Optional[FlushRequest] = Body(None),
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    Close the established connections a DROP/REJECT rule would now stop, or
    those a FORWARD ACCEPT policy decides, after its NAT changed: the NAT of a
    connection is decided on its first packet, so open ones keep the old
    address until they are reopened.

    Only connections whose first deciding rule — in the order the engine
    evaluates the chain — is this one: a connection an earlier rule accepts is
    left alone, and so is anything whose match depends on something unknown,
    plus every connection of the requesting client. dry_run (default) returns
    the preview; dry_run=false deletes exactly the listed entries.
    """
    dry_run = data.dry_run if data else True
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule ID format")

    rule = await firewall_orchestrator.get_rule_by_id(session, rule_uuid)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if rule.action not in ("DROP", "REJECT") and not (rule.action == "ACCEPT" and rule.chain == "FORWARD"):
        raise HTTPException(status_code=400, detail="Chiusura sessioni disponibile per DROP/REJECT e per le policy FORWARD")
    if rule.table_name != "filter" or rule.chain not in ("INPUT", "FORWARD"):
        raise HTTPException(status_code=400, detail="Chiusura sessioni disponibile solo per regole filter INPUT/FORWARD")
    if not rule.enabled:
        raise HTTPException(status_code=400, detail="La regola è disattivata")

    result = {"close": 0, "shadowed": 0, "uncertain": 0, "protected": 0, "samples": [], "deleted": 0}
    if settings.mock_iptables:
        return result

    views = await _rule_views(session, rule.chain)
    target = next((v for v in views if v.id == str(rule.id)), None)
    if target is None:
        return result
    try:
        topo = await asyncio.to_thread(flowmatch.Topology.from_system)
        flows = await asyncio.to_thread(flowmatch.list_flows)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as e:
        logger.warning(f"conntrack preview failed: {e}")
        raise HTTPException(status_code=503, detail="Impossibile leggere le sessioni attive (conntrack)")

    sel = flowmatch.select_flows(flows, target, rule.chain, views, topo, {get_client_ip(request)})
    result.update({k: len(v) for k, v in sel.items() if k != "close"})
    result["close"] = len(sel["close"])
    result["samples"] = [f.describe() for f in sel["close"][:10]]
    if dry_run:
        return result

    to_close = sel["close"][:_FLUSH_MAX]
    result["deleted"] = await asyncio.to_thread(lambda: sum(1 for f in to_close if flowmatch.delete_flow(f)))
    logger.info(f"Closed {result['deleted']} sessions for rule {rule.id} "
                f"(kept: {result['shadowed']} accepted earlier, {result['uncertain']} uncertain)")
    return result


_FLUSH_MAX = 5000


@router.put("/rules/order")
async def update_rule_order(
    orders: List[RuleOrderUpdate],
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Update the order of firewall rules."""
    order_list = [{"id": o.id, "order": o.order} for o in orders]
    
    try:
        await firewall_orchestrator.reorder_rules(session, order_list)
        await session.commit()
        return {"status": "ok", "message": f"Updated order for {len(orders)} rules"}
    except IptablesError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        logger.error(f"Error reordering firewall rules: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


class SingleRuleReorder(SQLModel):
    new_order: int


@router.patch("/rules/{rule_id}/reorder")
async def reorder_single_rule(
    rule_id: str,
    data: SingleRuleReorder,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Move a single rule to a new position."""
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule ID format")
    
    from sqlalchemy import select
    from .models import MachineFirewallRule
    
    try:
        # Get the rule
        result = await session.execute(
            select(MachineFirewallRule).where(MachineFirewallRule.id == rule_uuid)
        )
        rule = result.scalar_one_or_none()
        if not rule:
            raise HTTPException(status_code=404, detail="Rule not found")
        
        old_order = rule.order
        new_order = data.new_order
        
        # Get all rules in the same chain/table
        chain_rules = await session.execute(
            select(MachineFirewallRule)
            .where(MachineFirewallRule.chain == rule.chain)
            .where(MachineFirewallRule.table_name == rule.table_name)
            .order_by(MachineFirewallRule.order)
        )
        all_rules = list(chain_rules.scalars().all())
        
        # Shift rules
        if new_order < old_order:
            # Moving up
            for r in all_rules:
                if r.id != rule.id and r.order >= new_order and r.order < old_order:
                    r.order += 1
        else:
            # Moving down
            for r in all_rules:
                if r.id != rule.id and r.order > old_order and r.order <= new_order:
                    r.order -= 1
        
        rule.order = new_order
        await session.flush()

        # Re-apply rules BEFORE committing: if the kernel rejects the new
        # ruleset, the except IptablesError below must roll back the order
        # mutations too, or DB and kernel state permanently diverge.
        await firewall_orchestrator.apply_rules(session)

        await session.commit()

        return {"status": "ok", "message": f"Rule moved to position {new_order}"}
    except IptablesError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        await session.rollback()
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Error reordering firewall rule {rule_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/apply")
async def apply_rules(
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Manually trigger rule application to iptables."""
    try:
        success = await firewall_orchestrator.apply_rules(session)
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to apply some rules. Check server logs."
            )
        
        return {"status": "ok", "message": "Rules applied successfully"}
    except IptablesError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/geo/countries")
async def list_geo_countries(
    current_user: User = Depends(require_permission("firewall.view")),
):
    """List ISO 3166-1 alpha-2 countries available for geo-type address objects."""
    return [{"code": code.lower(), "name": name} for code, name in geoip.country_choices()]


# =============================================================================
# ADDRESS OBJECTS & GROUPS
# =============================================================================

def _validate_object_value(obj_type: str, value: str) -> str:
    """Validate + normalize an address object value by type (IPv4 only)."""
    if obj_type not in ADDRESS_OBJECT_TYPES:
        raise HTTPException(status_code=400, detail=f"Tipo oggetto non valido: {obj_type}")
    v = (value or "").strip()
    if not v:
        raise HTTPException(status_code=400, detail="Il valore è obbligatorio")
    try:
        if obj_type == "cidr":
            return addresses.normalize_cidr(v)
        if obj_type == "range":
            addresses.range_to_cidrs(v)   # validates, raises ValueError
            return v
        if obj_type == "fqdn":
            if not addresses.is_valid_fqdn(v):
                raise ValueError("FQDN non valido")
            return v.lower()
        if obj_type == "geo":
            cc = v.lower()
            if not geoip.is_valid_country_code(cc):
                raise ValueError(f"Codice paese non valido: {v}")
            return cc
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    raise HTTPException(status_code=400, detail="Tipo oggetto non valido")


async def _unique_ref_key(session: AsyncSession, model) -> str:
    for _ in range(12):
        key = addresses.new_ref_key()
        res = await session.execute(select(model).where(model.ref_key == key))
        if res.scalar_one_or_none() is None:
            return key
    raise HTTPException(status_code=500, detail="Impossibile generare una chiave univoca")


def _seed_fqdn_resolution(obj: AddressObject) -> None:
    """Best-effort initial DNS resolution for an fqdn object so its set has
    content immediately. geo lists are downloaded off the request path."""
    if obj.type == "fqdn":
        ips = addresses._resolve_fqdn(obj.value)
        if ips:
            obj.resolved_ips = json.dumps(ips)
            obj.resolved_at = datetime.utcnow()


def _object_to_response(o: AddressObject) -> AddressObjectResponse:
    ips = None
    if o.resolved_ips:
        try:
            ips = json.loads(o.resolved_ips)
        except Exception:
            ips = None
    return AddressObjectResponse(
        id=str(o.id), ref_key=o.ref_key, name=o.name, type=o.type, value=o.value,
        description=o.description, enabled=o.enabled, resolved_ips=ips,
        resolved_at=o.resolved_at, set_name=addresses.object_leaf_set_name(o.ref_key),
        created_at=o.created_at, updated_at=o.updated_at,
    )


async def _groups_to_response(session: AsyncSession, groups) -> List[AddressGroupResponse]:
    """Members, objects and nested groups loaded in one query each for the whole list."""
    groups = list(groups)
    if not groups:
        return []
    mres = await session.execute(
        select(AddressGroupMember).where(AddressGroupMember.group_id.in_([g.id for g in groups]))
    )
    members_by_group = {}
    for m in mres.scalars().all():
        members_by_group.setdefault(m.group_id, []).append(m)
    all_members = [m for ms in members_by_group.values() for m in ms]
    obj_ids = {m.member_object_id for m in all_members if m.member_object_id}
    grp_ids = {m.member_group_id for m in all_members if m.member_group_id}
    objs, grps = {}, {}
    if obj_ids:
        ores = await session.execute(select(AddressObject).where(AddressObject.id.in_(obj_ids)))
        objs = {o.id: o for o in ores.scalars().all()}
    if grp_ids:
        gres = await session.execute(select(AddressGroup).where(AddressGroup.id.in_(grp_ids)))
        grps = {gg.id: gg for gg in gres.scalars().all()}

    out = []
    for g in groups:
        member_resp = []
        for m in members_by_group.get(g.id, []):
            if m.member_object_id and m.member_object_id in objs:
                o = objs[m.member_object_id]
                member_resp.append(AddressGroupMemberResponse(
                    object_id=str(o.id), name=o.name, kind="object", type=o.type))
            elif m.member_group_id and m.member_group_id in grps:
                gg = grps[m.member_group_id]
                member_resp.append(AddressGroupMemberResponse(
                    group_id=str(gg.id), name=gg.name, kind="group"))
        out.append(AddressGroupResponse(
            id=str(g.id), ref_key=g.ref_key, name=g.name, description=g.description,
            enabled=g.enabled, set_name=addresses.group_set_name(g.ref_key),
            members=member_resp, created_at=g.created_at, updated_at=g.updated_at,
        ))
    return out


async def _group_to_response(session: AsyncSession, g: AddressGroup) -> AddressGroupResponse:
    return (await _groups_to_response(session, [g]))[0]


async def _set_group_members(session: AsyncSession, group_id, members) -> None:
    """Replace a group's members (v1: only object members)."""
    await session.execute(
        delete(AddressGroupMember).where(AddressGroupMember.group_id == group_id)
    )
    for m in (members or []):
        oid = getattr(m, "object_id", None)
        gid = getattr(m, "group_id", None)
        if gid:
            raise HTTPException(status_code=400, detail="Gruppi annidati non supportati in questa versione.")
        if not oid:
            continue
        ouid = _uuid(oid)
        obj = await session.get(AddressObject, ouid)
        if not obj:
            raise HTTPException(status_code=400, detail=f"Oggetto indirizzo non trovato: {oid}")
        session.add(AddressGroupMember(group_id=group_id, member_object_id=ouid))


# --- Address object endpoints ---

@router.get("/addresses", response_model=List[AddressObjectResponse])
async def list_address_objects(
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session),
):
    res = await session.execute(select(AddressObject).order_by(AddressObject.name))
    return [_object_to_response(o) for o in res.scalars().all()]


@router.post("/addresses", response_model=AddressObjectResponse, status_code=status.HTTP_201_CREATED)
async def create_address_object(
    payload: AddressObjectCreate,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session),
):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Il nome è obbligatorio")
    value = _validate_object_value(payload.type, payload.value)
    ref_key = await _unique_ref_key(session, AddressObject)
    obj = AddressObject(
        ref_key=ref_key, name=name, type=payload.type, value=value,
        description=payload.description, enabled=payload.enabled,
    )
    _seed_fqdn_resolution(obj)
    session.add(obj)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"Esiste già un oggetto con nome '{name}'")
    await session.refresh(obj)
    await firewall_orchestrator.resync_addresses(session)
    await session.commit()
    return _object_to_response(obj)


@router.get("/addresses/{obj_id}", response_model=AddressObjectResponse)
async def get_address_object(
    obj_id: str,
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session),
):
    o = await session.get(AddressObject, _uuid(obj_id))
    if not o:
        raise HTTPException(status_code=404, detail="Oggetto non trovato")
    return _object_to_response(o)


@router.patch("/addresses/{obj_id}", response_model=AddressObjectResponse)
async def update_address_object(
    obj_id: str,
    payload: AddressObjectUpdate,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session),
):
    obj = await session.get(AddressObject, _uuid(obj_id))
    if not obj:
        raise HTTPException(status_code=404, detail="Oggetto non trovato")
    data = payload.model_dump(exclude_unset=True)
    if "type" in data or "value" in data:
        new_type = data.get("type", obj.type)
        obj.value = _validate_object_value(new_type, data.get("value", obj.value))
        obj.type = new_type
        obj.resolved_ips = None
        obj.resolved_at = None
        _seed_fqdn_resolution(obj)
    if "name" in data:
        nm = (data["name"] or "").strip()
        if not nm:
            raise HTTPException(status_code=400, detail="Il nome è obbligatorio")
        obj.name = nm
    if "description" in data:
        obj.description = data["description"]
    if "enabled" in data:
        obj.enabled = data["enabled"]
    value_changed = "type" in data or "value" in data
    obj.updated_at = datetime.utcnow()
    session.add(obj)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Nome oggetto già in uso")
    await session.refresh(obj)

    # A DNAT-target object's value is baked into the chain as a literal
    # --to-destination at apply time — unlike every other usage, it's never
    # matched via its ipset. resync_addresses only refreshes ipset membership
    # and would leave the DNAT rewriting to the now-stale value; a changed
    # value on a referenced object needs a full apply_rules().
    is_dnat_target = value_changed and (await session.execute(
        select(MachineFirewallRule.id)
        .where(MachineFirewallRule.to_destination_object_id == obj.id)
        .limit(1)
    )).first() is not None
    if is_dnat_target:
        await firewall_orchestrator.apply_rules(session)
    else:
        await firewall_orchestrator.resync_addresses(session)
    await session.commit()
    return _object_to_response(obj)


@router.post(
    "/addresses/{obj_id}/refresh",
    response_model=AddressObjectResponse,
    responses={
        400: {"description": "Oggetto non dinamico o disabilitato"},
        404: {"description": "Address object non trovato"},
        502: {"description": "Risoluzione DNS fallita e nessuna cache disponibile"},
    },
)
async def refresh_address_object(
    obj_id: str,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session),
):
    """
    Force an immediate re-resolution of a dynamic (fqdn/geo) address object,
    rebuilding its ipset out-of-band of the daily task. fqdn A records and the
    fresh timestamp are persisted; geo re-downloads the country list (force) and
    only the timestamp is persisted (the CIDR list lives in the geoip disk cache,
    not the DB). Fail-soft: a failed DNS lookup keeps the last-good set.
    """
    import asyncio
    obj = await session.get(AddressObject, _uuid(obj_id))
    if not obj:
        raise HTTPException(status_code=404, detail="Oggetto non trovato")
    if obj.type not in ("fqdn", "geo"):
        raise HTTPException(
            status_code=400,
            detail="Solo gli oggetti fqdn o geo possono essere aggiornati."
        )
    if not obj.enabled:
        raise HTTPException(status_code=400, detail="Oggetto disabilitato.")

    obj_dict = {
        "ref_key": obj.ref_key, "type": obj.type, "value": obj.value,
        "enabled": obj.enabled,
        "resolved_ips": json.loads(obj.resolved_ips) if obj.resolved_ips else None,
    }
    fresh = await asyncio.to_thread(addresses.refresh_dynamic, [obj_dict])

    if obj.type == "fqdn":
        if obj.ref_key in fresh:
            obj.resolved_ips = json.dumps(fresh[obj.ref_key])
            obj.resolved_at = datetime.utcnow()
        elif not obj.resolved_ips:
            # No fresh resolution and no last-good cache: surface the failure.
            raise HTTPException(
                status_code=502,
                detail=f"Risoluzione DNS fallita per '{obj.value}' e nessuna cache disponibile."
            )
    else:  # geo: timestamp only (set rebuilt in-thread above via force_reload)
        obj.resolved_at = datetime.utcnow()

    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return _object_to_response(obj)


@router.delete("/addresses/{obj_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address_object(
    obj_id: str,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session),
):
    oid = _uuid(obj_id)
    obj = await session.get(AddressObject, oid)
    if not obj:
        raise HTTPException(status_code=404, detail="Oggetto non trovato")
    in_group = await session.execute(
        select(AddressGroupMember).where(AddressGroupMember.member_object_id == oid).limit(1)
    )
    if in_group.scalar_one_or_none():
        raise HTTPException(status_code=409,
            detail=f"Oggetto '{obj.name}' usato in un gruppo: rimuovilo prima dal gruppo.")
    in_rule = await session.execute(
        select(FirewallRuleAddress).where(FirewallRuleAddress.object_id == oid).limit(1)
    )
    if in_rule.scalar_one_or_none():
        raise HTTPException(status_code=409,
            detail=f"Oggetto '{obj.name}' usato in una regola: rimuovilo prima dalla regola.")
    in_dnat_target = await session.execute(
        select(MachineFirewallRule.id).where(MachineFirewallRule.to_destination_object_id == oid).limit(1)
    )
    if in_dnat_target.first():
        raise HTTPException(status_code=409,
            detail=f"Oggetto '{obj.name}' usato come destinazione di un port forwarding: "
                   f"rimuovilo prima dalla regola.")
    await session.delete(obj)
    await session.flush()
    await firewall_orchestrator.resync_addresses(session)
    await session.commit()


# --- Address group endpoints ---

@router.get("/address-groups", response_model=List[AddressGroupResponse])
async def list_address_groups(
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session),
):
    res = await session.execute(select(AddressGroup).order_by(AddressGroup.name))
    return await _groups_to_response(session, res.scalars().all())


@router.post("/address-groups", response_model=AddressGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_address_group(
    payload: AddressGroupCreate,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session),
):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Il nome è obbligatorio")
    ref_key = await _unique_ref_key(session, AddressGroup)
    group = AddressGroup(
        ref_key=ref_key, name=name, description=payload.description, enabled=payload.enabled,
    )
    session.add(group)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"Esiste già un gruppo con nome '{name}'")
    await _set_group_members(session, group.id, payload.members)
    await session.flush()
    await firewall_orchestrator.resync_addresses(session)
    await session.commit()
    await session.refresh(group)
    return await _group_to_response(session, group)


@router.get("/address-groups/{group_id}", response_model=AddressGroupResponse)
async def get_address_group(
    group_id: str,
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session),
):
    g = await session.get(AddressGroup, _uuid(group_id))
    if not g:
        raise HTTPException(status_code=404, detail="Gruppo non trovato")
    return await _group_to_response(session, g)


@router.patch("/address-groups/{group_id}", response_model=AddressGroupResponse)
async def update_address_group(
    group_id: str,
    payload: AddressGroupUpdate,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session),
):
    g = await session.get(AddressGroup, _uuid(group_id))
    if not g:
        raise HTTPException(status_code=404, detail="Gruppo non trovato")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        nm = (data["name"] or "").strip()
        if not nm:
            raise HTTPException(status_code=400, detail="Il nome è obbligatorio")
        g.name = nm
    if "description" in data:
        g.description = data["description"]
    if "enabled" in data:
        g.enabled = data["enabled"]
    g.updated_at = datetime.utcnow()
    session.add(g)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Nome gruppo già in uso")
    if payload.members is not None:
        await _set_group_members(session, g.id, payload.members)
        await session.flush()
    await firewall_orchestrator.resync_addresses(session)
    await session.commit()
    await session.refresh(g)
    return await _group_to_response(session, g)


@router.delete("/address-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address_group(
    group_id: str,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session),
):
    gid = _uuid(group_id)
    g = await session.get(AddressGroup, gid)
    if not g:
        raise HTTPException(status_code=404, detail="Gruppo non trovato")
    in_rule = await session.execute(
        select(FirewallRuleAddress).where(FirewallRuleAddress.group_id == gid).limit(1)
    )
    if in_rule.scalar_one_or_none():
        raise HTTPException(status_code=409,
            detail=f"Gruppo '{g.name}' usato in una regola: rimuovilo prima dalla regola.")
    in_group = await session.execute(
        select(AddressGroupMember).where(AddressGroupMember.member_group_id == gid).limit(1)
    )
    if in_group.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Gruppo '{g.name}' usato in un altro gruppo.")
    await session.execute(delete(AddressGroupMember).where(AddressGroupMember.group_id == gid))
    await session.delete(g)
    await session.flush()
    await firewall_orchestrator.resync_addresses(session)
    await session.commit()


# --- IP pool endpoints ---

async def _pool_responses(session: AsyncSession, pools) -> List[NatPoolResponse]:
    from core.network.service import NetworkService
    from sqlalchemy import func
    all_pools = (await session.execute(select(NatPool))).scalars().all()
    usage = dict((await session.execute(
        select(MachineFirewallRule.nat_pool_id, func.count())
        .where(MachineFirewallRule.nat_pool_id.isnot(None))
        .group_by(MachineFirewallRule.nat_pool_id)
    )).all())
    ifaces = await asyncio.to_thread(NetworkService.get_interfaces)
    out = []
    for p in pools:
        devs, warnings = natpool.describe(p, all_pools, ifaces)
        out.append(NatPoolResponse(
            id=str(p.id), name=p.name, type=p.type, value=p.value, arp_reply=p.arp_reply,
            description=p.description, size=len(natpool.pool_addresses(p)),
            in_use=usage.get(p.id, 0), interfaces=devs, warnings=warnings,
            created_at=p.created_at, updated_at=p.updated_at,
        ))
    return out


async def _validate_pool(session: AsyncSession, pool: NatPool) -> None:
    """Grammar, overlap with another pool, with an address configured on an interface."""
    from core.network.service import NetworkService
    try:
        natpool.parse_pool(pool.type, pool.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    others = (await session.execute(select(NatPool).where(NatPool.id != pool.id))).scalars().all()
    clash = next((o for o in others if natpool.pools_overlap(pool, o)), None)
    if clash:
        raise HTTPException(status_code=400, detail=f"Gli indirizzi si sovrappongono al pool '{clash.name}'.")
    # A configured address in a pool would be caught by the guard that keeps
    # the pool's /32s from receiving new connections
    configured = {a for i in await asyncio.to_thread(NetworkService.get_interfaces)
                  for a in (i.get("addresses") or [])}
    taken = sorted(configured.intersection(natpool.pool_addresses(pool)))
    if taken:
        raise HTTPException(
            status_code=400,
            detail=f"{', '.join(taken)} è già configurato su un'interfaccia: usalo come IP di uscita della policy, non in un pool.",
        )


@router.get("/nat-pools", response_model=List[NatPoolResponse])
async def list_nat_pools(
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session),
):
    pools = (await session.execute(select(NatPool).order_by(NatPool.name))).scalars().all()
    return await _pool_responses(session, pools)


@router.post("/nat-pools", response_model=NatPoolResponse, status_code=status.HTTP_201_CREATED)
async def create_nat_pool(
    data: NatPoolCreate,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session),
):
    if (await session.execute(select(NatPool).where(NatPool.name == data.name))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Esiste già un pool '{data.name}'")
    pool = NatPool(**data.model_dump())
    await _validate_pool(session, pool)
    session.add(pool)
    await session.flush()
    await firewall_orchestrator.apply_rules(session)
    await session.commit()
    return (await _pool_responses(session, [pool]))[0]


@router.patch("/nat-pools/{pool_id}", response_model=NatPoolResponse)
async def update_nat_pool(
    pool_id: str,
    data: NatPoolUpdate,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session),
):
    pool = await session.get(NatPool, _uuid(pool_id))
    if not pool:
        raise HTTPException(status_code=404, detail="Pool non trovato")
    changes = data.model_dump(exclude_unset=True)
    if changes.get("name") and changes["name"] != pool.name and (await session.execute(
            select(NatPool).where(NatPool.name == changes["name"]))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Esiste già un pool '{changes['name']}'")
    for key, value in changes.items():
        if value is not None or key == "description":
            setattr(pool, key, value)
    await _validate_pool(session, pool)
    if pool.type == "one_to_one":
        # every rule using it must still match its size
        users = (await session.execute(
            select(MachineFirewallRule).where(MachineFirewallRule.nat_pool_id == pool.id)
        )).scalars().all()
        with_refs = set((await session.execute(
            select(FirewallRuleAddress.rule_id).where(
                FirewallRuleAddress.rule_id.in_([u.id for u in users]),
                FirewallRuleAddress.direction == "source")
        )).scalars().all()) if users else set()
        for rule in users:
            _validate_one_to_one_source(pool, rule.source, rule.id in with_refs)
    pool.updated_at = datetime.utcnow()
    session.add(pool)
    await session.flush()
    await firewall_orchestrator.apply_rules(session)
    await session.commit()
    return (await _pool_responses(session, [pool]))[0]


@router.delete("/nat-pools/{pool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_nat_pool(
    pool_id: str,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session),
):
    pool = await session.get(NatPool, _uuid(pool_id))
    if not pool:
        raise HTTPException(status_code=404, detail="Pool non trovato")
    used = (await session.execute(
        select(MachineFirewallRule.id).where(MachineFirewallRule.nat_pool_id == pool.id).limit(1)
    )).first()
    if used:
        raise HTTPException(status_code=409, detail=f"Pool '{pool.name}' usato da una regola: cambia prima il NAT della regola.")
    await session.delete(pool)
    await session.flush()
    await firewall_orchestrator.apply_rules(session)
    await session.commit()


@router.get("/export", response_class=JSONResponse)
async def export_rules(
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session)
):
    """
    Export all firewall rules as JSON.
    """
    rules = await firewall_orchestrator.get_all_rules(session)
    refs_map = await _rule_refs_map(session, [r.id for r in rules])
    dnat_obj_names = await _dnat_obj_names_map(session, rules)
    pool_names = await _pool_names_map(session)
    export_data = [_rule_to_response(r, refs_map, dnat_obj_names, pool_names).model_dump() for r in rules]

    return JSONResponse(
        content=jsonable_encoder(export_data),
        headers={"Content-Disposition": "attachment; filename=firewall_rules.json"}
    )


async def _resolve_imported_refs(session: AsyncSession, exported_refs, errors, label) -> list:
    """Map exported address refs ({kind, name}) to {object_id|group_id} on this
    system by name. Missing names are reported and skipped."""
    resolved = []
    for ref in (exported_refs or []):
        kind = ref.get("kind")
        name = ref.get("name")
        if kind == "object":
            o = (await session.execute(
                select(AddressObject).where(AddressObject.name == name)
            )).scalar_one_or_none()
            if o:
                resolved.append({"object_id": str(o.id)})
            else:
                errors.append(f"{label}: oggetto indirizzo '{name}' non trovato, riferimento saltato")
        elif kind == "group":
            g = (await session.execute(
                select(AddressGroup).where(AddressGroup.name == name)
            )).scalar_one_or_none()
            if g:
                resolved.append({"group_id": str(g.id)})
            else:
                errors.append(f"{label}: gruppo indirizzi '{name}' non trovato, riferimento saltato")
    return resolved


@router.post("/import", status_code=status.HTTP_200_OK)
async def import_rules(
    file: UploadFile = File(...),
    mode: str = Query("append", description="Import mode: 'append' (default) or 'replace'"),
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    Import firewall rules from JSON file.
    Mode:
    - append: Add rules to existing ones (default)
    - replace: Delete all existing rules and add new ones
    """
    if mode not in ["append", "replace"]:
        raise HTTPException(status_code=400, detail="Invalid mode. Use 'append' or 'replace'")
    
    try:
        content = await file.read()
        rules_data = json.loads(content)
        
        if not isinstance(rules_data, list):
            raise HTTPException(status_code=400, detail="Invalid file format: expected a list of rules")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading file: {str(e)}")
        
    try:
        # If replace mode, clear existing rules
        if mode == "replace":
            await firewall_orchestrator.delete_all_rules(session)
            
        applied_count = 0
        errors = []
        
        for i, rule_dict in enumerate(rules_data):
            try:
                # Sanitize input (remove ID, dates, etc to treat as new rule)
                clean_data = {
                    k: v for k, v in rule_dict.items()
                    if k in MachineFirewallRuleCreate.model_fields
                }

                # Check required fields
                if "chain" not in clean_data or "action" not in clean_data:
                    errors.append(f"Rule #{i+1}: Missing chain or action")
                    continue

                # Address object/group references are exported by name; remap them
                # to local ids (missing names are reported and skipped).
                clean_data["source_refs"] = await _resolve_imported_refs(
                    session, rule_dict.get("source_refs"), errors, f"Rule #{i+1} (source)")
                clean_data["destination_refs"] = await _resolve_imported_refs(
                    session, rule_dict.get("destination_refs"), errors, f"Rule #{i+1} (destination)")

                # to_destination_object_id is exported by name (see
                # to_destination_object_name) — the raw id is meaningless
                # across systems, so remap it the same way address refs are;
                # never carry over the source system's raw id verbatim.
                obj_name = rule_dict.get("to_destination_object_name")
                clean_data["to_destination_object_id"] = None
                if obj_name:
                    dnat_obj = (await session.execute(
                        select(AddressObject).where(AddressObject.name == obj_name)
                    )).scalar_one_or_none()
                    if dnat_obj:
                        clean_data["to_destination_object_id"] = str(dnat_obj.id)
                    else:
                        errors.append(
                            f"Rule #{i+1}: oggetto indirizzo di destinazione '{obj_name}' "
                            f"non trovato, riferimento DNAT saltato"
                        )

                # IP pools likewise, by name
                pool_name = rule_dict.get("nat_pool_name")
                clean_data["nat_pool_id"] = None
                if pool_name:
                    pool = (await session.execute(
                        select(NatPool).where(NatPool.name == pool_name)
                    )).scalar_one_or_none()
                    if pool:
                        clean_data["nat_pool_id"] = str(pool.id)
                    else:
                        errors.append(f"Rule #{i+1}: IP pool '{pool_name}' non trovato")
                        continue

                # Same checks as POST /rules: the file is as untrusted as a request
                try:
                    rule_data = MachineFirewallRuleCreate.model_validate(clean_data)
                except ValidationError as e:
                    errors.append(f"Rule #{i+1}: " + "; ".join(err["msg"] for err in e.errors()))
                    continue
                await _validate_rule_payload(
                    session, rule_data.model_dump(),
                    has_source_refs=bool(rule_data.source_refs),
                    has_destination_refs=bool(rule_data.destination_refs),
                )
                await _validate_rule_refs(session, rule_data.source_refs, rule_data.destination_refs)

                await firewall_orchestrator.create_rule(session, rule_data.model_dump())
                applied_count += 1

            except HTTPException as e:
                errors.append(f"Rule #{i+1}: {e.detail}")
            except Exception as e:
                errors.append(f"Rule #{i+1}: {str(e)}")
        
        await session.commit()
        
        return {
            "status": "ok", 
            "message": f"Imported {applied_count} rules", 
            "errors": errors if errors else None
        }
        
    except Exception as e:
        await session.rollback()
        logger.error(f"Error importing firewall rules: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/apply-defaults", status_code=status.HTTP_200_OK)
async def apply_default_rules(
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    Replace all rules with the default protective ruleset, generated dynamically
    from the live interfaces (WAN = default route, LAN = other physical NICs).

    Used by the installer so the rules never depend on hardcoded names like eth0.
    """
    from .defaults import generate_default_protection_rules

    try:
        wan, lan_ifaces, rules = await generate_default_protection_rules(firewall_orchestrator)

        await firewall_orchestrator.delete_all_rules(session)
        for rule in rules:
            await firewall_orchestrator.create_rule(session, rule)
        await session.commit()

        logger.info(f"Applied default firewall rules (wan={wan}, lan={lan_ifaces})")
        return {
            "status": "ok",
            "message": f"Applied {len(rules)} default rules",
            "wan": wan,
            "lan": lan_ifaces,
            "count": len(rules),
        }
    except Exception as e:
        await session.rollback()
        logger.error(f"Error applying default firewall rules: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# --- Module Chain Endpoints (for admin/debug) ---

@router.get("/chains", response_model=List[ModuleChainResponse])
async def list_module_chains(
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session)
):
    """List all registered module chains."""
    from sqlalchemy import select
    from .models import ModuleChain
    
    result = await session.execute(
        select(ModuleChain).order_by(ModuleChain.parent_chain, ModuleChain.priority)
    )
    chains = result.scalars().all()
    
    return [
        ModuleChainResponse(
            id=str(c.id),
            module_id=c.module_id,
            chain_name=c.chain_name,
            parent_chain=c.parent_chain,
            priority=c.priority,
            table_name=c.table_name
        )
        for c in chains
    ]


class ModuleChainOrderUpdate(SQLModel):
    """Schema for updating module chain priority."""
    id: str
    priority: int


@router.put("/chains/order")
async def update_chain_order(
    orders: List[ModuleChainOrderUpdate],
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    Update the priority order of module chains.
    Lower priority = processed first (after MADMIN).
    """
    from sqlalchemy import select
    from .models import ModuleChain
    
    for item in orders:
        try:
            chain_uuid = uuid.UUID(item.id)
        except ValueError:
            continue
        
        result = await session.execute(
            select(ModuleChain).where(ModuleChain.id == chain_uuid)
        )
        chain = result.scalar_one_or_none()
        if chain:
            chain.priority = item.priority
            session.add(chain)
    
    await session.commit()
    
    # Rebuild all chain jumps to reflect new priorities
    # Get unique parent chains that need rebuilding
    result = await session.execute(select(ModuleChain))
    all_chains = result.scalars().all()
    
    rebuilt = set()
    for chain in all_chains:
        key = (chain.parent_chain, chain.table_name)
        if key not in rebuilt:
            await firewall_orchestrator.rebuild_chain_jumps(session, chain.parent_chain, chain.table_name)
            rebuilt.add(key)
    
    return {"status": "ok", "message": f"Updated priority for {len(orders)} chains"}


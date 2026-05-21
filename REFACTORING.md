# MADMIN — UTM Refactoring Tracker

## Branch: `feature/firewall-utm-refactor` (from `vdc`)

## Roadmap (confirmed scope)
Fase 1 → Fase 2 → Fase 3. No Fase 4 (deferred).

---

## FASE 1 — Fondamenta (Q3 2026)

### Step 1.4 — nftables backend abstraction [IN PROGRESS]

**Goal:** Astrarre `FirewallOrchestrator` con backend pluggable (`iptables` | `nftables`).
Feature flag in `.env`: `FIREWALL_BACKEND=iptables|nftables` (default `iptables` per backward compat, `nftables` per nuove install).

#### Files da creare/modificare
| File | Stato | Note |
|------|-------|------|
| `backend/core/firewall/base.py` | 🔲 TODO | Abstract `FirewallBackend` protocol/ABC |
| `backend/core/firewall/iptables.py` | 🔲 TODO | Implement `FirewallBackend`, wrap current funcs |
| `backend/core/firewall/nftables.py` | 🔲 TODO | New nftables backend, parità funzionale |
| `backend/core/firewall/orchestrator.py` | 🔲 TODO | Inject backend via factory, rimuovi hard-coded iptables calls |
| `backend/config.py` | 🔲 TODO | Add `FIREWALL_BACKEND: str = "iptables"` |

#### Design: `FirewallBackend` interface
```python
class FirewallBackend(ABC):
    @abstractmethod
    async def initialize_chains(self): ...
    @abstractmethod
    async def apply_rules(self, rules, module_chains, gateway_config): ...
    @abstractmethod
    async def restore_chains(self, chains_data): ...
    @abstractmethod
    async def create_chain(self, table, chain): ...
    @abstractmethod
    async def delete_chain(self, table, chain): ...
    @abstractmethod
    async def flush_chain(self, table, chain): ...
    @abstractmethod
    async def add_set(self, set_name, entries): ...  # ipset / nft set
    @abstractmethod
    async def swap_set(self, set_name, new_entries): ...  # atomic swap
    @abstractmethod
    async def terminate_connection(self, src_ip, dst_ip, sport, dport): ...  # conntrack
    @abstractmethod
    async def get_rules(self, table, chain) -> list[str]: ...
```

#### Checkpoint completato: ✅ 2026-05-21

**Files creati/modificati:**
| File | Stato | Descrizione |
|------|-------|-------------|
| `backend/core/firewall/base.py` | ✅ NUOVO | Abstract `FirewallBackend` + chain constants + `CHAIN_MAP` |
| `backend/core/firewall/iptables.py` | ✅ MODIFICATO | Import da `base.py`; aggiunto `IptablesBackend` class; `IptablesError` → subclass di `FirewallError` |
| `backend/core/firewall/nftables.py` | ✅ NUOVO | `NftablesBackend` full implementation (ip madmin table, dispatcher chains, nft sets) |
| `backend/core/firewall/orchestrator.py` | ✅ MODIFICATO | Usa `self._backend` (FirewallBackend); factory `_create_backend()`; rimosso hard-coding iptables |
| `backend/core/firewall/__init__.py` | ✅ MODIFICATO | Espone `FirewallBackend`, `FirewallError`, factory |
| `backend/config.py` | ✅ MODIFICATO | Aggiunto `firewall_backend: str = "iptables"` |
| `backend/.env.example` | ✅ MODIFICATO | Aggiunto `FIREWALL_BACKEND=iptables` |

**Cosa è cambiato:**
- `FirewallOrchestrator` non importa più `iptables` direttamente → usa `self._backend`
- `apply_rules()` usa `self._backend.restore_chains()`, `self._backend.rule_to_restore_line()`, ecc.
- `rebuild_chain_jumps()` usa `self._backend.chain_exists()`, `self._backend.restore_parent_chain_jumps()`, ecc.
- ESTABLISHED/RELATED built-in rule ora generata via `_EstablishedRelatedRule` stub + `rule_to_restore_line()`
- Moduli esistenti (wireguard, openvpn, dns, strongswan) ancora importano `iptables` direttamente → **backward compat preservato**

**Known issues / TODOs:**
- `backend/core/firewall/router.py` importa `IptablesError` e `flush_conntrack_for_rule` da `iptables` direttamente — funziona ma da migrare a `FirewallError` + backend.flush_conntrack in Fase successiva
- `build_rule_args` usa `-m state --state` (vecchio); originale usava `-m conntrack --ctstate`. Entrambi validi su Ubuntu 24.04. Migliorare in cleanup
- Comment su regole normali non aggiunto (pre-existing bug in `build_rule_args`: il comment è dentro il blocco `if limit_rate`)
- Moduli non ancora aggiornati per usare NftablesBackend natively (useranno iptables anche con `FIREWALL_BACKEND=nftables`)

---

### Step 1.1 — Firewall Objects ✅ 2026-05-21

**Files creati/modificati:**
| File | Stato | Descrizione |
|------|-------|-------------|
| `backend/core/firewall/models.py` | ✅ MODIFICATO | `FirewallObject` model + `FirewallObjectType` enum; FK fields `source/destination/service_object_id` su `MachineFirewallRule`; Pydantic schemas CRUD |
| `backend/core/firewall/objects.py` | ✅ NUOVO | `FirewallObjectService` CRUD + `resolve_address()` + `resolve_service()` ricorsivi |
| `backend/core/firewall/orchestrator.py` | ✅ MODIFICATO | `_RuleProxy` + `_resolve_rule()`: risolve FK refs a runtime; `_rebuild_object_sets()` crea nft set per multi-value; `apply_rules()` batch-load objects |
| `backend/core/firewall/router.py` | ✅ MODIFICATO | 5 endpoints `/firewall/objects`; `FirewallError` invece di `IptablesError` |
| `backend/core/database.py` | ✅ MODIFICATO | Import `FirewallObject`; `ADD COLUMN IF NOT EXISTS` migration per 3 FK columns |
| `backend/config.py` | ✅ MODIFICATO | `FIREWALL_BACKEND` default cambiato a `nftables` |
| `backend/.env.example` | ✅ MODIFICATO | `FIREWALL_BACKEND=nftables` |
| `backend/main.py` | ✅ MODIFICATO | Menu entry `firewall-objects` |
| `frontend/assets/js/app.js` | ✅ MODIFICATO | Route `firewall-objects` → `firewall-objects.js` |
| `frontend/assets/js/views/firewall-objects.js` | ✅ NUOVO | View CRUD con table, search/filter, modal create/edit, member picker per groups |

**Commit**: `bb9e6ff`

**Cosa funziona:**
- HOST/NETWORK/RANGE/FQDN/GROUP/SERVICE/SERVICE_GROUP fully supported
- Multi-value objects → nft sets (`FWOBJ_*`) creati/aggiornati ad ogni `apply_rules()`
- GROUP resolution ricorsiva (max depth 8) con cache
- FQDN → DNS lookup runtime
- SERVICE → proto/port override su regola
- DB migration safe (ADD COLUMN IF NOT EXISTS) per installazioni esistenti

**Note:**
- `resolve_address` per SERVICE_GROUP non expande il set (solo GROUP per indirizzi). Supporto SERVICE_GROUP multi-port in nft set è futuro work.
- Color picker in modal usa detection bordo colore — CSS specificity può variare su dark mode.

### Step 1.2 — Security Zones [TODO]
Tabella `firewall_zone` + inter-zone matrix + ZONE_* chains + view frontend.

### Step 1.3 — Port Forward UI dedicata [TODO]
Endpoint `/api/firewall/portforward` + wizard frontend.

---

## FASE 2 — Sicurezza Attiva (Q4 2026)

### Step 2.1 — Modulo `suricata` [TODO]
### Step 2.2 — Modulo `threatshield` [TODO]
### Step 2.3 — Modulo `geoip` [TODO]

---

## FASE 3 — Networking Avanzato (Q1 2027)

### Step 3.1 — Multi-WAN [TODO]
### Step 3.2 — QoS CAKE [TODO]
### Step 3.3 — DPI nDPI/netifyd [TODO]

---

## Decisioni architetturali
- **OS**: Ubuntu 24.04 (Alpine scartato: musl+openrc+no-netplan = 8 sett. refactor zero features)
- **IDS**: Suricata (non Snort) — multi-thread, nfqueue native, ET Open
- **nftables**: parallel backend, feature flag `FIREWALL_BACKEND`
- **Hub agent** (`feature/hub-agent-module`): in pausa, non mergiare

## Improvement backlog (da fare durante refactor quando naturale)
- [ ] Token refresh rotation
- [ ] Rate limit in-memory → DB (brute force survive restart)
- [ ] Audit log su tutti firewall endpoints
- [ ] Hot reload moduli senza restart
- [ ] Golden file test su orchestrator rendering

## Note sessioni

### 2026-05-21 — Step 1.4 completato
- **Commit**: `d8613e0` — "refactor(firewall): add pluggable backend abstraction (iptables/nftables)"
- **Fatto**: base.py, IptablesBackend, NftablesBackend, orchestrator refactored, config.py, .env.example
- **Branch**: `feature/firewall-utm-refactor` (da `vdc`)

### 2026-05-21 — Step 1.1 completato
- **Commit**: `bb9e6ff` — "feat(firewall): implement Firewall Objects (Step 1.1)"
- **Fatto**: FirewallObject model, objects.py service, orchestrator resolve, router endpoints, DB migration, frontend view
- **Prossimo step**: Step 1.2 — Security Zones

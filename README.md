# MADMIN (Modular Admin System)

<p align="center">
  <img src="docs/banner.png" alt="MADMIN Banner" width="100%">
</p>

> [!WARNING]
> **This project is currently under active development for a custom internal deployment with specific architectural and operational constraints tied to that context.**
> Once the target project goes live, a more open and general-purpose version of MADMIN will be published — without those limitations. Stay tuned.

> **MADMIN** is a high-performance, modular administrative dashboard designed for Linux servers (Ubuntu 24.04). It provides a unified interface to manage system services, networks, VPN, firewall, and specialized components via a powerful plugin architecture.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Frontend](https://img.shields.io/badge/frontend-Vanilla%20JS%20%2B%20Tabler-orange)
![Database](https://img.shields.io/badge/database-PostgreSQL%2015%2B-green)
![Version](https://img.shields.io/badge/version-1.0.0-brightgreen)

---

## Key Features

### Core System
- **Modular Architecture** — Lightweight core; all optional features are independent modules
- **Module Lifecycle** — Install, update, enable, disable, and remove modules from the dashboard
- **System Monitoring** — Real-time CPU, RAM, disk, and network stats with interactive ApexCharts
- **Service Management** — Start/stop/restart/enable/disable systemd services from the UI
- **Network Management** — Netplan-based interface configuration (IP, gateway, DNS, VLAN)
- **Crontab Management** — Create, edit, toggle, and delete scheduled tasks via UI
- **Configuration Backup** — Automated (daily/weekly) and manual backup/restore, local and remote

### Security
- **JWT Authentication** — Bearer tokens with configurable expiration (default 12h)
- **TOTP Two-Factor Authentication** — Optional per-user, enforceable globally; includes one-time backup codes for account recovery
- **RBAC** — Granular slug-based permissions per module and per user; superuser bypasses all
- **Login Rate Limiting** — 5 failed attempts triggers 15-minute lockout (in-memory)
- **Token Revocation** — Instant blacklisting on logout, user disable, or delete
- **Audit Logging** — Full API request trail with user identity, IP, method, and status codes; CSV export

### Firewall
- **iptables Orchestrator** — Hierarchical chain management (core → module → instance chains)
- **Gateway Protection** — Per-interface ipset-based DROP chains (`MADMIN_GW_PROTECT`) to protect gateway interfaces from unauthorized traffic
- **Active Session Termination** — conntrack flush on new DROP rules: kills existing connections matching newly created rules immediately
- **LAN Isolation** — Inter-LAN traffic blocked by default (`FORWARD` chain default policy)
- **Dashboard Access Restriction** — Port 7443 accessible only from the primary management interface (`eth0`) by default

### Frontend
- **Internationalization (i18n)** — Multi-language UI with English (`en`) and Italian (`it`) locale files; auto-detect from user preferences or system default; dot-namespaced keys with `{placeholder}` interpolation
- **Dark Mode** — Full dark theme, saved per-user in preferences
- **Customizable Primary Color** — CSS variable `--madmin-primary` configurable from Settings

### API
- **OpenAPI / Swagger UI** — Available at `/api/docs` (ReDoc at `/api/redoc`) when `DEBUG=true`; JWT Bearer security scheme injected globally; endpoints tagged by subsystem

---

## Technology Stack

### Backend
| Component | Technology |
|-----------|-----------|
| Framework | FastAPI + Uvicorn (async) |
| Language | Python 3.12+ |
| ORM | SQLModel / SQLAlchemy (async) |
| Database driver | AsyncPG |
| Validation | Pydantic v2 |
| Auth | PyJWT (HS256), pyotp (TOTP) |

### Frontend
| Component | Technology |
|-----------|-----------|
| Language | Vanilla JavaScript (ES Modules) |
| UI Kit | Tabler UI 1.4.0 (Bootstrap 5) via CDN |
| Charts | ApexCharts via CDN |
| Drag-drop | SortableJS via CDN |
| Icons | Tabler Icons (webfont) |
| Build step | None |

### Infrastructure
| Component | Technology |
|-----------|-----------|
| Database | PostgreSQL 15+ |
| Reverse proxy | Nginx (HTTPS :7443, self-signed cert, 10yr) |
| Process manager | systemd (`madmin.service`) |
| Network config | Netplan |
| Firewall | iptables + ipset + conntrack |

---

## Project Structure

```
madmin/
├── backend/
│   ├── main.py                 # FastAPI entry point, lifespan, router registration
│   ├── config.py               # Settings from .env (Pydantic Settings), MADMIN_VERSION
│   ├── default_rules.json      # Default firewall rules applied on init
│   ├── requirements.txt
│   ├── core/
│   │   ├── auth/               # JWT, RBAC, 2FA/TOTP, backup codes, rate limiting, token blacklist
│   │   ├── audit/              # Request logging middleware + CSV export
│   │   ├── backup/             # Config export/import, scheduled backups (local + remote)
│   │   ├── cron/               # Crontab CRUD
│   │   ├── database.py         # AsyncSession factory, init_db()
│   │   ├── files/              # File upload/download
│   │   ├── firewall/           # iptables wrapper, ipset, conntrack, chain orchestrator
│   │   ├── modules/            # Dynamic module loader (loader.py), lifecycle manager
│   │   ├── network/            # Netplan interface management
│   │   ├── openapi.py          # OpenAPI tags, JWT security scheme, Swagger setup
│   │   ├── services/           # systemctl wrapper
│   │   ├── settings/           # System settings CRUD (DB-stored)
│   │   └── system/             # CPU/RAM/disk/network stats + history
│   └── modules/
│       ├── dhcp/               # ISC DHCP Server (multi-subnet, reservations, leases)
│       ├── dns/                # BIND9 (zones, records, conditional forwarding)
│       ├── openvpn/            # OpenVPN multi-instance, PKI, groups, split tunnel
│       ├── reverseproxy/       # Nginx reverse proxy (SSL/TLS, Let's Encrypt, access lists)
│       ├── strongswan/         # IPsec site-to-site (strongSwan swanctl)
│       └── wireguard/          # WireGuard multi-instance, QR codes, groups, split tunnel
├── frontend/
│   ├── index.html              # Main SPA shell
│   ├── login.html              # Standalone login page
│   └── assets/
│       ├── css/app.css
│       ├── locales/
│       │   ├── en.json         # English translations
│       │   └── it.json         # Italian translations
│       └── js/
│           ├── app.js          # Hash router, init, menu, i18n bootstrap
│           ├── api.js          # fetch wrapper with JWT auto-inject
│           ├── i18n.js         # Lightweight i18n engine
│           ├── utils.js        # Toast, spinner, UI helpers
│           └── views/          # dashboard, users, firewall, network, crontab,
│                               # settings, modules, logs, services, backup, files
└── scripts/
    └── setup-madmin.sh         # Automated installer for Ubuntu 24.04
```

---

## Installation

### Requirements
- Ubuntu 24.04 LTS (fresh install recommended)
- Root access
- Internet connectivity (for apt/pip packages)

### Automated Install

```bash
git clone https://github.com/EdoardoFiore/madmin.git
cd madmin
sudo bash scripts/setup-madmin.sh -u <admin-username> -p '<admin-password>'
```

| Argument | Description |
|----------|-------------|
| `-u`, `--username` | Admin account username to create |
| `-p`, `--password` | Admin account password |

**The installer handles:**
1. System dependencies (PostgreSQL, Python 3.12, Nginx, iptables, ipset, conntrack)
2. PostgreSQL database and user with random password
3. Python virtualenv + `pip install -r requirements.txt`
4. Frontend deployment to `/opt/madmin/frontend/`
5. Nginx reverse proxy on HTTPS port **7443** (self-signed certificate, 10 years)
6. `madmin.service` systemd unit — enabled and started
7. Module apt/pip dependencies from each `manifest.json`
8. Default firewall ruleset applied (LAN isolation, eth0-only dashboard access)

### Post-Install Access
- **URL**: `https://<your-server-ip>:7443`
- **Credentials**: as specified via `-u` / `-p` during installation

> **Security**: Enable 2FA for admin accounts. Review firewall default rules before exposing to production networks.

---

## Configuration

File: `backend/.env` (production: `/opt/madmin/backend/.env`, chmod 600)

```env
DATABASE_URL=postgresql+asyncpg://madmin:<password>@localhost:5432/madmin
SECRET_KEY=<hex-64>
DEBUG=false
ALLOWED_ORIGINS=*
DATA_DIR=/opt/madmin/data
MODULES_DIR=/opt/madmin/backend/modules
MOCK_IPTABLES=false
ACCESS_TOKEN_EXPIRE_MINUTES=720
```

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | AsyncPG PostgreSQL connection string |
| `SECRET_KEY` | — | 64-char hex secret for JWT signing |
| `DEBUG` | `false` | Enables `/api/docs`, `/api/redoc`, verbose errors |
| `MOCK_IPTABLES` | `false` | Skip real iptables/ipset/conntrack calls (dev only) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `720` | JWT token lifetime (12h default) |
| `DATA_DIR` | `/opt/madmin/data` | Storage for backups, certs, uploads |

---

## Production Operations

```bash
# Service management
systemctl status madmin
systemctl restart madmin
systemctl stop madmin

# Real-time logs
journalctl -u madmin -f

# Configuration reload (no restart)
# Not applicable — restart required for env/config changes

# Log location
journalctl -u madmin --since "1 hour ago"
```

---

## Security Hardening (Post-Install Checklist)

- [ ] Change default `admin` password
- [ ] Enable TOTP 2FA for all admin accounts
- [ ] Review and rotate `SECRET_KEY` in `.env`
- [ ] Confirm `DEBUG=false` in `.env` (disables Swagger UI in production)
- [ ] Review default firewall rules (`default_rules.json`)
- [ ] Restrict `ALLOWED_ORIGINS` if not using wildcard
- [ ] Replace self-signed TLS certificate with a trusted CA cert in Nginx config
- [ ] Ensure `/opt/madmin/backend/.env` is `chmod 600`
- [ ] Set up remote backup destination in Settings → Backup

---

## Authentication Flow

```
POST /api/auth/token  (form-data: username, password)
  └─ if 2FA not enabled  → { access_token, token_type: "bearer" }
  └─ if 2FA enabled      → { token_type: "2fa_required", temp_token }
       └─ POST /api/auth/token/2fa?code=<TOTP or backup_code>
            └─ { access_token, token_type: "bearer" }
```

Token stored in `localStorage` as `madmin_token`. All subsequent requests include `Authorization: Bearer <token>`. On 401, auto-redirect to `/login`.

### 2FA Backup Codes
Generated at 2FA setup time. Each code is single-use. Codes can be regenerated from profile settings (invalidates all previous codes). Used in place of TOTP when authenticator app is unavailable.

---

## API Reference

Swagger UI available at `/api/docs` when `DEBUG=true`.

### Core Endpoints

| Prefix | Description |
|--------|-------------|
| `POST /api/auth/token` | Login (OAuth2 password flow) |
| `POST /api/auth/token/2fa` | Complete 2FA login |
| `GET /api/auth/me` | Current user profile |
| `/api/auth/users` | User management (CRUD, permissions) |
| `/api/auth/2fa` | 2FA setup, backup codes |
| `/api/firewall` | iptables rules, gateway protection, session drop |
| `/api/network` | Interface config (Netplan) |
| `/api/services` | Systemd service control |
| `/api/cron` | Crontab CRUD |
| `/api/modules` | Module lifecycle (activate/deactivate) |
| `/api/settings` | System settings, SMTP, backup schedule, UI prefs |
| `/api/backup` | Manual backup/restore, scheduled backup config |
| `/api/system` | CPU/RAM/disk stats, uptime, alerts |
| `/api/audit` | Audit log search + CSV export |
| `/api/files` | File upload/download |
| `/api/health` | Health check (DB connectivity) |
| `/api/modules/<id>/...` | Module-specific endpoints |

---

## Module System

### Available Modules

| ID | Name | Version | Description |
|----|------|---------|-------------|
| `dhcp` | DHCP Server | 1.1.0 | ISC DHCP — multi-interface subnets, static reservations, active leases view |
| `dns` | DNS Server | 1.1.0 | BIND9 — zone management, record editing, conditional forwarding |
| `openvpn` | OpenVPN Manager | 1.2.0 | Multi-instance OpenVPN with PKI (easy-rsa), client/group management, per-group firewall, split tunnel |
| `reverseproxy` | Reverse Proxy | 1.0.0 | Nginx-based reverse proxy — multiple hosts, Let's Encrypt SSL/TLS, HTTP basic auth, IP access lists, exploit blocking |
| `wireguard` | WireGuard VPN | 1.4.0 | Multi-instance WireGuard with QR code export, client/group management, per-group firewall, split tunnel |
| `strongswan` | IPsec VPN Manager | 1.1.0 | strongSwan site-to-site IKEv2/IPsec with per-Child-SA firewall chains |

### Module Permissions

| Module | Permissions |
|--------|-------------|
| DHCP | `dhcp.view`, `dhcp.manage`, `dhcp.reservations` |
| DNS | `dns.view`, `dns.manage`, `dns.zones`, `dns.records` |
| OpenVPN | `openvpn.view`, `openvpn.manage`, `openvpn.clients`, `openvpn.groups` |
| Reverse Proxy | `reverseproxy.view`, `reverseproxy.manage`, `reverseproxy.access_lists`, `reverseproxy.certs` |
| WireGuard | `wireguard.view`, `wireguard.manage`, `wireguard.clients`, `wireguard.groups` |
| IPsec | `ipsec.view`, `ipsec.manage` |

### Module Structure

```
<module_id>/
├── manifest.json          # REQUIRED: metadata, permissions, dependencies, hooks
├── models.py              # SQLModel DB models + Pydantic schemas
├── router.py              # FastAPI APIRouter (mounted at /api/modules/<id>/)
├── service.py             # Business logic
├── migrations/
│   └── 001_initial.py     # async def upgrade(session: AsyncSession)
├── hooks/
│   ├── post_install.py    # async def run(session: AsyncSession)
│   └── on_disable.py      # async def run(session: AsyncSession)
└── static/views/
    ├── main.js            # export async function render(container, params)
    └── widgets.js         # Dashboard widgets (optional)
```

### Module Lifecycle

1. **Activate** (`POST /api/modules/<id>/activate`):
   - Runs migration scripts
   - Runs `post_install` hook
   - Registers permissions and firewall chains in DB
   - Creates `InstalledModule` record

2. **Deactivate** (`POST /api/modules/<id>/deactivate`):
   - Runs `on_disable` hook
   - Removes chains and permissions from DB
   - Drops module DB tables
   - Removes `InstalledModule` record

3. **Load** (app startup via `lifespan`):
   - Scans `backend/modules/` filesystem
   - Loads only modules with `enabled=True` in DB
   - Mounts FastAPI router + static files

---

## Firewall Architecture

```
INPUT
  └── MADMIN_GW_EXCEPTS   (whitelist — bypass gateway protection)
  └── MADMIN_GW_PROTECT   (per-interface ipset DROP)
  └── MOD_*_INPUT         (module chains, e.g. MOD_WG_INPUT)
  └── MADMIN_INPUT        (host firewall rules)

FORWARD
  └── MOD_*_FORWARD       (module chains, e.g. MOD_WG_FORWARD)
  └── MADMIN_FORWARD      (inter-LAN isolation, LAN→WAN policy)

OUTPUT
  └── MADMIN_OUTPUT       (outbound host rules)
```

- Module chains use `MOD_` prefix; priority controls jump order from parent chain
- `MADMIN_GW_PROTECT`: per-interface ipset that blocks packets from unauthorized source IPs hitting the gateway
- Active session termination: when a DROP rule is added, existing conntrack entries matching that rule are flushed immediately
- `MOCK_IPTABLES=true` in `.env` for development — no real iptables/ipset/conntrack commands executed

---

## Core Permissions Reference

```
users.view / users.manage
permissions.manage
firewall.view / firewall.manage
settings.view / settings.manage
backup.view / backup.manage
system.view
network.view / network.manage
services.view / services.manage
cron.view / cron.manage
audit.view
modules.view / modules.manage
```

---

## Internationalization

Locale files: `frontend/assets/locales/{lang}.json`

Supported languages: `en` (English), `it` (Italian)

Language resolution order:
1. User preference (stored in `user.preferences.language`)
2. System default (configured in Settings → General)
3. Fallback: `en`

To add a language: create `frontend/assets/locales/<lang>.json` with the same key structure as `en.json`, then add the language code to `_supportedLangs` in `frontend/assets/js/i18n.js`.

---

## Development Setup

```bash
git clone https://github.com/EdoardoFiore/madmin.git
cd madmin

# Backend
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create .env from example
cp .env.example .env
# Edit .env: set DATABASE_URL, SECRET_KEY, DEBUG=true, MOCK_IPTABLES=true

# Create PostgreSQL DB
createdb madmin

# Start backend (hot reload)
uvicorn main:app --reload --port 8000
```

- Frontend served by FastAPI at `http://localhost:8000`
- Swagger UI: `http://localhost:8000/api/docs` (only when `DEBUG=true`)
- No build step — JS/CSS changes are immediate
- `MOCK_IPTABLES=true` prevents real firewall/ipset/conntrack calls

---

## Background Tasks

| Task | Interval | Description |
|------|----------|-------------|
| Stats collection | 60s | CPU/RAM/disk/network → `SystemStatsHistory` |
| Scheduled backups | Daily/Weekly | Local + remote backup |
| Audit log cleanup | 24h | Prune old entries per retention policy |

---

## Contributing

See individual module READMEs in `backend/modules/<id>/README.md` for module-specific documentation.

When writing a new module, follow the standard structure above. Key rules:
- Migration signature: `async def upgrade(session: AsyncSession)`
- Hook signature: `async def run(session: AsyncSession)`
- Frontend entry: `export async function render(container, params)`
- Use `from core.firewall import iptables` for firewall operations
- Use `Depends(require_permission("mod.slug"))` for RBAC on all endpoints

---

## License

MIT License — see [LICENSE](LICENSE) for details.

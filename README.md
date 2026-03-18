# MADMIN (Modular Admin System)

> **MADMIN** is a high-performance, modular administrative dashboard designed for Linux servers (Ubuntu 24.04). It provides a unified interface to manage system services, networks, and specialized components via a powerful plugin architecture.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Frontend](https://img.shields.io/badge/frontend-Vanilla%20JS%20%2B%20Tabler-orange)
![Database](https://img.shields.io/badge/database-PostgreSQL-green)

---

## 🚀 Key Features

- **Modular Architecture** — Core system is lightweight; everything else is a module
- **Module Lifecycle** — Install, update, disable, and remove modules from the dashboard
- **System Monitoring** — Real-time stats (CPU, RAM, Disk) with interactive charts
- **Service Management** — Control systemd services from the UI
- **Network Management** — Netplan-based interface configuration, firewall management with iptables
- **Role-Based Access Control** — Granular permissions per module, per user
- **Audit Logging** — Full audit trail with category filters and CSV export
- **Login Rate Limiting** — Incremental lockout on repeated failed attempts
- **JWT Token Revocation** — Instant revocation of tokens for disabled/deleted users
- **Configuration Backup** — Automated and manual backup/restore of entire system config

---

## 🛠 Technology Stack

### Backend
- **FastAPI** — High-performance async web framework
- **Python 3.12+** — Modern async features and type hinting
- **SQLModel / SQLAlchemy** — ORM for PostgreSQL interaction
- **Pydantic** — Robust data validation and settings management
- **AsyncPG** — High-performance asyncio PostgreSQL driver

### Frontend
- **Vanilla JavaScript** — No build steps, fast and lightweight
- **Tabler UI** — Professional, responsive Bootstrap-based UI kit
- **ApexCharts** — Interactive data visualization
- **SPA Architecture** — Single Page Application without heavy frameworks

### Database
- **PostgreSQL** — Robust relational database for data integrity

---

## 📁 Project Structure

```
madmin/
├── backend/
│   ├── main.py                 # FastAPI application entry point
│   ├── config.py               # Configuration management
│   ├── requirements.txt        # Python dependencies
│   ├── core/                   # Core subsystems
│   │   ├── auth/               # Authentication, RBAC, rate limiting, token blacklist
│   │   ├── audit/              # Audit logging middleware + CSV export
│   │   ├── backup/             # Configuration backup/restore
│   │   ├── cron/               # Scheduled tasks
│   │   ├── database.py         # Async PostgreSQL connection
│   │   ├── firewall/           # iptables management + orchestrator
│   │   ├── modules/            # Module loader + lifecycle manager
│   │   ├── network/            # Netplan interface management
│   │   ├── services/           # Systemd service control
│   │   ├── settings/           # System settings CRUD
│   │   └── system/             # CPU, RAM, disk monitoring
│   └── modules/                # Installed modules
│       ├── dhcp/               # ISC DHCP Server
│       ├── dns/                # BIND9 DNS Server
│       ├── openvpn/            # OpenVPN multi-instance
│       ├── strongswan/         # IPsec VPN (strongSwan)
│       └── wireguard/          # WireGuard VPN
├── frontend/
│   ├── index.html              # Main SPA shell
│   ├── login.html              # Login page
│   └── assets/
│       ├── css/                # Stylesheets
│       └── js/                 # Core JavaScript (app.js, api.js, utils.js, views/)
├── scripts/
│   └── setup-madmin.sh         # Automated installer
└── madmin-modules/             # Module registry (JSON store)
```

---

## 📥 Installation

MADMIN is designed to be installed on a fresh Ubuntu 24.04 server.

### Automated Install

```bash
# Clone the repository
git clone https://github.com/EdoardoFiore/madmin.git
cd madmin

# Run the installer (as root)
sudo bash scripts/setup-madmin.sh -u youruser -p yourpassword
```

**The installer handles:**
1. Installing system dependencies (PostgreSQL, Nginx, Python 3.12, etc.)
2. Setting up the PostgreSQL database and user
3. Creating the Python virtual environment and installing dependencies
4. Configuring Nginx as a reverse proxy with SSL
5. Creating and starting the `madmin.service` systemd unit

### Post-Install
After installation, access the dashboard at your server's IP:
- **URL**: `https://<your-server-ip>:7443`
- **Default Credentials**: `admin` / `admin`

> **Note**: Change the default password immediately after the first login.

---

## 🧩 Module System

Modules are self-contained packages in `backend/modules/` that extend MADMIN's functionality.

### Module Structure

```
my-module/
├── manifest.json       # Metadata, permissions, dependencies, hooks
├── models.py           # SQLModel database models + Pydantic schemas
├── service.py          # Business logic layer
├── router.py           # FastAPI API routes
├── hooks/
│   ├── post_install.py # Runs after installation
│   └── on_disable.py   # Runs when module is disabled
├── migrations/
│   └── 001_initial.py  # Database table creation
├── templates/          # Jinja2 templates (if applicable)
└── static/
    └── views/
        └── main.js     # Frontend entry point
```

### Manifest (`manifest.json`)

The manifest defines everything about the module:

```json
{
    "id": "my-module",
    "name": "My Module",
    "version": "1.0.0",
    "description": "Module description",
    "system_dependencies": {
        "apt": ["package1"],
        "pip": ["package2>=1.0"]
    },
    "database_migrations": ["migrations/001_initial.py"],
    "install_hooks": {
        "post_install": "hooks/post_install.py",
        "on_disable": "hooks/on_disable.py"
    },
    "backend_router": "router.py",
    "static_dir": "static",
    "frontend_entry": "views/main.js",
    "permissions": [
        {"slug": "mymod.view", "description": "View data"},
        {"slug": "mymod.manage", "description": "Manage data"}
    ],
    "menu": [
        {"label": "My Module", "icon": "https://icon-url.png", "route": "#my-module"}
    ],
    "firewall_chains": [],
    "config_export": {
        "tables": ["my_table"],
        "irrecoverable_files": []
    },
    "dashboard_widgets": []
}
```

### Available Modules

| Module | Description | Permissions |
|--------|-------------|-------------|
| **DHCP Server** | ISC DHCP with multi-interface subnets, reservations, leases | `dhcp.view`, `dhcp.manage`, `dhcp.reservations` |
| **DNS Server** | BIND9 with zone management, record editing, conditional forwarding | `dns.view`, `dns.manage`, `dns.zones`, `dns.records` |
| **OpenVPN** | Multi-instance with PKI, per-client firewall groups | `openvpn.view`, `openvpn.manage`, `openvpn.clients`, `openvpn.groups` |
| **WireGuard** | Multi-instance with firewall groups and QR codes | `wireguard.view`, `wireguard.manage`, `wireguard.clients` |
| **IPsec VPN** | strongSwan site-to-site VPN with per-Child-SA firewall | `strongswan.view`, `strongswan.manage` |

---

## 🔐 Core Security Features

### Authentication
- JWT-based authentication with configurable expiration
- Incremental rate limiting on failed login attempts
- Automatic token revocation on user disable/delete
- Token un-revocation on user re-enable

### Authorization
- Role-based access control (RBAC)
- Granular permissions per module
- Menu items hidden for unauthorized users (GUI + API enforcement)

### Audit
- Full request logging middleware
- Category filters (read/write/auth/system)
- CSV export for compliance

---

## 🔧 Core Utilities

Modules should leverage core utilities where possible:

| Utility | Import | Usage |
|---------|--------|-------|
| **Firewall** | `from core.firewall import iptables` | `add_rule()`, `create_or_flush_chain()`, `ensure_jump_rule()` |
| **Systemd** | `from core.services.service import SystemdService` | `start()`, `stop()`, `restart()`, `get_status()` |
| **Auth** | `from core.auth.dependencies import require_permission` | `Depends(require_permission("mod.view"))` |
| **Database** | `from core.database import get_session` | `Depends(get_session)` for async DB sessions |

---

## 🧠 Architecture

### AsyncIO
The entire backend is async, using `async` / `await`. This allows concurrent request handling without blocking.

### Database
SQLModel (SQLAlchemy + Pydantic) for models. Migrations are per-module via `database_migrations` scripts.

### Module Loader
Modules are discovered at startup from `backend/modules/`. The loader reads each `manifest.json`, registers routers, permissions, menu items, firewall chains, and dashboard widgets.

### Firewall Orchestrator
Manages iptables chains hierarchically — core chains (`MADMIN_FORWARD`, `MADMIN_INPUT`) → module chains (`MOD_*`) → instance chains. Supports filter, nat, mangle, and raw tables.

---

## 🤝 Contributing

Contributions are welcome! See the individual module READMEs for module-specific documentation.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

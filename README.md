# MADMIN (Modular Admin System)

> **MADMIN** is a high-performance, modular administrative dashboard designed for Linux servers (specifically Ubuntu 24.04). It provides a unified interface to manage system services, networks, and specialized components via a powerful plugin architecture.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Frontend](https://img.shields.io/badge/frontend-Vanilla%20JS%20%2B%20Tabler-orange)
![Database](https://img.shields.io/badge/database-PostgreSQL-green)

---

## 🚀 Key Features

*   **Modular Architecture**: Core system is lightweight; everything else (WireGuard, Firewall, Backups) is a module.
*   **Module Lifecycle Management**: Install, update, and uninstall modules directly from the dashboard or cloud store.
*   **System Monitoring**: Real-time stats (CPU, RAM, Disk) with historical data persistence and interactive charts.
*   **Service Management**: Monitor and control systemd services (MADMIN, PostgreSQL, Nginx, etc.).
*   **Security First**: Role-based access control (RBAC), granular permissions per module, and secure authentication.
*   **Network Management**: Integrated firewall management with `iptables` and support for module-specific chains.

---

## 🛠 Technology Stack

### Backend
*   **FastAPI**: High-performance async web framework.
*   **Python 3.12+**: Leveraging modern async features and type hinting.
*   **SQLModel / SQLAlchemy**: ORM for interact with PostgreSQL.
*   **Pydantic**: Robust data validation and settings management.
*   **AsyncPG**: High-performance asyncio PostgreSQL driver.

### Frontend
*   **Vanilla JavaScript**: No build steps, fast and lightweight.
*   **Tabler UI**: Professional, responsive Bootstrap-based UI kit.
*   **ApexCharts**: Interactive data visualization.
*   **SPA Architecture**: Single Page Application feel without heavy frameworks.

### Database
*   **PostgreSQL**: Robust, relational database for robust data integrity and complex relationships.

---

## 📥 Installation

MADMIN is designed to be installed on a fresh Ubuntu 24.04 server.

### Automated Install
Use the provided setup script to deploy MADMIN in minutes:

```bash
# Clone the repository
git clone https://github.com/EdoardoFiore/madmin.git
cd madmin

# Run the installer (as root)
sudo bash scripts/setup-madmin.sh
```

**The installer handles:**
1.  Installing system dependencies (PostgreSQL, Nginx, Python 3.12, etc.).
2.  Setting up the PostgreSQL database and user.
3.  Creating the Python virtual environment and installing dependencies.
4.  Configuring Nginx as a reverse proxy.
5.  Creating and starting the `madmin.service` systemd unit.

### Post-Install
After installation, access the dashboard at your server's public IP:
*   **URL**: `http://<your-server-ip>`
*   **Default Credentials**: `admin` / `admin`

> **Note**: Change the default password immediately after the first login.

---

## 🧩 Module System

The heart of MADMIN is its module system. Modules are self-contained packages that extend the platform's functionality.

### Module Structure
Each module is a directory in `backend/core/modules/` containing a `manifest.json`.

```
my-module/
├── manifest.json       # Metadata, permissions, dependencies
├── router.py           # Backend API routes
├── hooks/              # Lifecycle hooks (pre_install, post_update, etc.)
├── static/             # Frontend assets (JS, CSS)
│   └── views/
│       └── main.js     # Frontend entry point
└── requirements.txt    # Python dependencies
```

### Manifest (`manifest.json`)
The manifest defines *everything* about the module.

```json
{
    "id": "wireguard",
    "name": "WireGuard VPN",
    "version": "1.0.2",
    "system_dependencies": {
        "apt": ["wireguard", "qrencode"],
        "pip": ["qrcode>=7.3"]
    },
    "install_hooks": {
        "pre_uninstall": "hooks/pre_uninstall.py",
        "post_update": "hooks/post_update.py"
    },
    "permissions": [
        {"slug": "wireguard.view", "description": "View VPN status"}
    ],
    "menu": [
        {"label": "VPN", "route": "#wireguard", "icon": "vpn-icon.svg"}
    ]
}
```

### Lifecycle Hooks
Modules can define Python scripts to run at specific lifecycle events:
*   `pre_install`: Before installation starts.
*   `post_install`: After installation completes.
*   `pre_uninstall`: Before removal (e.g., stop services).
*   `post_uninstall`: After removal cleanup.
*   `pre_update`: Before applying an update.
*   `post_update`: After an update applied (e.g., restart services).

### Publishing Modules
Modules can be hosted in a public JSON registry (e.g., on GitHub). The registry lists available modules and their versions. MADMIN connects to this registry to discover and install updates.

**Registry Format (`modules.json`):**
```json
[
    {
        "id": "wireguard",
        "version": "1.0.2",
        "url": "https://github.com/EdoardoFiore/madmin-wireguard/archive/refs/tags/v1.0.2.zip",
        "changelog": {
            "1.0.2": "Added update hooks"
        }
    }
]
```

---

## 🧠 Architecture Deep Dive

### Pydantic & Data Validation
MADMIN relies heavily on **Pydantic** for data integrity. Every API request and response is validated against strict schemas (`backend/core/schemas.py` or module-specific models). This ensures that bad data never reaches the business logic.

### SQLAlchemy & SQLModel
We use **SQLModel** (which combines SQLAlchemy and Pydantic) to define database models. This reduces boilerplate and keeps code DRY.
*   **Models**: Defined as Python classes inheriting from `SQLModel`.
*   **Migrations**: Handled per-module via `database_migrations` scripts in the manifest.

### AsyncIO
The entire backend is async, using `async` / `await` syntax. This allows MADMIN to handle concurrent requests (like fetching stats and managing backups) without blocking the main event loop, making the UI feel snappy even under load.

---

## 🤝 Contributing

Contributions are welcome! Please check the [CONTRIBUTING.md](CONTRIBUTING.md) guide (coming soon) for details on setting up a development environment.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

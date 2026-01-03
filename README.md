# MADMIN - Machine Administration Panel

A modern, modular web-based administration panel for Linux servers.

## 🚀 Features

### Core System
- **User Authentication** - JWT-based authentication with role-based access control (RBAC)
- **Dashboard** - System overview with machine statistics
- **Firewall Management** - Machine-level firewall rules with drag-drop ordering
- **Module System** - Hot-pluggable modules for extending functionality
- **Settings** - Customizable branding, backup/restore, and system configuration
- **Dark/Light Theme** - Modern UI with theme preference persistence

### Architecture
- **Backend**: Python FastAPI with async SQLAlchemy (SQLite)
- **Frontend**: Vanilla JavaScript SPA with Tabler UI framework
- **Firewall**: Direct iptables integration with chain hierarchy

## 📁 Project Structure

```
VPNManager/
├── backend/
│   ├── core/                    # Core application
│   │   ├── auth/               # Authentication & authorization
│   │   ├── backup/             # Backup & restore functionality
│   │   ├── firewall/           # Machine firewall management
│   │   ├── modules/            # Module loader & management
│   │   └── settings/           # System settings
│   ├── modules/                # Installed modules
│   └── staging/                # Modules awaiting installation
├── frontend/
│   ├── assets/
│   │   ├── css/               # Stylesheets
│   │   └── js/
│   │       ├── api.js         # API client
│   │       ├── router.js      # SPA router
│   │       ├── utils.js       # Utilities (toast, modals)
│   │       └── views/         # Page components
│   └── index.html             # Main SPA entry
└── main.py                    # FastAPI application entry
```

## 🛠️ Technology Stack

| Component | Technology |
|-----------|------------|
| Backend Framework | FastAPI (Python 3.10+) |
| Database | SQLite with SQLAlchemy |
| Frontend | Vanilla JavaScript ES6+ |
| UI Framework | Tabler (Bootstrap-based) |
| Icons | Tabler Icons |
| Authentication | JWT (python-jose) |
| Firewall | iptables (subprocess) |
| Drag & Drop | Sortable.js |

## 🔥 Firewall Architecture

MADMIN uses a hierarchical chain structure for flexible firewall management:

```
MAIN CHAINS (INPUT, FORWARD, OUTPUT)
    └── MADMIN_* chains (machine-level rules)
    └── MOD_*_* chains (module chains, priority ordered)
```

### Priority System
- MADMIN rules are processed first (highest priority)
- Module chains are processed in configurable order

## 🔌 Module System

Modules extend MADMIN's functionality without modifying core code.

### Module Lifecycle
1. **Staging** - Modules in `backend/staging/` await installation
2. **Installation** - Copies to `backend/modules/`, registers in database
3. **Activation** - Module routes and static files become available

### Module Structure
```
module_name/
├── __init__.py          # Module metadata
├── models.py            # Database models
├── router.py            # API routes
├── service.py           # Business logic
└── static/              # Frontend assets
    └── views/           # JavaScript view components
```

## 🚀 Quick Start

### Requirements
- Python 3.10+
- Linux with iptables
- SQLite (included)

### Installation

```bash
# Clone repository
git clone https://github.com/yourusername/VPNManager.git
cd VPNManager

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run application
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Default Credentials
- Username: `admin`
- Password: `admin` (change on first login!)

## 📡 API Documentation

Once running, access the interactive API docs at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## 🔐 Authentication

All API endpoints (except `/auth/login`) require JWT authentication.

```javascript
// Login
POST /api/auth/login
{ "username": "admin", "password": "admin" }

// Response
{ "access_token": "eyJ...", "user": { ... } }

// Use token in subsequent requests
Authorization: Bearer eyJ...
```

## 📦 Available Modules

See `backend/staging/` for available modules.

## 🤝 Contributing

Contributions are welcome! Please read the contributing guidelines before submitting PRs.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

---

Built with ❤️ for system administrators who value simplicity and power.

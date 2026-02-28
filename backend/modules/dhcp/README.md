# DHCP Server Module for MADMIN

ISC DHCP server management module with multi-interface subnets, static reservations, and live lease monitoring.

## 🌟 Features

- **Multi-Interface Subnets** — Bind each subnet to a specific NIC
- **Static Reservations** — Map MAC addresses to fixed IPs (host entries)
- **Live Lease Monitoring** — Real-time parsing of `dhcpd.leases`
- **Config Generation** — Database as source of truth, `dhcpd.conf` is auto-generated
- **Config Validation** — Syntax check via `dhcpd -t` before applying
- **Custom Options** — Global or per-subnet DHCP options
- **Service Control** — Start/stop/restart from the UI

## 📁 Module Structure

```
dhcp/
├── manifest.json
├── models.py            # Database models (DhcpSubnet, DhcpHost, DhcpOption)
├── router.py            # FastAPI routes
├── service.py           # Config generation, lease parsing, systemd
├── migrations/
│   └── 001_initial.py   # Creates dhcp_* tables
├── hooks/
│   ├── post_install.py  # System setup
│   └── pre_uninstall.py # Cleanup & backup
└── static/
    └── views/
        └── main.js      # Management UI
```

## 📡 API Endpoints

### System
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/status` | Service status + stats |
| GET | `/interfaces` | Available network interfaces |
| POST | `/apply` | Generate config + validate + restart |
| POST | `/start` | Start service |
| POST | `/stop` | Stop service |
| POST | `/restart` | Restart service |
| GET | `/config/preview` | Preview generated config |
| GET | `/config/validate` | Validate current config |

### Subnets
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/subnets` | List all subnets |
| POST | `/subnets` | Create subnet |
| GET | `/subnets/{id}` | Get subnet detail |
| PATCH | `/subnets/{id}` | Update subnet |
| DELETE | `/subnets/{id}` | Delete subnet |

### Reservations (Hosts)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/subnets/{id}/hosts` | List reservations |
| POST | `/subnets/{id}/hosts` | Create reservation |
| PATCH | `/subnets/{id}/hosts/{hid}` | Update reservation |
| DELETE | `/subnets/{id}/hosts/{hid}` | Delete reservation |

### Leases
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/leases` | All active leases |
| GET | `/subnets/{id}/leases` | Leases for a subnet |

### Options
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/options` | List options (global or per-subnet) |
| POST | `/options` | Create option |
| DELETE | `/options/{id}` | Delete option |

## 🔐 Permissions

| Permission | Description |
|------------|-------------|
| `dhcp.view` | View configuration and leases |
| `dhcp.manage` | Create/modify subnets, apply config |
| `dhcp.reservations` | Manage static reservations |

## 📋 Requirements

- Linux with systemd
- Root access (for systemctl and dhcpd)
- `isc-dhcp-server` package

## 🔧 How It Works

1. **Database is the source of truth** — All subnet, host, and option configurations are stored in the database
2. **Config generation** — `dhcpd.conf` is fully rendered from DB state using Jinja2 templates
3. **Apply workflow** — Generate → Validate (`dhcpd -t`) → Update interfaces → Restart service
4. **Lease monitoring** — `/var/lib/dhcp/dhcpd.leases` is parsed on-demand (no DB storage for leases)

---

Made with ❤️ for the MADMIN project.

# OpenVPN Module for MADMIN

A comprehensive OpenVPN server management module with PKI, certificate renewal, and per-client firewall groups.

## 🌟 Features

- **Multi-Instance Support** - Run multiple OpenVPN servers on different ports
- **Full PKI Management** - CA, server certificates, client certificates, CRL
- **Certificate Renewal** - Renew server and client certificates via UI
- **TCP & UDP Support** - Choose protocol per instance
- **Client Management** - Create, revoke clients with QR code and config download
- **Firewall Groups** - Group clients and apply specific firewall rules
- **Firewall Group Priority** - Drag-and-drop ordering to define rule precedence
- **Static IP via CCD** - Automatic IP assignment for firewall rules
- **Full/Split Tunnel** - Route all traffic or specific networks

## 📁 Module Structure

```
openvpn/
├── models.py            # Database models (OvpnInstance, OvpnClient, OvpnGroup, etc.)
├── router.py            # FastAPI routes (40+ endpoints)
├── service.py           # Business logic, PKI, iptables management
├── hooks/
│   ├── post_install.py  # Setup firewall chains, enable IP forward
│   ├── pre_uninstall.py # Cleanup chains and instances
│   └── post_update.py   # Restart running instances
└── static/
    └── views/
        └── main.js      # Instance, client, PKI management UI
```

## 🔥 Firewall Architecture

### Chain Hierarchy

```
FORWARD
└── MADMIN_FORWARD (machine rules, highest priority)
└── MOD_OVPN_FORWARD (module chain)
    └── OVPN_{instance}_FWD (per-instance)
        └── OVPN_GRP_{group} (per-group rules)
            └── Individual rules
            └── RETURN (to check next group)
        └── -o tun_interface -j ACCEPT (responses)
        └── Default Policy (ACCEPT/DROP)
```

## 🛠️ Installation

### From MADMIN UI

1. Go to **Modules** → **Store**
2. Find **OpenVPN Manager**
3. Click **Install**
4. Module chains are automatically registered

### System Requirements

```bash
# Debian/Ubuntu
apt install openvpn easy-rsa openssl
```

## 📡 API Endpoints

### Instances

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/instances` | List all instances |
| POST | `/instances` | Create new instance (init PKI) |
| GET | `/instances/{id}` | Get instance details |
| DELETE | `/instances/{id}` | Delete instance |
| POST | `/instances/{id}/start` | Start instance |
| POST | `/instances/{id}/stop` | Stop instance |
| PATCH | `/instances/{id}/routing` | Change tunnel mode |

### PKI / Certificates

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/instances/{id}/pki/status` | PKI status & expiry info |
| POST | `/instances/{id}/pki/renew-server` | Renew server certificate |

### Clients

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/instances/{id}/clients` | List clients with cert status |
| POST | `/instances/{id}/clients` | Create client (gen cert) |
| DELETE | `/instances/{id}/clients/{name}` | Revoke client |
| GET | `/instances/{id}/clients/{name}/config` | Download .ovpn |
| GET | `/instances/{id}/clients/{name}/qr` | Get QR code (magic link) |
| POST | `/instances/{id}/clients/{name}/renew` | Renew client certificate |

### Groups & Rules

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/instances/{id}/groups` | List groups |
| POST | `/instances/{id}/groups` | Create group |
| DELETE | `/instances/{id}/groups/{gid}` | Delete group |
| POST | `/instances/{id}/groups/{gid}/members` | Add member |
| DELETE | `/instances/{id}/groups/{gid}/members/{cid}` | Remove member |
| POST | `/instances/{id}/groups/{gid}/rules` | Create rule |
| PUT | `/instances/{id}/groups/{gid}/rules/order` | Reorder rules |

## 💡 Usage Examples

### Create an Instance

```bash
curl -X POST /api/modules/openvpn/instances \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "office",
    "port": 1194,
    "protocol": "udp",
    "subnet": "10.8.0.0/24",
    "tunnel_mode": "full",
    "cert_duration_days": 3650
  }'
```

### Create a Client

```bash
curl -X POST /api/modules/openvpn/instances/office/clients \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name": "john-laptop"}'
```

### Renew a Client Certificate

```bash
curl -X POST /api/modules/openvpn/instances/office/clients/john-laptop/renew \
  -H "Authorization: Bearer $TOKEN"
```

## ⚙️ Configuration

### Instance Options

| Field | Type | Description | Default |
|-------|------|-------------|---------|
| `name` | string | Instance identifier | required |
| `port` | int | Listening port | 1194 |
| `protocol` | enum | `udp` or `tcp` | udp |
| `subnet` | string | VPN subnet CIDR | 10.8.0.0/24 |
| `tunnel_mode` | enum | `full` or `split` | full |
| `cipher` | string | Encryption cipher | AES-256-GCM |
| `cert_duration_days` | int | Certificate validity | 3650 (10 years) |

## 🔐 Permissions

| Permission | Description |
|------------|-------------|
| `openvpn.view` | View instances and clients |
| `openvpn.manage` | Create/delete instances |
| `openvpn.clients` | Create/revoke clients |
| `openvpn.groups` | Manage firewall groups |

## 🔧 Troubleshooting

### Instance won't start
```bash
# Check systemd service
systemctl status openvpn-server@instance_id

# Check logs
journalctl -u openvpn-server@instance_id -f
```

### Certificate issues
```bash
# Check expiry
openssl x509 -enddate -noout -in /etc/openvpn/server/instance/easy-rsa/pki/ca.crt
```

### Client can't connect
1. Verify port is open: `ss -ulnp | grep 1194`
2. Check client config has correct endpoint
3. Verify NAT masquerade rule exists
4. Client may need to re-download config after cert renewal

## 🔗 Core Integration

- Uses `core.firewall.iptables` for chain management and rule application
- Uses `core.auth.dependencies.require_permission()` for API access control
- Uses `core.database.get_session` for async database sessions

---

Made with ❤️ for the MADMIN project.

# Reverse Proxy Module

nginx-based reverse proxy manager with HTTP basic auth access lists, IP allow/deny rules, and automated Let's Encrypt certificate management.

## Features

- **Proxy hosts** — forward HTTP/HTTPS traffic to internal services; supports multiple domain names per host, custom headers, WebSocket proxying
- **Access lists** — protect hosts with HTTP basic auth (username/password) and/or IP-based allow/deny rules; lists are reusable across multiple hosts
- **TLS certificates** — issue and renew Let's Encrypt certificates via Certbot; certificates are tied to proxy hosts and renewed automatically
- **Firewall integration** — automatically opens ports 80 and 443 in the `MOD_REVPROXY_INPUT` iptables chain on module activation
- **Conflict detection** — startup check blocks the module if another process already owns port 80 or 443

## Permissions

| Slug | Description |
|------|-------------|
| `reverseproxy.view` | View proxy hosts, access lists, and certificates |
| `reverseproxy.manage` | Create, edit, and delete proxy hosts |
| `reverseproxy.access_lists` | Manage access lists (HTTP basic auth and IP rules) |
| `reverseproxy.certs` | Issue and revoke Let's Encrypt certificates |

## System Dependencies

- `nginx` — web server / reverse proxy
- `certbot` — Let's Encrypt certificate issuance
- `apache2-utils` — `htpasswd` for HTTP basic auth credential files

## Configuration Files

The module writes nginx configuration under `/etc/nginx/madmin-revproxy/` and htpasswd files under `/etc/nginx/madmin-revproxy/htpasswd/`. These paths are included in config export/restore.

## Backup / Restore

Config export includes all DB tables (`revproxy_host`, `revproxy_host_domain`, `revproxy_access_list`, `revproxy_access_list_auth`, `revproxy_access_list_rule`, `revproxy_certificate`) plus Let's Encrypt certificates from `/etc/letsencrypt/live/madmin-*` and `/etc/letsencrypt/archive/madmin-*`. A `post_restore` hook regenerates nginx configs after import.

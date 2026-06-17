#!/bin/bash

# =================================================================
#                     MADMIN - Installer
# =================================================================
# Installs and configures MADMIN (Modular Admin System) on Ubuntu 24.04
# Requires: PostgreSQL 15+, Python 3.12+, Nginx
# =================================================================

set -e

# --- Colors and logging ---
log_info() { echo -e "\033[34m[INFO]\033[0m $1"; }
log_success() { echo -e "\033[32m[SUCCESS]\033[0m $1"; }
log_error() { echo -e "\033[31m[ERROR]\033[0m $1" >&2; }
log_warning() { echo -e "\033[33m[WARNING]\033[0m $1"; }

# --- Disable unattended-upgrades for the duration of the installation ---
disable_unattended_upgrades() {
    log_info "Pausing unattended-upgrades for the duration of the installation..."
    systemctl stop unattended-upgrades 2>/dev/null || true
    systemctl stop apt-daily.service 2>/dev/null || true
    systemctl stop apt-daily-upgrade.service 2>/dev/null || true
    # Wait for any in-flight apt processes to finish
    local waited=0
    while pgrep -x "unattended-upgr" >/dev/null 2>&1 || pgrep -x "apt-get" >/dev/null 2>&1; do
        if [ $waited -eq 0 ]; then
            log_warning "An apt process is still running, waiting for it to finish..."
        fi
        sleep 2
        waited=$((waited + 2))
        if [ $waited -ge 120 ]; then
            log_warning "Timed out waiting for apt process. Proceeding anyway."
            break
        fi
    done
}

# Re-enable unattended-upgrades at the end (or on error)
reenable_unattended_upgrades() {
    systemctl start unattended-upgrades 2>/dev/null || true
    systemctl start apt-daily.timer 2>/dev/null || true
    systemctl start apt-daily-upgrade.timer 2>/dev/null || true
}

# --- Wait for apt/dpkg lock to be released ---
wait_for_apt() {
    local max_wait=300
    local waited=0
    while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || \
          fuser /var/lib/dpkg/lock >/dev/null 2>&1 || \
          fuser /var/lib/apt/lists/lock >/dev/null 2>&1 || \
          fuser /var/cache/apt/archives/lock >/dev/null 2>&1; do
        if [ $waited -eq 0 ]; then
            log_warning "apt lock still held, waiting (max ${max_wait}s)..."
        fi
        sleep 5
        waited=$((waited + 5))
        if [ $waited -ge $max_wait ]; then
            log_warning "apt lock still held after ${max_wait}s — proceeding anyway (apt may fail)."
            log_warning "If installation fails, re-run this script to retry: sudo bash setup-madmin.sh"
            break
        fi
    done
    if [ $waited -gt 0 ] && [ $waited -lt $max_wait ]; then
        log_info "apt lock released after ${waited}s."
    fi
}

# --- Banner ---
print_banner() {
    echo -e "\033[1;36m"
    cat << 'EOF'
    __  __    _    ____  __  __ ___ _   _
   |  \/  |  / \  |  _ \|  \/  |_ _| \ | |
   | |\/| | / _ \ | | | | |\/| || ||  \| |
   | |  | |/ ___ \| |_| | |  | || || |\  |
   |_|  |_/_/   \_\____/|_|  |_|___|_| \_|

     Modular Admin System - Installer
EOF
    echo -e "\033[0m"
}

# --- Arguments ---
ADMIN_USERNAME="admin"
ADMIN_PASSWORD="admin"
FORCE_PW_CHANGE="false"   # opt-in: used by install automations (e.g. madmin-hub)
PROVISION_LAN="false"     # opt-in: auto-provisions a managed LAN (interface + DHCP + NAT)
PROVISION_LAN_IFACES=""   # optional: comma-separated interfaces to lock (first = managed LAN)
PROTECT_WAN="false"       # opt-in: makes WAN (eth0) editing read-only via UI/API

while [[ "$#" -gt 0 ]]; do
    case $1 in
        -u|--username) ADMIN_USERNAME="$2"; shift ;;
        -p|--password) ADMIN_PASSWORD="$2"; shift ;;
        -f|--force-password-change) FORCE_PW_CHANGE="true" ;;
        -l|--provision-lan)
            PROVISION_LAN="true"
            # Optional value: comma-separated interface list (consumed only if the
            # next token is not another flag).
            if [[ -n "$2" && "$2" != -* ]]; then PROVISION_LAN_IFACES="$2"; shift; fi
            ;;
        -w|--protect-wan) PROTECT_WAN="true" ;;
    esac
    shift
done

# --- Root check ---
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root. Use 'sudo bash setup-madmin.sh'"
    exit 1
fi

print_banner

# Re-enable unattended-upgrades when the script ends (even on error)
trap reenable_unattended_upgrades EXIT

# --- Configuration variables ---
INSTALL_DIR="/opt/madmin"
DB_NAME="madmin"
DB_USER="madmin"
DB_PASSWORD=$(openssl rand -hex 16)
SECRET_KEY=$(openssl rand -hex 32)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

log_info "Installation directory: $INSTALL_DIR"
log_info "Project directory: $PROJECT_DIR"

# --- Step 1: System dependencies ---
log_info "Step 1/7: Installing system dependencies..."

disable_unattended_upgrades
wait_for_apt
apt-get update

# Base utilities (needed on Ubuntu Minimal where they are not preinstalled)
log_info "Installing base utilities..."
apt-get install -y \
    cron \
    iproute2 \
    openssl \
    debconf-utils \
    build-essential \
    libmagic-dev \
    libffi-dev \
    sudo \
    net-tools \
    curl \
    git

# PostgreSQL
log_info "Installing PostgreSQL..."
apt-get install -y postgresql postgresql-contrib libpq-dev

# Python
log_info "Installing Python..."
apt-get install -y python3-pip python3-venv python3-dev python3-full

# Nginx
log_info "Installing Nginx..."
apt-get install -y nginx

# Pre-seed iptables-persistent (silent install)
echo iptables-persistent iptables-persistent/autosave_v4 boolean true | debconf-set-selections
echo iptables-persistent iptables-persistent/autosave_v6 boolean true | debconf-set-selections

# Firewall
apt-get install -y iptables iptables-persistent ipset conntrack

# Enable and start the cron daemon
systemctl enable cron
systemctl start cron

log_success "Dependencies installed."

# --- Step 2: PostgreSQL configuration ---
log_info "Step 2/7: Configuring PostgreSQL..."

# Start PostgreSQL if not running
systemctl start postgresql
systemctl enable postgresql

# Create user and database
sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';" 2>/dev/null || \
    sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';"

sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" 2>/dev/null || \
    log_warning "Database $DB_NAME already exists."

sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"

log_success "PostgreSQL configured (DB: $DB_NAME, User: $DB_USER)"

# --- Step 3: Backend deployment ---
log_info "Step 3/7: Deploying backend..."

mkdir -p $INSTALL_DIR/backend
mkdir -p $INSTALL_DIR/backend/modules
mkdir -p $INSTALL_DIR/data

# Copy backend files
cp -r "$PROJECT_DIR/backend/"* $INSTALL_DIR/backend/

# Create virtual environment (skip if already functional)
if [ ! -x "$INSTALL_DIR/venv/bin/python3" ]; then
    log_info "Creating virtual environment..."
    python3 -m venv $INSTALL_DIR/venv
else
    log_info "Virtual environment already exists, skipping creation."
fi

# Install dependencies
log_info "Installing Python dependencies..."
$INSTALL_DIR/venv/bin/pip install --upgrade pip
$INSTALL_DIR/venv/bin/pip install -r $INSTALL_DIR/backend/requirements.txt

# Create .env file
cat > $INSTALL_DIR/backend/.env << EOF
DATABASE_URL=postgresql+asyncpg://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME
SECRET_KEY=$SECRET_KEY
DEBUG=false
ALLOWED_ORIGINS=*
DATA_DIR=$INSTALL_DIR/data
MODULES_DIR=$INSTALL_DIR/backend/modules
MOCK_IPTABLES=false
EOF

chmod 600 $INSTALL_DIR/backend/.env

log_success "Backend deployed."

# --- Step 4: Frontend deployment ---
log_info "Step 4/7: Deploying frontend..."

mkdir -p $INSTALL_DIR/frontend

# Copy frontend files
cp -r "$PROJECT_DIR/frontend/"* $INSTALL_DIR/frontend/

# Permissions
chown -R www-data:www-data $INSTALL_DIR/frontend
chmod -R 755 $INSTALL_DIR/frontend

log_success "Frontend deployed."

# --- Step 5: Nginx configuration ---
log_info "Step 5/7: Configuring Nginx..."

# Detect public IP
PUBLIC_IP=$(curl -s https://ifconfig.me 2>/dev/null || echo "localhost")

# Create SSL directory
mkdir -p $INSTALL_DIR/data/ssl
chmod 700 $INSTALL_DIR/data/ssl

# Generate self-signed certificate (10 years)
if [ ! -f "$INSTALL_DIR/data/ssl/server.crt" ]; then
    log_info "Generating self-signed SSL certificate (10 years)..."
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout $INSTALL_DIR/data/ssl/server.key \
        -out $INSTALL_DIR/data/ssl/server.crt \
        -subj "/C=IT/ST=Italy/L=Rome/O=MADMIN/OU=IT/CN=madmin.local" >/dev/null 2>&1
    chmod 600 $INSTALL_DIR/data/ssl/server.key
fi

cat > /etc/nginx/sites-available/madmin.conf << EOF
server {
    listen 7443 ssl;
    server_name $PUBLIC_IP _;

    ssl_certificate $INSTALL_DIR/data/ssl/server.crt;
    ssl_certificate_key $INSTALL_DIR/data/ssl/server.key;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    root $INSTALL_DIR/frontend;
    index index.html;

    # Module static files (served by FastAPI, mounted dynamically)
    location /static/modules {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_cache_valid 200 1d;
    }

    # Core static assets (served directly from filesystem)
    location /static {
        alias $INSTALL_DIR/frontend/assets;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # Uploaded files (logos, favicons, etc.)
    location /uploads {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    # API reverse proxy
    location /api {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Login page
    location /login {
        try_files /login.html =404;
    }

    # SPA fallback
    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF

# Create uploads directory
mkdir -p $INSTALL_DIR/uploads
chown -R www-data:www-data $INSTALL_DIR/uploads
chmod 755 $INSTALL_DIR/uploads

# Enable site
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/madmin.conf /etc/nginx/sites-enabled/

# Test and restart Nginx
nginx -t
systemctl restart nginx
systemctl enable nginx

log_success "Nginx configured."

# --- Step 6: Systemd service ---
log_info "Step 6/7: Configuring systemd service..."

cat > /etc/systemd/system/madmin.service << EOF
[Unit]
Description=MADMIN Backend (FastAPI)
After=network.target postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR/backend
Environment="PATH=$INSTALL_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
ExecStart=$INSTALL_DIR/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Enable IP forwarding
log_info "Enabling IP forwarding..."
echo "net.ipv4.ip_forward = 1" > /etc/sysctl.d/99-madmin.conf
sysctl -p /etc/sysctl.d/99-madmin.conf

# Don't start yet — install module dependencies first
systemctl daemon-reload
systemctl enable madmin.service

log_success "Systemd service configured."

# --- Step 7: Module dependencies (dynamic from manifest.json) ---
log_info "Step 7/7: Installing module dependencies..."

MODULE_COUNT=0
for manifest in $INSTALL_DIR/backend/modules/*/manifest.json; do
    [ -f "$manifest" ] || continue
    MODULE_COUNT=$((MODULE_COUNT + 1))

    MODULE_NAME=$(python3 -c "import json; print(json.load(open('$manifest'))['name'])" 2>/dev/null || echo "Unknown module")
    MODULE_ID=$(python3 -c "import json; print(json.load(open('$manifest'))['id'])" 2>/dev/null || echo "unknown")
    log_info "Module $MODULE_COUNT: $MODULE_NAME ($MODULE_ID)"

    # apt dependencies
    APT_DEPS=$(python3 -c "
import json
m = json.load(open('$manifest'))
deps = m.get('system_dependencies', {}).get('apt', [])
print(' '.join(deps))
" 2>/dev/null)

    if [ -n "$APT_DEPS" ]; then
        log_info "  Installing apt packages: $APT_DEPS"
        wait_for_apt
        if ! DEBIAN_FRONTEND=noninteractive apt-get install -y $APT_DEPS; then
            log_warning "  apt-get failed, retrying after waiting for lock..."
            wait_for_apt
            DEBIAN_FRONTEND=noninteractive apt-get install -y $APT_DEPS
        fi
    fi

    # pip dependencies
    PIP_DEPS=$(python3 -c "
import json
m = json.load(open('$manifest'))
deps = m.get('system_dependencies', {}).get('pip', [])
print(' '.join(deps))
" 2>/dev/null)

    if [ -n "$PIP_DEPS" ]; then
        log_info "  Installing pip packages: $PIP_DEPS"
        $INSTALL_DIR/venv/bin/pip install $PIP_DEPS
    fi

    log_success "  $MODULE_NAME — dependencies installed."
done

if [ $MODULE_COUNT -eq 0 ]; then
    log_warning "No modules found in $INSTALL_DIR/backend/modules/"
else
    log_success "$MODULE_COUNT modules detected, dependencies installed (modules disabled by default)."
fi

# --- Start service ---
log_info "Starting MADMIN service..."
systemctl restart madmin.service 2>/dev/null || systemctl start madmin.service

# Wait for the backend to be ready
log_info "Waiting for backend to start..."
sleep 5

# Check status
if systemctl is-active --quiet madmin.service; then
    log_success "MADMIN service is active."
else
    log_error "MADMIN service is not active. Check: journalctl -u madmin -f"
fi

# Create the initial administrator user
log_info "Creating administrator user..."
INIT_BODY=$(python3 -c "import json,sys; print(json.dumps({'username':sys.argv[1],'password':sys.argv[2]}))" "$ADMIN_USERNAME" "$ADMIN_PASSWORD")
INIT_HTTP=$(curl -s -o /tmp/madmin_init.json -w "%{http_code}" -X POST http://localhost:8000/api/auth/init \
    -H "Content-Type: application/json" \
    -d "$INIT_BODY")
if [ "$INIT_HTTP" = "201" ]; then
    log_success "Administrator user created: $ADMIN_USERNAME"
elif [ "$INIT_HTTP" = "400" ] || [ "$INIT_HTTP" = "409" ]; then
    log_info "Administrator user '$ADMIN_USERNAME' already exists, skipping."
else
    log_error "Failed to create administrator user (HTTP $INIT_HTTP): $(cat /tmp/madmin_init.json)"
fi
rm -f /tmp/madmin_init.json

# Import default firewall rules
log_info "Importing default firewall rules..."
LOGIN_BODY=$(python3 -c "import urllib.parse,sys; print(urllib.parse.urlencode({'username':sys.argv[1],'password':sys.argv[2],'grant_type':'password'}))" "$ADMIN_USERNAME" "$ADMIN_PASSWORD")
TOKEN_RESPONSE=$(curl -s -X POST http://localhost:8000/api/auth/token \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "$LOGIN_BODY")
JWT_TOKEN=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('access_token',''))" "$TOKEN_RESPONSE")

if [ -n "$JWT_TOKEN" ] && [ -f "$INSTALL_DIR/backend/default_rules.json" ]; then
    IMPORT_HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
        "http://localhost:8000/api/firewall/import?mode=replace" \
        -H "Authorization: Bearer $JWT_TOKEN" \
        -F "file=@$INSTALL_DIR/backend/default_rules.json")
    if [ "$IMPORT_HTTP" = "200" ]; then
        log_success "Default firewall rules imported."
    else
        log_warning "Default firewall rules import failed (HTTP $IMPORT_HTTP). Apply them manually from the UI."
    fi
    rm -f "$INSTALL_DIR/backend/default_rules.json"
else
    log_warning "JWT unavailable or rules file missing. Firewall import skipped."
fi

# Managed LAN auto-provisioning (opt-in, used by automations such as madmin-hub).
# Binds DHCP + NAT to the LAN interface so VMs behind the router get connectivity
# right away. The interface IP is NOT set here: it is assigned externally by the
# WAN-managing software, and DHCP derives its subnet/gateway from that live IP.
if [ "$PROVISION_LAN" = "true" ]; then
    if [ -n "$JWT_TOKEN" ]; then
        log_info "Enabling managed LAN provisioning (interface + DHCP + NAT)..."
        # If an explicit interface list was given, send it as JSON body; the first
        # is the managed LAN (DHCP/NAT), all are locked read-only.
        if [ -n "$PROVISION_LAN_IFACES" ]; then
            PROV_BODY=$(python3 -c "import json,sys; print(json.dumps({'interfaces':[s for s in sys.argv[1].split(',') if s.strip()]}))" "$PROVISION_LAN_IFACES")
            PROV_HTTP=$(curl -s -o /tmp/madmin_prov.json -w "%{http_code}" -X POST \
                "http://localhost:8000/api/provisioning/managed-lan/enable" \
                -H "Authorization: Bearer $JWT_TOKEN" \
                -H "Content-Type: application/json" \
                -d "$PROV_BODY")
        else
            PROV_HTTP=$(curl -s -o /tmp/madmin_prov.json -w "%{http_code}" -X POST \
                "http://localhost:8000/api/provisioning/managed-lan/enable" \
                -H "Authorization: Bearer $JWT_TOKEN")
        fi
        if [ "$PROV_HTTP" = "200" ]; then
            # enabled=false means the required interface(s) were not found:
            # provisioning was skipped, as if --provision-lan had not been passed.
            PROV_ENABLED=$(python3 -c "import json,sys; print(str(json.load(open('/tmp/madmin_prov.json')).get('enabled', False)).lower())" 2>/dev/null)
            PROV_IFACE=$(python3 -c "import json,sys; print(json.load(open('/tmp/madmin_prov.json')).get('interface') or '')" 2>/dev/null)
            PROV_LOCKED=$(python3 -c "import json,sys; print(', '.join(json.load(open('/tmp/madmin_prov.json')).get('locked_interfaces') or []))" 2>/dev/null)
            if [ "$PROV_ENABLED" = "true" ]; then
                log_success "Managed LAN configured: DHCP/NAT on '$PROV_IFACE', locked interfaces: $PROV_LOCKED."
            elif [ -n "$PROVISION_LAN_IFACES" ]; then
                log_warning "Managed LAN NOT configured: one or more specified interfaces ($PROVISION_LAN_IFACES) not found. DHCP/NAT not set up."
            else
                log_warning "Managed LAN NOT configured: no known LAN interface (eth1/ens19) found. DHCP/NAT not set up."
            fi
        else
            log_warning "Managed LAN provisioning failed (HTTP $PROV_HTTP): $(cat /tmp/madmin_prov.json)"
        fi
        rm -f /tmp/madmin_prov.json
    else
        log_warning "JWT unavailable: managed LAN provisioning not enabled."
    fi
fi

# Force password change at first login (opt-in, used by automations).
# Done AFTER the firewall import: the admin already obtained a full token above,
# avoiding the chicken-and-egg with the "password_change_required" login gate.
if [ "$FORCE_PW_CHANGE" = "true" ]; then
    if [ -n "$JWT_TOKEN" ]; then
        log_info "Enabling forced password change at first login..."
        PW_HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH \
            "http://localhost:8000/api/auth/users/$ADMIN_USERNAME" \
            -H "Authorization: Bearer $JWT_TOKEN" \
            -H "Content-Type: application/json" \
            -d '{"must_change_password": true}')
        if [ "$PW_HTTP" = "200" ]; then
            log_success "Forced password change enabled for $ADMIN_USERNAME."
        else
            log_warning "Could not enable forced password change (HTTP $PW_HTTP)."
        fi
    else
        log_warning "JWT unavailable: forced password change not enabled."
    fi
fi

# Enable WAN protection (eth0 editing read-only, opt-in used by automations).
if [ "$PROTECT_WAN" = "true" ]; then
    if [ -n "$JWT_TOKEN" ]; then
        log_info "Enabling WAN protection (eth0 editing read-only)..."
        WAN_HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH \
            "http://localhost:8000/api/settings/system" \
            -H "Authorization: Bearer $JWT_TOKEN" \
            -H "Content-Type: application/json" \
            -d '{"wan_protection_enabled": true}')
        if [ "$WAN_HTTP" = "200" ]; then
            log_success "WAN protection enabled: eth0 editing blocked."
        else
            log_warning "Could not enable WAN protection (HTTP $WAN_HTTP)."
        fi
    else
        log_warning "JWT unavailable: WAN protection not enabled."
    fi
fi

# If LAN provisioning enabled the DHCP module, restart the service so the module's
# router is mounted cleanly (the isc-dhcp-server service runs regardless).
if [ "$PROVISION_LAN" = "true" ]; then
    log_info "Restarting MADMIN to mount the DHCP module..."
    systemctl restart madmin.service
fi

# --- Completed ---
echo ""
log_success "=========================================="
log_success "   INSTALLATION COMPLETED!"
log_success "=========================================="
echo ""
echo "Dashboard: https://$PUBLIC_IP:7443"
echo ""
echo "Administrator credentials:"
echo "  Username: $ADMIN_USERNAME"
echo "  Password: (the one provided during installation)"
echo ""
echo "Database:"
echo "  Name:     $DB_NAME"
echo "  User:     $DB_USER"
echo "  Password: $DB_PASSWORD"
echo ""

# Auto-provisioning options actually enabled by flags
if [ "$FORCE_PW_CHANGE" = "true" ] || [ "$PROVISION_LAN" = "true" ] || [ "$PROTECT_WAN" = "true" ]; then
    echo "Auto-provisioning options enabled:"
    [ "$FORCE_PW_CHANGE" = "true" ] && echo "  - Forced password change at first login"
    [ "$PROVISION_LAN" = "true" ]  && echo "  - Managed LAN (interface + DHCP + NAT)"
    [ "$PROTECT_WAN" = "true" ]    && echo "  - WAN edit protection (eth0 config read-only)"
    echo ""
fi

# Password reminder: only meaningful when a change is not already forced
if [ "$FORCE_PW_CHANGE" = "true" ]; then
    echo "NOTE: You will be required to change the admin password at first login."
else
    echo "NOTE: Remember to change the admin password after first login."
fi
echo ""
echo "Useful commands:"
echo "  Logs:     journalctl -u madmin -f"
echo "  Restart:  systemctl restart madmin"
echo "  Status:   systemctl status madmin"
echo ""

#!/bin/bash

# =================================================================
#                     MADMIN - Installer
# =================================================================
# Installa e configura MADMIN (Modular Admin System) su Ubuntu 24.04
# Richiede: PostgreSQL 15+, Python 3.12+, Nginx
# =================================================================

set -e

# --- Colori e Logging ---
log_info() { echo -e "\033[34m[INFO]\033[0m $1"; }
log_success() { echo -e "\033[32m[SUCCESS]\033[0m $1"; }
log_error() { echo -e "\033[31m[ERROR]\033[0m $1" >&2; }
log_warning() { echo -e "\033[33m[WARNING]\033[0m $1"; }

# --- Disabilita unattended-upgrades per la durata dell'installazione ---
disable_unattended_upgrades() {
    log_info "Sospensione unattended-upgrades per la durata dell'installazione..."
    systemctl stop unattended-upgrades 2>/dev/null || true
    systemctl stop apt-daily.service 2>/dev/null || true
    systemctl stop apt-daily-upgrade.service 2>/dev/null || true
    # Attendi che eventuali processi apt in corso terminino
    local waited=0
    while pgrep -x "unattended-upgr" >/dev/null 2>&1 || pgrep -x "apt-get" >/dev/null 2>&1; do
        if [ $waited -eq 0 ]; then
            log_warning "Processo apt ancora in esecuzione, attendo terminazione..."
        fi
        sleep 2
        waited=$((waited + 2))
        if [ $waited -ge 120 ]; then
            log_warning "Timeout attesa processo apt. Procedo comunque."
            break
        fi
    done
}

# Riabilita unattended-upgrades al termine (o in caso di errore)
reenable_unattended_upgrades() {
    systemctl start unattended-upgrades 2>/dev/null || true
    systemctl start apt-daily.timer 2>/dev/null || true
    systemctl start apt-daily-upgrade.timer 2>/dev/null || true
}

# --- Attendi rilascio lock apt/dpkg ---
wait_for_apt() {
    local max_wait=60
    local waited=0
    while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || \
          fuser /var/lib/dpkg/lock >/dev/null 2>&1 || \
          fuser /var/lib/apt/lists/lock >/dev/null 2>&1 || \
          fuser /var/cache/apt/archives/lock >/dev/null 2>&1; do
        if [ $waited -eq 0 ]; then
            log_warning "Lock apt ancora occupato, attendo..."
        fi
        sleep 2
        waited=$((waited + 2))
        if [ $waited -ge $max_wait ]; then
            log_error "Timeout: impossibile ottenere il lock apt dopo ${max_wait}s."
            exit 1
        fi
    done
    if [ $waited -gt 0 ]; then
        log_info "Lock apt rilasciato dopo ${waited}s."
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

# --- Argomenti ---
ADMIN_USERNAME="admin"
ADMIN_PASSWORD="admin"

while [[ "$#" -gt 0 ]]; do
    case $1 in
        -u|--username) ADMIN_USERNAME="$2"; shift ;;
        -p|--password) ADMIN_PASSWORD="$2"; shift ;;
    esac
    shift
done

# --- Check Root ---
if [[ $EUID -ne 0 ]]; then
    log_error "Questo script deve essere eseguito come root. Usa 'sudo bash setup-madmin.sh'"
    exit 1
fi

print_banner

# Riabilita unattended-upgrades alla fine dello script (anche in caso di errore)
trap reenable_unattended_upgrades EXIT

# --- Variabili di Configurazione ---
INSTALL_DIR="/opt/madmin"
DB_NAME="madmin"
DB_USER="madmin"
DB_PASSWORD=$(openssl rand -hex 16)
SECRET_KEY=$(openssl rand -hex 32)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

log_info "Directory di installazione: $INSTALL_DIR"
log_info "Directory del progetto: $PROJECT_DIR"

# --- Fase 1: Dipendenze di Sistema ---
log_info "Fase 1/7: Installazione dipendenze di sistema..."

disable_unattended_upgrades
wait_for_apt
apt-get update

# Utility di base (necessarie su Ubuntu Minimal dove non sono preinstallate)
log_info "Installazione utility di base..."
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
log_info "Installazione PostgreSQL..."
apt-get install -y postgresql postgresql-contrib libpq-dev

# Python
log_info "Installazione Python..."
apt-get install -y python3-pip python3-venv python3-dev python3-full

# Nginx
log_info "Installazione Nginx..."
apt-get install -y nginx

# Pre-configurazione iptables-persistent (silent install)
echo iptables-persistent iptables-persistent/autosave_v4 boolean true | debconf-set-selections
echo iptables-persistent iptables-persistent/autosave_v6 boolean true | debconf-set-selections

# Firewall
apt-get install -y iptables iptables-persistent

# Abilita e avvia cron daemon
systemctl enable cron
systemctl start cron

log_success "Dipendenze installate."

# --- Fase 2: Configurazione PostgreSQL ---
log_info "Fase 2/7: Configurazione PostgreSQL..."

# Avvia PostgreSQL se non attivo
systemctl start postgresql
systemctl enable postgresql

# Crea utente e database
sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';" 2>/dev/null || \
    sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';"

sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" 2>/dev/null || \
    log_warning "Database $DB_NAME già esistente."

sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"

log_success "PostgreSQL configurato (DB: $DB_NAME, User: $DB_USER)"

# --- Fase 3: Deploy Backend ---
log_info "Fase 3/7: Deploy Backend..."

mkdir -p $INSTALL_DIR/backend
mkdir -p $INSTALL_DIR/backend/modules
mkdir -p $INSTALL_DIR/data

# Copia file backend
cp -r "$PROJECT_DIR/backend/"* $INSTALL_DIR/backend/

# Crea ambiente virtuale
log_info "Creazione virtual environment..."
python3 -m venv $INSTALL_DIR/venv

# Installa dipendenze
log_info "Installazione dipendenze Python..."
$INSTALL_DIR/venv/bin/pip install --upgrade pip
$INSTALL_DIR/venv/bin/pip install -r $INSTALL_DIR/backend/requirements.txt

# Crea file .env
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

log_success "Backend deployato."

# --- Fase 4: Deploy Frontend ---
log_info "Fase 4/7: Deploy Frontend..."

mkdir -p $INSTALL_DIR/frontend

# Copia file frontend
cp -r "$PROJECT_DIR/frontend/"* $INSTALL_DIR/frontend/

# Permessi
chown -R www-data:www-data $INSTALL_DIR/frontend
chmod -R 755 $INSTALL_DIR/frontend

log_success "Frontend deployato."

# --- Fase 5: Configurazione Nginx ---
log_info "Fase 5/7: Configurazione Nginx..."

# Rileva IP pubblico
PUBLIC_IP=$(curl -s https://ifconfig.me 2>/dev/null || echo "localhost")

# Crea directory SSL
mkdir -p $INSTALL_DIR/data/ssl
chmod 700 $INSTALL_DIR/data/ssl

# Genera certificato self-signed (10 anni)
if [ ! -f "$INSTALL_DIR/data/ssl/server.crt" ]; then
    log_info "Generazione certificato SSL self-signed (10 anni)..."
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

# Abilita sito
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/madmin.conf /etc/nginx/sites-enabled/

# Test e restart Nginx
nginx -t
systemctl restart nginx
systemctl enable nginx

log_success "Nginx configurato."

# --- Fase 6: Servizio Systemd ---
log_info "Fase 6/7: Configurazione servizio systemd..."

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

# Abilita IP forwarding
log_info "Abilitazione IP Forwarding..."
echo "net.ipv4.ip_forward = 1" > /etc/sysctl.d/99-madmin.conf
sysctl -p /etc/sysctl.d/99-madmin.conf

# Non avviare ancora — prima installiamo le dipendenze dei moduli
systemctl daemon-reload
systemctl enable madmin.service

log_success "Servizio systemd configurato."

# --- Fase 7: Dipendenze Moduli (dinamico da manifest.json) ---
log_info "Fase 7/7: Installazione dipendenze moduli..."

MODULE_COUNT=0
for manifest in $INSTALL_DIR/backend/modules/*/manifest.json; do
    [ -f "$manifest" ] || continue
    MODULE_COUNT=$((MODULE_COUNT + 1))

    MODULE_NAME=$(python3 -c "import json; print(json.load(open('$manifest'))['name'])" 2>/dev/null || echo "Modulo sconosciuto")
    MODULE_ID=$(python3 -c "import json; print(json.load(open('$manifest'))['id'])" 2>/dev/null || echo "unknown")
    log_info "Modulo $MODULE_COUNT: $MODULE_NAME ($MODULE_ID)"

    # Dipendenze apt
    APT_DEPS=$(python3 -c "
import json
m = json.load(open('$manifest'))
deps = m.get('system_dependencies', {}).get('apt', [])
print(' '.join(deps))
" 2>/dev/null)

    if [ -n "$APT_DEPS" ]; then
        log_info "  Installazione pacchetti apt: $APT_DEPS"
        wait_for_apt
        if ! DEBIAN_FRONTEND=noninteractive apt-get install -y $APT_DEPS; then
            log_warning "  apt-get fallito, riprovo dopo attesa lock..."
            wait_for_apt
            DEBIAN_FRONTEND=noninteractive apt-get install -y $APT_DEPS
        fi
    fi

    # Dipendenze pip
    PIP_DEPS=$(python3 -c "
import json
m = json.load(open('$manifest'))
deps = m.get('system_dependencies', {}).get('pip', [])
print(' '.join(deps))
" 2>/dev/null)

    if [ -n "$PIP_DEPS" ]; then
        log_info "  Installazione pacchetti pip: $PIP_DEPS"
        $INSTALL_DIR/venv/bin/pip install $PIP_DEPS
    fi

    log_success "  $MODULE_NAME — dipendenze installate."
done

if [ $MODULE_COUNT -eq 0 ]; then
    log_warning "Nessun modulo trovato in $INSTALL_DIR/backend/modules/"
else
    log_success "$MODULE_COUNT moduli rilevati, dipendenze installate (moduli disabilitati di default)."
fi

# --- Avvio servizio ---
log_info "Avvio servizio MADMIN..."
systemctl start madmin.service

# Attendi che il backend sia pronto
log_info "Attendo avvio backend..."
sleep 5

# Verifica stato
if systemctl is-active --quiet madmin.service; then
    log_success "Servizio MADMIN attivo."
else
    log_error "Servizio MADMIN non attivo. Controlla: journalctl -u madmin -f"
fi

# Crea utente amministratore iniziale
log_info "Creazione utente amministratore..."
INIT_BODY=$(python3 -c "import json,sys; print(json.dumps({'username':sys.argv[1],'password':sys.argv[2]}))" "$ADMIN_USERNAME" "$ADMIN_PASSWORD")
INIT_HTTP=$(curl -s -o /tmp/madmin_init.json -w "%{http_code}" -X POST http://localhost:8000/api/auth/init \
    -H "Content-Type: application/json" \
    -d "$INIT_BODY")
if [ "$INIT_HTTP" = "201" ]; then
    log_success "Utente amministratore creato: $ADMIN_USERNAME"
else
    log_error "Errore nella creazione dell'utente amministratore (HTTP $INIT_HTTP): $(cat /tmp/madmin_init.json)"
fi
rm -f /tmp/madmin_init.json

# Import regole firewall di default
log_info "Import regole firewall di default..."
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
        log_success "Regole firewall di default importate."
    else
        log_warning "Import regole firewall fallito (HTTP $IMPORT_HTTP). Applicare manualmente dalla UI."
    fi
    rm -f "$INSTALL_DIR/backend/default_rules.json"
else
    log_warning "JWT non disponibile o file regole mancante. Import firewall saltato."
fi

# --- Completato ---
echo ""
log_success "=========================================="
log_success "   INSTALLAZIONE COMPLETATA!"
log_success "=========================================="
echo ""
echo "Dashboard: https://$PUBLIC_IP:7443"
echo ""
echo "Credenziali Amministratore:"
echo "  Username: $ADMIN_USERNAME"
echo "  Password: (quella specificata al momento dell'installazione)"
echo ""
echo "Database:"
echo "  Nome: $DB_NAME"
echo "  Utente: $DB_USER"
echo "  Password: $DB_PASSWORD"
echo ""
echo "NOTA: Cambia la password al primo accesso!"
echo ""
echo "Comandi utili:"
echo "  Logs:     journalctl -u madmin -f"
echo "  Restart:  systemctl restart madmin"
echo "  Status:   systemctl status madmin"
echo ""

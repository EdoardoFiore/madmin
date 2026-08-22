#!/bin/bash

# =================================================================
#                     MADMIN - Uninstaller
# =================================================================
# Removes everything installed by setup-madmin.sh so a fresh, updated
# version can be installed cleanly. Reverses, in order:
#   - systemd services (madmin.service, madmin-firewall-boot.service)
#   - Nginx site config (restores the default site if present)
#   - firewall persistence + fail-closed DROP policy (RESET to ACCEPT)
#   - PostgreSQL database and user
#   - IP-forwarding sysctl drop-in
#   - the /opt/madmin install directory (code, venv, data, SSL, uploads)
#
# By design it does NOT:
#   - uninstall apt packages (postgres, nginx, python, iptables, module
#     dependencies like bind9/openvpn/...). Use --purge-packages for that.
#   - touch any host data outside the MADMIN footprint.
#
# Usage:
#   sudo bash uninstall-madmin.sh            # interactive confirm
#   sudo bash uninstall-madmin.sh -y         # no prompt
#   sudo bash uninstall-madmin.sh --keep-db  # keep the PostgreSQL DB/user
#   sudo bash uninstall-madmin.sh --purge-packages   # also apt-get purge deps
# =================================================================

set -u

# --- Colors and logging ---
log_info() { echo -e "\033[34m[INFO]\033[0m $1"; }
log_success() { echo -e "\033[32m[SUCCESS]\033[0m $1"; }
log_error() { echo -e "\033[31m[ERROR]\033[0m $1" >&2; }
log_warning() { echo -e "\033[33m[WARNING]\033[0m $1"; }

# --- Configuration (must match setup-madmin.sh) ---
INSTALL_DIR="/opt/madmin"
DB_NAME="madmin"
DB_USER="madmin"

ASSUME_YES="false"
KEEP_DB="false"
PURGE_PACKAGES="false"

while [[ "$#" -gt 0 ]]; do
    case $1 in
        -y|--yes) ASSUME_YES="true" ;;
        --keep-db) KEEP_DB="true" ;;
        --purge-packages) PURGE_PACKAGES="true" ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) log_warning "Unknown argument: $1" ;;
    esac
    shift
done

# --- Root check ---
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root. Use 'sudo bash uninstall-madmin.sh'"
    exit 1
fi

# --- Confirmation ---
echo ""
log_warning "This will REMOVE the MADMIN installation:"
echo "  - systemd services: madmin.service, madmin-firewall-boot.service"
echo "  - Nginx site: /etc/nginx/sites-available/madmin.conf"
echo "  - firewall persistence in /etc/iptables (rules.v4, ipsets.conf) and"
echo "    the running ruleset will be FLUSHED and policies reset to ACCEPT"
echo "  - sysctl drop-in: /etc/sysctl.d/99-madmin.conf"
if [ "$KEEP_DB" = "true" ]; then
    echo "  - PostgreSQL DB/user: KEPT (--keep-db)"
else
    echo "  - PostgreSQL database '$DB_NAME' and user '$DB_USER' (ALL DATA LOST)"
fi
echo "  - install directory: $INSTALL_DIR"
if [ "$PURGE_PACKAGES" = "true" ]; then
    echo "  - apt packages: PURGED (--purge-packages)"
fi
echo ""

if [ "$ASSUME_YES" != "true" ]; then
    read -r -p "Type 'yes' to continue: " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        log_info "Aborted. Nothing was changed."
        exit 0
    fi
fi

# --- Step 1: Stop and remove systemd services ---
log_info "Step 1/7: Removing systemd services..."

for svc in madmin.service madmin-firewall-boot.service; do
    systemctl stop "$svc" 2>/dev/null || true
    systemctl disable "$svc" 2>/dev/null || true
    rm -f "/etc/systemd/system/$svc"
done
systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true
log_success "Systemd services removed."

# --- Step 2: Remove Nginx site ---
log_info "Step 2/7: Removing Nginx site configuration..."

rm -f /etc/nginx/sites-enabled/madmin.conf
rm -f /etc/nginx/sites-available/madmin.conf

# setup-madmin.sh deletes the default site; restore it if the sample exists
# and no other enabled site remains, so nginx still has something to serve.
if [ ! -e /etc/nginx/sites-enabled/default ] && [ -f /etc/nginx/sites-available/default ]; then
    ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
    log_info "Restored the default Nginx site."
fi

if command -v nginx >/dev/null 2>&1; then
    if nginx -t 2>/dev/null; then
        systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null || true
    else
        log_warning "nginx -t failed after removing the MADMIN site; check the config manually."
    fi
fi
log_success "Nginx site removed."

# --- Step 3: Reset the firewall (CRITICAL) ---
# The fail-closed boot guard persists an INPUT/FORWARD DROP policy in
# /etc/iptables/rules.v4. Leaving it after removing madmin would lock the host
# out on the next reboot (nothing rebuilds the ACCEPT ruleset). Flush now and
# drop the persisted files.
log_info "Step 3/7: Resetting firewall to a clean, open state..."

if command -v iptables >/dev/null 2>&1; then
    iptables -P INPUT ACCEPT
    iptables -P FORWARD ACCEPT
    iptables -P OUTPUT ACCEPT
    iptables -t nat -F 2>/dev/null || true
    iptables -t mangle -F 2>/dev/null || true
    iptables -F 2>/dev/null || true
    iptables -X 2>/dev/null || true
fi

# Destroy any MADMIN/module ipsets, then all remaining sets (best effort).
if command -v ipset >/dev/null 2>&1; then
    ipset flush 2>/dev/null || true
    ipset destroy 2>/dev/null || true
fi

rm -f /etc/iptables/rules.v4 /etc/iptables/ipsets.conf

# Persist the clean state so a stray netfilter-persistent run can't reload stale
# DROP rules (the file was just deleted, so save an explicit ACCEPT ruleset).
if command -v netfilter-persistent >/dev/null 2>&1; then
    netfilter-persistent save 2>/dev/null || true
fi
log_success "Firewall reset (policies ACCEPT, persisted rules removed)."

# --- Step 4: Remove PostgreSQL database and user ---
if [ "$KEEP_DB" = "true" ]; then
    log_info "Step 4/7: Keeping PostgreSQL database (--keep-db)."
else
    log_info "Step 4/7: Dropping PostgreSQL database and user..."
    if command -v psql >/dev/null 2>&1; then
        # Terminate open connections so DROP DATABASE doesn't block.
        sudo -u postgres psql -c \
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB_NAME';" \
            >/dev/null 2>&1 || true
        sudo -u postgres psql -c "DROP DATABASE IF EXISTS $DB_NAME;" 2>/dev/null \
            || log_warning "Could not drop database $DB_NAME."
        sudo -u postgres psql -c "DROP ROLE IF EXISTS $DB_USER;" 2>/dev/null \
            || log_warning "Could not drop role $DB_USER."
        log_success "PostgreSQL database and user removed."
    else
        log_warning "psql not found; skipping database removal."
    fi
fi

# --- Step 5: Remove sysctl drop-in ---
log_info "Step 5/7: Removing IP-forwarding sysctl drop-in..."
rm -f /etc/sysctl.d/99-madmin.conf
# Reload sysctl so ip_forward reverts (unless another drop-in sets it).
sysctl --system >/dev/null 2>&1 || true
log_success "sysctl drop-in removed."

# --- Step 6: Remove the install directory ---
log_info "Step 6/7: Removing $INSTALL_DIR..."
rm -rf "$INSTALL_DIR"
log_success "Install directory removed."

# --- Step 7: Optionally purge apt packages ---
if [ "$PURGE_PACKAGES" = "true" ]; then
    log_info "Step 7/7: Purging apt packages installed by setup..."
    log_warning "This removes shared packages (nginx, postgresql, ...). Skip with"
    log_warning "no --purge-packages if other software on this host needs them."
    DEBIAN_FRONTEND=noninteractive apt-get purge -y \
        postgresql postgresql-contrib \
        nginx \
        iptables-persistent ipset conntrack \
        2>/dev/null || log_warning "Some packages could not be purged."
    apt-get autoremove -y 2>/dev/null || true
    log_success "Packages purged."
else
    log_info "Step 7/7: Leaving apt packages installed (use --purge-packages to remove)."
fi

# --- Done ---
echo ""
log_success "=========================================="
log_success "   MADMIN UNINSTALLED"
log_success "=========================================="
echo ""
echo "You can now reinstall a fresh version:"
echo "  sudo bash scripts/setup-madmin.sh"
echo ""
if [ "$KEEP_DB" = "true" ]; then
    echo "NOTE: the PostgreSQL database was kept. A reinstall will reuse it."
    echo "      Drop it manually for a truly clean install if needed."
    echo ""
fi

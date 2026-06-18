#!/bin/bash
# MADMIN fail-closed firewall boot guard.
#
# Runs BEFORE the network is configured (network-pre.target) and before madmin
# starts. It blocks every inbound and forwarded packet so nothing reaches the VM
# until the authoritative firewall is loaded by madmin (which rebuilds the full
# ruleset from the database at startup).
#
# Recovery, if madmin never starts (e.g. crash loop), is via the HYPERVISOR
# CONSOLE ONLY — there is intentionally no SSH lifeline. From the console, fix
# madmin and let it reapply, or restore the last-saved ruleset by hand:
#   ipset restore -exist < /etc/iptables/ipsets.conf
#   iptables-restore < /etc/iptables/rules.v4
set -u

IPSETS=/etc/iptables/ipsets.conf

# 1) Fail-closed default policy. OUTPUT stays ACCEPT so madmin can reach the
#    local PostgreSQL socket, DNS and the geoip download endpoint once it runs.
iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT ACCEPT

# Clear only the built-in chains of any stale ACCEPT rules. MADMIN_* and module
# chains are (re)built by madmin via apply_rules(); we never touch them here.
iptables -F INPUT
iptables -F FORWARD

# Minimal survival rules — no ipset references, so they load even if ipsets.conf
# is missing: loopback and already-established flows (none exist this early, but
# harmless and keeps the boot unit's own OUTPUT replies working).
iptables -A INPUT -i lo -j ACCEPT
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# 2) Restore persisted ipsets so that, once madmin applies its --match-set rules,
#    the backing sets already hold their last-good contents (shrinks the window
#    where geo/fqdn sets are empty). -exist tolerates sets already present.
if [ -f "$IPSETS" ]; then
    ipset restore -exist < "$IPSETS" || true
fi

exit 0

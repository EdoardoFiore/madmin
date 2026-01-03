#!/bin/bash
# Abilita IP forwarding per routing VPN e NAT

echo "Abilitazione IP Forwarding..."

# Abilita temporaneamente
sysctl -w net.ipv4.ip_forward=1

# Rendi persistente
if ! grep -q "net.ipv4.ip_forward = 1" /etc/sysctl.conf; then
    echo "net.ipv4.ip_forward = 1" >> /etc/sysctl.conf
fi

echo "IP Forwarding abilitato."

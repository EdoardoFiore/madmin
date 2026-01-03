#!/bin/bash
# Ripristina le regole iptables salvate

RULES_DIR="/etc/iptables"

if [ -f "$RULES_DIR/rules.v4" ]; then
    iptables-restore < $RULES_DIR/rules.v4
    echo "Regole IPv4 ripristinate."
else
    echo "File regole IPv4 non trovato."
fi

if [ -f "$RULES_DIR/rules.v6" ]; then
    ip6tables-restore < $RULES_DIR/rules.v6
    echo "Regole IPv6 ripristinate."
fi

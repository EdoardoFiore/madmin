#!/bin/bash
# Salva le regole iptables correnti

RULES_DIR="/etc/iptables"
mkdir -p $RULES_DIR

iptables-save > $RULES_DIR/rules.v4
ip6tables-save > $RULES_DIR/rules.v6 2>/dev/null || true

echo "Regole iptables salvate in $RULES_DIR"

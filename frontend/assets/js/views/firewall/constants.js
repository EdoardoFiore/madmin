/**
 * MADMIN - Firewall View / shared constants
 */

import { t } from '../../i18n.js';

// Sentinel comment marking the protected managed-LAN MASQUERADE rule (mirrors backend)
export const MANAGED_NAT_SENTINEL = 'MADMIN_MANAGED_LAN_NAT';

// Column definitions
export const ALL_COLUMNS = {
    protocol: { get label() { return t('firewall.columnLabels.protocol'); } },
    source: { get label() { return t('firewall.columnLabels.source'); } },
    destination: { get label() { return t('firewall.columnLabels.destination'); } },
    port: { get label() { return t('firewall.columnLabels.port'); } },
    state: { get label() { return t('firewall.columnLabels.state'); } },
    in_interface: { get label() { return t('firewall.columnLabels.in_interface'); } },
    out_interface: { get label() { return t('firewall.columnLabels.out_interface'); } },
    to_destination: { get label() { return t('firewall.columnLabels.to_destination'); }, tables: ['nat'] },
    to_source: { get label() { return t('firewall.columnLabels.to_source'); }, tables: ['nat'] },
    to_ports: { get label() { return t('firewall.columnLabels.to_ports'); }, tables: ['nat'] },
    log_prefix: { get label() { return t('firewall.columnLabels.log_prefix'); } },
    limit_rate: { get label() { return t('firewall.columnLabels.limit_rate'); } },
    comment: { get label() { return t('firewall.columnLabels.comment'); } }
};

export const DEFAULT_COLUMNS = {
    filter: ['protocol', 'source', 'destination', 'port', 'state', 'comment'],
    nat: ['protocol', 'source', 'destination', 'port', 'to_destination', 'to_source', 'comment'],
    mangle: ['protocol', 'source', 'destination', 'port', 'state', 'comment'],
    raw: ['protocol', 'source', 'destination', 'port', 'state', 'comment']
};

// Table definitions with their chains
export const TABLES = {
    filter: { label: 'Filter', chains: ['INPUT', 'OUTPUT', 'FORWARD'], icon: 'shield' },
    nat: { label: 'NAT', chains: ['PREROUTING', 'POSTROUTING', 'OUTPUT'], icon: 'arrows-exchange' },
    mangle: { label: 'Mangle', chains: ['PREROUTING', 'INPUT', 'FORWARD', 'OUTPUT', 'POSTROUTING'], icon: 'adjustments' },
    raw: { label: 'Raw', chains: ['PREROUTING', 'OUTPUT'], icon: 'bolt' }
};

// Actions available per table
export const TABLE_ACTIONS = {
    filter: ['ACCEPT', 'DROP', 'REJECT', 'LOG'],
    nat: ['SNAT', 'DNAT', 'MASQUERADE', 'REDIRECT', 'ACCEPT'],
    mangle: ['MARK', 'TOS', 'TTL', 'ACCEPT'],
    raw: ['NOTRACK', 'ACCEPT']
};

// Hook (chain) in cui ciascun match/azione è valido per netfilter.
export const IN_IFACE_VALID_CHAINS = ['PREROUTING', 'INPUT', 'FORWARD'];
export const OUT_IFACE_VALID_CHAINS = ['POSTROUTING', 'OUTPUT', 'FORWARD'];
export const NAT_ACTION_VALID_CHAINS = {
    DNAT: ['PREROUTING', 'OUTPUT'],
    REDIRECT: ['PREROUTING', 'OUTPUT'],
    SNAT: ['POSTROUTING'],
    MASQUERADE: ['POSTROUTING'],
};

// Virtual interface prefixes to exclude from the gateway LAN list (mirrors backend filter)
export const GW_VIRTUAL_PREFIXES = ['lo', 'wg', 'veth', 'docker', 'br-', 'virbr', 'tun', 'tap'];
export const GW_WAN_IFACE = 'eth0';

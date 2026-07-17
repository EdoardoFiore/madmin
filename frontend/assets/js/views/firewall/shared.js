/**
 * MADMIN - Firewall shared helpers
 *
 * Constants and small helpers shared by the Standard view, the rule editor and
 * the Advanced (power-user) view.
 */
import { t } from '../../i18n.js';

// Sentinel comment marking the protected managed-LAN navigation NAT policy
// (mirrors backend core/provisioning/service.py MANAGED_NAT_SENTINEL). The rule
// is now a filter/FORWARD ACCEPT with policy_nat=True (not a standalone
// POSTROUTING MASQUERADE).
export const MANAGED_NAT_SENTINEL = 'MADMIN_MANAGED_LAN_NAT';

// Netfilter hook (chain) validity, mirrors the backend denylist. Used to
// validate the editor before submit.
export const IN_IFACE_VALID_CHAINS = ['PREROUTING', 'INPUT', 'FORWARD'];
export const OUT_IFACE_VALID_CHAINS = ['POSTROUTING', 'OUTPUT', 'FORWARD'];
export const NAT_ACTION_VALID_CHAINS = {
    DNAT: ['PREROUTING', 'OUTPUT'],
    REDIRECT: ['PREROUTING', 'OUTPUT'],
    SNAT: ['POSTROUTING'],
    MASQUERADE: ['POSTROUTING'],
};

// Valid chains per table, mirrors the backend _TABLE_CHAINS
// (GW_EXCEPTIONS is the virtual filter chain).
export const TABLE_CHAINS = {
    filter: ['INPUT', 'OUTPUT', 'FORWARD', 'GW_EXCEPTIONS'],
    nat: ['PREROUTING', 'POSTROUTING', 'OUTPUT'],
    mangle: ['PREROUTING', 'INPUT', 'FORWARD', 'OUTPUT', 'POSTROUTING'],
    raw: ['PREROUTING', 'OUTPUT'],
};

// Common service presets for the editor's quick service picker.
export const SERVICE_PRESETS = [
    { label: 'HTTP', protocol: 'tcp', port: '80' },
    { label: 'HTTPS', protocol: 'tcp', port: '443' },
    { label: 'SSH', protocol: 'tcp', port: '22' },
    { label: 'DNS', protocol: 'udp', port: '53' },
    { label: 'RDP', protocol: 'tcp', port: '3389' },
    { label: 'SMTP', protocol: 'tcp', port: '25' },
];

/** Human label for a rule's service (protocol + port). The engine only emits
 * --dport for tcp/udp (iptables.py build_rule_args), so a port set on any
 * other protocol is dead data and must not be shown as if it mattered. */
export function serviceLabel(rule) {
    if (!rule.protocol) return 'ALL';
    const proto = rule.protocol.toUpperCase();
    const portActive = rule.port && (rule.protocol === 'tcp' || rule.protocol === 'udp');
    return portActive ? `${proto}/${rule.port}` : proto;
}

/** True for synthetic, read-only companion rows produced by the backend. */
export function isAutoRow(rule) {
    return !!rule.auto_generated
        || (typeof rule.id === 'string' && rule.id.startsWith('auto-'));
}

/** True for the protected managed navigation-NAT policy. */
export function isManagedNat(rule) {
    return rule.comment === MANAGED_NAT_SENTINEL;
}

// Actions each Standard editor mode knows how to render/save. A rule whose
// action falls outside its mode's set (e.g. a LOG policy, a REDIRECT port
// forward, an ACCEPT/RETURN outbound-NAT exemption created from Advanced)
// must never be opened for edit there: the mode's fixed action set would
// silently coerce it into something else on save.
export const STD_EDITABLE_ACTIONS = {
    policy: ['ACCEPT', 'DROP', 'REJECT'],
    portforward: ['DNAT'],
    outnat: ['MASQUERADE', 'SNAT'],
};

/** True when a rule's action isn't one the given Standard editor mode can represent. */
export function isLockedForMode(rule, mode) {
    const set = STD_EDITABLE_ACTIONS[mode];
    return !!set && !set.includes(rule.action);
}

/**
 * Validate a rule's field/chain (hook) compatibility client-side, mirroring the
 * backend. Returns a translated error string, or null if valid.
 */
export function validateRuleConstraints(data) {
    const chain = data.chain;
    const table = data.table_name || 'filter';
    const chains = TABLE_CHAINS[table];
    if (chains && !chains.includes(chain)) {
        return t('firewall.validation.tableChain', { chain, table });
    }
    if (data.in_interface && !IN_IFACE_VALID_CHAINS.includes(chain)) {
        return t('firewall.validation.inIfaceHook', { chain });
    }
    if (data.out_interface && !OUT_IFACE_VALID_CHAINS.includes(chain)) {
        return t('firewall.validation.outIfaceHook', { chain });
    }
    const validChains = NAT_ACTION_VALID_CHAINS[data.action];
    if (validChains && !validChains.includes(chain)) {
        return t('firewall.validation.natActionHook', { action: data.action, chain });
    }
    return null;
}

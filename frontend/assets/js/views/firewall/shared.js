/**
 * MADMIN - Firewall shared helpers
 *
 * Constants and small helpers shared by the Standard view, the rule editor and
 * the Advanced (power-user) view.
 */
import { escapeHtml, confirmDialog, showToast } from '../../utils.js';
import { apiPost } from '../../api.js';
import { t } from '../../i18n.js';

// Sentinel comment marking the protected managed-LAN navigation NAT policy
// (mirrors backend core/provisioning/service.py MANAGED_NAT_SENTINEL). The rule
// is now a filter/FORWARD ACCEPT with policy_nat=True (not a standalone
// POSTROUTING MASQUERADE).
export const MANAGED_NAT_SENTINEL = 'MADMIN_MANAGED_LAN_NAT';

// Netfilter hook (chain) validity, mirrors the backend denylist
// (router.py _IN_IFACE_VALID / _OUT_IFACE_VALID). Used to validate the editor
// before submit. The denylist is permissive by design: it blocks only
// known-incompatible combos and lets everything else through to iptables,
// which rejects any truly-invalid combination at apply time. Keep in exact
// sync with the backend — a mismatch either blocks a rule the engine accepts
// or lets through one it will reject on apply.
export const IN_IFACE_VALID_CHAINS = ['PREROUTING', 'INPUT', 'FORWARD', 'POSTROUTING'];
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
/** HTML-safe "TCP/443" label (the result goes straight into markup). */
export function serviceLabel(rule) {
    if (!rule.protocol) return 'ALL';
    const proto = escapeHtml(rule.protocol.toUpperCase());
    const portActive = rule.port && (rule.protocol === 'tcp' || rule.protocol === 'udp');
    return portActive ? `${proto}/${escapeHtml(rule.port)}` : proto;
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

// A plain uuid for a real DB rule, or the uuid embedded at the end of a
// synthetic companion id (e.g. "auto-nat-<uuid>", "auto-hairpin-fwd-<uuid>"
// — see router.py _auto_*_response). GET /firewall/counters keys its rows by
// the owning DB rule's uuid (every kernel line a rule expands to — the rule
// itself plus any auto-generated companion — shares one comment-tag uuid and
// is summed together, see iptables.read_rule_counters), so resolving a
// companion row back to that same uuid lets its counter icon show the
// policy's combined total instead of nothing. Returns null for the one
// synthetic row with no uuid at all (auto-implicit-deny).
const UUID_RE = /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/;
export function counterRuleId(rule) {
    if (!isAutoRow(rule)) return rule.id;
    const m = UUID_RE.exec(rule.id);
    return m ? m[0] : null;
}

// Actions each Standard editor mode knows how to render/save. A rule whose
// action falls outside its mode's set (e.g. a LOG policy, a REDIRECT port
// forward) must never be opened for edit there: the mode's fixed action set
// would silently coerce it into something else on save. Outbound NAT has no
// Standard mode: it belongs to the policies (nat/POSTROUTING rules are
// Advanced-only overrides).
export const STD_EDITABLE_ACTIONS = {
    policy: ['ACCEPT', 'DROP', 'REJECT'],
    portforward: ['DNAT'],
};

/** NAT cell of a forward policy: none, the interface address, or a specific one. */
export function natBadge(rule) {
    if (!rule.policy_nat) return '<span class="text-muted">—</span>';
    const warn = rule.nat_warning === 'ip_not_local'
        ? `<span class="badge bg-red-lt ms-1" title="${escapeHtml(t('firewall.nat.ipNotLocalHint'))}">
               <i class="ti ti-alert-triangle me-1"></i>${escapeHtml(t('firewall.nat.ipNotLocal'))}</span>`
        : '';
    if (rule.to_source) {
        return `<span class="badge bg-green-lt" title="${escapeHtml(t('firewall.nat.snatHint'))}">
            <i class="ti ti-arrows-exchange me-1"></i>${escapeHtml(rule.to_source)}</span>${warn}`;
    }
    return `<span class="badge bg-green-lt" title="${escapeHtml(t('firewall.nat.masqHint'))}">
        <i class="ti ti-arrows-exchange me-1"></i>${escapeHtml(t('firewall.nat.ifaceAddrShort'))}</span>`;
}

/** True when a rule's action isn't one the given Standard editor mode can represent. */
export function isLockedForMode(rule, mode) {
    const set = STD_EDITABLE_ACTIONS[mode];
    return !!set && !set.includes(rule.action);
}

/** True when a rule carries a match/behavior the Standard editor never shows
 * or edits (connection state, rate limiting, logging) — set only from
 * Advanced, but silently preserved (not stripped) when the rule is saved
 * again from Standard. Used to flag such rows so they don't look narrower
 * than they really are. */
export function hasAdvancedMatch(rule) {
    return !!(rule.state || rule.limit_rate || rule.log_prefix);
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

// ---------------------------------------------------------------------------
// filter/FORWARD interface-pair groups (backend: ForwardSection)
// ---------------------------------------------------------------------------

/** Group key of a forward rule or section; "*" = any interface. */
export function pairKey(inIf, outIf) {
    return `${inIf || '*'}|${outIf || '*'}`;
}

/** Can two interface matches see the same packet? (iptables "eth+" = prefix) */
function ifaceOverlap(a, b) {
    if (a === '*' || b === '*') return true;
    const pa = a.endsWith('+') ? a.slice(0, -1) : null;
    const pb = b.endsWith('+') ? b.slice(0, -1) : null;
    if (pa !== null && pb !== null) return pa.startsWith(pb) || pb.startsWith(pa);
    if (pa !== null) return b.startsWith(pa);
    if (pb !== null) return a.startsWith(pb);
    return a === b;
}

/** True when some packet could be evaluated by both groups. */
export function pairsOverlap(k1, k2) {
    const [i1, o1] = k1.split('|');
    const [i2, o2] = k2.split('|');
    return ifaceOverlap(i1, i2) && ifaceOverlap(o1, o2);
}

/**
 * Forward policies grouped by pair, in evaluation order: the section order
 * from GET /firewall/sections (the order of the MADMIN_FORWARD jumps), pairs
 * the backend has not synced yet last. Empty groups are dropped.
 */
export function groupBySections(policies, sections) {
    const groups = new Map();
    for (const s of sections || []) groups.set(pairKey(s.in_interface, s.out_interface), []);
    for (const r of policies) {
        const k = pairKey(r.in_interface, r.out_interface);
        if (!groups.has(k)) groups.set(k, []);
        groups.get(k).push(r);
    }
    for (const [k, list] of groups) if (!list.length) groups.delete(k);
    return groups;
}

// ---------------------------------------------------------------------------
// Closing the sessions a DROP/REJECT rule would now stop
// ---------------------------------------------------------------------------

/**
 * Preview, confirm, close. The backend simulates the chain for every tracked
 * connection and only closes those this rule is the first to decide: anything
 * an earlier rule accepts, anything uncertain and the admin's own connections
 * stay up. Nothing is closed without the confirm showing what will be.
 */
export async function terminateSessions(rule) {
    let preview;
    try {
        preview = await apiPost(`/firewall/rules/${rule.id}/flush-conntrack`, { dry_run: true });
    } catch (err) {
        showToast(t('common.errorPrefix') + err.message, 'error');
        return;
    }
    const kept = [];
    if (preview.shadowed) kept.push(t('firewall.sessions.keptShadowed', { n: preview.shadowed }));
    if (preview.uncertain) kept.push(t('firewall.sessions.keptUncertain', { n: preview.uncertain }));
    if (preview.protected) kept.push(t('firewall.sessions.keptProtected', { n: preview.protected }));

    if (!preview.close) {
        showToast([t('firewall.noActiveSessions'), ...kept].join(' '), 'info');
        return;
    }
    const rows = preview.samples.map(f => `
        <tr>
            <td>${escapeHtml(f.proto)}</td>
            <td><code>${escapeHtml(f.src)}${f.sport ? ':' + escapeHtml(f.sport) : ''}</code></td>
            <td><code>${escapeHtml(f.to || f.dst)}${f.dport ? ':' + escapeHtml(f.dport) : ''}</code></td>
        </tr>`).join('');
    const html = `
        <p>${escapeHtml(t('firewall.sessions.willClose', { n: preview.close, action: rule.action }))}</p>
        <div class="table-responsive mb-2">
            <table class="table table-sm table-vcenter card-table">
                <thead><tr><th>${escapeHtml(t('firewall.protocol'))}</th>
                    <th>${escapeHtml(t('firewall.source'))}</th><th>${escapeHtml(t('firewall.destination'))}</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
        ${preview.close > preview.samples.length
            ? `<div class="text-muted small mb-2">${escapeHtml(t('firewall.sessions.andMore', { n: preview.close - preview.samples.length }))}</div>` : ''}
        ${kept.map(k => `<div class="text-muted small"><i class="ti ti-shield-check me-1"></i>${escapeHtml(k)}</div>`).join('')}`;
    const ok = await confirmDialog(t('firewall.terminateSessionsTitle'), html, t('firewall.terminateBtn'),
                                   'btn-warning', true, 'lg');
    if (!ok) return;
    try {
        const res = await apiPost(`/firewall/rules/${rule.id}/flush-conntrack`, { dry_run: false });
        showToast(res.deleted === 1 ? t('firewall.sessionTerminated')
                                    : t('firewall.sessionsTerminated', { count: res.deleted }), 'success');
    } catch (err) {
        showToast(t('common.errorPrefix') + err.message, 'error');
    }
}

/**
 * Badge for a rule an earlier rule makes useless (backend: shadow.py):
 * shadowed = an earlier rule takes the opposite decision, this one never
 * applies; duplicate / redundant = the same decision is already taken above.
 */
export function shadowBadge(rule) {
    if (!rule.shadow_kind) return '';
    const n = rule.shadowed_by_seq;
    const map = {
        shadowed: ['bg-red-lt', 'ti-eye-off', 'firewall.shadow.shadowed', 'firewall.shadow.shadowedHint'],
        duplicate: ['bg-orange-lt', 'ti-copy', 'firewall.shadow.duplicate', 'firewall.shadow.duplicateHint'],
        redundant: ['bg-yellow-lt', 'ti-arrow-bar-to-up', 'firewall.shadow.redundant', 'firewall.shadow.redundantHint'],
    };
    const [cls, icon, label, hint] = map[rule.shadow_kind] || map.shadowed;
    return `<span class="badge ${cls} ms-1" title="${escapeHtml(t(hint, { n }))}">
        <i class="ti ${icon} me-1"></i>${escapeHtml(t(label, { n }))}</span>`;
}

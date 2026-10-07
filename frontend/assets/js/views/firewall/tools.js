/**
 * MADMIN - Firewall tools: packet tracer, iptables preview, traffic sparklines.
 *
 * Both tools open in a right-hand side panel over the current view; they hold
 * no unsaved state, so clicking outside or Esc simply closes them.
 */
import { apiGet, apiPost } from '../../api.js';
import { showToast, escapeHtml, actionBadge, copyButton } from '../../utils.js';
import { t } from '../../i18n.js';
import { loadInterfaces, interfaceSelect } from './interfaces.js';

/** A side panel appended to <body>, removed once hidden. */
function openSidePanel({ title, icon, body, width = 'min(760px, 96vw)', onShown }) {
    const el = document.createElement('div');
    el.className = 'offcanvas offcanvas-end';
    el.tabIndex = -1;
    el.style.width = width;
    el.innerHTML = `
        <div class="offcanvas-header border-bottom">
            <h3 class="offcanvas-title"><i class="ti ${icon} me-2"></i>${escapeHtml(title)}</h3>
            <button type="button" class="btn-close" data-bs-dismiss="offcanvas" aria-label="${escapeHtml(t('common.close'))}"></button>
        </div>
        <div class="offcanvas-body">${body}</div>`;
    document.body.appendChild(el);
    const oc = bootstrap.Offcanvas.getOrCreateInstance(el, { backdrop: true, keyboard: true });
    el.addEventListener('hidden.bs.offcanvas', () => { oc.dispose(); el.remove(); });
    window.addEventListener('hashchange', () => oc.hide(), { once: true });
    if (onShown) el.addEventListener('shown.bs.offcanvas', () => onShown(el), { once: true });
    oc.show();
    return { el, oc };
}

/** Scroll to a rule's row in the current view and flash it. */
function highlightRule(ruleId, seq) {
    const row = document.querySelector(`tr[data-id="${CSS.escape(ruleId)}"]`);
    if (!row) {
        showToast(t('firewall.trace.ruleNotInView', { seq: seq ?? '?' }), 'info');
        return;
    }
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    row.classList.add('fw-row-flash');
    setTimeout(() => row.classList.remove('fw-row-flash'), 2500);
}

// ---------------------------------------------------------------------------
// Packet tracer
// ---------------------------------------------------------------------------

/** advanced: also show engine details (chain names) in the result. */
export async function openTracer({ advanced = false } = {}) {
    await loadInterfaces();
    const body = `
        <p class="text-muted small">${t('firewall.trace.intro')}</p>
        <form id="tr-form" class="row g-3" autocomplete="off">
            <div class="col-md-3">
                <label class="form-label">${t('firewall.protocol')}</label>
                <select class="form-select" id="tr-proto">
                    <option value="tcp">TCP</option><option value="udp">UDP</option><option value="icmp">ICMP</option>
                </select>
            </div>
            <div class="col-md-5">
                <label class="form-label required">${t('firewall.source')}</label>
                <input class="form-control" id="tr-src" placeholder="192.168.1.10" required>
            </div>
            <div class="col-md-4" id="tr-port-wrap">
                <label class="form-label">${t('firewall.trace.dport')}</label>
                <input class="form-control" id="tr-port" type="number" min="1" max="65535" placeholder="443">
            </div>
            <div class="col-md-5 offset-md-3">
                <label class="form-label required">${t('firewall.destination')}</label>
                <input class="form-control" id="tr-dst" placeholder="8.8.8.8" required>
            </div>
            <div class="col-md-6">
                <label class="form-label">${t('firewall.trace.inIface')}</label>
                ${interfaceSelect('tr-in', '', { anyLabel: t('firewall.trace.auto') })}
            </div>
            <div class="col-md-6">
                <label class="form-label">${t('firewall.trace.outIface')}</label>
                ${interfaceSelect('tr-out', '', { anyLabel: t('firewall.trace.auto') })}
            </div>
            <div class="col-12 text-end">
                <button class="btn btn-primary" type="submit"><i class="ti ti-route me-1"></i>${t('firewall.trace.run')}</button>
            </div>
        </form>
        <div id="tr-result" class="mt-4"></div>`;
    openSidePanel({
        title: t('firewall.trace.title'), icon: 'ti-route', body,
        onShown: (el) => {
            el.querySelector('#tr-src').focus();
            el.querySelector('#tr-proto').addEventListener('change', (e) => {
                el.querySelector('#tr-port-wrap').classList.toggle('invisible', e.target.value === 'icmp');
            });
            el.querySelector('#tr-form').addEventListener('submit', (e) => {
                e.preventDefault();
                runTrace(el, advanced);
            });
        },
    });
}

async function runTrace(el, advanced) {
    const proto = el.querySelector('#tr-proto').value;
    const port = el.querySelector('#tr-port').value;
    const payload = {
        protocol: proto,
        source: el.querySelector('#tr-src').value.trim(),
        destination: el.querySelector('#tr-dst').value.trim(),
        dport: proto !== 'icmp' && port ? parseInt(port) : null,
        in_interface: el.querySelector('#tr-in').value || null,
        out_interface: el.querySelector('#tr-out').value || null,
    };
    const out = el.querySelector('#tr-result');
    out.innerHTML = '<div class="text-center py-3"><span class="spinner-border spinner-border-sm"></span></div>';
    let res;
    try {
        res = await apiPost('/firewall/trace', payload);
    } catch (err) {
        out.innerHTML = `<div class="alert alert-danger">${escapeHtml(err.message)}</div>`;
        return;
    }
    out.innerHTML = traceResultHtml(res, advanced);
    out.querySelectorAll('[data-goto-rule]').forEach(a => a.addEventListener('click', (e) => {
        e.preventDefault();
        highlightRule(a.dataset.gotoRule, a.dataset.seq);
    }));
}

function traceResultHtml(res, advanced) {
    const d = res.decision;
    const ruleLink = (id, seq) => `<a href="#" data-goto-rule="${escapeHtml(id)}" data-seq="${escapeHtml(seq ?? '')}">#${escapeHtml(seq ?? '?')}</a>`;
    let verdict;
    if (d.rule_id) {
        verdict = t('firewall.trace.decidedBy', { rule: '§', action: escapeHtml(d.action) }).replace('§', ruleLink(d.rule_id, d.seq));
    } else {
        verdict = escapeHtml(t(`firewall.trace.auto_${d.auto}`));
    }
    const ok = d.action === 'ACCEPT';
    const steps = res.steps.map(s => `
        <tr class="${s.result === 'match' ? 'table-active' : ''}">
            <td>${ruleLink(s.rule_id, s.seq)}</td>
            <td>${actionBadge(s.action)}</td>
            <td>${s.result === 'match'
                ? `<span class="badge bg-green-lt">${t('firewall.trace.match')}</span>`
                : s.result === 'unknown'
                    ? `<span class="badge bg-yellow-lt">${t('firewall.trace.unknown')}</span>`
                    : `<span class="text-muted">${t('firewall.trace.noMatch')}</span>`}</td>
        </tr>`).join('');
    const notes = (res.notes || []).map(n => `<div class="text-muted small"><i class="ti ti-info-circle me-1"></i>${escapeHtml(t(`firewall.trace.note_${n}`))}</div>`).join('');
    return `
        <div class="alert ${ok ? 'alert-success' : 'alert-danger'}">
            <div class="d-flex align-items-center gap-2">
                <i class="ti ${ok ? 'ti-circle-check' : 'ti-ban'} fs-2"></i>
                <div><strong>${escapeHtml(d.action)}</strong> — ${verdict}</div>
            </div>
        </div>
        <dl class="row small mb-3">
            ${advanced ? `<dt class="col-4">${t('firewall.trace.chain')}</dt><dd class="col-8"><code>${escapeHtml(res.chain)}</code></dd>` : ''}
            <dt class="col-4">${t('firewall.trace.interfaces')}</dt>
            <dd class="col-8"><code>${escapeHtml(res.in_interface || '?')}</code>${res.out_interface ? ` → <code>${escapeHtml(res.out_interface)}</code>` : ''}</dd>
            ${res.dnat ? `<dt class="col-4">${t('firewall.trace.portForward')}</dt>
                <dd class="col-8">${ruleLink(res.dnat.rule_id, '')} ${escapeHtml(res.dnat.action)} ${res.dnat.to ? `→ <code>${escapeHtml(res.dnat.to)}</code>` : ''}</dd>` : ''}
            ${res.snat ? `<dt class="col-4">${t('firewall.trace.leavesAs')}</dt>
                <dd class="col-8">${snatHtml(res.snat, ruleLink)}</dd>` : ''}
        </dl>
        ${res.steps.length ? `
        <div class="table-responsive">
            <table class="table table-sm table-vcenter card-table">
                <thead><tr><th>#</th><th>${t('firewall.action')}</th><th>${t('firewall.trace.result')}</th></tr></thead>
                <tbody>${steps}</tbody>
            </table>
        </div>` : ''}
        ${notes}`;
}

/**
 * The address a forwarded connection leaves with (backend _trace_snat): the
 * first Advanced nat/POSTROUTING rule that matches, else the NAT of the
 * policy that accepted it.
 */
function snatHtml(s, ruleLink) {
    const via = s.rule_id
        ? ` <span class="text-muted">— ${escapeHtml(t(s.advanced ? 'firewall.trace.viaNatRule' : 'firewall.trace.viaPolicy'))}</span> ${ruleLink(s.rule_id, s.seq)}`
        : '';
    const ip = s.ip ? `<code>${escapeHtml(s.ip)}</code>` : '';
    switch (s.kind) {
        case 'masquerade':
            return `${ip || `<span class="text-muted">?</span>`} <span class="text-muted">(${escapeHtml(t('firewall.trace.snat_masquerade', { iface: s.interface || '?' }))})</span>${via}`;
        case 'snat':
            return `${ip}${via}`;
        case 'pool':
            return `${ip} <span class="text-muted">(${escapeHtml(t('firewall.pools.badge', { name: s.pool }))}${s.ip && s.ip.includes('-') ? ', ' + escapeHtml(t('firewall.trace.snat_poolRange')) : ''})</span>${via}`;
        case 'netmap':
            return `${ip} <span class="text-muted">(${escapeHtml(t('firewall.pools.badge', { name: s.pool }))}, ${escapeHtml(t('firewall.pools.type_one_to_one'))})</span>${via}`;
        case 'unknown':
            return `<span class="text-warning">${escapeHtml(t('firewall.trace.snat_unknown'))}</span>${via}`;
        default:
            return `<span class="text-muted">${escapeHtml(t('firewall.trace.snat_none'))}</span>${via}`;
    }
}

// ---------------------------------------------------------------------------
// iptables preview
// ---------------------------------------------------------------------------

export async function openPreview() {
    const body = `
        <p class="text-muted small">${t('firewall.preview.intro')}</p>
        <div id="pv-content"><div class="text-center py-3"><span class="spinner-border spinner-border-sm"></span></div></div>`;
    openSidePanel({
        title: t('firewall.preview.title'), icon: 'ti-terminal-2', body, width: 'min(1000px, 96vw)',
        onShown: async (el) => {
            const content = el.querySelector('#pv-content');
            let tables;
            try {
                tables = (await apiGet('/firewall/preview')).tables || [];
            } catch (err) {
                content.innerHTML = `<div class="alert alert-danger">${escapeHtml(err.message)}</div>`;
                return;
            }
            if (!tables.length) {
                content.innerHTML = `<div class="text-muted">${t('firewall.preview.noLines')}</div>`;
                return;
            }
            // One tab per iptables table (filter, nat, mangle, raw), each with
            // its own copy button; the text filter applies to the active tab.
            content.innerHTML = `
                <ul class="nav nav-tabs mb-2" role="tablist">
                    ${tables.map((tb, i) => `
                    <li class="nav-item" role="presentation">
                        <button class="nav-link ${i === 0 ? 'active' : ''}" data-bs-toggle="tab" type="button" role="tab"
                                data-bs-target="#pv-tab-${escapeHtml(tb.table)}">
                            ${escapeHtml(tb.table)} <span class="badge bg-secondary-lt ms-1">${Number(tb.rules)}</span>
                        </button>
                    </li>`).join('')}
                </ul>
                <input type="search" class="form-control mb-2" id="pv-filter" placeholder="${escapeHtml(t('firewall.preview.filter'))}">
                <div class="tab-content">
                    ${tables.map((tb, i) => `
                    <div class="tab-pane position-relative ${i === 0 ? 'active show' : ''}" id="pv-tab-${escapeHtml(tb.table)}" role="tabpanel">
                        <div class="position-absolute top-0 end-0 m-2">${copyButton(`#pv-text-${tb.table}`, 'btn btn-icon btn-sm btn-dark')}</div>
                        <pre class="small pe-5" id="pv-text-${escapeHtml(tb.table)}" style="white-space:pre-wrap;word-break:break-all"></pre>
                    </div>`).join('')}
                </div>`;
            const filterInput = content.querySelector('#pv-filter');
            const show = () => {
                const q = filterInput.value.trim().toLowerCase();
                tables.forEach(tb => {
                    const pre = content.querySelector(`#pv-text-${CSS.escape(tb.table)}`);
                    pre.textContent = q
                        ? tb.text.split('\n').filter(l => l.toLowerCase().includes(q)).join('\n')
                        : tb.text;
                });
            };
            show();
            filterInput.addEventListener('input', show);
        },
    });
}

// ---------------------------------------------------------------------------
// Traffic sparklines
// ---------------------------------------------------------------------------

/**
 * Draw a 24h traffic sparkline inside every `.fw-spark[data-rule-id]` under
 * `root` (Tabler Sparkline, bars = bytes per hour). Rows rendered after
 * tabler.js loaded are not auto-initialised, so instances are created here.
 */
export async function renderSparklines(root) {
    const els = root?.querySelectorAll('.fw-spark[data-rule-id]');
    if (!els || !els.length || !window.tabler?.Sparkline) return;
    let series = {};
    try {
        series = (await apiGet('/firewall/counters/history?hours=24&buckets=24')).series || {};
    } catch {
        return;
    }
    els.forEach(el => {
        const values = series[el.dataset.ruleId];
        if (!values || !values.some(v => v > 0)) return;
        el.classList.add('sparkline', 'sparkline-sm');
        el.title = t('firewall.std.sparkHint');
        window.tabler.Sparkline.getOrCreateInstance(el, { type: 'bar', values, animation: 0 });
    });
}

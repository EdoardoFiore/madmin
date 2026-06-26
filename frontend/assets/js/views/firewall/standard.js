/**
 * MADMIN - Firewall Standard view
 *
 * FortiGate-style simplified view. Three areas:
 *  1. Firewall Policy   — filter/FORWARD rules grouped by interface pair (in->out),
 *                          NAT shown inline (policy_nat).
 *  2. Port Forwarding   — nat/PREROUTING DNAT rules.
 *  3. Outbound NAT      — nat/POSTROUTING SNAT/MASQUERADE (incl. read-only
 *                          policy-NAT companions and the managed nav NAT).
 */
import { apiGet, apiPatch, apiDelete } from '../../api.js';
import { showToast, confirmDialog, actionBadge, emptyState, escapeHtml } from '../../utils.js';
import { setPageActions, checkPermission } from '../../app.js';
import { t } from '../../i18n.js';
import { loadInterfaces } from './interfaces.js';
import { serviceLabel, isAutoRow, isManagedNat } from './shared.js';
import { openEditor } from './editor.js';

let rules = [];
let containerEl = null;

export async function render(container, _params = []) {
    containerEl = container;
    const canManage = checkPermission('firewall.manage');

    if (canManage) {
        setPageActions(`
            <div class="btn-list">
                <button class="btn btn-primary" id="btn-new-policy">
                    <i class="ti ti-plus me-2"></i>${t('firewall.std.newPolicy')}
                </button>
            </div>
        `);
    }

    container.innerHTML = `
        <div id="std-policy"></div>
        <div id="std-portfwd" class="mt-3"></div>
        <div id="std-outnat" class="mt-3"></div>
    `;

    document.getElementById('btn-new-policy')?.addEventListener('click',
        () => edit('policy', null));

    await loadInterfaces();
    await reload();
}

async function reload() {
    try {
        rules = await apiGet('/firewall/rules');
    } catch (e) {
        showToast(t('firewall.loadRulesError', { error: e.message }), 'error');
        rules = [];
    }
    renderPolicy();
    renderPortForward();
    renderOutboundNat();
}

/** Open the editor in-place, returning to this view on close. */
function edit(mode, rule, duplicate = false) {
    openEditor({
        container: containerEl,
        mode,
        rule,
        duplicate,
        onClose: () => { render(containerEl); },
    });
}

// ---------------------------------------------------------------------------
// 1. Firewall Policy (forward, grouped by interface pair)
// ---------------------------------------------------------------------------

function renderAddrCell(literal, refs) {
    if (refs && refs.length) {
        return refs.map(r => {
            const icon = r.kind === 'group' ? 'ti-stack-2' : 'ti-box';
            return `<span class="badge bg-azure-lt me-1"><i class="ti ${icon} me-1"></i>${escapeHtml(r.name)}</span>`;
        }).join(' ');
    }
    if (literal) return `<code>${escapeHtml(literal)}</code>`;
    return `<span class="text-muted">${t('firewall.std.anyAddr')}</span>`;
}

function natCell(rule) {
    return rule.policy_nat
        ? `<span class="badge bg-green-lt"><i class="ti ti-arrows-exchange me-1"></i>${t('firewall.std.masquerade')}</span>`
        : `<span class="text-muted">—</span>`;
}

function renderPolicy() {
    const wrap = document.getElementById('std-policy');
    const canManage = checkPermission('firewall.manage');

    const policies = rules
        .filter(r => r.table_name === 'filter' && r.chain === 'FORWARD' && !isAutoRow(r))
        .sort((a, b) => a.order - b.order);

    // Group by in->out interface pair, preserving first-seen order.
    const groups = new Map();
    for (const r of policies) {
        const key = `${r.in_interface || '*'}|${r.out_interface || '*'}`;
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(r);
    }

    const header = `
        <div class="card-header d-flex align-items-center">
            <h3 class="card-title mb-0"><i class="ti ti-arrow-guide me-2"></i>${t('firewall.std.policyTitle')}</h3>
            <span class="text-muted ms-2 small">${t('firewall.std.policyHint')}</span>
        </div>`;

    if (!policies.length) {
        wrap.innerHTML = `<div class="card">${header}<div class="card-body">${
            emptyState('ti-arrow-guide', t('firewall.std.noPolicies'), t('firewall.std.noPoliciesHint'))
        }</div></div>`;
        return;
    }

    let body = '';
    for (const [key, list] of groups) {
        const [inIf, outIf] = key.split('|');
        const pairLabel = `${inIf === '*' ? t('firewall.editor.anyInterface') : escapeHtml(inIf)}
            <i class="ti ti-arrow-right mx-1 text-muted"></i>
            ${outIf === '*' ? t('firewall.editor.anyInterface') : escapeHtml(outIf)}`;
        body += `
            <div class="fw-pair-group">
                <div class="px-3 py-2 bg-light border-top fw-pair-header d-flex align-items-center">
                    <i class="ti ti-arrows-right-left me-2 text-muted"></i>
                    <strong>${pairLabel}</strong>
                    <span class="badge bg-secondary-lt ms-2">${list.length}</span>
                </div>
                <div class="table-responsive">
                    <table class="table table-vcenter card-table mb-0">
                        <thead>
                            <tr>
                                <th style="width:42px"></th>
                                <th>${t('firewall.std.colSource')}</th>
                                <th>${t('firewall.std.colDest')}</th>
                                <th>${t('firewall.std.colService')}</th>
                                <th>${t('firewall.action')}</th>
                                <th>${t('firewall.std.colNat')}</th>
                                <th>${t('firewall.comment')}</th>
                                <th class="text-end"></th>
                            </tr>
                        </thead>
                        <tbody class="fw-sortable" data-pair="${escapeHtml(key)}">
                            ${list.map(r => policyRow(r, canManage)).join('')}
                        </tbody>
                    </table>
                </div>
            </div>`;
    }

    wrap.innerHTML = `<div class="card">${header}<div class="card-body p-0">${body}</div></div>`;

    bindRowActions(wrap, 'policy');
    if (canManage) wrap.querySelectorAll('.fw-sortable').forEach(setupDragDrop);
}

function policyRow(r, canManage) {
    const disabled = r.enabled ? '' : 'opacity-50';
    if (isManagedNat(r)) {
        return `
            <tr class="${disabled}" data-id="${r.id}">
                <td class="text-muted"><i class="ti ti-lock" title="${t('firewall.managedNatHint')}"></i></td>
                <td>${renderAddrCell(r.source, r.source_refs)}</td>
                <td>${renderAddrCell(r.destination, r.destination_refs)}</td>
                <td><span class="text-muted">${serviceLabel(r)}</span></td>
                <td>${actionBadge(r.action)}</td>
                <td>${natCell(r)}</td>
                <td><span class="badge bg-azure-lt"><i class="ti ti-lock me-1"></i>${t('firewall.managedNat')}</span></td>
                <td></td>
            </tr>`;
    }
    return `
        <tr class="${disabled} fw-drag" data-id="${r.id}" draggable="${canManage}">
            <td>${canManage ? '<i class="ti ti-grip-vertical fw-handle text-muted" style="cursor:grab"></i>' : ''}</td>
            <td>${renderAddrCell(r.source, r.source_refs)}</td>
            <td>${renderAddrCell(r.destination, r.destination_refs)}</td>
            <td><span class="text-muted">${serviceLabel(r)}</span></td>
            <td>${actionBadge(r.action)}</td>
            <td>${natCell(r)}</td>
            <td><span class="text-muted">${r.comment ? escapeHtml(r.comment) : '—'}</span></td>
            <td class="text-end">${canManage ? rowButtons() : ''}</td>
        </tr>`;
}

function rowButtons() {
    return `
        <div class="btn-group btn-group-sm">
            <button class="btn btn-ghost-secondary fw-dup" title="${t('common.copy')}"><i class="ti ti-copy"></i></button>
            <button class="btn btn-ghost-primary fw-edit" title="${t('common.edit')}"><i class="ti ti-edit"></i></button>
            <button class="btn btn-ghost-danger fw-del" title="${t('common.delete')}"><i class="ti ti-trash"></i></button>
        </div>`;
}

// ---------------------------------------------------------------------------
// 2. Port Forwarding (nat/PREROUTING DNAT)
// ---------------------------------------------------------------------------

function renderPortForward() {
    const wrap = document.getElementById('std-portfwd');
    const canManage = checkPermission('firewall.manage');

    const list = rules
        .filter(r => r.table_name === 'nat' && r.chain === 'PREROUTING'
            && ['DNAT', 'REDIRECT'].includes(r.action) && !isAutoRow(r))
        .sort((a, b) => a.order - b.order);

    const header = `
        <div class="card-header d-flex align-items-center">
            <h3 class="card-title mb-0"><i class="ti ti-arrow-bounce me-2"></i>${t('firewall.std.portFwdTitle')}</h3>
            ${canManage ? `<div class="ms-auto"><button class="btn btn-sm btn-primary" id="btn-new-portfwd">
                <i class="ti ti-plus me-1"></i>${t('firewall.std.newPortFwd')}</button></div>` : ''}
        </div>`;

    let inner;
    if (!list.length) {
        inner = `<div class="card-body">${emptyState('ti-arrow-bounce',
            t('firewall.std.noPortFwd'), t('firewall.std.noPortFwdHint'))}</div>`;
    } else {
        inner = `
            <div class="table-responsive">
                <table class="table table-vcenter card-table mb-0">
                    <thead><tr>
                        <th>${t('firewall.comment')}</th>
                        <th>${t('firewall.inInterface')}</th>
                        <th>${t('firewall.std.external')}</th>
                        <th>${t('firewall.std.internal')}</th>
                        <th class="text-end"></th>
                    </tr></thead>
                    <tbody>
                        ${list.map(r => `
                            <tr data-id="${r.id}">
                                <td>${r.comment ? escapeHtml(r.comment) : '<span class="text-muted">—</span>'}</td>
                                <td>${r.in_interface ? `<code>${escapeHtml(r.in_interface)}</code>` : `<span class="text-muted">${t('firewall.editor.anyInterface')}</span>`}</td>
                                <td><span class="badge bg-blue-lt">${serviceLabel(r)}</span></td>
                                <td><code>${escapeHtml(r.to_destination || '')}</code></td>
                                <td class="text-end">${canManage ? rowButtons() : ''}</td>
                            </tr>`).join('')}
                    </tbody>
                </table>
            </div>`;
    }

    wrap.innerHTML = `<div class="card">${header}${inner}</div>`;
    document.getElementById('btn-new-portfwd')?.addEventListener('click', () => edit('portforward', null));
    bindRowActions(wrap, 'portforward');
}

// ---------------------------------------------------------------------------
// 3. Outbound NAT (nat/POSTROUTING) — incl. read-only policy-NAT companions
// ---------------------------------------------------------------------------

function renderOutboundNat() {
    const wrap = document.getElementById('std-outnat');
    const canManage = checkPermission('firewall.manage');

    const list = rules
        .filter(r => r.table_name === 'nat' && r.chain === 'POSTROUTING')
        .sort((a, b) => a.order - b.order);

    const header = `
        <div class="card-header d-flex align-items-center">
            <h3 class="card-title mb-0"><i class="ti ti-arrows-exchange me-2"></i>${t('firewall.std.outNatTitle')}</h3>
            <span class="text-muted ms-2 small">${t('firewall.std.outNatHint')}</span>
            ${canManage ? `<div class="ms-auto"><button class="btn btn-sm btn-outline-primary" id="btn-new-outnat">
                <i class="ti ti-plus me-1"></i>${t('firewall.std.newOutNat')}</button></div>` : ''}
        </div>`;

    let inner;
    if (!list.length) {
        inner = `<div class="card-body">${emptyState('ti-arrows-exchange',
            t('firewall.std.noOutNat'), t('firewall.std.noOutNatHint'))}</div>`;
    } else {
        inner = `
            <div class="table-responsive">
                <table class="table table-vcenter card-table mb-0">
                    <thead><tr>
                        <th>${t('firewall.std.colSource')}</th>
                        <th>${t('firewall.std.colDest')}</th>
                        <th>${t('firewall.outInterface')}</th>
                        <th>${t('firewall.action')}</th>
                        <th class="text-end"></th>
                    </tr></thead>
                    <tbody>
                        ${list.map(r => {
                            const locked = isAutoRow(r) || isManagedNat(r);
                            return `
                            <tr data-id="${r.id}">
                                <td>${renderAddrCell(r.source, r.source_refs)}</td>
                                <td>${renderAddrCell(r.destination, r.destination_refs)}</td>
                                <td>${r.out_interface ? `<code>${escapeHtml(r.out_interface)}</code>` : '<span class="text-muted">—</span>'}</td>
                                <td>${actionBadge(r.action)} ${locked ? `<span class="badge bg-azure-lt ms-1"><i class="ti ti-lock me-1"></i>${t('firewall.autoRule')}</span>` : ''}</td>
                                <td class="text-end">${(canManage && !locked) ? rowButtons() : ''}</td>
                            </tr>`;
                        }).join('')}
                    </tbody>
                </table>
            </div>`;
    }

    wrap.innerHTML = `<div class="card">${header}${inner}</div>`;
    document.getElementById('btn-new-outnat')?.addEventListener('click', () => edit('outnat', null));
    bindRowActions(wrap, 'outnat');
}

// ---------------------------------------------------------------------------
// Row action wiring (edit / duplicate / delete) shared by all three tables
// ---------------------------------------------------------------------------

function bindRowActions(wrap, mode) {
    wrap.querySelectorAll('.fw-edit').forEach(btn => btn.addEventListener('click', (e) => {
        const r = ruleOf(e); if (r) edit(mode, r);
    }));
    wrap.querySelectorAll('.fw-dup').forEach(btn => btn.addEventListener('click', (e) => {
        const r = ruleOf(e); if (r) edit(mode, r, true);
    }));
    wrap.querySelectorAll('.fw-del').forEach(btn => btn.addEventListener('click', async (e) => {
        const r = ruleOf(e); if (!r) return;
        const ok = await confirmDialog(t('firewall.deleteRule'), t('firewall.deleteRuleConfirm'),
            t('common.delete'), 'btn-danger');
        if (!ok) return;
        try {
            await apiDelete(`/firewall/rules/${r.id}`);
            showToast(t('firewall.ruleDeleted'), 'success');
            await reload();
        } catch (err) {
            showToast(t('common.errorPrefix') + err.message, 'error');
        }
    }));
}

function ruleOf(e) {
    const id = e.target.closest('tr')?.dataset.id;
    return rules.find(r => r.id === id);
}

// ---------------------------------------------------------------------------
// Drag & drop reordering within an interface-pair group
// ---------------------------------------------------------------------------

function setupDragDrop(tbody) {
    let dragged = null;
    tbody.querySelectorAll('.fw-drag').forEach(row => {
        row.addEventListener('dragstart', (e) => {
            dragged = row;
            row.classList.add('opacity-50');
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', row.dataset.id);
        });
        row.addEventListener('dragend', () => { row.classList.remove('opacity-50'); dragged = null; });
        row.addEventListener('dragover', (e) => e.preventDefault());
        row.addEventListener('drop', async (e) => {
            e.preventDefault();
            if (!dragged || dragged === row) return;
            const draggedRule = rules.find(r => r.id === dragged.dataset.id);
            const targetRule = rules.find(r => r.id === row.dataset.id);
            if (!draggedRule || !targetRule) return;
            try {
                await apiPatch(`/firewall/rules/${draggedRule.id}/reorder`, { new_order: targetRule.order });
                showToast(t('firewall.orderUpdated'), 'success');
                await reload();
            } catch (err) {
                showToast(t('common.errorPrefix') + err.message, 'error');
            }
        });
    });
}

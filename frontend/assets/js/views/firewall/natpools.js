/**
 * MADMIN - IP pools (Objects page, third tab)
 *
 * FortiGate-style IP pools a policy can NAT to:
 *   overload   -> many clients share the addresses (SNAT range --persistent)
 *   one_to_one -> each host of a subnet gets its own address (NETMAP)
 * "Reply to ARP" makes MADMIN add the addresses to the interface whose subnet
 * contains them; no service of the machine is reachable on them (backend
 * natpool.py). The interface is deduced, never asked.
 */
import { apiGet, apiPost, apiPatch, apiDelete } from '../../api.js';
import { showToast, confirmDialog, emptyState, escapeHtml } from '../../utils.js';
import { checkPermission } from '../../app.js';
import { t } from '../../i18n.js';

let pools = [];
let paneEl = null;
let editing = null;
let modal = null;

export async function mountPools(pane) {
    paneEl = pane;
    const canManage = checkPermission('firewall.manage');
    pane.innerHTML = `
        <div class="d-flex align-items-center mb-3">
            <span class="text-muted small">${t('firewall.pools.intro')}</span>
            ${canManage ? `
            <button class="btn btn-primary btn-sm ms-auto" id="btn-new-pool">
                <i class="ti ti-plus me-1"></i>${t('firewall.pools.new')}
            </button>` : ''}
        </div>
        <div id="pools-table-wrap"></div>`;
    pane.querySelector('#btn-new-pool')?.addEventListener('click', () => openPoolModal(null));
    ensureModal();
    await reload();
}

async function reload() {
    try {
        pools = await apiGet('/firewall/nat-pools');
    } catch (err) {
        pools = [];
        showToast(t('common.errorPrefix') + err.message, 'error');
    }
    render();
}

const TYPE_BADGE = { overload: 'bg-blue-lt', one_to_one: 'bg-purple-lt' };

function warningBadges(p) {
    return (p.warnings || []).map(w => `
        <span class="badge bg-yellow-lt ms-1" title="${escapeHtml(t(`firewall.pools.warn_${w}_hint`))}">
            <i class="ti ti-alert-triangle me-1"></i>${escapeHtml(t(`firewall.pools.warn_${w}`))}</span>`).join('');
}

function render() {
    const wrap = paneEl?.querySelector('#pools-table-wrap');
    if (!wrap) return;
    const canManage = checkPermission('firewall.manage');
    if (!pools.length) {
        wrap.innerHTML = emptyState('ti-world-share', t('firewall.pools.empty'), t('firewall.pools.emptyHint'));
        return;
    }
    wrap.innerHTML = `
        <table class="table table-vcenter table-hover card-table">
            <thead><tr>
                <th>${t('firewall.addr.colName')}</th>
                <th>${t('firewall.addr.colType')}</th>
                <th>${t('firewall.pools.colAddresses')}</th>
                <th>${t('firewall.pools.colArp')}</th>
                <th>${t('firewall.pools.colUsedBy')}</th>
                <th></th>
            </tr></thead>
            <tbody>${pools.map(p => `
                <tr>
                    <td><strong>${escapeHtml(p.name)}</strong>
                        ${p.description ? `<br><small class="text-muted">${escapeHtml(p.description)}</small>` : ''}</td>
                    <td><span class="badge ${TYPE_BADGE[p.type] || 'bg-secondary-lt'}">${escapeHtml(t(`firewall.pools.type_${p.type}`))}</span></td>
                    <td><code>${escapeHtml(p.value)}</code>
                        <span class="text-muted small ms-1">${escapeHtml(t('firewall.pools.size', { n: p.size }))}</span></td>
                    <td>${p.arp_reply
                        ? (p.interfaces.length
                            ? p.interfaces.map(d => `<span class="badge bg-green-lt me-1"><i class="ti ti-plug-connected me-1"></i>${escapeHtml(d)}</span>`).join('')
                            : '')
                        : `<span class="text-muted small">${escapeHtml(t('firewall.pools.routed'))}</span>`}${warningBadges(p)}</td>
                    <td>${p.in_use
                        ? `<span class="badge bg-azure-lt">${escapeHtml(t('firewall.pools.rules', { n: p.in_use }))}</span>`
                        : '<span class="text-muted">—</span>'}</td>
                    <td class="text-end">${canManage ? `
                        <div class="btn-group btn-group-sm">
                            <button class="btn btn-ghost-primary pool-edit" data-id="${escapeHtml(p.id)}" title="${escapeHtml(t('common.edit'))}"><i class="ti ti-edit"></i></button>
                            <button class="btn btn-ghost-danger pool-del" data-id="${escapeHtml(p.id)}" title="${escapeHtml(t('common.delete'))}"
                                ${p.in_use ? `disabled` : ''}><i class="ti ti-trash"></i></button>
                        </div>` : ''}</td>
                </tr>`).join('')}
            </tbody>
        </table>`;
    wrap.querySelectorAll('.pool-edit').forEach(b => b.addEventListener('click', () =>
        openPoolModal(pools.find(p => p.id === b.dataset.id))));
    wrap.querySelectorAll('.pool-del').forEach(b => b.addEventListener('click', () =>
        deletePool(pools.find(p => p.id === b.dataset.id))));
}

function ensureModal() {
    if (document.getElementById('pool-modal')) {
        modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('pool-modal'));
        return;
    }
    const el = document.createElement('div');
    el.className = 'modal modal-blur fade';
    el.id = 'pool-modal';
    el.tabIndex = -1;
    const typeOption = (value, icon) => `
        <label class="form-selectgroup-item flex-fill">
            <input type="radio" name="pool-type" value="${value}" class="form-selectgroup-input">
            <div class="form-selectgroup-label d-flex align-items-center p-3">
                <div class="me-3"><span class="form-selectgroup-check"></span></div>
                <div class="text-start">
                    <div class="fw-bold"><i class="ti ${icon} me-1"></i>${t(`firewall.pools.type_${value}`)}</div>
                    <div class="text-muted small">${t(`firewall.pools.type_${value}_hint`)}</div>
                </div>
            </div>
        </label>`;
    el.innerHTML = `
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="pool-modal-title"></h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <form id="pool-form" autocomplete="off">
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label required">${t('firewall.addr.labelName')}</label>
                            <input type="text" class="form-control" id="pool-name" maxlength="64" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">${t('firewall.addr.colType')}</label>
                            <div class="form-selectgroup form-selectgroup-boxes d-flex flex-column flex-md-row gap-2">
                                ${typeOption('overload', 'ti-users-group')}
                                ${typeOption('one_to_one', 'ti-arrows-left-right')}
                            </div>
                        </div>
                        <div class="mb-3">
                            <label class="form-label required">${t('firewall.pools.colAddresses')}</label>
                            <input type="text" class="form-control" id="pool-value" required>
                            <small class="form-hint" id="pool-value-hint"></small>
                        </div>
                        <div class="mb-3">
                            <label class="form-check form-switch">
                                <input class="form-check-input" type="checkbox" id="pool-arp">
                                <span class="form-check-label">${t('firewall.pools.arpLabel')}</span>
                            </label>
                            <small class="form-hint">${t('firewall.pools.arpHint')}</small>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">${t('common.description')}</label>
                            <input type="text" class="form-control" id="pool-description" maxlength="255">
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.cancel')}</button>
                        <button type="submit" class="btn btn-primary">${t('common.save')}</button>
                    </div>
                </form>
            </div>
        </div>`;
    document.body.appendChild(el);
    modal = bootstrap.Modal.getOrCreateInstance(el);
    el.querySelectorAll('input[name="pool-type"]').forEach(r => r.addEventListener('change', updateValueHint));
    el.querySelector('#pool-form').addEventListener('submit', savePool);
    // The view may go away while the modal is not shown: drop it with the route
    window.addEventListener('hashchange', () => { modal?.dispose(); el.remove(); modal = null; }, { once: true });
}

function selectedType() {
    return document.querySelector('#pool-modal input[name="pool-type"]:checked')?.value || 'overload';
}

function updateValueHint() {
    const type = selectedType();
    document.getElementById('pool-value-hint').textContent = t(`firewall.pools.value_${type}_hint`);
    document.getElementById('pool-value').placeholder = type === 'one_to_one' ? '203.0.113.16/28' : '203.0.113.10-203.0.113.20';
}

function openPoolModal(pool) {
    editing = pool;
    ensureModal();
    document.getElementById('pool-modal-title').textContent = pool ? t('firewall.pools.edit') : t('firewall.pools.new');
    document.getElementById('pool-name').value = pool?.name || '';
    document.getElementById('pool-value').value = pool?.value || '';
    document.getElementById('pool-arp').checked = pool ? pool.arp_reply : true;
    document.getElementById('pool-description').value = pool?.description || '';
    const type = pool?.type || 'overload';
    document.querySelectorAll('#pool-modal input[name="pool-type"]').forEach(r => { r.checked = r.value === type; });
    updateValueHint();
    modal.show();
}

async function savePool(e) {
    e.preventDefault();
    const data = {
        name: document.getElementById('pool-name').value.trim(),
        type: selectedType(),
        value: document.getElementById('pool-value').value.trim(),
        arp_reply: document.getElementById('pool-arp').checked,
        description: document.getElementById('pool-description').value.trim() || null,
    };
    try {
        if (editing) await apiPatch(`/firewall/nat-pools/${editing.id}`, data);
        else await apiPost('/firewall/nat-pools', data);
        showToast(t('firewall.pools.saved'), 'success');
        modal.hide();
        await reload();
    } catch (err) {
        showToast(t('common.errorPrefix') + err.message, 'error');
    }
}

async function deletePool(pool) {
    if (!pool) return;
    const ok = await confirmDialog(t('firewall.pools.deleteTitle'), t('firewall.pools.deleteConfirm', { name: pool.name }),
                                   t('common.delete'), 'btn-danger');
    if (!ok) return;
    try {
        await apiDelete(`/firewall/nat-pools/${pool.id}`);
        showToast(t('firewall.pools.deleted'), 'success');
        await reload();
    } catch (err) {
        showToast(t('common.errorPrefix') + err.message, 'error');
    }
}

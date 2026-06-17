/**
 * MADMIN - Address Objects & Groups View
 *
 * FortiGate-style dedicated page for managing reusable address objects and groups.
 * Two tabs: Addresses (single objects) and Groups.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '../api.js';
import { showToast, confirmDialog, emptyState, escapeHtml } from '../utils.js';
import { setPageActions, checkPermission } from '../app.js';
import { t } from '../i18n.js';

let addressObjects = [];
let addressGroups = [];
let geoCountries = null;
let editingObject = null;
let editingGroup = null;
let groupPickerGetSelected = null;

const TYPE_COLOR = {
    cidr:  'bg-blue-lt',
    range: 'bg-cyan-lt',
    fqdn:  'bg-orange-lt',
    geo:   'bg-green-lt',
};

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

export async function render(container) {
    const canManage = checkPermission('firewall.manage');

    if (canManage) {
        setPageActions(`
            <div class="btn-list">
                <button class="btn btn-primary" id="btn-new-addr">
                    <i class="ti ti-plus me-2"></i>${t('firewall.addr.newObject')}
                </button>
            </div>
        `);
    }

    container.innerHTML = `
        <div class="card">
            <div class="card-header">
                <ul class="nav nav-tabs card-header-tabs" id="addr-page-tabs" role="tablist">
                    <li class="nav-item" role="presentation">
                        <button class="nav-link active" data-bs-toggle="tab"
                                data-bs-target="#addr-page-objects" type="button" role="tab">
                            <i class="ti ti-box me-1"></i>${t('firewall.addr.tabObjects')}
                        </button>
                    </li>
                    <li class="nav-item" role="presentation">
                        <button class="nav-link" data-bs-toggle="tab"
                                data-bs-target="#addr-page-groups" type="button" role="tab">
                            <i class="ti ti-stack-2 me-1"></i>${t('firewall.addr.tabGroups')}
                        </button>
                    </li>
                </ul>
            </div>
            <div class="card-body p-0">
                <div class="tab-content">
                    <div class="tab-pane active show p-3" id="addr-page-objects">
                        <div id="objects-table-wrap"></div>
                    </div>
                    <div class="tab-pane p-3" id="addr-page-groups">
                        <div class="d-flex justify-content-end mb-3">
                            ${canManage ? `
                            <button class="btn btn-primary btn-sm" id="btn-new-group">
                                <i class="ti ti-plus me-1"></i>${t('firewall.addr.newGroup')}
                            </button>` : ''}
                        </div>
                        <div id="groups-table-wrap"></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Address Object Modal -->
        <div class="modal modal-blur fade" id="ao-modal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="ao-modal-title">${t('firewall.addr.newObject')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <form id="ao-form">
                        <div class="modal-body">
                            <div class="mb-3">
                                <label class="form-label required">${t('firewall.addr.labelName')}</label>
                                <input type="text" class="form-control" id="ao-name" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label required">${t('firewall.addr.labelType')}</label>
                                <select class="form-select" id="ao-type" required>
                                    <option value="cidr">${t('firewall.addr.typeCidr')}</option>
                                    <option value="range">${t('firewall.addr.typeRange')}</option>
                                    <option value="fqdn">${t('firewall.addr.typeFqdn')}</option>
                                    <option value="geo">${t('firewall.addr.typeGeo')}</option>
                                </select>
                            </div>
                            <div class="mb-3" id="ao-value-group">
                                <label class="form-label required">${t('firewall.addr.labelValue')}</label>
                                <input type="text" class="form-control" id="ao-value"
                                       placeholder="es. 192.168.1.0/24">
                                <select class="form-select" id="ao-value-geo" style="display:none;"></select>
                                <small class="form-hint" id="ao-value-hint">
                                    ${t('firewall.addr.hintCidr')}
                                </small>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">${t('common.description')}</label>
                                <input type="text" class="form-control" id="ao-description">
                            </div>
                            <label class="form-check form-switch">
                                <input class="form-check-input" type="checkbox" id="ao-enabled" checked>
                                <span class="form-check-label">${t('common.enabled')}</span>
                            </label>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-link"
                                    data-bs-dismiss="modal">${t('common.cancel')}</button>
                            <button type="submit" class="btn btn-primary">${t('common.save')}</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>

        <!-- Address Group Modal -->
        <div class="modal modal-blur fade" id="ag-modal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="ag-modal-title">${t('firewall.addr.newGroup')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <form id="ag-form">
                        <div class="modal-body">
                            <div class="mb-3">
                                <label class="form-label required">${t('firewall.addr.labelName')}</label>
                                <input type="text" class="form-control" id="ag-name" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">${t('common.description')}</label>
                                <input type="text" class="form-control" id="ag-description">
                            </div>
                            <div class="mb-3">
                                <label class="form-label">${t('firewall.addr.labelMembers')}</label>
                                <div id="ag-picker"></div>
                            </div>
                            <label class="form-check form-switch">
                                <input class="form-check-input" type="checkbox" id="ag-enabled" checked>
                                <span class="form-check-label">${t('common.enabled')}</span>
                            </label>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-link"
                                    data-bs-dismiss="modal">${t('common.cancel')}</button>
                            <button type="submit" class="btn btn-primary">${t('common.save')}</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    `;

    setupListeners();
    await loadAll();
    renderObjects();
    renderGroups();
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadAll() {
    try {
        const [objs, grps] = await Promise.all([
            apiGet('/firewall/addresses'),
            apiGet('/firewall/address-groups'),
        ]);
        addressObjects = objs || [];
        addressGroups  = grps || [];
    } catch {
        addressObjects = [];
        addressGroups  = [];
    }
}

async function loadGeoCountries() {
    if (geoCountries) return;
    try {
        geoCountries = await apiGet('/firewall/geo/countries');
    } catch {
        geoCountries = [];
    }
}

// ---------------------------------------------------------------------------
// Render tables
// ---------------------------------------------------------------------------

function typeLabel(type) {
    const keys = { cidr: 'typeCidr', range: 'typeRange', fqdn: 'typeFqdn', geo: 'typeGeo' };
    return t(`firewall.addr.${keys[type] || 'typeCidr'}`);
}

function renderObjects() {
    const wrap = document.getElementById('objects-table-wrap');
    if (!wrap) return;
    const canManage = checkPermission('firewall.manage');

    if (!addressObjects.length) {
        wrap.innerHTML = emptyState('ti-box',
            t('firewall.addr.emptyObjects'),
            t('firewall.addr.emptyObjectsHint'));
        return;
    }

    wrap.innerHTML = `
        <table class="table table-vcenter table-hover card-table">
            <thead>
                <tr>
                    <th>${t('firewall.addr.colName')}</th>
                    <th>${t('firewall.addr.colType')}</th>
                    <th>${t('firewall.addr.colValue')}</th>
                    <th>${t('firewall.addr.colResolved')}</th>
                    <th>${t('common.status')}</th>
                    <th></th>
                </tr>
            </thead>
            <tbody>
                ${addressObjects.map(o => objectRow(o, canManage)).join('')}
            </tbody>
        </table>
    `;

    wrap.querySelectorAll('[data-bs-toggle="popover"]').forEach(el => {
        bootstrap.Popover.getOrCreateInstance(el, {
            trigger: 'hover focus',
            html: true,
            placement: 'left',
            container: 'body',
        });
    });

    wrap.querySelectorAll('.ao-edit').forEach(btn =>
        btn.addEventListener('click', () => {
            const obj = addressObjects.find(x => x.id === btn.dataset.id);
            if (obj) openObjectModal(obj);
        })
    );
    wrap.querySelectorAll('.ao-del').forEach(btn =>
        btn.addEventListener('click', () => deleteObject(btn.dataset.id))
    );
}

function objectRow(o, canManage) {
    const color = TYPE_COLOR[o.type] || 'bg-secondary-lt';
    const statusBadge = o.enabled
        ? `<span class="badge bg-success-lt">${t('firewall.addr.statusActive')}</span>`
        : `<span class="badge bg-secondary-lt">${t('firewall.addr.statusInactive')}</span>`;

    let resolvedCell = '<span class="text-muted small">—</span>';
    if ((o.type === 'fqdn' || o.type === 'geo') && o.resolved_ips && o.resolved_ips.length) {
        const when = o.resolved_at
            ? `<small class="text-muted">${t('firewall.addr.resolvedAt')}: ${relativeTime(o.resolved_at)}</small>`
            : '';
        const ipList = o.resolved_ips.slice(0, 8).map(ip => `<code>${escapeHtml(ip)}</code>`).join('<br>');
        const more = o.resolved_ips.length > 8
            ? `<br><small class="text-muted">${t('firewall.addr.andMore', { n: o.resolved_ips.length - 8 })}</small>`
            : '';
        const popContent = `${ipList}${more}<br>${when}`;
        resolvedCell = `
            <span class="badge bg-secondary-lt" style="cursor:help"
                  data-bs-toggle="popover"
                  data-bs-title="${escapeHtml(t('firewall.addr.resolvedIps'))}"
                  data-bs-content="${escapeAttr(popContent)}">
                ${o.resolved_ips.length} IP
            </span>`;
    } else if (o.type === 'fqdn' || o.type === 'geo') {
        resolvedCell = `<span class="badge bg-warning-lt">${t('firewall.addr.notResolved')}</span>`;
    }

    const actions = canManage ? `
        <div class="btn-group btn-group-sm">
            <button class="btn btn-ghost-primary ao-edit" data-id="${o.id}"
                    title="${t('common.edit')}">
                <i class="ti ti-edit"></i>
            </button>
            <button class="btn btn-ghost-danger ao-del" data-id="${o.id}"
                    title="${t('common.delete')}">
                <i class="ti ti-trash"></i>
            </button>
        </div>` : '';

    return `
        <tr>
            <td>
                <strong>${escapeHtml(o.name)}</strong>
                ${o.description ? `<br><small class="text-muted">${escapeHtml(o.description)}</small>` : ''}
            </td>
            <td><span class="badge ${color}">${typeLabel(o.type)}</span></td>
            <td><code>${escapeHtml(o.value)}</code></td>
            <td>${resolvedCell}</td>
            <td>${statusBadge}</td>
            <td class="text-end">${actions}</td>
        </tr>
    `;
}

function renderGroups() {
    const wrap = document.getElementById('groups-table-wrap');
    if (!wrap) return;
    const canManage = checkPermission('firewall.manage');

    if (!addressGroups.length) {
        wrap.innerHTML = emptyState('ti-stack-2',
            t('firewall.addr.emptyGroups'),
            t('firewall.addr.emptyGroupsHint'));
        return;
    }

    wrap.innerHTML = `
        <table class="table table-vcenter table-hover card-table">
            <thead>
                <tr>
                    <th>${t('firewall.addr.colName')}</th>
                    <th>${t('common.description')}</th>
                    <th>${t('firewall.addr.colMembers')}</th>
                    <th>${t('common.status')}</th>
                    <th></th>
                </tr>
            </thead>
            <tbody>
                ${addressGroups.map(g => groupRow(g, canManage)).join('')}
            </tbody>
        </table>
    `;

    wrap.querySelectorAll('.ag-edit').forEach(btn =>
        btn.addEventListener('click', () => {
            const grp = addressGroups.find(x => x.id === btn.dataset.id);
            if (grp) openGroupModal(grp);
        })
    );
    wrap.querySelectorAll('.ag-del').forEach(btn =>
        btn.addEventListener('click', () => deleteGroup(btn.dataset.id))
    );
}

function groupRow(g, canManage) {
    const members = (g.members || [])
        .map(m => `<span class="badge bg-azure-lt me-1">${escapeHtml(m.name)}</span>`)
        .join(' ') || '<span class="text-muted">—</span>';
    const statusBadge = g.enabled
        ? `<span class="badge bg-success-lt">${t('firewall.addr.statusActive')}</span>`
        : `<span class="badge bg-secondary-lt">${t('firewall.addr.statusInactive')}</span>`;
    const actions = canManage ? `
        <div class="btn-group btn-group-sm">
            <button class="btn btn-ghost-primary ag-edit" data-id="${g.id}"
                    title="${t('common.edit')}">
                <i class="ti ti-edit"></i>
            </button>
            <button class="btn btn-ghost-danger ag-del" data-id="${g.id}"
                    title="${t('common.delete')}">
                <i class="ti ti-trash"></i>
            </button>
        </div>` : '';

    return `
        <tr>
            <td><strong>${escapeHtml(g.name)}</strong></td>
            <td><span class="text-muted">${g.description ? escapeHtml(g.description) : '—'}</span></td>
            <td>${members}</td>
            <td>${statusBadge}</td>
            <td class="text-end">${actions}</td>
        </tr>
    `;
}

// ---------------------------------------------------------------------------
// Object modal
// ---------------------------------------------------------------------------

async function openObjectModal(obj = null) {
    editingObject = obj;
    document.getElementById('ao-modal-title').textContent =
        obj ? t('firewall.addr.editObject') : t('firewall.addr.newObject');
    document.getElementById('ao-name').value = obj?.name || '';
    document.getElementById('ao-description').value = obj?.description || '';
    document.getElementById('ao-enabled').checked = obj ? obj.enabled : true;

    const type = obj?.type || 'cidr';
    document.getElementById('ao-type').value = type;
    applyTypeUI(type);

    if (type === 'geo') {
        await loadGeoCountries();
        populateGeoSelect();
        document.getElementById('ao-value-geo').value = obj?.value || '';
    } else {
        document.getElementById('ao-value').value = obj?.value || '';
    }

    new bootstrap.Modal(document.getElementById('ao-modal')).show();
}

function applyTypeUI(type) {
    const input = document.getElementById('ao-value');
    const geo   = document.getElementById('ao-value-geo');
    const hint  = document.getElementById('ao-value-hint');
    const isGeo = type === 'geo';
    if (input) input.style.display = isGeo ? 'none' : '';
    if (geo)   geo.style.display   = isGeo ? ''     : 'none';
    const hintKeys = { cidr: 'hintCidr', range: 'hintRange', fqdn: 'hintFqdn', geo: 'hintGeo' };
    if (hint)  hint.textContent = t(`firewall.addr.${hintKeys[type] || 'hintCidr'}`);
    const placeholders = {
        range: 'es. 10.0.0.10-10.0.0.50',
        fqdn:  'es. example.com',
        cidr:  'es. 192.168.1.0/24',
        geo:   '',
    };
    if (input) input.placeholder = placeholders[type] || '';
}

function populateGeoSelect() {
    const sel = document.getElementById('ao-value-geo');
    if (!sel || !geoCountries) return;
    sel.innerHTML = geoCountries
        .map(c => `<option value="${c.code}">${escapeHtml(c.name)} (${c.code.toUpperCase()})</option>`)
        .join('');
}

async function handleObjectSubmit(e) {
    e.preventDefault();
    const type = document.getElementById('ao-type').value;
    const value = type === 'geo'
        ? document.getElementById('ao-value-geo').value
        : document.getElementById('ao-value').value.trim();
    const payload = {
        name:        document.getElementById('ao-name').value.trim(),
        type,
        value,
        description: document.getElementById('ao-description').value.trim() || null,
        enabled:     document.getElementById('ao-enabled').checked,
    };
    try {
        if (editingObject) {
            await apiPatch(`/firewall/addresses/${editingObject.id}`, payload);
            showToast(t('firewall.addr.objectUpdated'), 'success');
        } else {
            await apiPost('/firewall/addresses', payload);
            showToast(t('firewall.addr.objectCreated'), 'success');
        }
        bootstrap.Modal.getInstance(document.getElementById('ao-modal')).hide();
        await loadAll();
        renderObjects();
        renderGroups();
    } catch (err) {
        showToast(t('common.errorPrefix') + err.message, 'error');
    }
}

async function deleteObject(id) {
    const obj = addressObjects.find(x => x.id === id);
    const ok = await confirmDialog(
        t('firewall.addr.deleteObjectTitle'),
        t('firewall.addr.deleteObjectConfirm', { name: obj?.name || '' }),
        t('common.delete'), 'btn-danger');
    if (!ok) return;
    try {
        await apiDelete(`/firewall/addresses/${id}`);
        showToast(t('firewall.addr.objectDeleted'), 'success');
        await loadAll();
        renderObjects();
        renderGroups();
    } catch (err) {
        showToast(t('common.errorPrefix') + err.message, 'error');
    }
}

// ---------------------------------------------------------------------------
// Group modal
// ---------------------------------------------------------------------------

function openGroupModal(group = null) {
    editingGroup = group;
    document.getElementById('ag-modal-title').textContent =
        group ? t('firewall.addr.editGroup') : t('firewall.addr.newGroup');
    document.getElementById('ag-name').value = group?.name || '';
    document.getElementById('ag-description').value = group?.description || '';
    document.getElementById('ag-enabled').checked = group ? group.enabled : true;

    const items = addressObjects.map(o => ({
        id:       o.id,
        label:    o.name,
        subtitle: typeLabel(o.type),
        icon:     o.type,
    }));
    const selected = new Set(
        (group?.members || []).filter(m => m.object_id).map(m => m.object_id)
    );

    groupPickerGetSelected = buildAddressPicker(
        document.getElementById('ag-picker'), items, selected
    );

    new bootstrap.Modal(document.getElementById('ag-modal')).show();
}

async function handleGroupSubmit(e) {
    e.preventDefault();
    const members = (groupPickerGetSelected?.() || []).map(id => ({ object_id: id }));
    const payload = {
        name:        document.getElementById('ag-name').value.trim(),
        description: document.getElementById('ag-description').value.trim() || null,
        enabled:     document.getElementById('ag-enabled').checked,
        members,
    };
    try {
        if (editingGroup) {
            await apiPatch(`/firewall/address-groups/${editingGroup.id}`, payload);
            showToast(t('firewall.addr.groupUpdated'), 'success');
        } else {
            await apiPost('/firewall/address-groups', payload);
            showToast(t('firewall.addr.groupCreated'), 'success');
        }
        bootstrap.Modal.getInstance(document.getElementById('ag-modal')).hide();
        await loadAll();
        renderObjects();
        renderGroups();
    } catch (err) {
        showToast(t('common.errorPrefix') + err.message, 'error');
    }
}

async function deleteGroup(id) {
    const grp = addressGroups.find(x => x.id === id);
    const ok = await confirmDialog(
        t('firewall.addr.deleteGroupTitle'),
        t('firewall.addr.deleteGroupConfirm', { name: grp?.name || '' }),
        t('common.delete'), 'btn-danger');
    if (!ok) return;
    try {
        await apiDelete(`/firewall/address-groups/${id}`);
        showToast(t('firewall.addr.groupDeleted'), 'success');
        await loadAll();
        renderGroups();
    } catch (err) {
        showToast(t('common.errorPrefix') + err.message, 'error');
    }
}

// ---------------------------------------------------------------------------
// Address picker component
// Returns a getSelected() function → string[]
// items: [{id, label, subtitle, icon}]
// ---------------------------------------------------------------------------

export function buildAddressPicker(container, items, selectedIds = new Set()) {
    let selected = new Set(selectedIds);

    const TYPE_ICON = { cidr: '🌐', range: '↔', fqdn: '🔗', geo: '🌍' };

    container.innerHTML = `
        <div class="address-picker">
            <input class="form-control form-control-sm mb-2 picker-search"
                   placeholder="${t('firewall.addr.pickerSearch')}"
                   type="search" autocomplete="off">
            <div class="picker-list border rounded bg-white"
                 style="max-height:200px;overflow-y:auto;"></div>
            <div class="picker-chips mt-2 d-flex flex-wrap gap-1 min-height-chips"></div>
        </div>
    `;

    const searchEl = container.querySelector('.picker-search');
    const listEl   = container.querySelector('.picker-list');
    const chipsEl  = container.querySelector('.picker-chips');

    function renderList(query = '') {
        const q = query.toLowerCase();
        const filtered = items.filter(item =>
            !q || item.label.toLowerCase().includes(q) ||
            (item.subtitle || '').toLowerCase().includes(q)
        );

        if (!filtered.length) {
            listEl.innerHTML = `<div class="px-3 py-2 text-muted small">${t('common.noResults')}</div>`;
            return;
        }

        listEl.innerHTML = filtered.map(item => {
            const checked = selected.has(item.id);
            const icon = TYPE_ICON[item.icon] || '';
            return `
                <label class="d-flex align-items-center gap-2 px-2 py-1 picker-item
                              ${checked ? 'picker-item-selected' : ''}"
                       style="cursor:pointer;" data-id="${item.id}">
                    <input type="checkbox" class="form-check-input m-0 flex-shrink-0"
                           value="${item.id}" ${checked ? 'checked' : ''}>
                    <span class="flex-grow-1 text-truncate">
                        ${icon} ${escapeHtml(item.label)}
                    </span>
                    <small class="text-muted flex-shrink-0">${escapeHtml(item.subtitle || '')}</small>
                </label>
            `;
        }).join('');

        listEl.querySelectorAll('input[type=checkbox]').forEach(chk => {
            chk.addEventListener('change', () => {
                if (chk.checked) selected.add(chk.value);
                else selected.delete(chk.value);
                renderChips();
                renderList(searchEl.value);
            });
        });
    }

    function renderChips() {
        if (!selected.size) {
            chipsEl.innerHTML = `<small class="text-muted">${t('firewall.addr.pickerEmpty')}</small>`;
            return;
        }
        chipsEl.innerHTML = [...selected].map(id => {
            const item = items.find(i => i.id === id);
            if (!item) return '';
            return `
                <span class="badge bg-azure-lt d-inline-flex align-items-center gap-1 picker-chip"
                      data-id="${id}">
                    ${escapeHtml(item.label)}
                    <button type="button" class="btn-close" aria-label="${t('common.delete')}"
                            style="font-size:0.45em;filter:none;opacity:0.7;"></button>
                </span>
            `;
        }).join('');
        chipsEl.querySelectorAll('.picker-chip').forEach(chip => {
            chip.querySelector('.btn-close').addEventListener('click', () => {
                selected.delete(chip.dataset.id);
                renderChips();
                renderList(searchEl.value);
            });
        });
    }

    searchEl.addEventListener('input', () => renderList(searchEl.value));
    renderList();
    renderChips();

    return () => [...selected];
}

// ---------------------------------------------------------------------------
// Event listeners
// ---------------------------------------------------------------------------

function setupListeners() {
    document.getElementById('btn-new-addr')?.addEventListener('click', () => openObjectModal());
    document.getElementById('btn-new-group')?.addEventListener('click', () => openGroupModal());
    document.getElementById('ao-form')?.addEventListener('submit', handleObjectSubmit);
    document.getElementById('ag-form')?.addEventListener('submit', handleGroupSubmit);
    document.getElementById('ao-type')?.addEventListener('change', async (e) => {
        applyTypeUI(e.target.value);
        if (e.target.value === 'geo') {
            await loadGeoCountries();
            populateGeoSelect();
        }
    });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function relativeTime(isoString) {
    if (!isoString) return '';
    const diff = Date.now() - new Date(isoString).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 2)   return t('firewall.addr.timeNow');
    if (mins < 60)  return t('firewall.addr.timeMinAgo', { n: mins });
    const hrs = Math.floor(mins / 60);
    if (hrs < 24)   return t('firewall.addr.timeHoursAgo', { n: hrs });
    return t('firewall.addr.timeDaysAgo', { n: Math.floor(hrs / 24) });
}

function escapeAttr(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

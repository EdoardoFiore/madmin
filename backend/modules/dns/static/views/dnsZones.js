/**
 * DNS Module - Zones Tab & Zone Detail View
 *
 * Zone list, zone detail with DNS records management.
 */

import { t } from '/static/js/i18n.js';
import { apiGet, apiPost, apiDelete, apiPatch } from '/static/js/api.js';
import { showToast, confirmDialog, escapeHtml } from '/static/js/utils.js';

const RECORD_TYPES = ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'SRV', 'NS', 'PTR'];

// State for search/filter within a zone
let currentZoneRecords = [];
let currentSearchTerm = '';
let currentTypeFilter = '';
let _container = null;
let _perms = null;

// ============================================================
//  ZONES TAB
// ============================================================

export function renderDnsZonesTab(zones, container, perms) {
    const content = document.getElementById('dns-tab-content');
    if (!content) return;

    content.innerHTML = `
        <div class="card-body">
            <div class="d-flex flex-column flex-md-row justify-content-between align-items-md-center mb-3 gap-2">
                <h4 class="mb-0">${t('dns.zonesTitle')}</h4>
                <div class="d-flex gap-2 align-items-center">
                    <div class="input-icon">
                        <span class="input-icon-addon"><i class="ti ti-search"></i></span>
                        <input type="search" class="form-control d-inline-block w-9" id="input-zone-search"
                               placeholder="${t('dns.searchZone')}" style="min-width: 200px;">
                    </div>
                    ${perms.zones ? `
                    <button class="btn btn-primary text-nowrap" id="btn-new-zone">
                        <i class="ti ti-plus me-1"></i>${t('dns.newZone')}
                    </button>` : ''}
                </div>
            </div>
            ${zones.length === 0 ? `
                <div class="text-center py-5 text-muted">
                    <i class="ti ti-world-off" style="font-size: 3rem;"></i>
                    <p class="mt-2">${t('dns.noZones')}</p>
                    <small>${t('dns.noZonesHint')}</small>
                </div>
            ` : `
                <div class="table-responsive">
                    <table class="table table-vcenter table-hover">
                        <thead>
                            <tr>
                                <th style="width: 50px;">${t('dns.active')}</th>
                                <th>${t('dns.zoneName')}</th>
                                <th>${t('dns.type')}</th>
                                <th>${t('dns.record')}</th>
                                <th>${t('dns.description')}</th>
                                <th class="w-1"></th>
                            </tr>
                        </thead>
                        <tbody>
                            ${zones.map(z => `
                                <tr class="zone-row ${!z.enabled ? 'text-muted' : ''}" data-id="${z.id}" style="cursor: pointer;">
                                    <td onclick="event.stopPropagation();">
                                        ${perms.zones ? `
                                        <label class="form-check form-switch mb-0">
                                            <input class="form-check-input zone-toggle" type="checkbox"
                                                   data-id="${z.id}" ${z.enabled ? 'checked' : ''}>
                                        </label>` : `
                                        <span class="status-dot ${z.enabled ? 'bg-success' : 'bg-secondary'}"></span>`}
                                    </td>
                                    <td>
                                        <a href="#dns/${z.id}" class="text-reset">
                                            <strong>${escapeHtml(z.name)}</strong>
                                        </a>
                                    </td>
                                    <td>
                                        <span class="badge ${z.zone_type === 'master' ? 'bg-blue' : z.zone_type === 'forward' ? 'bg-green' : 'bg-yellow'}-lt">
                                            ${z.zone_type}
                                        </span>
                                    </td>
                                    <td><span class="badge bg-blue-lt">${z.record_count}</span></td>
                                    <td><small class="text-muted">${escapeHtml(z.description || '—')}</small></td>
                                    <td>
                                        ${perms.zones ? `
                                        <button class="btn btn-sm btn-ghost-danger btn-delete-zone"
                                                data-id="${z.id}" onclick="event.stopPropagation();" title="${t('dns.delete')}">
                                            <i class="ti ti-trash"></i>
                                        </button>` : ''}
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            `}
        </div>

        <!-- New Zone Modal -->
        ${renderNewZoneModal()}
    `;

    setupZonesActions(zones, container, perms);
}

function setupZonesActions(zones, container, perms) {
    // Zone search
    document.getElementById('input-zone-search')?.addEventListener('input', (e) => {
        const term = e.target.value.toLowerCase();
        document.querySelectorAll('.zone-row').forEach(row => {
            const name = row.querySelector('strong').textContent.toLowerCase();
            const desc = row.querySelector('.text-muted').textContent.toLowerCase();
            row.style.display = (name.includes(term) || desc.includes(term)) ? '' : 'none';
        });
    });

    // New zone
    document.getElementById('btn-new-zone')?.addEventListener('click', () => {
        const fwdGroup = document.getElementById('new-zone-fwd-group');
        if (fwdGroup) fwdGroup.style.display = 'none';
        const typeSelect = document.getElementById('new-zone-type');
        if (typeSelect) typeSelect.value = 'master';
        new bootstrap.Modal(document.getElementById('modal-new-zone')).show();
    });
    document.getElementById('btn-create-zone')?.addEventListener('click', () => createZone(container, perms));

    // Toggle forward servers visibility (new zone)
    document.getElementById('new-zone-type')?.addEventListener('change', (e) => {
        const fwdGroup = document.getElementById('new-zone-fwd-group');
        if (fwdGroup) fwdGroup.style.display = e.target.value !== 'master' ? '' : 'none';
    });

    // Zone row click
    document.querySelectorAll('.zone-row').forEach(row => {
        row.addEventListener('click', (e) => {
            if (e.target.closest('.btn-group') || e.target.closest('.btn-delete-zone')) return;
            window.location.hash = `#dns/${row.dataset.id}`;
        });
    });

    // Delete zone
    document.querySelectorAll('.btn-delete-zone').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            if (!await confirmDialog(t('dns.confirmDeleteZone'), t('dns.confirmDeleteZoneMsg'))) return;
            try {
                await apiDelete(`/modules/dns/zones/${btn.dataset.id}`);
                showToast(t('dns.zoneDeleted'), 'success');
                // Reload dashboard
                const { renderDnsStatus } = await import('/static/modules/dns/views/dnsStatus.js');
                await renderDnsStatus(container, perms);
            } catch (err) { showToast(err.message, 'error'); }
        });
    });

    // Zone toggle
    document.querySelectorAll('.zone-toggle').forEach(toggle => {
        toggle.addEventListener('change', async () => {
            const id = toggle.dataset.id;
            const enabled = toggle.checked;
            try {
                const res = await apiPatch(`/modules/dns/zones/${id}`, { enabled });
                if (res.applied) {
                    showToast(enabled ? t('dns.zoneEnabledApplied') : t('dns.zoneDisabledApplied'), 'success');
                } else {
                    showToast(`${enabled ? t('dns.zoneEnabled') : t('dns.zoneDisabled')} — ${t('dns.applyError')}: ${res.apply_message}`, 'warning');
                }
                const { renderDnsStatus } = await import('/static/modules/dns/views/dnsStatus.js');
                await renderDnsStatus(container, perms);
            } catch (err) {
                toggle.checked = !enabled;
                showToast(err.message, 'error');
            }
        });
    });
}

async function createZone(container, perms) {
    const name = document.getElementById('new-zone-name')?.value.trim();
    const zoneType = document.getElementById('new-zone-type')?.value;
    const description = document.getElementById('new-zone-desc')?.value.trim();
    const forwardServers = document.getElementById('new-zone-fwd-servers')?.value.trim();

    if (!name) {
        showToast(t('dns.zoneNameRequired'), 'error');
        return;
    }
    if (zoneType !== 'master' && !forwardServers) {
        showToast(t('dns.forwardServersRequired'), 'error');
        return;
    }

    const data = { name, zone_type: zoneType, description };
    if (zoneType !== 'master' && forwardServers) {
        data.forward_servers = JSON.stringify(forwardServers.split(',').map(s => s.trim()).filter(Boolean));
    }

    try {
        const result = await apiPost('/modules/dns/zones', data);
        showToast(
            result.applied ? t('dns.zoneCreatedApplied') : `${t('dns.zoneCreatedWarning')}: ${result.apply_message}`,
            result.applied ? 'success' : 'warning'
        );
        bootstrap.Modal.getInstance(document.getElementById('modal-new-zone'))?.hide();
        const { renderDnsStatus } = await import('/static/modules/dns/views/dnsStatus.js');
        await renderDnsStatus(container, perms);
    } catch (err) { showToast(err.message, 'error'); }
}

// ============================================================
//  ZONE DETAIL
// ============================================================

export async function renderDnsZoneDetail(container, zoneId, perms) {
    _container = container;
    _perms = perms;
    try {
        const zone = await apiGet(`/modules/dns/zones/${zoneId}`);
        currentZoneRecords = zone.records || [];

        const sortOrder = { NS: 1, MX: 2, TXT: 3, A: 4, CNAME: 5, SRV: 6, PTR: 7 };
        currentZoneRecords.sort((a, b) => {
            const orderA = sortOrder[a.record_type] || 99;
            const orderB = sortOrder[b.record_type] || 99;
            if (orderA !== orderB) return orderA - orderB;
            return a.name.localeCompare(b.name);
        });

        const availableTypes = [...new Set(currentZoneRecords.map(r => r.record_type))].sort();

        container.innerHTML = `
            <div class="mb-3">
                <a href="#dns" class="text-muted" onclick="void 0;">
                    <i class="ti ti-arrow-left me-1"></i>${t('dns.backToZones')}
                </a>
            </div>

            <div class="card mb-3">
                <div class="card-header">
                    <div class="d-flex justify-content-between align-items-center w-100">
                        <div>
                            <h3 class="card-title mb-0">
                                <span class="status-dot ${zone.enabled ? 'bg-success' : 'bg-secondary'} me-2"></span>
                                ${escapeHtml(zone.name)}
                            </h3>
                            <small class="text-muted">
                                ${t('dns.typeLabel')}: <span class="badge bg-blue-lt">${zone.zone_type}</span>
                                — ${t('dns.ttlDefault')}: ${zone.ttl_default}s
                                ${zone.description ? ` — ${escapeHtml(zone.description)}` : ''}
                            </small>
                        </div>
                        ${perms.zones ? `
                        <div class="btn-group">
                            <button class="btn btn-outline-primary" id="btn-edit-zone">
                                <i class="ti ti-edit me-1"></i>${t('dns.edit')}
                            </button>
                            <button class="btn btn-outline-danger" id="btn-delete-zone">
                                <i class="ti ti-trash me-1"></i>${t('dns.delete')}
                            </button>
                        </div>` : ''}
                    </div>
                </div>
            </div>

            ${zone.zone_type === 'master' ? `
            <div class="card">
                <div class="card-header d-flex flex-wrap justify-content-between align-items-center gap-2">
                    <h3 class="card-title mb-0">
                        <i class="ti ti-list me-2"></i>${t('dns.dnsRecords')}
                        <span id="records-count-badge"></span>
                    </h3>
                    <div class="d-flex flex-wrap gap-2">
                        <div class="input-icon" style="max-width: 200px;">
                            <span class="input-icon-addon"><i class="ti ti-search"></i></span>
                            <input type="text" class="form-control form-control-sm" id="record-search-input"
                                   value="${escapeHtml(currentSearchTerm)}" placeholder="${t('dns.searchRecord')}">
                        </div>
                        <select class="form-select form-select-sm" id="record-type-filter" style="width: auto;">
                            <option value="">${t('dns.allTypes')}</option>
                            ${availableTypes.map(tp => `<option value="${tp}" ${currentTypeFilter === tp ? 'selected' : ''}>${tp}</option>`).join('')}
                        </select>
                        ${perms.records ? `
                        <button class="btn btn-primary btn-sm ms-md-2" id="btn-new-record">
                            <i class="ti ti-plus me-1"></i>${t('dns.newRecord')}
                        </button>` : ''}
                    </div>
                </div>
                <div class="card-body p-0" id="records-list-container"></div>
            </div>

            ${renderNewRecordModal(zone)}
            ${renderEditRecordModal()}
            ` : `
            <div class="card">
                <div class="card-body text-center text-muted py-4">
                    <i class="ti ti-arrows-right" style="font-size: 2rem;"></i>
                    <p class="mt-2">${t('dns.forwardZoneMsg', { type: zone.zone_type })}</p>
                    ${zone.forward_servers ? `<p>${t('dns.server')}: <code>${escapeHtml(zone.forward_servers)}</code></p>` : ''}
                </div>
            </div>
            `}

            ${renderEditZoneModal(zone)}
        `;

        setupZoneDetailActions(zone, zoneId, container, perms);
        refreshRecordsUI(zoneId, perms);

        document.getElementById('record-search-input')?.addEventListener('input', (e) => {
            currentSearchTerm = e.target.value;
            refreshRecordsUI(zoneId, perms);
        });
        document.getElementById('record-type-filter')?.addEventListener('change', (e) => {
            currentTypeFilter = e.target.value;
            refreshRecordsUI(zoneId, perms);
        });

    } catch (err) {
        container.innerHTML = `
            <div class="mb-3"><a href="#dns" class="text-muted"><i class="ti ti-arrow-left me-1"></i>${t('dns.backToZones')}</a></div>
            <div class="alert alert-danger"><i class="ti ti-alert-triangle me-2"></i>${err.message}</div>`;
    }
}

function refreshRecordsUI(zoneId, perms) {
    const listContainer = document.getElementById('records-list-container');
    const countBadge = document.getElementById('records-count-badge');
    if (!listContainer) return;

    let filteredRecords = currentZoneRecords;
    if (currentTypeFilter) filteredRecords = filteredRecords.filter(r => r.record_type === currentTypeFilter);
    if (currentSearchTerm) {
        const term = currentSearchTerm.toLowerCase();
        filteredRecords = filteredRecords.filter(r =>
            r.name.toLowerCase().includes(term) || r.value.toLowerCase().includes(term)
        );
    }

    if (countBadge) countBadge.textContent = `(${filteredRecords.length}/${currentZoneRecords.length})`;
    listContainer.innerHTML = renderRecordsTable(filteredRecords, perms);
    setupRecordItemActions(zoneId, perms);
}

function renderRecordsTable(records, perms) {
    if (records.length === 0) {
        return `
            <div class="text-center py-4 text-muted">
                <i class="ti ti-list" style="font-size: 2rem;"></i>
                <p class="mt-2">${t('dns.noRecords')}</p>
            </div>`;
    }

    return `
        <div class="table-responsive">
            <table class="table table-vcenter">
                <thead>
                    <tr>
                        <th>${t('dns.type')}</th>
                        <th>${t('dns.name')}</th>
                        <th>${t('dns.value')}</th>
                        <th>${t('dns.ttl')}</th>
                        <th class="w-1">${t('dns.actions')}</th>
                    </tr>
                </thead>
                <tbody>
                    ${records.map(r => {
                        let extraBadges = '';
                        if (r.record_type === 'MX') {
                            extraBadges = `<div class="mt-1"><span class="badge bg-purple-lt" title="${t('dns.priority')}">${t('dns.priority')}: ${r.priority ?? 10}</span></div>`;
                        } else if (r.record_type === 'SRV') {
                            extraBadges = `<div class="mt-1">
                                <span class="badge bg-purple-lt">Pri: ${r.priority ?? 10}</span>
                                <span class="badge bg-azure-lt">Wt: ${r.weight ?? 0}</span>
                                <span class="badge bg-teal-lt">Port: ${r.port || '-'}</span>
                            </div>`;
                        }
                        return `
                        <tr>
                            <td><span class="badge bg-azure-lt">${escapeHtml(r.record_type)}</span></td>
                            <td><strong>${escapeHtml(r.name)}</strong></td>
                            <td>
                                <code>${escapeHtml(r.value)}</code>
                                ${extraBadges}
                            </td>
                            <td><small>${r.ttl || 'default'}</small></td>
                            <td>
                                ${perms.records ? `
                                <div class="btn-group btn-group-sm">
                                    <button class="btn btn-ghost-primary btn-edit-record"
                                            data-record='${JSON.stringify(r).replace(/'/g, "&#39;")}' title="${t('dns.edit')}">
                                        <i class="ti ti-edit"></i>
                                    </button>
                                    <button class="btn btn-ghost-danger btn-delete-record" data-id="${r.id}" title="${t('dns.delete')}">
                                        <i class="ti ti-trash"></i>
                                    </button>
                                </div>` : ''}
                            </td>
                        </tr>`;
                    }).join('')}
                </tbody>
            </table>
        </div>`;
}

function setupZoneDetailActions(zone, zoneId, container, perms) {
    document.getElementById('btn-new-record')?.addEventListener('click', () => {
        new bootstrap.Modal(document.getElementById('modal-new-record')).show();
        setupRecordTypeSegmented('new');
    });
    document.getElementById('btn-create-record')?.addEventListener('click', () => createRecord(zoneId));

    document.getElementById('btn-edit-zone')?.addEventListener('click', () => {
        document.getElementById('edit-zone-type').value = zone.zone_type;
        const fwdGroup = document.getElementById('edit-zone-fwd-group');
        if (fwdGroup) fwdGroup.style.display = zone.zone_type !== 'master' ? '' : 'none';
        let fwdServers = '';
        if (zone.forward_servers) {
            try { fwdServers = JSON.parse(zone.forward_servers).join(', '); } catch (e) { fwdServers = zone.forward_servers; }
        }
        const fwdInput = document.getElementById('edit-zone-fwd-servers');
        if (fwdInput) fwdInput.value = fwdServers;
        new bootstrap.Modal(document.getElementById('modal-edit-zone')).show();
    });
    document.getElementById('edit-zone-type')?.addEventListener('change', (e) => {
        const fwdGroup = document.getElementById('edit-zone-fwd-group');
        if (fwdGroup) fwdGroup.style.display = e.target.value !== 'master' ? '' : 'none';
    });
    document.getElementById('btn-save-zone')?.addEventListener('click', () => saveZone(zoneId, container, perms));

    document.getElementById('btn-delete-zone')?.addEventListener('click', async () => {
        if (!await confirmDialog(t('dns.confirmDeleteZone'), t('dns.confirmDeleteZoneMsgShort'))) return;
        try {
            await apiDelete(`/modules/dns/zones/${zoneId}`);
            showToast(t('dns.zoneDeleted'), 'success');
            window.location.hash = '#dns';
        } catch (err) { showToast(err.message, 'error'); }
    });
}

function setupRecordItemActions(zoneId, perms) {
    document.querySelectorAll('.btn-edit-record').forEach(btn => {
        btn.addEventListener('click', () => {
            const record = JSON.parse(btn.dataset.record);
            showEditRecordModal(record, zoneId, perms);
        });
    });

    document.querySelectorAll('.btn-delete-record').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!await confirmDialog(t('dns.confirmDeleteRecord'))) return;
            try {
                await apiDelete(`/modules/dns/records/${btn.dataset.id}`);
                showToast(t('dns.recordDeleted'), 'success');
                currentSearchTerm = '';
                currentTypeFilter = '';
                currentZoneRecords = [];
                await renderDnsZoneDetail(_container, zoneId, _perms);
            } catch (err) { showToast(err.message, 'error'); }
        });
    });
}

async function createRecord(zoneId) {
    const container = _container;
    const perms = _perms;
    const recordType = document.getElementById('new-record-type')?.value;
    const name = document.getElementById('new-record-name')?.value.trim();
    const value = document.getElementById('new-record-value')?.value.trim();
    const ttl = document.getElementById('new-record-ttl')?.value.trim();
    const priority = document.getElementById('new-record-priority')?.value.trim();
    const weight = document.getElementById('new-record-weight')?.value.trim();
    const port = document.getElementById('new-record-port')?.value.trim();

    if (!name || !value) {
        showToast(t('dns.nameValueRequired'), 'error');
        return;
    }

    const data = { record_type: recordType, name, value };
    if (ttl) data.ttl = parseInt(ttl);
    if (priority) data.priority = parseInt(priority);
    if (weight) data.weight = parseInt(weight);
    if (port) data.port = parseInt(port);

    try {
        const result = await apiPost(`/modules/dns/zones/${zoneId}/records`, data);
        showToast(
            result.applied ? t('dns.recordCreatedApplied') : `${t('dns.recordCreatedWarning')}: ${result.apply_message}`,
            result.applied ? 'success' : 'warning'
        );
        bootstrap.Modal.getInstance(document.getElementById('modal-new-record'))?.hide();
        currentSearchTerm = '';
        currentTypeFilter = '';
        currentZoneRecords = [];
        await renderDnsZoneDetail(container, zoneId, perms);
    } catch (err) { showToast(err.message, 'error'); }
}

async function saveZone(zoneId, container, perms) {
    const data = {};
    const desc = document.getElementById('edit-zone-desc')?.value.trim();
    const ttl = document.getElementById('edit-zone-ttl')?.value;
    const enabled = document.getElementById('edit-zone-enabled')?.checked;
    const zoneType = document.getElementById('edit-zone-type')?.value;
    const forwardServers = document.getElementById('edit-zone-fwd-servers')?.value.trim();

    data.description = desc;
    if (ttl) data.ttl_default = parseInt(ttl);
    data.enabled = enabled;
    data.zone_type = zoneType;

    if (zoneType !== 'master') {
        if (!forwardServers) {
            showToast(t('dns.forwardServersRequired'), 'error');
            return;
        }
        data.forward_servers = JSON.stringify(forwardServers.split(',').map(s => s.trim()).filter(Boolean));
    } else {
        data.forward_servers = null;
    }

    try {
        const result = await apiPatch(`/modules/dns/zones/${zoneId}`, data);
        showToast(
            result.applied ? t('dns.zoneUpdatedApplied') : `${t('dns.zoneUpdatedWarning')}: ${result.apply_message}`,
            result.applied ? 'success' : 'warning'
        );
        bootstrap.Modal.getInstance(document.getElementById('modal-edit-zone'))?.hide();
        await renderDnsZoneDetail(container, zoneId, perms);
    } catch (err) { showToast(err.message, 'error'); }
}

// ============================================================
//  RECORD TYPE HELPERS
// ============================================================

function getValueHints() {
    return {
        A:    { placeholder: '192.168.1.1',         hint: t('dns.hintA') },
        AAAA: { placeholder: '2001:db8::1',          hint: t('dns.hintAAAA') },
        CNAME:{ placeholder: 'target.example.com.', hint: t('dns.hintCNAME') },
        MX:   { placeholder: 'mail.example.com.',   hint: t('dns.hintMX') },
        TXT:  { placeholder: 'v=spf1 include:...',  hint: t('dns.hintTXT') },
        SRV:  { placeholder: 'target.example.com.', hint: t('dns.hintSRV') },
        NS:   { placeholder: 'ns1.example.com.',    hint: t('dns.hintNS') },
        PTR:  { placeholder: 'host.example.com.',   hint: t('dns.hintPTR') },
    };
}

function setupRecordTypeSegmented(prefix) {
    const nav = document.getElementById(`${prefix}-record-type-nav`);
    const hiddenInput = document.getElementById(`${prefix}-record-type`);
    const valueInput = document.getElementById(`${prefix}-record-value`);
    const valueHint = document.getElementById(`${prefix}-record-value-hint`);
    const priorityRow = document.getElementById(`${prefix}-record-priority-row`);
    const srvRow = document.getElementById(`${prefix}-record-srv-row`);

    if (!nav) return;

    function updateFieldsForType(type) {
        hiddenInput.value = type;
        const info = getValueHints()[type] || { placeholder: '', hint: '' };
        if (valueInput) valueInput.placeholder = info.placeholder;
        if (valueHint) valueHint.textContent = info.hint;
        if (priorityRow) priorityRow.style.display = ['MX', 'SRV'].includes(type) ? '' : 'none';
        if (srvRow) srvRow.style.display = type === 'SRV' ? '' : 'none';
    }

    nav.addEventListener('click', (e) => {
        e.preventDefault();
        const link = e.target.closest('.nav-link');
        if (!link) return;
        nav.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
        link.classList.add('active');
        updateFieldsForType(link.dataset.type);
    });

    updateFieldsForType(hiddenInput.value);
}

function showEditRecordModal(record, zoneId, perms) {
    document.getElementById('edit-record-id').value = record.id;
    document.getElementById('edit-record-name').value = record.name;
    document.getElementById('edit-record-value').value = record.value;
    document.getElementById('edit-record-type').value = record.record_type;
    document.getElementById('edit-record-ttl').value = record.ttl || '';
    document.getElementById('edit-record-priority').value = record.priority ?? 10;
    document.getElementById('edit-record-weight').value = record.weight ?? 0;
    document.getElementById('edit-record-port').value = record.port || '';

    const nav = document.getElementById('edit-record-type-nav');
    nav.querySelectorAll('.nav-link').forEach(l => {
        l.classList.toggle('active', l.dataset.type === record.record_type);
    });
    setupRecordTypeSegmented('edit');

    const modal = new bootstrap.Modal(document.getElementById('modal-edit-record'));
    modal.show();

    const saveBtn = document.getElementById('btn-save-record');
    const newBtn = saveBtn.cloneNode(true);
    saveBtn.parentNode.replaceChild(newBtn, saveBtn);
    newBtn.id = 'btn-save-record';
    newBtn.addEventListener('click', () => editRecord(zoneId));
}

async function editRecord(zoneId) {
    const perms = _perms;
    const id = document.getElementById('edit-record-id')?.value;
    const recordType = document.getElementById('edit-record-type')?.value;
    const name = document.getElementById('edit-record-name')?.value.trim();
    const value = document.getElementById('edit-record-value')?.value.trim();
    const ttl = document.getElementById('edit-record-ttl')?.value.trim();
    const priority = document.getElementById('edit-record-priority')?.value.trim();
    const weight = document.getElementById('edit-record-weight')?.value.trim();
    const port = document.getElementById('edit-record-port')?.value.trim();

    if (!name || !value) {
        showToast(t('dns.nameValueRequired'), 'error');
        return;
    }

    const data = { record_type: recordType, name, value };
    if (ttl) data.ttl = parseInt(ttl); else data.ttl = null;
    if (['MX', 'SRV'].includes(recordType) && priority) data.priority = parseInt(priority);
    if (recordType === 'SRV') {
        if (weight) data.weight = parseInt(weight);
        if (port) data.port = parseInt(port);
    }

    try {
        const result = await apiPatch(`/modules/dns/records/${id}`, data);
        showToast(
            result.applied ? t('dns.recordUpdatedApplied') : `${t('dns.recordUpdatedWarning')}: ${result.apply_message}`,
            result.applied ? 'success' : 'warning'
        );
        bootstrap.Modal.getInstance(document.getElementById('modal-edit-record'))?.hide();
        currentSearchTerm = '';
        currentTypeFilter = '';
        currentZoneRecords = [];
        await renderDnsZoneDetail(_container, zoneId, perms);
    } catch (err) { showToast(err.message, 'error'); }
}

// ============================================================
//  MODALS
// ============================================================

function renderNewZoneModal() {
    return `
        <div class="modal fade" id="modal-new-zone" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${t('dns.newZoneTitle')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">${t('dns.zoneName')}</label>
                            <input type="text" class="form-control" id="new-zone-name" placeholder="es. lab.local">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">${t('dns.type')}</label>
                            <select class="form-select" id="new-zone-type">
                                <option value="master">${t('dns.zoneMasterDesc')}</option>
                                <option value="forward">${t('dns.zoneForwardDesc')}</option>
                                <option value="stub">${t('dns.zoneStubDesc')}</option>
                            </select>
                        </div>
                        <div class="mb-3" id="new-zone-fwd-group" style="display:none;">
                            <label class="form-label">${t('dns.remoteServers')}</label>
                            <input type="text" class="form-control" id="new-zone-fwd-servers" placeholder="10.0.0.1, 10.0.0.2">
                            <small class="form-hint">${t('dns.ipSeparated')}</small>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">${t('dns.descOptional')}</label>
                            <input type="text" class="form-control" id="new-zone-desc" placeholder="es. Zona interna laboratorio">
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">${t('dns.cancel')}</button>
                        <button class="btn btn-primary" id="btn-create-zone">
                            <i class="ti ti-check me-1"></i>${t('dns.createZone')}
                        </button>
                    </div>
                </div>
            </div>
        </div>`;
}

function renderNewRecordModal(zone) {
    return `
        <div class="modal fade" id="modal-new-record" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title"><i class="ti ti-plus me-2"></i>${t('dns.newRecordTitle', { zone: escapeHtml(zone.name) })}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-4">
                            <label class="form-label">${t('dns.recordType')}</label>
                            <nav class="nav nav-segmented nav-8" role="tablist" id="new-record-type-nav">
                                ${RECORD_TYPES.map((tp, i) => `
                                    <button class="nav-link ${i === 0 ? 'active' : ''}" role="tab" data-bs-toggle="tab"
                                            data-type="${tp}" aria-selected="${i === 0}" ${i !== 0 ? 'tabindex="-1"' : ''}>${tp}</button>
                                `).join('')}
                            </nav>
                            <input type="hidden" id="new-record-type" value="A">
                        </div>
                        <div class="row">
                            <div class="col-md-5 mb-3">
                                <label class="form-label">${t('dns.name')}</label>
                                <div class="input-group">
                                    <input type="text" class="form-control" id="new-record-name" placeholder="@">
                                    <span class="input-group-text">.${escapeHtml(zone.name)}</span>
                                </div>
                                <small class="form-hint">${t('dns.recordNameHint')}</small>
                            </div>
                            <div class="col-md-7 mb-3">
                                <label class="form-label">${t('dns.value')}</label>
                                <input type="text" class="form-control" id="new-record-value" placeholder="192.168.1.1">
                                <small class="form-hint" id="new-record-value-hint">${t('dns.hintA')}</small>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-4 mb-3">
                                <label class="form-label">${t('dns.ttlOptional')}</label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="new-record-ttl" placeholder="${zone.ttl_default}">
                                    <span class="input-group-text">sec</span>
                                </div>
                            </div>
                            <div class="col-md-4 mb-3" id="new-record-priority-row" style="display:none;">
                                <label class="form-label">${t('dns.priority')}</label>
                                <input type="number" class="form-control" id="new-record-priority" value="10">
                            </div>
                        </div>
                        <div class="row" id="new-record-srv-row" style="display:none;">
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Weight</label>
                                <input type="number" class="form-control" id="new-record-weight" value="0">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Port</label>
                                <input type="number" class="form-control" id="new-record-port" placeholder="443">
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">${t('dns.cancel')}</button>
                        <button class="btn btn-primary" id="btn-create-record">
                            <i class="ti ti-check me-1"></i>${t('dns.createRecord')}
                        </button>
                    </div>
                </div>
            </div>
        </div>`;
}

function renderEditRecordModal() {
    return `
        <div class="modal fade" id="modal-edit-record" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title"><i class="ti ti-edit me-2"></i>${t('dns.editRecordTitle')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <input type="hidden" id="edit-record-id">
                        <div class="mb-4">
                            <label class="form-label">${t('dns.recordType')}</label>
                            <nav class="nav nav-segmented nav-8" role="tablist" id="edit-record-type-nav">
                                ${RECORD_TYPES.map(tp => `
                                    <button class="nav-link" role="tab" data-bs-toggle="tab"
                                            data-type="${tp}" aria-selected="false" tabindex="-1">${tp}</button>
                                `).join('')}
                            </nav>
                            <input type="hidden" id="edit-record-type" value="A">
                        </div>
                        <div class="row">
                            <div class="col-md-5 mb-3">
                                <label class="form-label">${t('dns.name')}</label>
                                <input type="text" class="form-control" id="edit-record-name" placeholder="@">
                            </div>
                            <div class="col-md-7 mb-3">
                                <label class="form-label">${t('dns.value')}</label>
                                <input type="text" class="form-control" id="edit-record-value">
                                <small class="form-hint" id="edit-record-value-hint"></small>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-4 mb-3">
                                <label class="form-label">${t('dns.ttlOptional')}</label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="edit-record-ttl">
                                    <span class="input-group-text">sec</span>
                                </div>
                            </div>
                            <div class="col-md-4 mb-3" id="edit-record-priority-row" style="display:none;">
                                <label class="form-label">${t('dns.priority')}</label>
                                <input type="number" class="form-control" id="edit-record-priority" value="10">
                            </div>
                        </div>
                        <div class="row" id="edit-record-srv-row" style="display:none;">
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Weight</label>
                                <input type="number" class="form-control" id="edit-record-weight" value="0">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Port</label>
                                <input type="number" class="form-control" id="edit-record-port">
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">${t('dns.cancel')}</button>
                        <button class="btn btn-primary" id="btn-save-record">
                            <i class="ti ti-check me-1"></i>${t('dns.saveRecord')}
                        </button>
                    </div>
                </div>
            </div>
        </div>`;
}

function renderEditZoneModal(zone) {
    return `
        <div class="modal fade" id="modal-edit-zone" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title"><i class="ti ti-edit me-2"></i>${t('dns.editZoneTitle')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">${t('dns.type')}</label>
                            <select class="form-select" id="edit-zone-type">
                                <option value="master">${t('dns.zoneMasterDesc')}</option>
                                <option value="forward">${t('dns.zoneForwardDesc')}</option>
                                <option value="stub">${t('dns.zoneStubDesc')}</option>
                            </select>
                        </div>
                        <div class="mb-3" id="edit-zone-fwd-group" style="display:none;">
                            <label class="form-label">${t('dns.remoteServers')}</label>
                            <input type="text" class="form-control" id="edit-zone-fwd-servers" placeholder="10.0.0.1, 10.0.0.2">
                            <small class="form-hint">${t('dns.ipSeparated')}</small>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">${t('dns.description')}</label>
                            <input type="text" class="form-control" id="edit-zone-desc" value="${escapeHtml(zone.description || '')}">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">${t('dns.ttlDefaultSec')}</label>
                            <input type="number" class="form-control" id="edit-zone-ttl" value="${zone.ttl_default}">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">${t('dns.status')}</label>
                            <div class="form-check form-switch">
                                <input class="form-check-input" type="checkbox" id="edit-zone-enabled" ${zone.enabled ? 'checked' : ''}>
                                <label class="form-check-label">${t('dns.enabled')}</label>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">${t('dns.cancel')}</button>
                        <button class="btn btn-primary" id="btn-save-zone">
                            <i class="ti ti-check me-1"></i>${t('dns.save')}
                        </button>
                    </div>
                </div>
            </div>
        </div>`;
}

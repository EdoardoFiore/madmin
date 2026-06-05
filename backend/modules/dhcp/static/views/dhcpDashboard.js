/**
 * DHCP Module - Dashboard View
 *
 * Service status, stats cards, subnet list, create modal.
 */

import { t } from '/static/js/i18n.js';
import { apiGet, apiPost, apiDelete, apiPatch } from '/static/js/api.js';
import { showToast, confirmDialog, loadingSpinner } from '/static/js/utils.js';

let networkInterfaces = [];

// ============================================================
//  ENTRY POINT
// ============================================================

export async function renderDhcpDashboard(container, canManage) {
    container.innerHTML = `<div class="text-center py-5">${loadingSpinner()}</div>`;

    try {
        const [status, subnets] = await Promise.all([
            apiGet('/modules/dhcp/status'),
            apiGet('/modules/dhcp/subnets')
        ]);

        container.innerHTML = `
            <!-- Status & Stats -->
            <div class="row row-deck row-cards mb-3">
                <div class="col-sm-6 col-lg-3">
                    <div class="card">
                        <div class="card-body">
                            <div class="d-flex align-items-center">
                                <div class="subheader">${t('dhcp.serviceStatus')}</div>
                            </div>
                            <div class="d-flex align-items-baseline mt-1">
                                <span class="status-dot ${status.running ? 'status-dot-animated bg-success' : 'bg-danger'} me-2"></span>
                                <span class="h1 mb-0">${status.running ? t('dhcp.statusActive') : t('dhcp.statusStopped')}</span>
                            </div>
                            ${canManage ? `
                            <div class="mt-2">
                                ${status.running
                                    ? `<button class="btn btn-sm btn-warning" id="btn-stop"><i class="ti ti-player-stop me-1"></i>${t('dhcp.stop')}</button>`
                                    : `<button class="btn btn-sm btn-success" id="btn-start"><i class="ti ti-player-play me-1"></i>${t('dhcp.start')}</button>`}
                            </div>` : ''}
                        </div>
                    </div>
                </div>
                <div class="col-sm-6 col-lg-3">
                    <div class="card">
                        <div class="card-body">
                            <div class="subheader">${t('dhcp.subnet')}</div>
                            <div class="h1 mb-0 mt-1">${status.total_subnets}</div>
                        </div>
                    </div>
                </div>
                <div class="col-sm-6 col-lg-3">
                    <div class="card">
                        <div class="card-body">
                            <div class="subheader">${t('dhcp.reservations')}</div>
                            <div class="h1 mb-0 mt-1">${status.total_hosts}</div>
                        </div>
                    </div>
                </div>
                <div class="col-sm-6 col-lg-3">
                    <div class="card">
                        <div class="card-body">
                            <div class="subheader">${t('dhcp.activeLeases')}</div>
                            <div class="h1 mb-0 mt-1">${status.total_leases}</div>
                            ${status.config_valid !== null ? `
                            <div class="mt-1">
                                <span class="badge ${status.config_valid ? 'bg-success' : 'bg-danger'}-lt">
                                    <i class="ti ti-${status.config_valid ? 'check' : 'alert-triangle'} me-1"></i>
                                    ${status.config_valid ? t('dhcp.configValid') : t('dhcp.configInvalid')}
                                </span>
                            </div>` : ''}
                        </div>
                    </div>
                </div>
            </div>

            <!-- Subnets Table -->
            <div class="card">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h3 class="card-title"><i class="ti ti-affiliate me-2"></i>${t('dhcp.dhcpSubnets')}</h3>
                    <div class="d-flex gap-2">
                        ${canManage ? `
                        <button class="btn btn-outline-primary" id="btn-apply" title="${t('dhcp.applyBtnTitle')}">
                            <i class="ti ti-reload me-1"></i>${t('dhcp.applyConfig')}
                        </button>
                        <button class="btn btn-primary" id="btn-new-subnet">
                            <i class="ti ti-plus me-1"></i>${t('dhcp.newSubnet')}
                        </button>` : ''}
                    </div>
                </div>
                <div class="card-body" id="subnets-list">
                    ${renderSubnetsTable(subnets, canManage)}
                </div>
            </div>

            <!-- New Subnet Modal -->
            ${renderNewSubnetModal()}

            <!-- Config Preview Modal -->
            <div class="modal fade" id="modal-config-preview" tabindex="-1">
                <div class="modal-dialog modal-lg">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title"><i class="ti ti-file-code me-2"></i>${t('dhcp.configPreview')}</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <pre id="config-preview-content" class="p-3 bg-dark text-light rounded" style="max-height: 500px; overflow-y: auto; font-size: 0.85rem;"></pre>
                        </div>
                    </div>
                </div>
            </div>
        `;

        setupDashboardActions(status, container, canManage);
    } catch (err) {
        container.innerHTML = `<div class="alert alert-danger"><i class="ti ti-alert-triangle me-2"></i>${err.message}</div>`;
    }
}

// ============================================================
//  SUBNET TABLE
// ============================================================

function renderSubnetsTable(subnets, canManage) {
    if (subnets.length === 0) {
        return `
            <div class="text-center py-5 text-muted">
                <i class="ti ti-network-off" style="font-size: 3rem;"></i>
                <p class="mt-2">${t('dhcp.noSubnets')}</p>
                <small>${t('dhcp.noSubnetsHint')}</small>
            </div>`;
    }

    return `
        <div class="table-responsive">
            <table class="table table-vcenter card-table table-hover">
                <thead>
                    <tr>
                        <th style="width: 50px;">${t('dhcp.active')}</th>
                        <th>${t('dhcp.name')}</th>
                        <th>Network</th>
                        <th>${t('dhcp.interface')}</th>
                        <th>Range</th>
                        <th>Gateway</th>
                        <th>${t('dhcp.reservations')}</th>
                        <th>Lease</th>
                        <th class="w-1"></th>
                    </tr>
                </thead>
                <tbody>
                    ${subnets.map(s => `
                        <tr class="subnet-row ${!s.enabled ? 'text-muted' : ''}" data-id="${s.id}" style="cursor: pointer;">
                            <td onclick="event.stopPropagation();">
                                ${s.managed ? `
                                <span class="status-dot bg-success" title="${t('dhcp.managedLan')}"></span>`
                                : canManage ? `
                                <label class="form-check form-switch mb-0">
                                    <input class="form-check-input subnet-toggle" type="checkbox"
                                           data-id="${s.id}" ${s.enabled ? 'checked' : ''}>
                                </label>` : `
                                <span class="status-dot ${s.enabled ? 'bg-success' : 'bg-secondary'}"></span>
                                `}
                            </td>
                            <td>
                                <a href="#dhcp/${s.id}" class="text-reset">
                                    <strong>${s.name}</strong>
                                </a>
                                ${s.managed ? `<span class="badge bg-azure-lt ms-1" title="${t('dhcp.managedLanHint')}"><i class="ti ti-lock"></i> ${t('dhcp.managedLan')}</span>` : ''}
                                <div class="small text-muted">${s.domain_name || ''}</div>
                            </td>
                            <td><code>${s.network}</code></td>
                            <td><code>${s.interface}</code></td>
                            <td><small>${s.range_start} — ${s.range_end}</small></td>
                            <td><code>${s.gateway}</code></td>
                            <td>
                                <span class="badge bg-blue-lt">${s.host_count}</span>
                            </td>
                            <td>
                                <span class="badge bg-green-lt">${s.active_leases}</span>
                            </td>
                            <td>
                                <div class="btn-group btn-group-sm" onclick="event.stopPropagation();">
                                    ${canManage && !s.managed ? `
                                    <button class="btn btn-ghost-danger btn-delete-subnet" data-id="${s.id}" title="${t('dhcp.delete')}">
                                        <i class="ti ti-trash"></i>
                                    </button>` : s.managed ? `<i class="ti ti-lock text-muted" title="${t('dhcp.managedLanHint')}"></i>` : ''}
                                </div>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>`;
}

// ============================================================
//  NEW SUBNET MODAL
// ============================================================

function renderNewSubnetModal() {
    return `
        <div class="modal fade" id="modal-new-subnet" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${t('dhcp.newSubnetTitle')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">${t('dhcp.name')}</label>
                                <input type="text" class="form-control" id="new-subnet-name" placeholder="LAN Ufficio">
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label">${t('dhcp.interface')}</label>
                                <select class="form-select" id="new-subnet-interface">
                                    <option value="">${t('dhcp.selectInterface')}</option>
                                </select>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-4 mb-3">
                                <label class="form-label">${t('dhcp.networkCIDR')}</label>
                                <input type="text" class="form-control" id="new-subnet-network" placeholder="192.168.1.0/24">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">${t('dhcp.rangeStart')}</label>
                                <input type="text" class="form-control" id="new-subnet-range-start" placeholder="192.168.1.100">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">${t('dhcp.rangeEnd')}</label>
                                <input type="text" class="form-control" id="new-subnet-range-end" placeholder="192.168.1.200">
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Gateway</label>
                                <input type="text" class="form-control" id="new-subnet-gateway" placeholder="192.168.1.1">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">${t('dhcp.dnsServers')}</label>
                                <input type="text" class="form-control" id="new-subnet-dns" value="8.8.8.8, 1.1.1.1" placeholder="8.8.8.8, 1.1.1.1">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">${t('dhcp.domainName')}</label>
                                <input type="text" class="form-control" id="new-subnet-domain" placeholder="example.local">
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">${t('dhcp.leaseTimeSec')}</label>
                                <input type="number" class="form-control" id="new-subnet-lease-time" value="86400">
                                <small class="form-hint">${t('dhcp.leaseTimeHint')}</small>
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label">${t('dhcp.maxLeaseTimeSec')}</label>
                                <input type="number" class="form-control" id="new-subnet-max-lease" value="172800">
                                <small class="form-hint">${t('dhcp.maxLeaseTimeHint')}</small>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">${t('dhcp.cancel')}</button>
                        <button class="btn btn-primary" id="btn-create-subnet">
                            <i class="ti ti-check me-1"></i>${t('dhcp.createSubnetBtn')}
                        </button>
                    </div>
                </div>
            </div>
        </div>`;
}

// ============================================================
//  EVENT HANDLERS
// ============================================================

function setupDashboardActions(status, container, canManage) {
    // Start
    document.getElementById('btn-start')?.addEventListener('click', async () => {
        try {
            await apiPost('/modules/dhcp/start');
            showToast(t('dhcp.serviceStarted'), 'success');
            await renderDhcpDashboard(container, canManage);
        } catch (err) { showToast(err.message, 'error'); }
    });

    // Stop
    document.getElementById('btn-stop')?.addEventListener('click', async () => {
        if (!await confirmDialog(t('dhcp.confirmStopTitle'), t('dhcp.confirmStopMsg'))) return;
        try {
            await apiPost('/modules/dhcp/stop');
            showToast(t('dhcp.serviceStopped'), 'success');
            await renderDhcpDashboard(container, canManage);
        } catch (err) { showToast(err.message, 'error'); }
    });

    // Apply config
    document.getElementById('btn-apply')?.addEventListener('click', async () => {
        if (!await confirmDialog(t('dhcp.confirmApplyTitle'), t('dhcp.confirmApplyMsg'))) return;

        const btn = document.getElementById('btn-apply');
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('dhcp.applying')}`;
        try {
            await apiPost('/modules/dhcp/apply');
            showToast(t('dhcp.configApplied'), 'success');
            await renderDhcpDashboard(container, canManage);
        } catch (err) {
            showToast(err.message, 'error');
            btn.disabled = false;
            btn.innerHTML = `<i class="ti ti-reload me-1"></i>${t('dhcp.applyConfig')}`;
        }
    });

    // New Subnet
    document.getElementById('btn-new-subnet')?.addEventListener('click', async () => {
        await loadInterfaces();
        populateInterfaceSelect('new-subnet-interface');
        new bootstrap.Modal(document.getElementById('modal-new-subnet')).show();
    });

    document.getElementById('btn-create-subnet')?.addEventListener('click', () => createSubnet(container, canManage));

    // Subnet row click
    document.querySelectorAll('.subnet-row').forEach(row => {
        row.addEventListener('click', (e) => {
            if (e.target.closest('.btn-group')) return;
            window.location.hash = `#dhcp/${row.dataset.id}`;
        });
    });

    // Delete subnet
    document.querySelectorAll('.btn-delete-subnet').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            if (!await confirmDialog(t('dhcp.confirmDeleteSubnetTitle'), t('dhcp.confirmDeleteSubnetMsg'))) return;
            try {
                await apiDelete(`/modules/dhcp/subnets/${btn.dataset.id}`);
                showToast(t('dhcp.subnetDeleted'), 'success');
                await renderDhcpDashboard(container, canManage);
            } catch (err) { showToast(err.message, 'error'); }
        });
    });

    // Subnet toggle
    document.querySelectorAll('.subnet-toggle').forEach(toggle => {
        toggle.addEventListener('change', async () => {
            const id = toggle.dataset.id;
            const enabled = toggle.checked;
            try {
                await apiPatch(`/modules/dhcp/subnets/${id}`, { enabled });
                showToast(
                    enabled ? t('dhcp.subnetEnabled') : t('dhcp.subnetDisabled'),
                    enabled ? 'success' : 'warning'
                );
                await renderDhcpDashboard(container, canManage);
            } catch (err) {
                toggle.checked = !enabled;
                showToast(err.message, 'error');
            }
        });
    });
}

// ============================================================
//  HELPERS
// ============================================================

async function loadInterfaces() {
    try {
        const data = await apiGet('/modules/dhcp/interfaces');
        networkInterfaces = data.interfaces || [];
    } catch (err) {
        console.warn('Could not load interfaces:', err);
        networkInterfaces = [{ name: 'eth0', state: 'unknown', addresses: [] }];
    }
}

function populateInterfaceSelect(selectId) {
    const select = document.getElementById(selectId);
    if (!select) return;
    const lanIfaces = networkInterfaces.filter(iface => iface.name !== 'eth0');
    select.innerHTML = `<option value="">${t('dhcp.selectInterface')}</option>` +
        lanIfaces.map(iface =>
            `<option value="${iface.name}" ${iface.state === 'up' ? 'class="fw-bold"' : ''}>
                ${iface.name} ${iface.state === 'up' ? '●' : '○'} ${iface.addresses?.join(', ') || ''}
            </option>`
        ).join('');
}

async function createSubnet(container, canManage) {
    const name = document.getElementById('new-subnet-name').value.trim();
    const network = document.getElementById('new-subnet-network').value.trim();
    const rangeStart = document.getElementById('new-subnet-range-start').value.trim();
    const rangeEnd = document.getElementById('new-subnet-range-end').value.trim();
    const gateway = document.getElementById('new-subnet-gateway').value.trim();
    const dns = document.getElementById('new-subnet-dns').value.trim();
    const domain = document.getElementById('new-subnet-domain').value.trim();
    const iface = document.getElementById('new-subnet-interface').value;
    const leaseTime = parseInt(document.getElementById('new-subnet-lease-time').value) || 86400;
    const maxLease = parseInt(document.getElementById('new-subnet-max-lease').value) || 172800;

    if (!name || !network || !rangeStart || !rangeEnd || !gateway || !iface) {
        showToast(t('dhcp.fillAllFields'), 'error');
        return;
    }

    try {
        await apiPost('/modules/dhcp/subnets', {
            name,
            network,
            range_start: rangeStart,
            range_end: rangeEnd,
            gateway,
            dns_servers: dns || '8.8.8.8, 1.1.1.1',
            domain_name: domain || null,
            interface: iface,
            lease_time: leaseTime,
            max_lease_time: maxLease
        });
        showToast(t('dhcp.subnetCreated'), 'success');
        bootstrap.Modal.getInstance(document.getElementById('modal-new-subnet'))?.hide();
        await renderDhcpDashboard(container, canManage);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

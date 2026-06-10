/**
 * DHCP Module - Subnet Detail View
 *
 * Subnet info, static reservations (hosts), active leases, edit modal.
 */

import { t } from '/static/js/i18n.js';
import { apiGet, apiPost, apiDelete, apiPatch } from '/static/js/api.js';
import { showToast, confirmDialog } from '/static/js/utils.js';

let networkInterfaces = [];

// ============================================================
//  ENTRY POINT
// ============================================================

export async function renderDhcpDetail(container, subnetId, canManage, canReservations) {
    try {
        const [subnet, hosts, leases] = await Promise.all([
            apiGet(`/modules/dhcp/subnets/${subnetId}`),
            apiGet(`/modules/dhcp/subnets/${subnetId}/hosts`),
            apiGet(`/modules/dhcp/subnets/${subnetId}/leases`)
        ]);

        container.innerHTML = `
            <!-- Back Link -->
            <div class="mb-3">
                <a href="#dhcp" class="text-muted">
                    <i class="ti ti-arrow-left me-1"></i>${t('dhcp.backToSubnets')}
                </a>
            </div>

            <!-- Subnet Info Card -->
            <div class="card mb-3">
                <div class="card-header">
                    <div class="d-flex justify-content-between align-items-center w-100">
                        <div>
                            <h3 class="card-title mb-0">
                                <span class="status-dot ${subnet.enabled ? 'bg-success' : 'bg-secondary'} me-2"></span>
                                ${subnet.name}
                            </h3>
                            <small class="text-muted">${subnet.network} ${t('dhcp.on')} ${subnet.interface}</small>
                            ${subnet.managed ? `<span class="badge bg-azure-lt ms-2" title="${t('dhcp.managedLanHint')}"><i class="ti ti-lock me-1"></i>${t('dhcp.managedLan')}</span>` : ''}
                        </div>
                        ${canManage ? `
                        <div class="btn-group">
                            <button class="btn btn-outline-primary" id="btn-edit-subnet">
                                <i class="ti ti-edit me-1"></i>${t('dhcp.edit')}
                            </button>
                            ${subnet.managed ? '' : `
                            <button class="btn btn-outline-danger" id="btn-delete-subnet">
                                <i class="ti ti-trash me-1"></i>${t('dhcp.delete')}
                            </button>`}
                        </div>` : ''}
                    </div>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-2">
                            <span class="text-muted">Network</span><br>
                            <code>${subnet.network}</code>
                        </div>
                        <div class="col-md-2">
                            <span class="text-muted">Range</span><br>
                            <small>${subnet.range_start}<br>${subnet.range_end}</small>
                        </div>
                        <div class="col-md-2">
                            <span class="text-muted">Gateway</span><br>
                            <code>${subnet.gateway}</code>
                        </div>
                        <div class="col-md-2">
                            <span class="text-muted">DNS</span><br>
                            <small>${subnet.dns_servers}</small>
                        </div>
                        <div class="col-md-2">
                            <span class="text-muted">${t('dhcp.leaseTime')}</span><br>
                            <small>${formatLeaseTime(subnet.lease_time)}</small>
                        </div>
                        <div class="col-md-2">
                            <span class="text-muted">${t('dhcp.interface')}</span><br>
                            <code>${subnet.interface}</code>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Tabs -->
            <ul class="nav nav-tabs" role="tablist">
                <li class="nav-item" role="presentation">
                    <button class="nav-link active" id="tab-hosts" data-bs-toggle="tab" data-bs-target="#pane-hosts" type="button">
                        <i class="ti ti-device-desktop me-1"></i>${t('dhcp.reservationsTab', { n: hosts.length })}
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link" id="tab-leases" data-bs-toggle="tab" data-bs-target="#pane-leases" type="button">
                        <i class="ti ti-clock me-1"></i>${t('dhcp.leasesTab', { n: leases.length })}
                    </button>
                </li>
            </ul>

            <div class="tab-content">
                <!-- Hosts Tab -->
                <div class="tab-pane fade show active" id="pane-hosts" role="tabpanel">
                    <div class="card card-body border-top-0 rounded-top-0">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <h4 class="mb-0">${t('dhcp.staticReservations')}</h4>
                            ${canReservations ? `
                            <button class="btn btn-primary" id="btn-new-host">
                                <i class="ti ti-plus me-1"></i>${t('dhcp.newReservation')}
                            </button>` : ''}
                        </div>
                        ${renderHostsTable(hosts, subnetId, canReservations)}
                    </div>
                </div>

                <!-- Leases Tab -->
                <div class="tab-pane fade" id="pane-leases" role="tabpanel">
                    <div class="card card-body border-top-0 rounded-top-0">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <h4 class="mb-0">${t('dhcp.activeLeases')}</h4>
                            <button class="btn btn-outline-secondary btn-sm" id="btn-refresh-leases">
                                <i class="ti ti-refresh me-1"></i>${t('dhcp.refresh')}
                            </button>
                        </div>
                        <div id="leases-table-container">
                            ${renderLeasesTable(leases, hosts, canReservations)}
                        </div>
                    </div>
                </div>
            </div>

            <!-- New/Edit Host Modal -->
            ${renderHostModal(subnet)}

            <!-- Edit Subnet Modal -->
            ${renderEditSubnetModal(subnet)}
        `;

        setupDetailActions(subnet, subnetId, container, canManage, canReservations);
    } catch (err) {
        container.innerHTML = `
            <div class="mb-3"><a href="#dhcp" class="text-muted"><i class="ti ti-arrow-left me-1"></i>${t('dhcp.backToSubnets')}</a></div>
            <div class="alert alert-danger"><i class="ti ti-alert-triangle me-2"></i>${err.message}</div>`;
    }
}

// ============================================================
//  HOSTS TABLE
// ============================================================

function renderHostsTable(hosts, subnetId, canReservations) {
    if (hosts.length === 0) {
        return `
            <div class="text-center py-4 text-muted">
                <i class="ti ti-device-desktop-off" style="font-size: 2rem;"></i>
                <p class="mt-2">${t('dhcp.noReservations')}</p>
                <small>${t('dhcp.noReservationsHint')}</small>
            </div>`;
    }

    return `
        <div class="table-responsive">
            <table class="table table-vcenter">
                <thead>
                    <tr>
                        <th>${t('dhcp.hostname')}</th>
                        <th>${t('dhcp.macAddress')}</th>
                        <th>${t('dhcp.ipAddress')}</th>
                        <th>${t('dhcp.description')}</th>
                        <th class="w-1">${t('dhcp.actions')}</th>
                    </tr>
                </thead>
                <tbody>
                    ${hosts.map(h => `
                        <tr>
                            <td><strong>${h.hostname}</strong></td>
                            <td><code>${h.mac_address}</code></td>
                            <td><code>${h.ip_address}</code></td>
                            <td><small class="text-muted">${h.description || '—'}</small></td>
                            <td>
                                ${canReservations ? `
                                <div class="btn-group btn-group-sm">
                                    <button class="btn btn-ghost-primary btn-edit-host"
                                            data-id="${h.id}" data-hostname="${h.hostname}"
                                            data-mac="${h.mac_address}" data-ip="${h.ip_address}"
                                            data-desc="${h.description || ''}" title="${t('dhcp.edit')}">
                                        <i class="ti ti-edit"></i>
                                    </button>
                                    <button class="btn btn-ghost-danger btn-delete-host"
                                            data-id="${h.id}" data-subnet="${subnetId}" title="${t('dhcp.delete')}">
                                        <i class="ti ti-trash"></i>
                                    </button>
                                </div>` : ''}
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>`;
}

// ============================================================
//  LEASES TABLE
// ============================================================

function renderLeasesTable(leases, hosts = [], canReservations) {
    if (leases.length === 0) {
        return `
            <div class="text-center py-4 text-muted">
                <i class="ti ti-clock-off" style="font-size: 2rem;"></i>
                <p class="mt-2">${t('dhcp.noActiveLeases')}</p>
            </div>`;
    }

    const reservedMacs = new Set(hosts.map(h => h.mac_address?.toLowerCase()));

    return `
        <div class="table-responsive">
            <table class="table table-vcenter table-striped">
                <thead>
                    <tr>
                        <th>${t('dhcp.ipAddress')}</th>
                        <th>${t('dhcp.macAddress')}</th>
                        <th>${t('dhcp.hostname')}</th>
                        <th>${t('dhcp.starts')}</th>
                        <th>${t('dhcp.expires')}</th>
                        <th>${t('dhcp.state')}</th>
                        ${canReservations ? `<th class="w-1">${t('dhcp.actions')}</th>` : ''}
                    </tr>
                </thead>
                <tbody>
                    ${leases.map(l => {
                        const isReserved = l.mac_address && reservedMacs.has(l.mac_address.toLowerCase());
                        return `
                        <tr class="${isReserved ? 'fw-bold' : ''}">
                            <td><code>${l.ip_address}</code></td>
                            <td><code>${l.mac_address || '—'}</code></td>
                            <td>${l.hostname || '<span class="text-muted">—</span>'}</td>
                            <td><small>${l.starts || '—'}</small></td>
                            <td><small>${l.ends || '—'}</small></td>
                            <td>
                                <span class="badge ${l.state === 'active' ? 'bg-success' : 'bg-secondary'}-lt">
                                    ${l.state}
                                </span>
                            </td>
                            ${canReservations ? `
                            <td>
                                ${!isReserved && l.mac_address ? `
                                <button class="btn btn-sm btn-ghost-primary btn-reserve-lease"
                                        data-mac="${l.mac_address}" data-ip="${l.ip_address}"
                                        data-hostname="${l.hostname || ''}" title="${t('dhcp.reserve')}">
                                    <i class="ti ti-pin me-1"></i>${t('dhcp.reserve')}
                                </button>` : `
                                <span class="badge bg-blue-lt"><i class="ti ti-pin-filled me-1"></i>${t('dhcp.reserved')}</span>
                                `}
                            </td>` : ''}
                        </tr>`;
                    }).join('')}
                </tbody>
            </table>
        </div>`;
}

// ============================================================
//  HOST MODAL (new + edit)
// ============================================================

function renderHostModal(subnet) {
    return `
        <div class="modal fade" id="modal-new-host" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${t('dhcp.newReservation')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">${t('dhcp.hostname')}</label>
                            <input type="text" class="form-control" id="new-host-name" placeholder="es. server-web">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">${t('dhcp.macAddress')}</label>
                            <input type="text" class="form-control" id="new-host-mac" placeholder="AA:BB:CC:DD:EE:FF">
                            <small class="form-hint">${t('dhcp.macFormat')}</small>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">${t('dhcp.ipAddress')}</label>
                            <input type="text" class="form-control" id="new-host-ip" placeholder="es. ${subnet.range_start}">
                            <small class="form-hint">${t('dhcp.ipHint', { subnet: subnet.network })}</small>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">${t('dhcp.descOptional')}</label>
                            <input type="text" class="form-control" id="new-host-desc" placeholder="es. Server web principale">
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">${t('dhcp.cancel')}</button>
                        <button class="btn btn-primary" id="btn-create-host">
                            <i class="ti ti-check me-1"></i>${t('dhcp.create')}
                        </button>
                    </div>
                </div>
            </div>
        </div>`;
}

// ============================================================
//  EDIT SUBNET MODAL
// ============================================================

function renderEditSubnetModal(subnet) {
    return `
        <div class="modal fade" id="modal-edit-subnet" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title"><i class="ti ti-edit me-2"></i>${t('dhcp.editSubnetTitle')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="alert alert-warning">
                            <i class="ti ti-alert-triangle me-2"></i>
                            <strong>${t('dhcp.warning')}:</strong> ${t('dhcp.editWarning')}
                        </div>
                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">${t('dhcp.name')}</label>
                                <input type="text" class="form-control" id="edit-subnet-name" value="${subnet.name}">
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label">${t('dhcp.interface')}</label>
                                <select class="form-select" id="edit-subnet-interface" ${subnet.managed ? 'disabled' : ''}>
                                    <option value="${subnet.interface}" selected>${subnet.interface}</option>
                                </select>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">${t('dhcp.rangeStart')}</label>
                                <input type="text" class="form-control" id="edit-subnet-range-start" value="${subnet.range_start}">
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label">${t('dhcp.rangeEnd')}</label>
                                <input type="text" class="form-control" id="edit-subnet-range-end" value="${subnet.range_end}">
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Gateway</label>
                                <input type="text" class="form-control" id="edit-subnet-gateway" value="${subnet.gateway}" ${subnet.managed ? 'disabled' : ''}>
                                ${subnet.managed ? `<small class="form-hint">${t('dhcp.managedGatewayHint')}</small>` : ''}
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">${t('dhcp.dnsServers')}</label>
                                <input type="text" class="form-control" id="edit-subnet-dns" value="${subnet.dns_servers}">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">${t('dhcp.domainName')}</label>
                                <input type="text" class="form-control" id="edit-subnet-domain" value="${subnet.domain_name || ''}">
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-4 mb-3">
                                <label class="form-label">${t('dhcp.leaseTimeSec')}</label>
                                <input type="number" class="form-control" id="edit-subnet-lease-time" value="${subnet.lease_time}">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">${t('dhcp.maxLeaseTimeSec')}</label>
                                <input type="number" class="form-control" id="edit-subnet-max-lease" value="${subnet.max_lease_time}">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">${t('dhcp.status')}</label>
                                <div class="form-check form-switch mt-2">
                                    <input class="form-check-input" type="checkbox" id="edit-subnet-enabled" ${subnet.enabled ? 'checked' : ''} ${subnet.managed ? 'disabled' : ''}>
                                    <label class="form-check-label" for="edit-subnet-enabled">${t('dhcp.enabled')}</label>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">${t('dhcp.cancel')}</button>
                        <button class="btn btn-primary" id="btn-save-subnet">
                            <i class="ti ti-device-floppy me-1"></i>${t('dhcp.saveChanges')}
                        </button>
                    </div>
                </div>
            </div>
        </div>`;
}

// ============================================================
//  EVENT HANDLERS
// ============================================================

function setupDetailActions(subnet, subnetId, container, canManage, canReservations) {
    // Edit Subnet
    document.getElementById('btn-edit-subnet')?.addEventListener('click', async () => {
        await loadInterfaces();
        const select = document.getElementById('edit-subnet-interface');
        select.innerHTML = networkInterfaces
            .filter(iface => iface.name !== 'eth0')
            .map(iface =>
                `<option value="${iface.name}" ${iface.name === subnet.interface ? 'selected' : ''}>
                    ${iface.name} ${iface.state === 'up' ? '●' : '○'}
                </option>`
            ).join('');
        new bootstrap.Modal(document.getElementById('modal-edit-subnet')).show();
    });

    // Save Subnet
    document.getElementById('btn-save-subnet')?.addEventListener('click', async () => {
        try {
            const payload = {
                name: document.getElementById('edit-subnet-name').value.trim(),
                range_start: document.getElementById('edit-subnet-range-start').value.trim(),
                range_end: document.getElementById('edit-subnet-range-end').value.trim(),
                dns_servers: document.getElementById('edit-subnet-dns').value.trim(),
                domain_name: document.getElementById('edit-subnet-domain').value.trim() || null,
                lease_time: parseInt(document.getElementById('edit-subnet-lease-time').value) || 86400,
                max_lease_time: parseInt(document.getElementById('edit-subnet-max-lease').value) || 172800,
            };
            // Locked fields on a managed subnet (gateway/interface/enabled) are omitted
            if (!subnet.managed) {
                payload.gateway = document.getElementById('edit-subnet-gateway').value.trim();
                payload.interface = document.getElementById('edit-subnet-interface').value;
                payload.enabled = document.getElementById('edit-subnet-enabled').checked;
            }
            await apiPatch(`/modules/dhcp/subnets/${subnetId}`, payload);
            showToast(t('dhcp.subnetUpdated'), 'success');
            bootstrap.Modal.getInstance(document.getElementById('modal-edit-subnet'))?.hide();
            await renderDhcpDetail(container, subnetId, canManage, canReservations);
        } catch (err) { showToast(err.message, 'error'); }
    });

    // Delete Subnet
    document.getElementById('btn-delete-subnet')?.addEventListener('click', async () => {
        if (!await confirmDialog(t('dhcp.confirmDeleteSubnetTitle'), t('dhcp.confirmDeleteSubnetMsgShort'))) return;
        try {
            await apiDelete(`/modules/dhcp/subnets/${subnetId}`);
            showToast(t('dhcp.subnetDeleted'), 'success');
            window.location.hash = '#dhcp';
        } catch (err) { showToast(err.message, 'error'); }
    });

    // New Host
    document.getElementById('btn-new-host')?.addEventListener('click', () => {
        document.getElementById('new-host-name').value = '';
        document.getElementById('new-host-mac').value = '';
        document.getElementById('new-host-ip').value = '';
        document.getElementById('new-host-desc').value = '';
        document.querySelector('#modal-new-host .modal-title').textContent = t('dhcp.newReservation');
        new bootstrap.Modal(document.getElementById('modal-new-host')).show();
    });

    // Create Host
    document.getElementById('btn-create-host')?.addEventListener('click', async () => {
        const hostname = document.getElementById('new-host-name').value.trim();
        const mac = document.getElementById('new-host-mac').value.trim();
        const ip = document.getElementById('new-host-ip').value.trim();
        const desc = document.getElementById('new-host-desc').value.trim();

        if (!hostname || !mac || !ip) {
            showToast(t('dhcp.fillHostFields'), 'error');
            return;
        }

        try {
            await apiPost(`/modules/dhcp/subnets/${subnetId}/hosts`, {
                hostname, mac_address: mac, ip_address: ip, description: desc
            });
            showToast(t('dhcp.reservationCreated'), 'success');
            bootstrap.Modal.getInstance(document.getElementById('modal-new-host'))?.hide();
            await renderDhcpDetail(container, subnetId, canManage, canReservations);
        } catch (err) { showToast(err.message, 'error'); }
    });

    // Edit Host
    document.querySelectorAll('.btn-edit-host').forEach(btn => {
        btn.addEventListener('click', () => {
            document.getElementById('new-host-name').value = btn.dataset.hostname;
            document.getElementById('new-host-mac').value = btn.dataset.mac;
            document.getElementById('new-host-ip').value = btn.dataset.ip;
            document.getElementById('new-host-desc').value = btn.dataset.desc;

            const modal = new bootstrap.Modal(document.getElementById('modal-new-host'));
            document.querySelector('#modal-new-host .modal-title').textContent = t('dhcp.editReservation');

            const createBtn = document.getElementById('btn-create-host');
            const newBtn = createBtn.cloneNode(true);
            createBtn.parentNode.replaceChild(newBtn, createBtn);
            newBtn.id = 'btn-create-host';
            newBtn.innerHTML = `<i class="ti ti-check me-1"></i>${t('dhcp.save')}`;

            newBtn.addEventListener('click', async () => {
                try {
                    await apiPatch(`/modules/dhcp/subnets/${subnetId}/hosts/${btn.dataset.id}`, {
                        hostname: document.getElementById('new-host-name').value.trim(),
                        mac_address: document.getElementById('new-host-mac').value.trim(),
                        ip_address: document.getElementById('new-host-ip').value.trim(),
                        description: document.getElementById('new-host-desc').value.trim()
                    });
                    showToast(t('dhcp.reservationUpdated'), 'success');
                    bootstrap.Modal.getInstance(document.getElementById('modal-new-host'))?.hide();
                    await renderDhcpDetail(container, subnetId, canManage, canReservations);
                } catch (err) { showToast(err.message, 'error'); }
            });

            modal.show();
        });
    });

    // Delete Host
    document.querySelectorAll('.btn-delete-host').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!await confirmDialog(t('dhcp.confirmDeleteReservation'))) return;
            try {
                await apiDelete(`/modules/dhcp/subnets/${btn.dataset.subnet}/hosts/${btn.dataset.id}`);
                showToast(t('dhcp.reservationDeleted'), 'success');
                await renderDhcpDetail(container, subnetId, canManage, canReservations);
            } catch (err) { showToast(err.message, 'error'); }
        });
    });

    // Refresh leases
    document.getElementById('btn-refresh-leases')?.addEventListener('click', async () => {
        const btn = document.getElementById('btn-refresh-leases');
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('dhcp.updating')}`;
        try {
            const [leases, freshHosts] = await Promise.all([
                apiGet(`/modules/dhcp/subnets/${subnetId}/leases`),
                apiGet(`/modules/dhcp/subnets/${subnetId}/hosts`)
            ]);
            document.getElementById('leases-table-container').innerHTML = renderLeasesTable(leases, freshHosts, canReservations);
            setupReserveFromLeaseButtons(subnetId, container, canManage, canReservations);
            const tabBtn = document.getElementById('tab-leases');
            tabBtn.innerHTML = `<i class="ti ti-clock me-1"></i>${t('dhcp.leasesTab', { n: leases.length })}`;
        } catch (err) { showToast(err.message, 'error'); }
        btn.disabled = false;
        btn.innerHTML = `<i class="ti ti-refresh me-1"></i>${t('dhcp.refresh')}`;
    });

    setupReserveFromLeaseButtons(subnetId, container, canManage, canReservations);
}

function setupReserveFromLeaseButtons(subnetId, container, canManage, canReservations) {
    document.querySelectorAll('.btn-reserve-lease').forEach(btn => {
        btn.addEventListener('click', () => {
            const hostname = btn.dataset.hostname || `host-${btn.dataset.ip.split('.').pop()}`;
            document.getElementById('new-host-name').value = hostname;
            document.getElementById('new-host-mac').value = btn.dataset.mac;
            document.getElementById('new-host-ip').value = btn.dataset.ip;
            document.getElementById('new-host-desc').value = t('dhcp.reservedFromLease');
            document.querySelector('#modal-new-host .modal-title').textContent = t('dhcp.newReservation');
            new bootstrap.Modal(document.getElementById('modal-new-host')).show();
        });
    });
}

// ============================================================
//  HELPERS
// ============================================================

function formatLeaseTime(seconds) {
    if (seconds >= 86400) return t('dhcp.nDays', { n: Math.floor(seconds / 86400) });
    if (seconds >= 3600)  return t('dhcp.nHours', { n: Math.floor(seconds / 3600) });
    return t('dhcp.nMin', { n: Math.floor(seconds / 60) });
}

async function loadInterfaces() {
    try {
        const data = await apiGet('/modules/dhcp/interfaces');
        networkInterfaces = data.interfaces || [];
    } catch (err) {
        console.warn('Could not load interfaces:', err);
        networkInterfaces = [{ name: 'eth0', state: 'unknown', addresses: [] }];
    }
}

/**
 * DHCP Module - Main View
 * 
 * Complete management UI for ISC DHCP Server.
 * Subnets, reservations, leases, options, and service control.
 */

import { apiGet, apiPost, apiDelete, apiPatch } from '/static/js/api.js';
import { showToast, confirmDialog, loadingSpinner } from '/static/js/utils.js';
import { checkPermission } from '/static/js/app.js';

let canManage = false;
let canReservations = false;
let currentContainer = null;
let networkInterfaces = [];

// ============================================================
//  ENTRY POINT
// ============================================================

export async function render(container, params) {
    currentContainer = container;
    canManage = checkPermission('dhcp.manage');
    canReservations = checkPermission('dhcp.reservations');

    if (params && params.length > 0) {
        await renderSubnetDetail(container, params[0]);
    } else {
        await renderDashboard(container);
    }
}

// ============================================================
//  DASHBOARD
// ============================================================

async function renderDashboard(container) {
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
                                <div class="subheader">Stato Servizio</div>
                            </div>
                            <div class="d-flex align-items-baseline mt-1">
                                <span class="status-dot ${status.running ? 'status-dot-animated bg-success' : 'bg-danger'} me-2"></span>
                                <span class="h1 mb-0">${status.running ? 'Attivo' : 'Fermo'}</span>
                            </div>
                            ${canManage ? `
                            <div class="mt-2">
                                ${status.running
                    ? '<button class="btn btn-sm btn-warning" id="btn-stop"><i class="ti ti-player-stop me-1"></i>Ferma</button>'
                    : '<button class="btn btn-sm btn-success" id="btn-start"><i class="ti ti-player-play me-1"></i>Avvia</button>'}
                            </div>` : ''}
                        </div>
                    </div>
                </div>
                <div class="col-sm-6 col-lg-3">
                    <div class="card">
                        <div class="card-body">
                            <div class="subheader">Subnet</div>
                            <div class="h1 mb-0 mt-1">${status.total_subnets}</div>
                        </div>
                    </div>
                </div>
                <div class="col-sm-6 col-lg-3">
                    <div class="card">
                        <div class="card-body">
                            <div class="subheader">Prenotazioni</div>
                            <div class="h1 mb-0 mt-1">${status.total_hosts}</div>
                        </div>
                    </div>
                </div>
                <div class="col-sm-6 col-lg-3">
                    <div class="card">
                        <div class="card-body">
                            <div class="subheader">Lease Attivi</div>
                            <div class="h1 mb-0 mt-1">${status.total_leases}</div>
                            ${status.config_valid !== null ? `
                            <div class="mt-1">
                                <span class="badge ${status.config_valid ? 'bg-success' : 'bg-danger'}-lt">
                                    <i class="ti ti-${status.config_valid ? 'check' : 'alert-triangle'} me-1"></i>
                                    Config ${status.config_valid ? 'Valida' : 'Non Valida'}
                                </span>
                            </div>` : ''}
                        </div>
                    </div>
                </div>
            </div>

            <!-- Subnets Table -->
            <div class="card">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h3 class="card-title"><i class="ti ti-affiliate me-2"></i>Subnet DHCP</h3>
                    <div class="d-flex gap-2">
                        ${canManage ? `
                        <button class="btn btn-outline-primary" id="btn-apply" title="Rigenera dhcpd.conf dal database e riavvia il servizio">
                            <i class="ti ti-reload me-1"></i>Applica Config
                        </button>
                        <button class="btn btn-primary" id="btn-new-subnet">
                            <i class="ti ti-plus me-1"></i>Nuova Subnet
                        </button>` : ''}
                    </div>
                </div>
                <div class="card-body" id="subnets-list">
                    ${renderSubnetsTable(subnets)}
                </div>
            </div>

            <!-- New Subnet Modal -->
            ${renderNewSubnetModal()}

            <!-- Config Preview Modal -->
            <div class="modal fade" id="modal-config-preview" tabindex="-1">
                <div class="modal-dialog modal-lg">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title"><i class="ti ti-file-code me-2"></i>Anteprima dhcpd.conf</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <pre id="config-preview-content" class="p-3 bg-dark text-light rounded" style="max-height: 500px; overflow-y: auto; font-size: 0.85rem;"></pre>
                        </div>
                    </div>
                </div>
            </div>
        `;

        setupDashboardActions(status);
    } catch (err) {
        container.innerHTML = `<div class="alert alert-danger"><i class="ti ti-alert-triangle me-2"></i>${err.message}</div>`;
    }
}

function renderSubnetsTable(subnets) {
    if (subnets.length === 0) {
        return `
            <div class="text-center py-5 text-muted">
                <i class="ti ti-network-off" style="font-size: 3rem;"></i>
                <p class="mt-2">Nessuna subnet configurata</p>
                <small>Clicca "Nuova Subnet" per crearne una</small>
            </div>`;
    }

    return `
        <div class="table-responsive">
            <table class="table table-vcenter card-table table-hover">
                <thead>
                    <tr>
                        <th style="width: 50px;">Attiva</th>
                        <th>Nome</th>
                        <th>Network</th>
                        <th>Interfaccia</th>
                        <th>Range</th>
                        <th>Gateway</th>
                        <th>Prenotazioni</th>
                        <th>Lease</th>
                        <th class="w-1"></th>
                    </tr>
                </thead>
                <tbody>
                    ${subnets.map(s => `
                        <tr class="subnet-row ${!s.enabled ? 'text-muted' : ''}" data-id="${s.id}" style="cursor: pointer;">
                            <td onclick="event.stopPropagation();">
                                ${canManage ? `
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
                                    ${canManage ? `
                                    <button class="btn btn-ghost-danger btn-delete-subnet" data-id="${s.id}" title="Elimina">
                                        <i class="ti ti-trash"></i>
                                    </button>` : ''}
                                </div>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>`;
}

function renderNewSubnetModal() {
    return `
        <div class="modal fade" id="modal-new-subnet" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Nuova Subnet DHCP</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Nome</label>
                                <input type="text" class="form-control" id="new-subnet-name" placeholder="LAN Ufficio">
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Interfaccia</label>
                                <select class="form-select" id="new-subnet-interface">
                                    <option value="">Seleziona interfaccia...</option>
                                </select>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Network (CIDR)</label>
                                <input type="text" class="form-control" id="new-subnet-network" placeholder="192.168.1.0/24">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Range Inizio</label>
                                <input type="text" class="form-control" id="new-subnet-range-start" placeholder="192.168.1.100">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Range Fine</label>
                                <input type="text" class="form-control" id="new-subnet-range-end" placeholder="192.168.1.200">
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Gateway</label>
                                <input type="text" class="form-control" id="new-subnet-gateway" placeholder="192.168.1.1">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">DNS Servers</label>
                                <input type="text" class="form-control" id="new-subnet-dns" value="8.8.8.8, 1.1.1.1" placeholder="8.8.8.8, 1.1.1.1">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Nome Dominio</label>
                                <input type="text" class="form-control" id="new-subnet-domain" placeholder="example.local">
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Lease Time (secondi)</label>
                                <input type="number" class="form-control" id="new-subnet-lease-time" value="86400">
                                <small class="form-hint">Default: 86400 (24 ore)</small>
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Max Lease Time (secondi)</label>
                                <input type="number" class="form-control" id="new-subnet-max-lease" value="172800">
                                <small class="form-hint">Default: 172800 (48 ore)</small>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">Annulla</button>
                        <button class="btn btn-primary" id="btn-create-subnet">
                            <i class="ti ti-check me-1"></i>Crea Subnet
                        </button>
                    </div>
                </div>
            </div>
        </div>`;
}

function setupDashboardActions(status) {
    // Start/Stop
    document.getElementById('btn-start')?.addEventListener('click', async () => {
        try {
            await apiPost('/modules/dhcp/start');
            showToast('Servizio avviato', 'success');
            await renderDashboard(currentContainer);
        } catch (err) { showToast(err.message, 'error'); }
    });

    document.getElementById('btn-stop')?.addEventListener('click', async () => {
        if (!await confirmDialog('Fermare il servizio DHCP?', 'I client non riceveranno più indirizzi IP.')) return;
        try {
            await apiPost('/modules/dhcp/stop');
            showToast('Servizio fermato', 'success');
            await renderDashboard(currentContainer);
        } catch (err) { showToast(err.message, 'error'); }
    });

    // Apply config
    document.getElementById('btn-apply')?.addEventListener('click', async () => {
        if (!await confirmDialog(
            'Applicare la configurazione?',
            'Verrà rigenerato il file dhcpd.conf con tutte le subnet abilitate, ' +
            'validata la sintassi e riavviato il servizio DHCP. ' +
            'Solo le subnet con il toggle attivo saranno incluse.'
        )) return;

        const btn = document.getElementById('btn-apply');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Applicando...';
        try {
            await apiPost('/modules/dhcp/apply');
            showToast('Configurazione applicata con successo', 'success');
            await renderDashboard(currentContainer);
        } catch (err) {
            showToast(err.message, 'error');
            btn.disabled = false;
            btn.innerHTML = '<i class="ti ti-reload me-1"></i>Applica Config';
        }
    });

    // New Subnet
    document.getElementById('btn-new-subnet')?.addEventListener('click', async () => {
        await loadInterfaces();
        populateInterfaceSelect('new-subnet-interface');
        new bootstrap.Modal(document.getElementById('modal-new-subnet')).show();
    });

    document.getElementById('btn-create-subnet')?.addEventListener('click', createSubnet);

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
            if (!await confirmDialog('Eliminare questa subnet?', 'Saranno eliminate anche tutte le prenotazioni associate.')) return;
            try {
                await apiDelete(`/modules/dhcp/subnets/${btn.dataset.id}`);
                showToast('Subnet eliminata', 'success');
                await renderDashboard(currentContainer);
            } catch (err) { showToast(err.message, 'error'); }
        });
    });

    // Subnet enable/disable toggle
    document.querySelectorAll('.subnet-toggle').forEach(toggle => {
        toggle.addEventListener('change', async (e) => {
            const id = toggle.dataset.id;
            const enabled = toggle.checked;
            try {
                await apiPatch(`/modules/dhcp/subnets/${id}`, { enabled });
                showToast(
                    enabled ? 'Subnet abilitata' : 'Subnet disabilitata — ricorda di applicare la config',
                    enabled ? 'success' : 'warning'
                );
                await renderDashboard(currentContainer);
            } catch (err) {
                toggle.checked = !enabled; // Rollback
                showToast(err.message, 'error');
            }
        });
    });
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

function populateInterfaceSelect(selectId) {
    const select = document.getElementById(selectId);
    if (!select) return;
    select.innerHTML = '<option value="">Seleziona interfaccia...</option>' +
        networkInterfaces.map(iface =>
            `<option value="${iface.name}" ${iface.state === 'up' ? 'class="fw-bold"' : ''}>
                ${iface.name} ${iface.state === 'up' ? '●' : '○'} ${iface.addresses?.join(', ') || ''}
            </option>`
        ).join('');
}

async function createSubnet() {
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
        showToast('Compila tutti i campi obbligatori', 'error');
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
        showToast('Subnet creata con successo', 'success');
        bootstrap.Modal.getInstance(document.getElementById('modal-new-subnet'))?.hide();
        await renderDashboard(currentContainer);
    } catch (err) {
        showToast(err.message, 'error');
    }
}


// ============================================================
//  SUBNET DETAIL
// ============================================================

async function renderSubnetDetail(container, subnetId) {
    container.innerHTML = `<div class="text-center py-5">${loadingSpinner()}</div>`;

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
                    <i class="ti ti-arrow-left me-1"></i>Torna alle subnet
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
                            <small class="text-muted">${subnet.network} su ${subnet.interface}</small>
                        </div>
                        ${canManage ? `
                        <div class="btn-group">
                            <button class="btn btn-outline-primary" id="btn-edit-subnet">
                                <i class="ti ti-edit me-1"></i>Modifica
                            </button>
                            <button class="btn btn-outline-danger" id="btn-delete-subnet">
                                <i class="ti ti-trash me-1"></i>Elimina
                            </button>
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
                            <span class="text-muted">Lease Time</span><br>
                            <small>${formatLeaseTime(subnet.lease_time)}</small>
                        </div>
                        <div class="col-md-2">
                            <span class="text-muted">Interfaccia</span><br>
                            <code>${subnet.interface}</code>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Tabs -->
            <ul class="nav nav-tabs" role="tablist">
                <li class="nav-item" role="presentation">
                    <button class="nav-link active" id="tab-hosts" data-bs-toggle="tab" data-bs-target="#pane-hosts" type="button">
                        <i class="ti ti-device-desktop me-1"></i>Prenotazioni (${hosts.length})
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link" id="tab-leases" data-bs-toggle="tab" data-bs-target="#pane-leases" type="button">
                        <i class="ti ti-clock me-1"></i>Lease Attivi (${leases.length})
                    </button>
                </li>
            </ul>

            <div class="tab-content">
                <!-- Hosts Tab -->
                <div class="tab-pane fade show active" id="pane-hosts" role="tabpanel">
                    <div class="card card-body border-top-0 rounded-top-0">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <h4 class="mb-0">Prenotazioni Statiche</h4>
                            ${canReservations ? `
                            <button class="btn btn-primary" id="btn-new-host">
                                <i class="ti ti-plus me-1"></i>Nuova Prenotazione
                            </button>` : ''}
                        </div>
                        ${renderHostsTable(hosts, subnetId)}
                    </div>
                </div>

                <!-- Leases Tab -->
                <div class="tab-pane fade" id="pane-leases" role="tabpanel">
                    <div class="card card-body border-top-0 rounded-top-0">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <h4 class="mb-0">Lease Attivi</h4>
                            <button class="btn btn-outline-secondary btn-sm" id="btn-refresh-leases">
                                <i class="ti ti-refresh me-1"></i>Aggiorna
                            </button>
                        </div>
                        <div id="leases-table-container">
                            ${renderLeasesTable(leases, hosts)}
                        </div>
                    </div>
                </div>
            </div>

            <!-- New Host Modal -->
            ${renderNewHostModal(subnet)}

            <!-- Edit Subnet Modal -->
            ${renderEditSubnetModal(subnet)}
        `;

        setupSubnetDetailActions(subnet, subnetId);
    } catch (err) {
        container.innerHTML = `
            <div class="mb-3"><a href="#dhcp" class="text-muted"><i class="ti ti-arrow-left me-1"></i>Torna alle subnet</a></div>
            <div class="alert alert-danger"><i class="ti ti-alert-triangle me-2"></i>${err.message}</div>`;
    }
}

function formatLeaseTime(seconds) {
    if (seconds >= 86400) return `${Math.floor(seconds / 86400)} giorni`;
    if (seconds >= 3600) return `${Math.floor(seconds / 3600)} ore`;
    return `${Math.floor(seconds / 60)} min`;
}

function renderHostsTable(hosts, subnetId) {
    if (hosts.length === 0) {
        return `
            <div class="text-center py-4 text-muted">
                <i class="ti ti-device-desktop-off" style="font-size: 2rem;"></i>
                <p class="mt-2">Nessuna prenotazione statica</p>
                <small>Le prenotazioni associano un indirizzo MAC a un IP fisso</small>
            </div>`;
    }

    return `
        <div class="table-responsive">
            <table class="table table-vcenter">
                <thead>
                    <tr>
                        <th>Hostname</th>
                        <th>MAC Address</th>
                        <th>IP Address</th>
                        <th>Descrizione</th>
                        <th class="w-1">Azioni</th>
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
                                            data-desc="${h.description || ''}" title="Modifica">
                                        <i class="ti ti-edit"></i>
                                    </button>
                                    <button class="btn btn-ghost-danger btn-delete-host" 
                                            data-id="${h.id}" data-subnet="${subnetId}" title="Elimina">
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

function renderLeasesTable(leases, hosts = []) {
    if (leases.length === 0) {
        return `
            <div class="text-center py-4 text-muted">
                <i class="ti ti-clock-off" style="font-size: 2rem;"></i>
                <p class="mt-2">Nessun lease attivo</p>
            </div>`;
    }

    // Build a set of reserved MACs for cross-reference
    const reservedMacs = new Set(hosts.map(h => h.mac_address?.toLowerCase()));

    return `
        <div class="table-responsive">
            <table class="table table-vcenter table-striped">
                <thead>
                    <tr>
                        <th>IP Address</th>
                        <th>MAC Address</th>
                        <th>Hostname</th>
                        <th>Inizio</th>
                        <th>Scadenza</th>
                        <th>Stato</th>
                        ${canReservations ? '<th class="w-1">Azioni</th>' : ''}
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
                                        data-hostname="${l.hostname || ''}" title="Crea prenotazione">
                                    <i class="ti ti-pin me-1"></i>Prenota
                                </button>` : `
                                <span class="badge bg-blue-lt"><i class="ti ti-pin-filled me-1"></i>Prenotato</span>
                                `}
                            </td>` : ''}
                        </tr>`;
    }).join('')}
                </tbody>
            </table>
        </div>`;
}

function renderNewHostModal(subnet) {
    return `
        <div class="modal fade" id="modal-new-host" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Nuova Prenotazione</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">Hostname</label>
                            <input type="text" class="form-control" id="new-host-name" placeholder="es. server-web">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">MAC Address</label>
                            <input type="text" class="form-control" id="new-host-mac" placeholder="AA:BB:CC:DD:EE:FF">
                            <small class="form-hint">Formato: AA:BB:CC:DD:EE:FF</small>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">IP Address</label>
                            <input type="text" class="form-control" id="new-host-ip" placeholder="es. ${subnet.range_start}">
                            <small class="form-hint">Deve essere nella subnet ${subnet.network}</small>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Descrizione (opzionale)</label>
                            <input type="text" class="form-control" id="new-host-desc" placeholder="es. Server web principale">
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">Annulla</button>
                        <button class="btn btn-primary" id="btn-create-host">
                            <i class="ti ti-check me-1"></i>Crea
                        </button>
                    </div>
                </div>
            </div>
        </div>`;
}

function renderEditSubnetModal(subnet) {
    return `
        <div class="modal fade" id="modal-edit-subnet" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title"><i class="ti ti-edit me-2"></i>Modifica Subnet</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="alert alert-warning">
                            <i class="ti ti-alert-triangle me-2"></i>
                            <strong>Attenzione:</strong> Dopo la modifica, ricorda di applicare la configurazione per rendere effettive le modifiche.
                        </div>
                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Nome</label>
                                <input type="text" class="form-control" id="edit-subnet-name" value="${subnet.name}">
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Interfaccia</label>
                                <select class="form-select" id="edit-subnet-interface">
                                    <option value="${subnet.interface}" selected>${subnet.interface}</option>
                                </select>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Range Inizio</label>
                                <input type="text" class="form-control" id="edit-subnet-range-start" value="${subnet.range_start}">
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Range Fine</label>
                                <input type="text" class="form-control" id="edit-subnet-range-end" value="${subnet.range_end}">
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Gateway</label>
                                <input type="text" class="form-control" id="edit-subnet-gateway" value="${subnet.gateway}">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">DNS Servers</label>
                                <input type="text" class="form-control" id="edit-subnet-dns" value="${subnet.dns_servers}">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Nome Dominio</label>
                                <input type="text" class="form-control" id="edit-subnet-domain" value="${subnet.domain_name || ''}">
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Lease Time (sec)</label>
                                <input type="number" class="form-control" id="edit-subnet-lease-time" value="${subnet.lease_time}">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Max Lease Time (sec)</label>
                                <input type="number" class="form-control" id="edit-subnet-max-lease" value="${subnet.max_lease_time}">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Stato</label>
                                <div class="form-check form-switch mt-2">
                                    <input class="form-check-input" type="checkbox" id="edit-subnet-enabled" ${subnet.enabled ? 'checked' : ''}>
                                    <label class="form-check-label" for="edit-subnet-enabled">Abilitata</label>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">Annulla</button>
                        <button class="btn btn-primary" id="btn-save-subnet">
                            <i class="ti ti-device-floppy me-1"></i>Salva Modifiche
                        </button>
                    </div>
                </div>
            </div>
        </div>`;
}

function setupSubnetDetailActions(subnet, subnetId) {
    // Edit Subnet
    document.getElementById('btn-edit-subnet')?.addEventListener('click', async () => {
        await loadInterfaces();
        const select = document.getElementById('edit-subnet-interface');
        select.innerHTML = networkInterfaces.map(iface =>
            `<option value="${iface.name}" ${iface.name === subnet.interface ? 'selected' : ''}>
                ${iface.name} ${iface.state === 'up' ? '●' : '○'}
            </option>`
        ).join('');
        new bootstrap.Modal(document.getElementById('modal-edit-subnet')).show();
    });

    // Save Subnet
    document.getElementById('btn-save-subnet')?.addEventListener('click', async () => {
        try {
            await apiPatch(`/modules/dhcp/subnets/${subnetId}`, {
                name: document.getElementById('edit-subnet-name').value.trim(),
                range_start: document.getElementById('edit-subnet-range-start').value.trim(),
                range_end: document.getElementById('edit-subnet-range-end').value.trim(),
                gateway: document.getElementById('edit-subnet-gateway').value.trim(),
                dns_servers: document.getElementById('edit-subnet-dns').value.trim(),
                domain_name: document.getElementById('edit-subnet-domain').value.trim() || null,
                interface: document.getElementById('edit-subnet-interface').value,
                lease_time: parseInt(document.getElementById('edit-subnet-lease-time').value) || 86400,
                max_lease_time: parseInt(document.getElementById('edit-subnet-max-lease').value) || 172800,
                enabled: document.getElementById('edit-subnet-enabled').checked
            });
            showToast('Subnet aggiornata', 'success');
            bootstrap.Modal.getInstance(document.getElementById('modal-edit-subnet'))?.hide();
            await renderSubnetDetail(currentContainer, subnetId);
        } catch (err) { showToast(err.message, 'error'); }
    });

    // Delete Subnet
    document.getElementById('btn-delete-subnet')?.addEventListener('click', async () => {
        if (!await confirmDialog('Eliminare questa subnet?', 'Saranno eliminate anche tutte le prenotazioni.')) return;
        try {
            await apiDelete(`/modules/dhcp/subnets/${subnetId}`);
            showToast('Subnet eliminata', 'success');
            window.location.hash = '#dhcp';
        } catch (err) { showToast(err.message, 'error'); }
    });

    // New Host
    document.getElementById('btn-new-host')?.addEventListener('click', () => {
        // Clear form
        document.getElementById('new-host-name').value = '';
        document.getElementById('new-host-mac').value = '';
        document.getElementById('new-host-ip').value = '';
        document.getElementById('new-host-desc').value = '';
        new bootstrap.Modal(document.getElementById('modal-new-host')).show();
    });

    // Create Host
    document.getElementById('btn-create-host')?.addEventListener('click', async () => {
        const hostname = document.getElementById('new-host-name').value.trim();
        const mac = document.getElementById('new-host-mac').value.trim();
        const ip = document.getElementById('new-host-ip').value.trim();
        const desc = document.getElementById('new-host-desc').value.trim();

        if (!hostname || !mac || !ip) {
            showToast('Compila hostname, MAC e IP', 'error');
            return;
        }

        try {
            await apiPost(`/modules/dhcp/subnets/${subnetId}/hosts`, {
                hostname, mac_address: mac, ip_address: ip, description: desc
            });
            showToast('Prenotazione creata', 'success');
            bootstrap.Modal.getInstance(document.getElementById('modal-new-host'))?.hide();
            await renderSubnetDetail(currentContainer, subnetId);
        } catch (err) { showToast(err.message, 'error'); }
    });

    // Edit Host (inline modal reuse)
    document.querySelectorAll('.btn-edit-host').forEach(btn => {
        btn.addEventListener('click', () => {
            document.getElementById('new-host-name').value = btn.dataset.hostname;
            document.getElementById('new-host-mac').value = btn.dataset.mac;
            document.getElementById('new-host-ip').value = btn.dataset.ip;
            document.getElementById('new-host-desc').value = btn.dataset.desc;

            const modal = new bootstrap.Modal(document.getElementById('modal-new-host'));
            document.querySelector('#modal-new-host .modal-title').textContent = 'Modifica Prenotazione';

            // Override create button to patch
            const createBtn = document.getElementById('btn-create-host');
            const newBtn = createBtn.cloneNode(true);
            createBtn.parentNode.replaceChild(newBtn, createBtn);
            newBtn.id = 'btn-create-host';
            newBtn.innerHTML = '<i class="ti ti-check me-1"></i>Salva';

            newBtn.addEventListener('click', async () => {
                try {
                    await apiPatch(`/modules/dhcp/subnets/${subnetId}/hosts/${btn.dataset.id}`, {
                        hostname: document.getElementById('new-host-name').value.trim(),
                        mac_address: document.getElementById('new-host-mac').value.trim(),
                        ip_address: document.getElementById('new-host-ip').value.trim(),
                        description: document.getElementById('new-host-desc').value.trim()
                    });
                    showToast('Prenotazione aggiornata', 'success');
                    bootstrap.Modal.getInstance(document.getElementById('modal-new-host'))?.hide();
                    await renderSubnetDetail(currentContainer, subnetId);
                } catch (err) { showToast(err.message, 'error'); }
            });

            modal.show();
        });
    });

    // Delete Host
    document.querySelectorAll('.btn-delete-host').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!await confirmDialog('Eliminare questa prenotazione?')) return;
            try {
                await apiDelete(`/modules/dhcp/subnets/${btn.dataset.subnet}/hosts/${btn.dataset.id}`);
                showToast('Prenotazione eliminata', 'success');
                await renderSubnetDetail(currentContainer, subnetId);
            } catch (err) { showToast(err.message, 'error'); }
        });
    });

    // Refresh leases
    document.getElementById('btn-refresh-leases')?.addEventListener('click', async () => {
        const btn = document.getElementById('btn-refresh-leases');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Aggiornando...';
        try {
            const [leases, freshHosts] = await Promise.all([
                apiGet(`/modules/dhcp/subnets/${subnetId}/leases`),
                apiGet(`/modules/dhcp/subnets/${subnetId}/hosts`)
            ]);
            document.getElementById('leases-table-container').innerHTML = renderLeasesTable(leases, freshHosts);
            setupReserveFromLeaseButtons(subnetId);
            // Update tab badge
            const tabBtn = document.getElementById('tab-leases');
            tabBtn.innerHTML = `<i class="ti ti-clock me-1"></i>Lease Attivi (${leases.length})`;
        } catch (err) { showToast(err.message, 'error'); }
        btn.disabled = false;
        btn.innerHTML = '<i class="ti ti-refresh me-1"></i>Aggiorna';
    });

    // Reserve-from-lease buttons
    setupReserveFromLeaseButtons(subnetId);
}

function setupReserveFromLeaseButtons(subnetId) {
    document.querySelectorAll('.btn-reserve-lease').forEach(btn => {
        btn.addEventListener('click', () => {
            // Pre-fill the new-host modal with lease data
            const hostname = btn.dataset.hostname || `host-${btn.dataset.ip.split('.').pop()}`;
            document.getElementById('new-host-name').value = hostname;
            document.getElementById('new-host-mac').value = btn.dataset.mac;
            document.getElementById('new-host-ip').value = btn.dataset.ip;
            document.getElementById('new-host-desc').value = `Prenotato da lease attivo`;

            // Reset modal title (in case it was changed by edit)
            document.querySelector('#modal-new-host .modal-title').textContent = 'Nuova Prenotazione';

            new bootstrap.Modal(document.getElementById('modal-new-host')).show();
        });
    });
}

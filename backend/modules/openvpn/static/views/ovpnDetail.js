/**
 * OpenVPN Module - Instance Detail View
 *
 * Displays instance details, clients, PKI status, and firewall tab.
 */

import { t } from '/static/js/i18n.js';
import { apiGet, apiPost, apiPatch, apiDelete } from '/static/js/api.js';
import { showToast, confirmDialog, escapeHtml, isValidCIDR } from '/static/js/utils.js';

const MODULE_API = '/modules/openvpn';

let currentInstanceId = null;
let currentContainer = null;
let networkInterfaces = [];

export async function renderOvpnDetail(container, instanceId, canManage, canClients) {
    currentInstanceId = instanceId;
    currentContainer = container;
    await renderInstanceDetail(container, canManage, canClients);
}

async function loadNetworkInterfaces() {
    try {
        const data = await apiGet(`${MODULE_API}/system/interfaces`);
        networkInterfaces = data.interfaces || [];
    } catch (err) {
        console.warn('Could not load interfaces:', err);
        networkInterfaces = [];
    }
}

function populateInterfaceSelects() {
    document.querySelectorAll('.route-interface').forEach(select => {
        const currentVal = select.value;
        select.innerHTML = `<option value="">Auto</option>` +
            networkInterfaces.map(iface => `<option value="${iface.name}">${iface.name}</option>`).join('');
        if (currentVal) select.value = currentVal;
    });
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatTimeAgo(isoString) {
    if (!isoString) return t('openvpn.never');
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return t('openvpn.justNow');
    if (diffSec < 3600) return t('openvpn.minutesAgo').replace('{n}', Math.floor(diffSec / 60));
    if (diffSec < 86400) return t('openvpn.hoursAgo').replace('{n}', Math.floor(diffSec / 3600));
    return t('openvpn.daysAgo').replace('{n}', Math.floor(diffSec / 86400));
}

function renderCertStatus(daysRemaining, revoked) {
    if (revoked) return `<span class="badge bg-danger-lt">${t('openvpn.revoked')}</span>`;
    if (daysRemaining === null || daysRemaining === undefined) return '<span class="badge bg-secondary-lt">N/A</span>';
    if (daysRemaining < 0) return `<span class="badge bg-danger-lt">${t('openvpn.expired')}</span>`;
    if (daysRemaining < 30) return `<span class="badge bg-warning-lt">${daysRemaining} ${t('openvpn.days')}</span>`;
    if (daysRemaining < 90) return `<span class="badge bg-info-lt">${daysRemaining} ${t('openvpn.days')}</span>`;
    return `<span class="badge bg-success-lt">${daysRemaining} ${t('openvpn.days')}</span>`;
}

async function renderInstanceDetail(container, canManage, canClients) {
    try {
        const instance = await apiGet(`${MODULE_API}/instances/${currentInstanceId}`);
        const clients = await apiGet(`${MODULE_API}/instances/${currentInstanceId}/clients`);

        container.innerHTML = `
            <div class="mb-3">
                <a href="#openvpn" class="text-muted">
                    <i class="ti ti-arrow-left me-1"></i>${t('openvpn.backToInstances')}
                </a>
            </div>

            <!-- Instance Info Card -->
            <div class="card mb-3">
                <div class="card-header">
                    <div class="d-flex justify-content-between align-items-center w-100">
                        <div>
                            <h3 class="card-title mb-0">${escapeHtml(instance.name)}</h3>
                            <small class="text-muted">${t('openvpn.interfaceLabel')}: ${instance.interface}</small>
                        </div>
                        <div class="btn-group">
                            ${canManage ? `
                            <button class="btn ${instance.status === 'running' ? 'btn-warning' : 'btn-success'}"
                                    onclick="${instance.status === 'running' ? 'stopInstance' : 'startInstance'}('${instance.id}')">
                                <i class="ti ti-player-${instance.status === 'running' ? 'stop' : 'play'} me-1"></i>
                                ${instance.status === 'running' ? t('openvpn.stop') : t('openvpn.start')}
                            </button>
                            <button class="btn btn-outline-danger" onclick="deleteInstance('${instance.id}')">
                                <i class="ti ti-trash"></i>
                            </button>` : ''}
                        </div>
                    </div>
                </div>
                <div class="card-body">
                    <div class="row mb-3">
                        <div class="col-md-3">
                            <span class="text-muted">${t('openvpn.status')}</span><br>
                            <span class="badge ${instance.status === 'running' ? 'bg-success-lt' : 'bg-secondary-lt'} fs-6">
                                ${instance.status === 'running' ? t('openvpn.statusRunning') : t('openvpn.statusStopped')}
                            </span>
                        </div>
                        <div class="col-md-3">
                            <span class="text-muted">${t('openvpn.port')}</span><br>
                            <strong>${instance.port}/${instance.protocol.toUpperCase()}</strong>
                        </div>
                        <div class="col-md-3">
                            <span class="text-muted">${t('openvpn.subnet')}</span><br>
                            <code>${instance.subnet}</code>
                        </div>
                        <div class="col-md-3">
                            <span class="text-muted">${t('openvpn.activeClients')}</span><br>
                            <strong>${instance.client_count}</strong>
                        </div>
                    </div>

                    <hr>

                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <h4 class="mb-0"><i class="ti ti-settings me-2"></i>${t('openvpn.defaultSettings')}</h4>
                        ${canManage ? `<button class="btn btn-sm btn-outline-primary" id="btn-edit-defaults">
                            <i class="ti ti-edit me-1"></i>${t('openvpn.edit')}
                        </button>` : ''}
                    </div>

                    <div class="row">
                        <div class="col-md-4">
                            <div class="mb-2">
                                <span class="text-muted">${t('openvpn.routingMode')}</span><br>
                                <span id="display-tunnel-mode" class="badge ${instance.tunnel_mode === 'full' ? 'bg-blue' : 'bg-purple'}-lt fs-6">
                                    ${instance.tunnel_mode === 'full' ? t('openvpn.fullTunnel') : t('openvpn.splitTunnel')}
                                </span>
                            </div>
                            ${instance.tunnel_mode === 'split' && instance.routes?.length ? `
                            <div class="mt-2">
                                <small class="text-muted">${t('openvpn.routes')}</small><br>
                                <div class="d-flex flex-wrap gap-1 mt-1">
                                    ${instance.routes.map(r => `<code class="badge bg-light text-dark">${r.network || r}</code>`).join('')}
                                </div>
                            </div>
                            ` : ''}
                        </div>
                        <div class="col-md-4">
                            <span class="text-muted">${t('openvpn.defaultDns')}</span><br>
                            <code id="display-dns">${instance.dns_servers?.join(', ') || 'N/A'}</code>
                        </div>
                        <div class="col-md-4">
                            <span class="text-muted">${t('openvpn.publicEndpointLabel')}</span><br>
                            <code id="display-endpoint">${instance.endpoint || t('openvpn.autoDetect')}</code>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Tabs -->
            <ul class="nav nav-tabs" role="tablist">
                <li class="nav-item" role="presentation">
                    <button class="nav-link active" id="tab-clients" data-bs-toggle="tab" data-bs-target="#pane-clients" type="button">
                        <i class="ti ti-users me-1"></i>${t('openvpn.clientsTab').replace('{n}', clients.length)}
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link" id="tab-pki" data-bs-toggle="tab" data-bs-target="#pane-pki" type="button">
                        <i class="ti ti-certificate me-1"></i>${t('openvpn.pkiTab')}
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link" id="tab-firewall" data-bs-toggle="tab" data-bs-target="#pane-firewall" type="button">
                        <i class="ti ti-shield me-1"></i>${t('openvpn.firewallTab')}
                    </button>
                </li>
            </ul>

            <div class="tab-content">
                <!-- Clients Tab -->
                <div class="tab-pane fade show active" id="pane-clients" role="tabpanel">
                    <div class="card card-body border-top-0 rounded-top-0">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <h4 class="mb-0">${t('openvpn.vpnClients')}</h4>
                            ${canClients ? `
                            <button class="btn btn-primary" id="btn-new-client">
                                <i class="ti ti-user-plus me-1"></i>${t('openvpn.newClient')}
                            </button>` : ''}
                        </div>
                        ${clients.length === 0 ? `
                            <div class="text-center py-4 text-muted">
                                <i class="ti ti-users-minus" style="font-size: 2rem;"></i>
                                <p class="mt-2">${t('openvpn.noClients')}</p>
                                <small>${t('openvpn.noClientsHint')}</small>
                            </div>
                        ` : `
                            <div class="table-responsive">
                                <table class="table table-vcenter">
                                    <thead>
                                        <tr>
                                            <th>${t('openvpn.clientStatus')}</th>
                                            <th>${t('openvpn.clientName')}</th>
                                            <th>${t('openvpn.assignedIp')}</th>
                                            <th>${t('openvpn.certificate')}</th>
                                            <th>${t('openvpn.traffic')}</th>
                                            <th>${t('openvpn.connectedSince')}</th>
                                            <th class="w-1">${t('openvpn.actions')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        ${clients.map(c => `
                                            <tr class="${c.revoked ? 'text-muted' : ''}">
                                                <td>
                                                    ${c.is_connected === true
                                                        ? `<span class="status-dot status-dot-animated bg-success" title="${t('openvpn.connected')}"></span>`
                                                        : `<span class="status-dot bg-secondary" title="${t('openvpn.offline')}"></span>`}
                                                </td>
                                                <td>
                                                    <strong>${escapeHtml(c.name)}</strong>
                                                    ${c.revoked ? `<span class="badge bg-danger-lt ms-1">${t('openvpn.revoked')}</span>` : ''}
                                                </td>
                                                <td><code>${c.allocated_ip}</code></td>
                                                <td>${renderCertStatus(c.cert_days_remaining, c.revoked)}</td>
                                                <td>
                                                    ${c.is_connected === true ? `
                                                    <small class="text-muted">
                                                        <i class="ti ti-arrow-down text-success"></i> ${formatBytes(c.bytes_received || 0)}
                                                        <i class="ti ti-arrow-up text-primary ms-2"></i> ${formatBytes(c.bytes_sent || 0)}
                                                    </small>
                                                    ` : '<small class="text-muted">-</small>'}
                                                </td>
                                                <td>
                                                    ${c.last_connection
                                                        ? `<small class="text-muted">${formatTimeAgo(c.last_connection)}</small>`
                                                        : '<small class="text-muted">-</small>'}
                                                </td>
                                                <td>
                                                    <div class="btn-group">
                                                        ${!c.revoked && canClients ? `
                                                        <button class="btn btn-sm btn-outline-primary" onclick="downloadConfig('${escapeHtml(c.name)}')" title="${t('openvpn.downloadConfig')}">
                                                            <i class="ti ti-download"></i>
                                                        </button>
                                                        <button class="btn btn-sm btn-outline-success" onclick="openSendEmailModal('${escapeHtml(c.name)}')" title="${t('openvpn.sendEmail')}">
                                                            <i class="ti ti-mail"></i>
                                                        </button>
                                                        <button class="btn btn-sm btn-outline-warning" onclick="renewClientCert('${escapeHtml(c.name)}')" title="${t('openvpn.renewCert')}">
                                                            <i class="ti ti-refresh"></i>
                                                        </button>
                                                        <button class="btn btn-sm btn-outline-danger" onclick="revokeClient('${escapeHtml(c.name)}')" title="${t('openvpn.revoke')}">
                                                            <i class="ti ti-ban"></i>
                                                        </button>` : ''}
                                                        ${c.revoked && canClients ? `
                                                        <button class="btn btn-sm btn-outline-success" onclick="restoreClient('${escapeHtml(c.name)}')" title="${t('openvpn.restore')}">
                                                            <i class="ti ti-restore"></i>
                                                        </button>
                                                        <button class="btn btn-sm btn-outline-danger" onclick="deleteClientPermanent('${escapeHtml(c.name)}')" title="${t('openvpn.deletePermanent')}">
                                                            <i class="ti ti-trash"></i>
                                                        </button>` : ''}
                                                    </div>
                                                </td>
                                            </tr>
                                        `).join('')}
                                    </tbody>
                                </table>
                            </div>
                        `}
                    </div>
                </div>

                <!-- PKI Tab -->
                <div class="tab-pane fade" id="pane-pki" role="tabpanel">
                    <div class="card card-body border-top-0 rounded-top-0" id="pki-content">
                        <div class="text-center py-4 text-muted">
                            <i class="ti ti-loader ti-spin" style="font-size: 2rem;"></i>
                            <p class="mt-2">${t('openvpn.loading')}</p>
                        </div>
                    </div>
                </div>

                <!-- Firewall Tab -->
                <div class="tab-pane fade" id="pane-firewall" role="tabpanel">
                    <div class="card card-body border-top-0 rounded-top-0" id="firewall-content">
                        <div class="text-center py-4 text-muted">
                            <i class="ti ti-loader ti-spin" style="font-size: 2rem;"></i>
                            <p class="mt-2">${t('openvpn.loading')}</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- New Client Modal -->
        <div class="modal" id="modal-new-client" tabindex="-1">
            <div class="modal-dialog modal-sm">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${t('openvpn.newClientTitle')}</h5>
                        <button class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label" for="new-client-name">${t('openvpn.clientNameLabel')}</label>
                            <input type="text" class="form-control" id="new-client-name" placeholder="${t('openvpn.clientNamePlaceholder')}">
                            <small class="form-hint">${t('openvpn.clientNameHint')}</small>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">${t('openvpn.clientCertDays')}</label>
                            <input type="number" class="form-control" id="new-client-cert-days" placeholder="${t('openvpn.clientCertDaysPlaceholder')}">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">${t('openvpn.firewallGroup')}</label>
                            <select class="form-select" id="new-client-group">
                                <option value="">${t('openvpn.noGroup')}</option>
                            </select>
                            <small class="form-hint">${t('openvpn.firewallGroupHint')}</small>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" data-bs-dismiss="modal">${t('openvpn.cancel')}</button>
                        <button class="btn btn-primary" id="btn-confirm-new-client">${t('openvpn.create')}</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Edit Defaults Modal -->
        <div class="modal" id="modal-edit-defaults" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title"><i class="ti ti-settings me-2"></i>${t('openvpn.editDefaultSettings')}</h5>
                        <button class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">${t('openvpn.tunnelMode')}</label>
                            <div class="row g-2">
                                <div class="col-6">
                                    <input type="radio" class="btn-check" name="defaults-tunnel-mode" id="defaults-tunnel-full" value="full" ${instance.tunnel_mode === 'full' ? 'checked' : ''}>
                                    <label class="btn btn-outline-primary w-100 text-start py-2 d-block" for="defaults-tunnel-full">
                                        <i class="ti ti-world me-2"></i><strong>${t('openvpn.fullTunnel')}</strong><br>
                                        <small class="opacity-75">${t('openvpn.fullTunnelDesc')}</small>
                                    </label>
                                </div>
                                <div class="col-6">
                                    <input type="radio" class="btn-check" name="defaults-tunnel-mode" id="defaults-tunnel-split" value="split" ${instance.tunnel_mode === 'split' ? 'checked' : ''}>
                                    <label class="btn btn-outline-primary w-100 text-start py-2 d-block" for="defaults-tunnel-split">
                                        <i class="ti ti-route me-2"></i><strong>${t('openvpn.splitTunnel')}</strong><br>
                                        <small class="opacity-75">${t('openvpn.splitTunnelDesc')}</small>
                                    </label>
                                </div>
                            </div>
                        </div>

                        <div id="defaults-routes-section" class="${instance.tunnel_mode === 'full' ? 'd-none' : ''}">
                            <div class="mb-3">
                                <label class="form-label">${t('openvpn.splitRoutesLabel')}</label>
                                <div id="defaults-routes-list">
                                    ${(instance.routes || []).length > 0
                                        ? (instance.routes || []).map(r => `
                                            <div class="defaults-route-row mb-2 d-flex gap-2 align-items-center">
                                                <input type="text" class="form-control defaults-route-input" value="${r.network || r}" placeholder="es. 192.168.1.0/24" style="flex: 2">
                                                <select class="form-select defaults-route-interface route-interface" style="flex: 1">
                                                    <option value="">Auto</option>
                                                    ${networkInterfaces.map(iface => `<option value="${iface.name}" ${r.interface === iface.name ? 'selected' : ''}>${iface.name}</option>`).join('')}
                                                </select>
                                                <button class="btn btn-outline-danger defaults-remove-route" type="button"><i class="ti ti-minus"></i></button>
                                            </div>
                                        `).join('')
                                        : ''}
                                    <div class="defaults-route-row mb-2 d-flex gap-2 align-items-center defaults-add-row">
                                        <input type="text" class="form-control defaults-route-input" placeholder="es. 192.168.1.0/24" style="flex: 2">
                                        <select class="form-select defaults-route-interface route-interface" style="flex: 1">
                                            <option value="">Auto</option>
                                            ${networkInterfaces.map(iface => `<option value="${iface.name}">${iface.name}</option>`).join('')}
                                        </select>
                                        <button class="btn btn-outline-success btn-add-defaults-route" type="button"><i class="ti ti-plus"></i></button>
                                    </div>
                                </div>
                                <small class="form-hint d-block mt-2">${t('openvpn.splitRoutesHint')}</small>
                            </div>
                        </div>

                        <hr>

                        <div class="mb-3">
                            <label class="form-label">${t('openvpn.dnsServers')}</label>
                            <input type="text" class="form-control" id="edit-default-dns"
                                   value="${(instance.dns_servers || []).join(', ')}"
                                   placeholder="1.1.1.1, 8.8.8.8">
                            <small class="form-hint">${t('openvpn.dnsHintAdvanced')}</small>
                        </div>

                        <div class="mb-3">
                            <label class="form-label">${t('openvpn.endpointPublic')}</label>
                            <input type="text" class="form-control" id="edit-default-endpoint"
                                   value="${instance.endpoint || ''}"
                                   placeholder="vpn.example.com">
                            <small class="form-hint">${t('openvpn.endpointHint')}</small>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">${t('openvpn.cancel')}</button>
                        <button class="btn btn-primary" id="btn-save-defaults">
                            <i class="ti ti-device-floppy me-1"></i>${t('openvpn.saveChanges')}
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Send Email Modal -->
        <div class="modal" id="modal-send-email" tabindex="-1">
            <div class="modal-dialog modal-sm">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${t('openvpn.sendConfigEmail')}</h5>
                        <button class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <input type="hidden" id="send-email-client-name">
                        <div class="mb-3">
                            <label class="form-label" for="send-email-address">${t('openvpn.emailRecipient')}</label>
                            <input type="email" class="form-control" id="send-email-address" placeholder="${t('openvpn.emailRecipientPlaceholder')}">
                            <small class="form-hint">${t('openvpn.emailHint')}</small>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" data-bs-dismiss="modal">${t('openvpn.cancel')}</button>
                        <button class="btn btn-success" id="btn-send-email">
                            <i class="ti ti-mail me-1"></i>${t('openvpn.send')}
                        </button>
                    </div>
                </div>
            </div>
        </div>
        `;

        // New client - open modal and load groups
        document.getElementById('btn-new-client')?.addEventListener('click', async () => {
            document.getElementById('new-client-name').value = '';
            document.getElementById('new-client-cert-days').value = '';
            const groupSelect = document.getElementById('new-client-group');
            groupSelect.innerHTML = `<option value="">${t('openvpn.noGroup')}</option>`;
            try {
                const groups = await apiGet(`${MODULE_API}/instances/${currentInstanceId}/groups`);
                groups.forEach(g => {
                    groupSelect.innerHTML += `<option value="${g.id}">${escapeHtml(g.name)}</option>`;
                });
            } catch (e) { /* Groups not available */ }
            new bootstrap.Modal(document.getElementById('modal-new-client')).show();
        });

        // Confirm new client
        document.getElementById('btn-confirm-new-client')?.addEventListener('click', async () => {
            const name = document.getElementById('new-client-name').value.trim();
            const certDays = document.getElementById('new-client-cert-days').value;
            const groupId = document.getElementById('new-client-group').value || null;
            if (!name) {
                showToast(t('openvpn.clientNameLabel') + ' ' + t('openvpn.insertName'), 'error');
                return;
            }
            try {
                await apiPost(`${MODULE_API}/instances/${currentInstanceId}/clients`, {
                    name,
                    cert_duration_days: certDays ? parseInt(certDays) : null,
                    group_id: groupId
                });
                showToast(t('openvpn.clientCreated'), 'success');
                bootstrap.Modal.getInstance(document.getElementById('modal-new-client'))?.hide();
                renderInstanceDetail(container, canManage, canClients);
            } catch (err) {
                showToast(err.message, 'error');
            }
        });

        // Edit defaults
        document.getElementById('btn-edit-defaults')?.addEventListener('click', async () => {
            await loadNetworkInterfaces();
            populateInterfaceSelects();
            new bootstrap.Modal(document.getElementById('modal-edit-defaults')).show();
        });

        // Toggle routes section
        document.querySelectorAll('input[name="defaults-tunnel-mode"]').forEach(radio => {
            radio.addEventListener('change', () => {
                const routesSection = document.getElementById('defaults-routes-section');
                if (document.getElementById('defaults-tunnel-split').checked) {
                    routesSection.classList.remove('d-none');
                } else {
                    routesSection.classList.add('d-none');
                }
            });
        });

        // Route add/remove event delegation
        document.getElementById('defaults-routes-list')?.addEventListener('click', (e) => {
            const addBtn = e.target.closest('.btn-add-defaults-route');
            const removeBtn = e.target.closest('.defaults-remove-route');

            if (addBtn) {
                const addRow = addBtn.closest('.defaults-add-row');
                const input = addRow.querySelector('.defaults-route-input');
                const select = addRow.querySelector('.defaults-route-interface');
                const network = input.value.trim();
                if (!network) return;
                if (!isValidCIDR(network)) { input.classList.add('is-invalid'); return; }
                input.classList.remove('is-invalid');
                const row = document.createElement('div');
                row.className = 'defaults-route-row mb-2 d-flex gap-2 align-items-center';
                row.innerHTML = `
                    <input type="text" class="form-control defaults-route-input" value="${escapeHtml(network)}" placeholder="es. 192.168.1.0/24" style="flex: 2">
                    <select class="form-select defaults-route-interface route-interface" style="flex: 1">
                        <option value="">Auto</option>
                        ${networkInterfaces.map(iface => `<option value="${iface.name}" ${select.value === iface.name ? 'selected' : ''}>${iface.name}</option>`).join('')}
                    </select>
                    <button class="btn btn-outline-danger defaults-remove-route" type="button"><i class="ti ti-minus"></i></button>
                `;
                addRow.parentNode.insertBefore(row, addRow);
                input.value = '';
                select.value = '';
            }

            if (removeBtn && !removeBtn.closest('.defaults-add-row')) {
                removeBtn.closest('.defaults-route-row').remove();
            }
        });

        // Save defaults
        document.getElementById('btn-save-defaults')?.addEventListener('click', async () => {
            const btn = document.getElementById('btn-save-defaults');
            const originalHtml = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('openvpn.saving')}`;

            try {
                const tunnelMode = document.querySelector('input[name="defaults-tunnel-mode"]:checked')?.value || 'full';
                const dnsInput = document.getElementById('edit-default-dns').value.trim();
                const dnsServers = dnsInput ? dnsInput.split(',').map(s => s.trim()).filter(s => s) : [];
                const endpoint = document.getElementById('edit-default-endpoint').value.trim() || null;

                let routes = [];
                let hasInvalidCidr = false;
                if (tunnelMode === 'split') {
                    document.querySelectorAll('.defaults-route-row:not(.defaults-add-row)').forEach(row => {
                        const input = row.querySelector('.defaults-route-input');
                        const network = input?.value.trim();
                        const iface = row.querySelector('.defaults-route-interface')?.value;
                        if (network) {
                            if (!isValidCIDR(network)) { hasInvalidCidr = true; input.classList.add('is-invalid'); }
                            else { input.classList.remove('is-invalid'); routes.push({ network, interface: iface || null }); }
                        }
                    });
                    const addRowInput = document.querySelector('.defaults-add-row .defaults-route-input');
                    const addRowNetwork = addRowInput?.value.trim();
                    if (addRowNetwork) {
                        if (!isValidCIDR(addRowNetwork)) { hasInvalidCidr = true; addRowInput.classList.add('is-invalid'); }
                        else {
                            addRowInput.classList.remove('is-invalid');
                            const addRowIface = document.querySelector('.defaults-add-row .defaults-route-interface')?.value;
                            routes.push({ network: addRowNetwork, interface: addRowIface || null });
                        }
                    }
                    if (hasInvalidCidr) { showToast(t('openvpn.invalidCIDR'), 'error'); btn.disabled = false; btn.innerHTML = originalHtml; return; }
                    if (routes.length === 0) { showToast(t('openvpn.splitTunnelRequiresRoute'), 'error'); btn.disabled = false; btn.innerHTML = originalHtml; return; }
                }

                const result = await apiPatch(`${MODULE_API}/instances/${currentInstanceId}/routing`, {
                    tunnel_mode: tunnelMode, routes, dns_servers: dnsServers
                });
                if (endpoint !== instance.endpoint) {
                    await apiPatch(`${MODULE_API}/instances/${currentInstanceId}`, { endpoint });
                }
                bootstrap.Modal.getInstance(document.getElementById('modal-edit-defaults'))?.hide();
                showToast(result.message || t('openvpn.defaultsUpdated'), 'success');
                if (result.warning) setTimeout(() => showToast(result.warning, 'warning'), 1500);
                renderInstanceDetail(container, canManage, canClients);
            } catch (err) {
                showToast(err.message, 'error');
            } finally {
                btn.disabled = false;
                btn.innerHTML = originalHtml;
            }
        });

        registerGlobalFunctions(container, canManage, canClients);

        // Load PKI tab on click
        document.getElementById('tab-pki')?.addEventListener('shown.bs.tab', async () => {
            await loadPKIStatus(canManage);
        });

        // Load firewall tab on click
        document.getElementById('tab-firewall')?.addEventListener('shown.bs.tab', async () => {
            try {
                const firewallModule = await import('./firewall.js');
                await firewallModule.init(document.getElementById('firewall-content'), currentInstanceId);
            } catch (err) {
                document.getElementById('firewall-content').innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
            }
        });
    } catch (err) {
        container.innerHTML = `<div class="alert alert-danger"><i class="ti ti-alert-circle me-2"></i>${err.message}</div>`;
    }
}

async function loadPKIStatus(canManage) {
    const pkiContent = document.getElementById('pki-content');
    try {
        const [instance, pkiStatus] = await Promise.all([
            apiGet(`${MODULE_API}/instances/${currentInstanceId}`),
            apiGet(`${MODULE_API}/instances/${currentInstanceId}/pki/status`)
        ]);
        pkiContent.innerHTML = `
            <div class="row">
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header"><h4 class="card-title">${t('openvpn.serverCertTitle')}</h4></div>
                        <div class="card-body">
                            <div class="datagrid">
                                <div class="datagrid-item">
                                    <div class="datagrid-title">${t('openvpn.certExpiry')}</div>
                                    <div class="datagrid-content">
                                        ${instance.server_cert_expiry ? new Date(instance.server_cert_expiry).toLocaleDateString(undefined) : 'N/A'}
                                    </div>
                                </div>
                                <div class="datagrid-item">
                                    <div class="datagrid-title">${t('openvpn.daysRemaining')}</div>
                                    <div class="datagrid-content">${renderCertStatus(pkiStatus.server_cert_days_remaining, false)}</div>
                                </div>
                            </div>
                            ${canManage ? `
                            <button class="btn btn-warning mt-3" onclick="renewServerCert()">
                                <i class="ti ti-refresh me-1"></i>${t('openvpn.renewServerCert')}
                            </button>` : ''}
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header"><h4 class="card-title">${t('openvpn.caTitle')}</h4></div>
                        <div class="card-body">
                            <div class="datagrid">
                                <div class="datagrid-item">
                                    <div class="datagrid-title">${t('openvpn.caExpiry')}</div>
                                    <div class="datagrid-content">
                                        ${pkiStatus.ca_expiry ? new Date(pkiStatus.ca_expiry).toLocaleDateString(undefined) : 'N/A'}
                                    </div>
                                </div>
                                <div class="datagrid-item">
                                    <div class="datagrid-title">${t('openvpn.revokedClients')}</div>
                                    <div class="datagrid-content">${pkiStatus.revoked_clients_count}</div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    } catch (err) {
        pkiContent.innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
    }
}

function registerGlobalFunctions(container, canManage, canClients) {
    window.startInstance = async (id) => {
        try {
            await apiPost(`${MODULE_API}/instances/${id}/start`);
            showToast(t('openvpn.instanceStarted'), 'success');
            if (currentContainer) renderInstanceDetail(currentContainer, canManage, canClients);
        } catch (err) { showToast(err.message, 'error'); }
    };

    window.stopInstance = async (id) => {
        try {
            await apiPost(`${MODULE_API}/instances/${id}/stop`);
            showToast(t('openvpn.instanceStopped'), 'success');
            if (currentContainer) renderInstanceDetail(currentContainer, canManage, canClients);
        } catch (err) { showToast(err.message, 'error'); }
    };

    window.deleteInstance = async (id) => {
        if (await confirmDialog(t('openvpn.confirmDeleteInstance'), t('openvpn.confirmDeleteInstanceMsg'))) {
            try {
                await apiDelete(`${MODULE_API}/instances/${id}`);
                showToast(t('openvpn.instanceDeleted'), 'success');
                location.href = '#openvpn';
            } catch (err) { showToast(err.message, 'error'); }
        }
    };

    window.downloadConfig = async (name) => {
        try {
            const token = localStorage.getItem('madmin_token');
            const res = await fetch(`/api${MODULE_API}/instances/${currentInstanceId}/clients/${name}/config`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!res.ok) throw new Error(t('openvpn.downloadFailed') + ': ' + res.statusText);
            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = `${name}.ovpn`;
            document.body.appendChild(a); a.click();
            window.URL.revokeObjectURL(url); document.body.removeChild(a);
        } catch (err) { showToast(err.message, 'error'); }
    };

    window.showQR = async (name) => {
        try {
            const token = localStorage.getItem('madmin_token');
            const res = await fetch(`/api${MODULE_API}/instances/${currentInstanceId}/clients/${name}/qr`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!res.ok) throw new Error(t('openvpn.loadQRFailed') + ': ' + res.statusText);
            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const modal = document.createElement('div');
            modal.innerHTML = `
                <div class="modal fade" tabindex="-1">
                    <div class="modal-dialog modal-sm">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h5 class="modal-title">${t('openvpn.qrTitle').replace('{name}', escapeHtml(name))}</h5>
                                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                            </div>
                            <div class="modal-body text-center p-4">
                                <img src="${url}" class="img-fluid" alt="QR Code">
                                <p class="mt-3 mb-0 text-muted small">${t('openvpn.qrHint')}</p>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
            const bsModal = new bootstrap.Modal(modal.querySelector('.modal'));
            bsModal.show();
            modal.querySelector('.modal').addEventListener('hidden.bs.modal', () => { modal.remove(); window.URL.revokeObjectURL(url); });
        } catch (err) { showToast(err.message, 'error'); }
    };

    window.revokeClient = async (name) => {
        if (await confirmDialog(t('openvpn.confirmRevoke'), t('openvpn.confirmRevokeMsg').replace('{name}', name), 'Revoca')) {
            try {
                await apiDelete(`${MODULE_API}/instances/${currentInstanceId}/clients/${name}`);
                showToast(t('openvpn.clientRevoked'), 'success');
                if (currentContainer) renderInstanceDetail(currentContainer, canManage, canClients);
            } catch (err) { showToast(err.message, 'error'); }
        }
    };

    window.renewClientCert = async (name) => {
        if (await confirmDialog(t('openvpn.confirmRenewCert'), t('openvpn.confirmRenewCertMsg').replace('{name}', name))) {
            try {
                await apiPost(`${MODULE_API}/instances/${currentInstanceId}/clients/${name}/renew`);
                showToast(t('openvpn.certRenewed'), 'success');
                if (currentContainer) renderInstanceDetail(currentContainer, canManage, canClients);
            } catch (err) { showToast(err.message, 'error'); }
        }
    };

    window.restoreClient = async (name) => {
        if (await confirmDialog(t('openvpn.confirmRestoreClient'), t('openvpn.confirmRestoreClientMsg').replace('{name}', name), t('openvpn.confirmRestoreBtn'))) {
            try {
                await apiPost(`${MODULE_API}/instances/${currentInstanceId}/clients/${name}/restore`);
                showToast(t('openvpn.clientRestored'), 'success');
                if (currentContainer) renderInstanceDetail(currentContainer, canManage, canClients);
            } catch (err) { showToast(err.message, 'error'); }
        }
    };

    window.deleteClientPermanent = async (name) => {
        if (await confirmDialog(t('openvpn.confirmDeleteClient'), t('openvpn.confirmDeleteClientMsg').replace('{name}', name))) {
            try {
                await apiDelete(`${MODULE_API}/instances/${currentInstanceId}/clients/${name}/permanent`);
                showToast(t('openvpn.clientDeleted'), 'success');
                if (currentContainer) renderInstanceDetail(currentContainer, canManage, canClients);
            } catch (err) { showToast(err.message, 'error'); }
        }
    };

    window.renewServerCert = async () => {
        if (await confirmDialog(t('openvpn.confirmRenewServer'), t('openvpn.confirmRenewServerMsg'))) {
            try {
                await apiPost(`${MODULE_API}/instances/${currentInstanceId}/pki/renew-server`);
                showToast(t('openvpn.serverCertRenewed'), 'success');
                if (currentContainer) renderInstanceDetail(currentContainer, canManage, canClients);
            } catch (err) { showToast(err.message, 'error'); }
        }
    };

    window.openSendEmailModal = (clientName) => {
        document.getElementById('send-email-client-name').value = clientName;
        document.getElementById('send-email-address').value = '';
        new bootstrap.Modal(document.getElementById('modal-send-email')).show();
    };
}

// Send email button handler
document.addEventListener('click', async (e) => {
    if (e.target.id === 'btn-send-email' || e.target.closest('#btn-send-email')) {
        const clientName = document.getElementById('send-email-client-name')?.value;
        const email = document.getElementById('send-email-address')?.value.trim();
        if (!email) { showToast(t('openvpn.fillEmailField'), 'error'); return; }
        const btn = document.getElementById('btn-send-email');
        const originalHtml = btn.innerHTML;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('openvpn.sending')}`;
        btn.disabled = true;
        try {
            await apiPost(`${MODULE_API}/instances/${currentInstanceId}/clients/${clientName}/send-config`, { email });
            showToast(t('openvpn.emailSent').replace('{email}', email), 'success');
            bootstrap.Modal.getInstance(document.getElementById('modal-send-email'))?.hide();
        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            btn.innerHTML = originalHtml;
            btn.disabled = false;
        }
    }
});

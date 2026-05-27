/**
 * WireGuard Module - Instance Detail View
 *
 * Displays instance details, clients, and firewall tab.
 */

import { t } from '/static/js/i18n.js';
import { apiGet, apiPost, apiPatch, apiDelete } from '/static/js/api.js';
import { showToast, confirmDialog, escapeHtml, isValidCIDR } from '/static/js/utils.js';

const MODULE_API = '/modules/wireguard';

let currentInstanceId = null;
let currentContainer = null;
let networkInterfaces = [];

export async function renderWgDetail(container, instanceId, canManage, canClients) {
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

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatTimeAgo(isoString) {
    if (!isoString) return t('wireguard.never');
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return t('wireguard.justNow');
    if (diffSec < 3600) return t('wireguard.minutesAgo').replace('{n}', Math.floor(diffSec / 60));
    if (diffSec < 86400) return t('wireguard.hoursAgo').replace('{n}', Math.floor(diffSec / 3600));
    return t('wireguard.daysAgo').replace('{n}', Math.floor(diffSec / 86400));
}

async function renderInstanceDetail(container, canManage, canClients) {
    try {
        const instance = await apiGet(`${MODULE_API}/instances/${currentInstanceId}`);

        if (instance.direction === 'client') {
            await renderClientModeDetail(container, instance, canManage);
            return;
        }

        const clients = await apiGet(`${MODULE_API}/instances/${currentInstanceId}/clients`);

        container.innerHTML = `
            <div class="mb-3">
                <a href="#wireguard" class="text-muted">
                    <i class="ti ti-arrow-left me-1"></i>${t('wireguard.backToInstances')}
                </a>
            </div>

            <!-- Instance Info Card -->
            <div class="card mb-3">
                <div class="card-header">
                    <div class="d-flex justify-content-between align-items-center w-100">
                        <div>
                            <h3 class="card-title mb-0">${escapeHtml(instance.name)}</h3>
                            <small class="text-muted">${t('wireguard.interface')}: ${instance.interface}</small>
                        </div>
                        <div class="btn-group">
                            ${canManage ? `
                            <button class="btn ${instance.status === 'running' ? 'btn-warning' : 'btn-success'}"
                                    onclick="${instance.status === 'running' ? 'stopInstance' : 'startInstance'}('${instance.id}')">
                                <i class="ti ti-player-${instance.status === 'running' ? 'stop' : 'play'} me-1"></i>
                                ${instance.status === 'running' ? t('wireguard.stop') : t('wireguard.start')}
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
                            <span class="text-muted">${t('wireguard.status')}</span><br>
                            <span class="badge ${instance.status === 'running' ? 'bg-success-lt' : 'bg-secondary-lt'} fs-6">
                                ${instance.status === 'running' ? t('wireguard.statusRunning') : t('wireguard.statusStopped')}
                            </span>
                        </div>
                        <div class="col-md-3">
                            <span class="text-muted">${t('wireguard.port')}</span><br>
                            <strong>${instance.port}/UDP</strong>
                        </div>
                        <div class="col-md-3">
                            <span class="text-muted">${t('wireguard.vpnSubnet')}</span><br>
                            <code>${instance.subnet}</code>
                        </div>
                        <div class="col-md-3">
                            <span class="text-muted">${t('wireguard.activeClients')}</span><br>
                            <strong>${instance.client_count}</strong>
                        </div>
                    </div>

                    <hr>

                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <h4 class="mb-0"><i class="ti ti-settings me-2"></i>${t('wireguard.defaultSettings')}</h4>
                        ${canManage ? `<button class="btn btn-sm btn-outline-primary" id="btn-edit-defaults">
                            <i class="ti ti-edit me-1"></i>${t('wireguard.edit')}
                        </button>` : ''}
                    </div>

                    <div class="row">
                        <div class="col-md-4">
                            <div class="mb-2">
                                <span class="text-muted">${t('wireguard.routingMode')}</span><br>
                                <span id="display-tunnel-mode" class="badge ${instance.tunnel_mode === 'full' ? 'bg-blue' : 'bg-purple'}-lt fs-6">
                                    ${instance.tunnel_mode === 'full' ? t('wireguard.fullTunnel') : t('wireguard.splitTunnel')}
                                </span>
                            </div>
                            ${instance.tunnel_mode === 'split' && instance.routes?.length ? `
                            <div class="mt-2">
                                <small class="text-muted">${t('wireguard.routes')}:</small><br>
                                <div class="d-flex flex-wrap gap-1 mt-1">
                                    ${instance.routes.map(r => `<code class="badge bg-light text-dark">${r.network || r}</code>`).join('')}
                                </div>
                            </div>
                            ` : ''}
                        </div>
                        <div class="col-md-4">
                            <span class="text-muted">${t('wireguard.defaultDns')}</span><br>
                            <code id="display-dns">${instance.dns_servers?.join(', ') || '8.8.8.8, 1.1.1.1'}</code>
                        </div>
                        <div class="col-md-4">
                            <span class="text-muted">${t('wireguard.publicEndpoint')}</span><br>
                            <code id="display-endpoint">${instance.endpoint || t('wireguard.endpointAuto')}</code>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Tabs -->
            <ul class="nav nav-tabs" role="tablist">
                <li class="nav-item" role="presentation">
                    <button class="nav-link active" id="tab-clients" data-bs-toggle="tab" data-bs-target="#pane-clients" type="button">
                        <i class="ti ti-users me-1"></i>${t('wireguard.clientsTab').replace('{n}', clients.length)}
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link" id="tab-firewall" data-bs-toggle="tab" data-bs-target="#pane-firewall" type="button">
                        <i class="ti ti-shield me-1"></i>${t('wireguard.firewallTab')}
                    </button>
                </li>
            </ul>

            <div class="tab-content">
                <!-- Clients Tab -->
                <div class="tab-pane fade show active" id="pane-clients" role="tabpanel">
                    <div class="card card-body border-top-0 rounded-top-0">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <h4 class="mb-0">${t('wireguard.vpnClients')}</h4>
                            ${canClients ? `
                            <button class="btn btn-primary" id="btn-new-client">
                                <i class="ti ti-user-plus me-1"></i>${t('wireguard.newClient')}
                            </button>` : ''}
                        </div>
                        ${clients.length === 0 ? `
                            <div class="text-center py-4 text-muted">
                                <i class="ti ti-users-minus" style="font-size: 2rem;"></i>
                                <p class="mt-2">${t('wireguard.noClients')}</p>
                                <small>${t('wireguard.noClientsHint')}</small>
                            </div>
                        ` : `
                            <div class="table-responsive">
                                <table class="table table-vcenter">
                                    <thead>
                                        <tr>
                                            <th>${t('wireguard.clientStatus')}</th>
                                            <th>${t('wireguard.clientName')}</th>
                                            <th>${t('wireguard.assignedIp')}</th>
                                            <th>${t('wireguard.traffic')}</th>
                                            <th>${t('wireguard.lastConnection')}</th>
                                            <th class="w-1">${t('wireguard.actions')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        ${clients.map(c => `
                                            <tr>
                                                <td>
                                                    ${c.is_connected === true
                                                        ? `<span class="status-dot status-dot-animated bg-success" title="${t('wireguard.connected')}"></span>`
                                                        : `<span class="status-dot bg-secondary" title="${t('wireguard.disconnected')}"></span>`}
                                                </td>
                                                <td>
                                                    <strong>${escapeHtml(c.name)}</strong>
                                                    ${(c.allowed_ips || c.dns) ? `
                                                        <span class="ms-2" data-bs-toggle="tooltip" data-bs-html="true"
                                                              title="<strong>${t('wireguard.customConfigTooltipTitle')}</strong><br>
                                                                     ${c.allowed_ips ? t('wireguard.routesOverride') + ': ' + escapeHtml(c.allowed_ips) + '<br>' : ''}
                                                                     ${c.dns ? t('wireguard.dnsOverride') + ': ' + escapeHtml(c.dns) : ''}">
                                                            <i class="ti ti-adjustments text-blue"></i>
                                                        </span>
                                                    ` : ''}
                                                </td>
                                                <td><code>${c.allocated_ip}</code></td>
                                                <td>
                                                    ${c.is_connected === true ? `
                                                    <small class="text-muted">
                                                        <i class="ti ti-arrow-down text-success"></i> ${formatBytes(c.rx_bytes || 0)}
                                                        <i class="ti ti-arrow-up text-primary ms-2"></i> ${formatBytes(c.tx_bytes || 0)}
                                                    </small>
                                                    ` : '<small class="text-muted">-</small>'}
                                                </td>
                                                <td>
                                                    ${c.last_seen
                                                        ? `<small class="text-muted">${formatTimeAgo(c.last_seen)}</small>`
                                                        : `<small class="text-muted">${t('wireguard.neverConnected')}</small>`}
                                                </td>
                                                <td>
                                                    <div class="btn-group">
                                                        ${canClients ? `
                                                        <button class="btn btn-sm btn-outline-primary" onclick="downloadConfig('${escapeHtml(c.name)}')" title="${t('wireguard.downloadConfig')}">
                                                            <i class="ti ti-download"></i>
                                                        </button>
                                                        <button class="btn btn-sm btn-outline-secondary" onclick="showQR('${escapeHtml(c.name)}')" title="${t('wireguard.qrCode')}">
                                                            <i class="ti ti-qrcode"></i>
                                                        </button>
                                                        ${(c.allowed_ips || c.dns) ? `
                                                            <button class="btn btn-sm btn-outline-warning" onclick="resetClientDefaults('${escapeHtml(c.name)}')" title="${t('wireguard.resetDefaults')}" data-bs-toggle="tooltip">
                                                                <i class="ti ti-restore"></i>
                                                            </button>
                                                        ` : ''}
                                                        <button class="btn btn-sm btn-outline-success" onclick="openSendEmailModal('${escapeHtml(c.name)}')" title="${t('wireguard.sendEmail')}">
                                                            <i class="ti ti-mail"></i>
                                                        </button>
                                                        <button class="btn btn-sm btn-outline-danger" onclick="revokeClient('${escapeHtml(c.name)}')" title="${t('wireguard.revoke')}">
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

                <!-- Firewall Tab -->
                <div class="tab-pane fade" id="pane-firewall" role="tabpanel">
                    <div class="card card-body border-top-0 rounded-top-0" id="firewall-content">
                        <div class="text-center py-4 text-muted">
                            <i class="ti ti-loader ti-spin" style="font-size: 2rem;"></i>
                            <p class="mt-2">${t('wireguard.loading')}</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- New Client Modal -->
        <div class="modal" id="modal-new-client" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${t('wireguard.newClient')}</h5>
                        <button class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label" for="new-client-name">${t('wireguard.clientNameLabel')}</label>
                            <input type="text" class="form-control" id="new-client-name" placeholder="es. iPhone-Mario">
                        </div>
                        <div class="mb-3" id="new-client-group-container" style="display: none;">
                            <label class="form-label" for="new-client-group">${t('wireguard.groupOptional')}</label>
                            <select class="form-select" id="new-client-group">
                                <option value="">${t('wireguard.noGroup')}</option>
                            </select>
                            <small class="form-hint">${t('wireguard.groupHint')}</small>
                        </div>

                        <div class="accordion" id="accordionOverrides">
                            <div class="accordion-item">
                                <h2 class="accordion-header">
                                    <button class="accordion-button collapsed" type="button"
                                            data-bs-toggle="collapse" data-bs-target="#collapseOverrides"
                                            style="font-size: 0.9375rem;">
                                        <i class="ti ti-settings me-2"></i>${t('wireguard.customConfig')}
                                    </button>
                                </h2>
                                <div id="collapseOverrides" class="accordion-collapse collapse">
                                    <div class="accordion-body">
                                        <div class="mb-3">
                                            <label class="form-label">${t('wireguard.routesOverride')}</label>
                                            <div id="new-client-routes-list">
                                                <div class="client-route-row mb-2 d-flex gap-2 align-items-center">
                                                    <input type="text" class="form-control client-route-input" placeholder="${t('wireguard.routesPlaceholder')}" style="flex: 1">
                                                    <button class="btn btn-outline-success btn-add-client-route" type="button">
                                                        <i class="ti ti-plus"></i>
                                                    </button>
                                                </div>
                                            </div>
                                            <small class="form-hint d-block mt-2">
                                                ${t('wireguard.routesHintDefault').replace('{default}', instance.default_allowed_ips || '0.0.0.0/0, ::/0')}<br>
                                                <strong>Tip:</strong> ${t('wireguard.routesTip')}
                                            </small>
                                        </div>
                                        <div class="mb-3">
                                            <label class="form-label">${t('wireguard.dnsOverride')}</label>
                                            <input type="text" class="form-control" id="new-client-dns"
                                                   placeholder="Default: ${instance.dns_servers?.join(', ') || '8.8.8.8, 1.1.1.1'}">
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" data-bs-dismiss="modal">${t('wireguard.cancel')}</button>
                        <button class="btn btn-primary" id="btn-confirm-new-client">${t('wireguard.create')}</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Edit Defaults Modal -->
        <div class="modal" id="modal-edit-defaults" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title"><i class="ti ti-settings me-2"></i>${t('wireguard.editDefaultsTitle')}</h5>
                        <button class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="alert alert-warning">
                            <i class="ti ti-alert-triangle me-2"></i>
                            ${t('wireguard.editDefaultsWarning')}
                        </div>

                        <div class="mb-3">
                            <label class="form-label">${t('wireguard.tunnelMode')}</label>
                            <div class="row g-2">
                                <div class="col-6">
                                    <input type="radio" class="btn-check" name="defaults-tunnel-mode" id="defaults-tunnel-full" value="full" ${instance.tunnel_mode === 'full' ? 'checked' : ''}>
                                    <label class="btn btn-outline-primary w-100 text-start py-2 d-block" for="defaults-tunnel-full">
                                        <i class="ti ti-world me-2"></i><strong>${t('wireguard.fullTunnel')}</strong><br>
                                        <small class="opacity-75">${t('wireguard.fullTunnelDesc')}</small>
                                    </label>
                                </div>
                                <div class="col-6">
                                    <input type="radio" class="btn-check" name="defaults-tunnel-mode" id="defaults-tunnel-split" value="split" ${instance.tunnel_mode === 'split' ? 'checked' : ''}>
                                    <label class="btn btn-outline-primary w-100 text-start py-2 d-block" for="defaults-tunnel-split">
                                        <i class="ti ti-route me-2"></i><strong>${t('wireguard.splitTunnel')}</strong><br>
                                        <small class="opacity-75">${t('wireguard.splitTunnelDesc')}</small>
                                    </label>
                                </div>
                            </div>
                        </div>

                        <div id="defaults-routes-section" class="${instance.tunnel_mode === 'full' ? 'd-none' : ''}">
                            <div class="mb-3">
                                <label class="form-label">${t('wireguard.splitRoutes')}</label>
                                <div id="defaults-routes-list">
                                    ${(instance.routes || []).length > 0
                                        ? (instance.routes || []).map(r => `
                                            <div class="defaults-route-row mb-2 d-flex gap-2 align-items-center">
                                                <input type="text" class="form-control defaults-route-input" value="${r.network || r}" placeholder="es. 192.168.1.0/24" style="flex: 2">
                                                <select class="form-select defaults-route-interface" style="flex: 1">
                                                    <option value="">Auto</option>
                                                    ${networkInterfaces.map(iface => `<option value="${iface.name}" ${r.interface === iface.name ? 'selected' : ''}>${iface.name}</option>`).join('')}
                                                </select>
                                                <button class="btn btn-outline-danger defaults-remove-route" type="button"><i class="ti ti-minus"></i></button>
                                            </div>
                                        `).join('')
                                        : ''}
                                    <div class="defaults-route-row mb-2 d-flex gap-2 align-items-center defaults-add-row">
                                        <input type="text" class="form-control defaults-route-input" placeholder="es. 192.168.1.0/24" style="flex: 2">
                                        <select class="form-select defaults-route-interface" style="flex: 1">
                                            <option value="">Auto</option>
                                            ${networkInterfaces.map(iface => `<option value="${iface.name}">${iface.name}</option>`).join('')}
                                        </select>
                                        <button class="btn btn-outline-success btn-add-defaults-route" type="button"><i class="ti ti-plus"></i></button>
                                    </div>
                                </div>
                                <small class="form-hint d-block mt-2">${t('wireguard.splitRoutesHint')}</small>
                            </div>
                        </div>

                        <hr>

                        <div class="mb-3">
                            <label class="form-label">${t('wireguard.dnsServers')}</label>
                            <input type="text" class="form-control" id="edit-default-dns"
                                   value="${instance.dns_servers?.join(', ') || '8.8.8.8, 1.1.1.1'}"
                                   placeholder="8.8.8.8, 1.1.1.1">
                            <small class="form-hint">${t('wireguard.dnsHint')}</small>
                        </div>

                        <div class="mb-3">
                            <label class="form-label">${t('wireguard.publicEndpoint')}</label>
                            <input type="text" class="form-control" id="edit-default-endpoint"
                                   value="${instance.endpoint || ''}"
                                   placeholder="${t('wireguard.autoEndpoint')}">
                            <small class="form-hint">${t('wireguard.endpointHint')}</small>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">${t('wireguard.cancel')}</button>
                        <button class="btn btn-primary" id="btn-save-defaults">
                            <i class="ti ti-device-floppy me-1"></i>${t('wireguard.saveChanges')}
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
                        <h5 class="modal-title">${t('wireguard.sendConfigEmail')}</h5>
                        <button class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <input type="hidden" id="send-email-client-name">
                        <div class="mb-3">
                            <label class="form-label" for="send-email-address">${t('wireguard.recipientEmail')}</label>
                            <input type="email" class="form-control" id="send-email-address" placeholder="utente@example.com">
                            <small class="form-hint">${t('wireguard.emailHint')}</small>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" data-bs-dismiss="modal">${t('wireguard.cancel')}</button>
                        <button class="btn btn-success" id="btn-send-email">
                            <i class="ti ti-mail me-1"></i>${t('wireguard.send')}
                        </button>
                    </div>
                </div>
            </div>
        </div>
        `;

        // Inject site-to-site panel before tabs (server mode)
        const tabsEl = container.querySelector('.nav.nav-tabs');
        if (tabsEl) {
            const s2sPanel = createS2SPanel(instance, canManage);
            tabsEl.parentNode.insertBefore(s2sPanel, tabsEl);
            setupS2SHandlers(instance, canManage, canClients);
        }

        // Initialize Bootstrap tooltips
        document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => new bootstrap.Tooltip(el));

        // Add route button in new client modal
        document.getElementById('new-client-routes-list')?.addEventListener('click', (e) => {
            const addBtn = e.target.closest('.btn-add-client-route');
            const removeBtn = e.target.closest('.btn-remove-client-route');
            if (addBtn) {
                const list = document.getElementById('new-client-routes-list');
                const row = document.createElement('div');
                row.className = 'client-route-row mb-2 d-flex gap-2 align-items-center';
                row.innerHTML = `
                    <input type="text" class="form-control client-route-input" placeholder="${t('wireguard.routesPlaceholder')}" style="flex: 1">
                    <button class="btn btn-outline-danger btn-remove-client-route" type="button"><i class="ti ti-minus"></i></button>
                `;
                list.appendChild(row);
            }
            if (removeBtn) removeBtn.closest('.client-route-row').remove();
        });

        // New client button
        document.getElementById('btn-new-client')?.addEventListener('click', async () => {
            document.getElementById('new-client-name').value = '';
            document.getElementById('new-client-routes-list').innerHTML = `
                <div class="client-route-row mb-2 d-flex gap-2 align-items-center">
                    <input type="text" class="form-control client-route-input" placeholder="${t('wireguard.routesPlaceholder')}" style="flex: 1">
                    <button class="btn btn-outline-success btn-add-client-route" type="button"><i class="ti ti-plus"></i></button>
                </div>
            `;
            document.getElementById('new-client-dns').value = '';
            try {
                const groups = await apiGet(`${MODULE_API}/instances/${currentInstanceId}/groups`);
                const groupSelect = document.getElementById('new-client-group');
                const groupContainer = document.getElementById('new-client-group-container');
                groupSelect.innerHTML = `<option value="">${t('wireguard.noGroup')}</option>`;
                if (groups && groups.length > 0) {
                    groups.forEach(g => { groupSelect.innerHTML += `<option value="${g.id}">${escapeHtml(g.name)}</option>`; });
                    groupContainer.style.display = 'block';
                } else {
                    groupContainer.style.display = 'none';
                }
            } catch (err) {
                document.getElementById('new-client-group-container').style.display = 'none';
            }
            const collapseEl = document.getElementById('collapseOverrides');
            if (collapseEl?.classList.contains('show')) bootstrap.Collapse.getInstance(collapseEl)?.hide();
            new bootstrap.Modal(document.getElementById('modal-new-client')).show();
        });

        // Confirm new client
        document.getElementById('btn-confirm-new-client')?.addEventListener('click', async () => {
            const name = document.getElementById('new-client-name').value.trim();
            if (!name) { showToast(t('wireguard.enterClientName'), 'error'); return; }

            const routes = [];
            let hasInvalidCidr = false;
            document.querySelectorAll('.client-route-row .client-route-input').forEach(input => {
                const value = input.value.trim();
                if (value) {
                    if (!isValidCIDR(value)) { hasInvalidCidr = true; input.classList.add('is-invalid'); }
                    else { input.classList.remove('is-invalid'); routes.push(value); }
                }
            });
            if (hasInvalidCidr) { showToast(t('wireguard.invalidCidr'), 'error'); return; }

            const allowed_ips = routes.length > 0 ? routes.join(', ') : null;
            const dns = document.getElementById('new-client-dns').value.trim() || null;
            const group_id = document.getElementById('new-client-group')?.value || null;

            try {
                await apiPost(`${MODULE_API}/instances/${currentInstanceId}/clients`, { name, allowed_ips, dns, group_id });
                showToast(t('wireguard.clientCreated'), 'success');
                bootstrap.Modal.getInstance(document.getElementById('modal-new-client'))?.hide();
                renderInstanceDetail(container, canManage, canClients);
            } catch (err) { showToast(err.message, 'error'); }
        });

        // Edit defaults
        document.getElementById('btn-edit-defaults')?.addEventListener('click', async () => {
            await loadNetworkInterfaces();
            new bootstrap.Modal(document.getElementById('modal-edit-defaults')).show();
        });

        // Toggle defaults routes section
        document.querySelectorAll('input[name="defaults-tunnel-mode"]').forEach(radio => {
            radio.addEventListener('change', () => {
                const routesSection = document.getElementById('defaults-routes-section');
                if (document.getElementById('defaults-tunnel-split').checked) routesSection.classList.remove('d-none');
                else routesSection.classList.add('d-none');
            });
        });

        // Route add/remove in defaults modal
        document.getElementById('defaults-routes-list')?.addEventListener('click', (e) => {
            const addBtn = e.target.closest('.btn-add-defaults-route');
            const removeBtn = e.target.closest('.defaults-remove-route');
            if (addBtn) {
                const list = document.getElementById('defaults-routes-list');
                const row = document.createElement('div');
                row.className = 'defaults-route-row mb-2 d-flex gap-2 align-items-center';
                row.innerHTML = `
                    <input type="text" class="form-control defaults-route-input" placeholder="es. 192.168.1.0/24" style="flex: 2">
                    <select class="form-select defaults-route-interface" style="flex: 1">
                        <option value="">Auto</option>
                        ${networkInterfaces.map(iface => `<option value="${iface.name}">${iface.name}</option>`).join('')}
                    </select>
                    <button class="btn btn-outline-danger defaults-remove-route" type="button"><i class="ti ti-minus"></i></button>
                `;
                list.appendChild(row);
            }
            if (removeBtn && !removeBtn.closest('.defaults-add-row')) removeBtn.closest('.defaults-route-row').remove();
        });

        // Save defaults
        document.getElementById('btn-save-defaults')?.addEventListener('click', async () => {
            const tunnelMode = document.querySelector('input[name="defaults-tunnel-mode"]:checked')?.value || 'full';
            const dnsInput = document.getElementById('edit-default-dns').value.trim();
            const dns_servers = dnsInput ? dnsInput.split(',').map(s => s.trim()).filter(s => s) : null;
            const endpoint = document.getElementById('edit-default-endpoint').value.trim() || null;

            let routes = [];
            let hasInvalidCidr = false;
            if (tunnelMode === 'split') {
                document.querySelectorAll('.defaults-route-row').forEach(row => {
                    const input = row.querySelector('.defaults-route-input');
                    const network = input?.value.trim();
                    const iface = row.querySelector('.defaults-route-interface')?.value;
                    if (network) {
                        if (!isValidCIDR(network)) { hasInvalidCidr = true; input.classList.add('is-invalid'); }
                        else { input.classList.remove('is-invalid'); routes.push({ network, interface: iface || null }); }
                    }
                });
            }
            if (hasInvalidCidr) { showToast(t('wireguard.invalidCidr'), 'error'); return; }

            let defaultAllowedIps;
            if (tunnelMode === 'full') {
                defaultAllowedIps = '0.0.0.0/0, ::/0';
            } else {
                const routeNetworks = routes.map(r => r.network).filter(n => n);
                routeNetworks.push(instance.subnet);
                defaultAllowedIps = routeNetworks.join(', ');
            }

            try {
                await apiPatch(`${MODULE_API}/instances/${currentInstanceId}/routing`, { tunnel_mode: tunnelMode, routes });
                await apiPatch(`${MODULE_API}/instances/${currentInstanceId}/defaults`, { dns_servers, default_allowed_ips: defaultAllowedIps });
                if (endpoint !== instance.endpoint) {
                    await apiPatch(`${MODULE_API}/instances/${currentInstanceId}`, { endpoint });
                }
                showToast(t('wireguard.defaultsUpdated'), 'success');
                bootstrap.Modal.getInstance(document.getElementById('modal-edit-defaults'))?.hide();
                renderInstanceDetail(container, canManage, canClients);
            } catch (err) { showToast(err.message, 'error'); }
        });

        // Load firewall tab
        document.getElementById('tab-firewall')?.addEventListener('shown.bs.tab', async () => {
            try {
                const firewallModule = await import('./firewall.js');
                await firewallModule.init(document.getElementById('firewall-content'), currentInstanceId);
            } catch (err) {
                document.getElementById('firewall-content').innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
            }
        });

        registerGlobalFunctions(container, canManage, canClients);
    } catch (err) {
        container.innerHTML = `<div class="alert alert-danger"><i class="ti ti-alert-circle me-2"></i>${err.message}</div>`;
    }
}

function registerGlobalFunctions(container, canManage, canClients) {
    window.startInstance = async (id) => {
        try {
            await apiPost(`${MODULE_API}/instances/${id}/start`);
            showToast(t('wireguard.instanceStarted'), 'success');
            if (currentContainer) renderInstanceDetail(currentContainer, canManage, canClients);
        } catch (err) { showToast(err.message, 'error'); }
    };

    window.stopInstance = async (id) => {
        try {
            await apiPost(`${MODULE_API}/instances/${id}/stop`);
            showToast(t('wireguard.instanceStopped'), 'success');
            if (currentContainer) renderInstanceDetail(currentContainer, canManage, canClients);
        } catch (err) { showToast(err.message, 'error'); }
    };

    window.deleteInstance = async (id) => {
        if (await confirmDialog(t('wireguard.confirmDeleteInstanceTitle'), t('wireguard.confirmDeleteInstanceMsg'))) {
            try {
                await apiDelete(`${MODULE_API}/instances/${id}`);
                showToast(t('wireguard.instanceDeleted'), 'success');
                location.href = '#wireguard';
            } catch (err) { showToast(err.message, 'error'); }
        }
    };

    window.downloadConfig = async (name) => {
        try {
            const token = localStorage.getItem('madmin_token');
            const res = await fetch(`/api${MODULE_API}/instances/${currentInstanceId}/clients/${name}/config`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!res.ok) throw new Error(t('wireguard.downloadFailed').replace('{error}', res.statusText));
            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = `${name}.conf`;
            document.body.appendChild(a); a.click();
            window.URL.revokeObjectURL(url); document.body.removeChild(a);
        } catch (err) { showToast(err.message, 'error'); }
    };

    window.resetClientDefaults = async (name) => {
        if (await confirmDialog(t('wireguard.confirmResetTitle'), t('wireguard.confirmResetMsg').replace('{name}', name), t('wireguard.confirmResetBtn'), 'btn-warning', true)) {
            try {
                await apiPatch(`${MODULE_API}/instances/${currentInstanceId}/clients/${name}`, { allowed_ips: '', dns: '' });
                showToast(t('wireguard.clientResetDone'), 'success');
                if (currentContainer) renderInstanceDetail(currentContainer, canManage, canClients);
            } catch (err) { showToast(err.message, 'error'); }
        }
    };

    window.showQR = async (name) => {
        try {
            const token = localStorage.getItem('madmin_token');
            const res = await fetch(`/api${MODULE_API}/instances/${currentInstanceId}/clients/${name}/qr`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!res.ok) throw new Error(t('wireguard.qrLoadFailed').replace('{error}', res.statusText));
            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const modal = document.createElement('div');
            modal.innerHTML = `
                <div class="modal fade" tabindex="-1">
                    <div class="modal-dialog modal-sm">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h5 class="modal-title">QR Code - ${escapeHtml(name)}</h5>
                                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                            </div>
                            <div class="modal-body text-center p-4">
                                <img src="${url}" class="img-fluid" alt="QR Code">
                                <p class="mt-3 mb-0 text-muted small">${t('wireguard.qrScanHint')}</p>
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
        if (await confirmDialog(t('wireguard.confirmRevokeTitle'), t('wireguard.confirmRevokeMsg').replace('{name}', name), t('wireguard.confirmRevokeBtn'))) {
            try {
                await apiDelete(`${MODULE_API}/instances/${currentInstanceId}/clients/${name}`);
                showToast(t('wireguard.clientRevoked'), 'success');
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
        if (!email) { showToast(t('wireguard.enterEmail'), 'error'); return; }
        const btn = document.getElementById('btn-send-email');
        const originalHtml = btn.innerHTML;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('wireguard.sending')}`;
        btn.disabled = true;
        try {
            await apiPost(`${MODULE_API}/instances/${currentInstanceId}/clients/${clientName}/send-config`, { email });
            showToast(t('wireguard.emailSent').replace('{email}', email), 'success');
            bootstrap.Modal.getInstance(document.getElementById('modal-send-email'))?.hide();
        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            btn.innerHTML = originalHtml;
            btn.disabled = false;
        }
    }
});

// ============================================================
//  CLIENT MODE DETAIL VIEW
// ============================================================

async function renderClientModeDetail(container, instance, canManage) {
    const isRunning = instance.status === 'running';

    container.innerHTML = `
        <div class="mb-3">
            <a href="#wireguard" class="text-muted">
                <i class="ti ti-arrow-left me-1"></i>${t('wireguard.backToInstances')}
            </a>
        </div>

        <div class="card mb-3">
            <div class="card-header">
                <div class="d-flex justify-content-between align-items-center w-100">
                    <div>
                        <h3 class="card-title mb-0">
                            <span class="badge bg-orange-lt me-2">Client</span>${escapeHtml(instance.name)}
                        </h3>
                        <small class="text-muted">${t('wireguard.interface')}: ${instance.interface}</small>
                    </div>
                    <div class="btn-group">
                        ${canManage ? `
                        <button class="btn ${isRunning ? 'btn-warning' : 'btn-success'}"
                                onclick="${isRunning ? 'stopInstance' : 'startInstance'}('${instance.id}')">
                            <i class="ti ti-player-${isRunning ? 'stop' : 'play'} me-1"></i>
                            ${isRunning ? t('wireguard.stop') : t('wireguard.start')}
                        </button>
                        <button class="btn btn-outline-secondary" id="btn-reconnect" title="${t('wireguard.clientModeReconnect')}">
                            <i class="ti ti-refresh me-1"></i>${t('wireguard.clientModeReconnect')}
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
                        <span class="text-muted">${t('wireguard.status')}</span><br>
                        <span class="badge ${isRunning ? 'bg-success-lt' : 'bg-secondary-lt'} fs-6">
                            ${isRunning ? t('wireguard.statusRunning') : t('wireguard.statusStopped')}
                        </span>
                    </div>
                    <div class="col-md-3">
                        <span class="text-muted">${t('wireguard.clientModeUpstreamTunnel')}</span><br>
                        <span id="upstream-status-badge" class="badge ${instance.upstream_status === 'connected' ? 'bg-success-lt' : 'bg-secondary-lt'} fs-6">
                            ${escapeHtml(instance.upstream_status || t('wireguard.statusUnknown'))}
                        </span>
                    </div>
                    <div class="col-md-3">
                        <span class="text-muted">${t('wireguard.clientModeEndpointPeer')}</span><br>
                        <code>${escapeHtml(instance.upstream_endpoint || '–')}</code>
                    </div>
                    <div class="col-md-3">
                        <span class="text-muted">${t('wireguard.clientModeLastHandshake')}</span><br>
                        <span id="upstream-last-handshake" class="text-muted small">
                            ${instance.upstream_last_handshake ? formatTimeAgo(instance.upstream_last_handshake) : '–'}
                        </span>
                    </div>
                </div>
                <hr>
                <div class="row">
                    <div class="col-md-6">
                        <span class="text-muted">${t('wireguard.clientModeLanInterfaces')}</span><br>
                        ${(instance.client_lan_interfaces || []).length
                            ? instance.client_lan_interfaces.map(i => `<code class="badge bg-azure-lt me-1">${escapeHtml(i)}</code>`).join('')
                            : `<span class="text-muted small">${t('wireguard.clientModeNoLan')}</span>`}
                    </div>
                    <div class="col-md-3">
                        <span class="text-muted">${t('wireguard.clientModeTunnelMode')}</span><br>
                        <span class="badge ${instance.tunnel_mode === 'full' ? 'bg-blue' : 'bg-purple'}-lt">
                            ${instance.tunnel_mode === 'full' ? t('wireguard.fullTunnel') : t('wireguard.splitTunnel')}
                        </span>
                    </div>
                    <div class="col-md-3">
                        <span class="text-muted">${t('wireguard.clientModeAutoRestart')}</span><br>
                        <span class="badge ${instance.auto_restart ? 'bg-success-lt' : 'bg-secondary-lt'}">
                            ${instance.auto_restart ? t('wireguard.clientModeActive') : t('wireguard.clientModeInactive')}
                        </span>
                    </div>
                </div>
            </div>
        </div>

        <div class="card mb-3" id="upstream-live-card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h4 class="card-title mb-0"><i class="ti ti-activity me-2"></i>${t('wireguard.clientModeConnectionStatus')}</h4>
                <button class="btn btn-sm btn-outline-secondary" id="btn-refresh-status">
                    <i class="ti ti-refresh"></i>
                </button>
            </div>
            <div class="card-body" id="upstream-live-content">
                <div class="text-muted text-center py-3">${t('wireguard.clientModeClickRefresh')}</div>
            </div>
        </div>
    `;

    document.getElementById('btn-reconnect')?.addEventListener('click', async () => {
        const btn = document.getElementById('btn-reconnect');
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('wireguard.clientModeReconnecting')}`;
        try {
            await apiPost(`${MODULE_API}/instances/${instance.id}/reconnect`);
            showToast(t('wireguard.clientModeReconnectStarted'), 'success');
            setTimeout(() => renderClientModeDetail(container, { ...instance }, canManage), 2000);
        } catch (err) {
            showToast(err.message, 'error');
            btn.disabled = false;
            btn.innerHTML = `<i class="ti ti-refresh me-1"></i>${t('wireguard.clientModeReconnect')}`;
        }
    });

    document.getElementById('btn-refresh-status')?.addEventListener('click', async () => {
        const liveContent = document.getElementById('upstream-live-content');
        liveContent.innerHTML = '<div class="text-center py-3"><span class="spinner-border spinner-border-sm"></span></div>';
        try {
            const status = await apiGet(`${MODULE_API}/instances/${instance.id}/upstream-status`);
            document.getElementById('upstream-status-badge').textContent = status.state || t('wireguard.statusUnknown');
            document.getElementById('upstream-status-badge').className =
                `badge ${status.connected ? 'bg-success-lt' : 'bg-secondary-lt'} fs-6`;
            liveContent.innerHTML = `
                <div class="row">
                    <div class="col-md-3">
                        <span class="text-muted">${t('wireguard.clientModeStatus')}</span><br>
                        <span class="badge ${status.connected ? 'bg-success-lt' : 'bg-secondary-lt'}">
                            ${escapeHtml(status.state || '–')}
                        </span>
                    </div>
                    ${status.endpoint ? `<div class="col-md-3">
                        <span class="text-muted">${t('wireguard.clientModeEndpoint')}</span><br><code>${escapeHtml(status.endpoint)}</code>
                    </div>` : ''}
                    ${status.rx_bytes != null ? `<div class="col-md-3">
                        <span class="text-muted">${t('wireguard.clientModeTrafficIn')}</span><br>
                        <span class="text-success"><i class="ti ti-arrow-down me-1"></i>${formatBytes(status.rx_bytes)}</span>
                    </div>
                    <div class="col-md-3">
                        <span class="text-muted">${t('wireguard.clientModeTrafficOut')}</span><br>
                        <span class="text-primary"><i class="ti ti-arrow-up me-1"></i>${formatBytes(status.tx_bytes || 0)}</span>
                    </div>` : ''}
                </div>
            `;
        } catch (err) {
            liveContent.innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
        }
    });

    window.startInstance = async (id) => {
        try {
            await apiPost(`${MODULE_API}/instances/${id}/start`);
            showToast(t('wireguard.instanceStarted'), 'success');
            renderClientModeDetail(container, { ...instance, status: 'running' }, canManage);
        } catch (err) { showToast(err.message, 'error'); }
    };
    window.stopInstance = async (id) => {
        try {
            await apiPost(`${MODULE_API}/instances/${id}/stop`);
            showToast(t('wireguard.instanceStopped'), 'success');
            renderClientModeDetail(container, { ...instance, status: 'stopped' }, canManage);
        } catch (err) { showToast(err.message, 'error'); }
    };
    window.deleteInstance = async (id) => {
        if (!await confirmDialog(t('wireguard.confirmDeleteInstance'))) return;
        try {
            await apiDelete(`${MODULE_API}/instances/${id}`);
            showToast(t('wireguard.instanceDeleted'), 'success');
            window.location.hash = '#wireguard';
        } catch (err) { showToast(err.message, 'error'); }
    };
}

// ============================================================
//  SITE-TO-SITE PANEL (server mode)
// ============================================================

function createS2SPanel(instance, canManage) {
    const panel = document.createElement('div');
    panel.className = 'card mb-3';
    panel.id = 'site-to-site-panel';
    const isEnabled = !!instance.site_to_site;
    const lans = (instance.site_to_site_lans || []).join('\n');
    panel.innerHTML = `
        <div class="card-header">
            <h4 class="card-title mb-0"><i class="ti ti-network me-2"></i>${t('wireguard.s2sTitle')}</h4>
        </div>
        <div class="card-body">
            <div class="d-flex align-items-start mb-3">
                <div class="form-check form-switch me-3 mt-1">
                    <input class="form-check-input" type="checkbox" id="s2s-enabled" ${isEnabled ? 'checked' : ''} ${!canManage ? 'disabled' : ''}>
                </div>
                <div>
                    <strong>${t('wireguard.s2sNatExemptLabel')}</strong><br>
                    <small class="text-muted">${t('wireguard.s2sNatExemptDesc')}</small>
                </div>
            </div>
            <div id="s2s-config" ${!isEnabled ? 'style="display:none;"' : ''}>
                <div class="mb-3">
                    <label class="form-label">${t('wireguard.s2sLanCidrLabel')}</label>
                    <textarea class="form-control" id="s2s-lans" rows="3" placeholder="${t('wireguard.s2sLanCidrPlaceholder')}" ${!canManage ? 'readonly' : ''}>${escapeHtml(lans)}</textarea>
                    <small class="form-hint">${t('wireguard.s2sLanCidrHint')}</small>
                </div>
            </div>
            ${canManage ? `<button class="btn btn-primary mt-2" id="btn-save-s2s">
                <i class="ti ti-device-floppy me-1"></i>${t('wireguard.s2sSave')}
            </button>` : ''}
        </div>
    `;
    return panel;
}

function setupS2SHandlers(instance, canManage, canClients) {
    const checkbox = document.getElementById('s2s-enabled');
    const config = document.getElementById('s2s-config');
    if (!checkbox || !config) return;

    checkbox.addEventListener('change', () => {
        config.style.display = checkbox.checked ? '' : 'none';
    });

    document.getElementById('btn-save-s2s')?.addEventListener('click', async () => {
        const enabled = document.getElementById('s2s-enabled').checked;
        const lans = document.getElementById('s2s-lans').value
            .split('\n').map(s => s.trim()).filter(s => s);
        const btn = document.getElementById('btn-save-s2s');
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('wireguard.s2sSaving')}`;
        try {
            await apiPatch(`${MODULE_API}/instances/${instance.id}/site-to-site`, { enabled, lans });
            showToast(t('wireguard.s2sUpdated'), 'success');
            if (currentContainer) renderInstanceDetail(currentContainer, canManage, canClients);
        } catch (err) {
            showToast(err.message, 'error');
            btn.disabled = false;
            btn.innerHTML = `<i class="ti ti-device-floppy me-1"></i>${t('wireguard.s2sSave')}`;
        }
    });
}

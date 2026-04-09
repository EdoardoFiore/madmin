/**
 * OpenVPN Module - Instance List View
 *
 * Lists all OpenVPN instances with start/stop/delete actions,
 * and includes the New Instance creation modal.
 */

import { t } from '/static/js/i18n.js';
import { apiGet, apiPost, apiDelete } from '/static/js/api.js';
import { showToast, confirmDialog, loadingSpinner, escapeHtml } from '/static/js/utils.js';

const MODULE_API = '/modules/openvpn';

let _canManage = false;

// ============================================================
//  ENTRY POINT
// ============================================================

export async function renderOvpnList(container, canManage) {
    _canManage = canManage;

    container.innerHTML = `
        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h3 class="card-title"><i class="ti ti-lock me-2"></i>${t('openvpn.instancesTitle')}</h3>
                ${canManage ? `
                <button class="btn btn-primary" id="btn-new-instance">
                    <i class="ti ti-plus me-1"></i>${t('openvpn.newInstance')}
                </button>` : ''}
            </div>
            <div class="card-body" id="instances-list">${loadingSpinner()}</div>
        </div>

        <!-- New Instance Modal -->
        <div class="modal fade" id="modal-new-instance" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${t('openvpn.newInstanceTitle')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">${t('openvpn.instanceName')}</label>
                                <input type="text" class="form-control" id="new-instance-name" placeholder="Office VPN">
                            </div>
                            <div class="col-md-3 mb-3">
                                <label class="form-label">${t('openvpn.port')}</label>
                                <input type="number" class="form-control" id="new-instance-port" value="1194">
                            </div>
                            <div class="col-md-3 mb-3">
                                <label class="form-label">${t('openvpn.protocol')}</label>
                                <select class="form-select" id="new-instance-protocol">
                                    <option value="udp">UDP</option>
                                    <option value="tcp" selected>TCP</option>
                                </select>
                            </div>
                        </div>

                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">${t('openvpn.vpnSubnet')}</label>
                                <input type="text" class="form-control" id="new-instance-subnet" placeholder="10.8.0.0/24">
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label">${t('openvpn.publicEndpoint')}</label>
                                <input type="text" class="form-control" id="new-instance-endpoint" placeholder="${t('openvpn.endpointPlaceholder')}">
                            </div>
                        </div>

                        <div class="mb-3">
                            <label class="form-label">${t('openvpn.tunnelMode')}</label>
                            <div class="row g-2">
                                <div class="col-6">
                                    <input type="radio" class="btn-check" name="tunnel-mode" id="tunnel-full" value="full" checked>
                                    <label class="btn btn-outline-primary w-100 text-start py-2 d-block" for="tunnel-full">
                                        <i class="ti ti-world me-2"></i><strong>${t('openvpn.fullTunnel')}</strong><br>
                                        <small class="opacity-75">${t('openvpn.fullTunnelDesc')}</small>
                                    </label>
                                </div>
                                <div class="col-6">
                                    <input type="radio" class="btn-check" name="tunnel-mode" id="tunnel-split" value="split">
                                    <label class="btn btn-outline-primary w-100 text-start py-2 d-block" for="tunnel-split">
                                        <i class="ti ti-route me-2"></i><strong>${t('openvpn.splitTunnel')}</strong><br>
                                        <small class="opacity-75">${t('openvpn.splitTunnelDesc')}</small>
                                    </label>
                                </div>
                            </div>
                        </div>

                        <!-- Full Tunnel Options -->
                        <div id="full-tunnel-options">
                            <div class="mb-3">
                                <label class="form-label">${t('openvpn.dnsServers')}</label>
                                <input type="text" class="form-control" id="new-instance-dns"
                                       placeholder="8.8.8.8, 1.1.1.1" value="8.8.8.8, 1.1.1.1">
                                <small class="form-hint">${t('openvpn.dnsHint')}</small>
                            </div>
                        </div>

                        <!-- Split Tunnel Options -->
                        <div id="split-tunnel-options" style="display: none;">
                            <div class="mb-3">
                                <label class="form-label">${t('openvpn.routesToForward')}</label>
                                <div id="routes-container">
                                    <div class="route-row mb-2 d-flex gap-2 align-items-center">
                                        <input type="text" class="form-control route-network" placeholder="192.168.1.0/24" style="flex: 2">
                                        <button class="btn btn-outline-success btn-add-route" type="button">
                                            <i class="ti ti-plus"></i>
                                        </button>
                                    </div>
                                </div>
                                <small class="form-hint">${t('openvpn.routesHint')}</small>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">${t('openvpn.optionalDns')}</label>
                                <input type="text" class="form-control" id="new-instance-dns-split" placeholder="${t('openvpn.optionalDnsPlaceholder')}">
                            </div>
                        </div>

                        <!-- Advanced options -->
                        <details class="mb-3">
                            <summary class="text-muted cursor-pointer">
                                <i class="ti ti-settings me-1"></i>${t('openvpn.advancedOptions')}
                            </summary>
                            <div class="mt-3 ps-3">
                                <div class="row">
                                    <div class="col-md-6 mb-3">
                                        <label class="form-label">${t('openvpn.cipher')}</label>
                                        <select class="form-select" id="new-instance-cipher">
                                            <option value="AES-256-GCM" selected>AES-256-GCM (${t('openvpn.recommended')})</option>
                                            <option value="AES-128-GCM">AES-128-GCM</option>
                                            <option value="CHACHA20-POLY1305">CHACHA20-POLY1305</option>
                                        </select>
                                    </div>
                                    <div class="col-md-6 mb-3">
                                        <label class="form-label">${t('openvpn.certDurationDays')}</label>
                                        <input type="number" class="form-control" id="new-instance-cert-days"
                                               value="3650" min="365" max="36500">
                                        <small class="form-hint">${t('openvpn.certDurationDefault')}</small>
                                    </div>
                                </div>
                            </div>
                        </details>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">${t('openvpn.cancel')}</button>
                        <button class="btn btn-primary" id="btn-create-instance">
                            <i class="ti ti-check me-1"></i>${t('openvpn.createInstance')}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    await loadInstances();
    setupCreateForm();
}

// ============================================================
//  LOAD & RENDER INSTANCES
// ============================================================

async function loadInstances() {
    const listEl = document.getElementById('instances-list');
    try {
        const instances = await apiGet(`${MODULE_API}/instances`);

        if (instances.length === 0) {
            listEl.innerHTML = `<div class="text-center py-5 text-muted">
                <i class="ti ti-server-off" style="font-size: 3rem;"></i>
                <p class="mt-2">${t('openvpn.noInstances')}</p>
                <small>${t('openvpn.noInstancesHint')}</small>
            </div>`;
            return;
        }

        listEl.innerHTML = `<div class="table-responsive"><table class="table table-vcenter card-table table-hover">
            <thead><tr>
                <th style="width: 30px;"></th>
                <th>${t('openvpn.instanceName')}</th>
                <th>${t('openvpn.interface')}</th>
                <th>${t('openvpn.port')}</th>
                <th>${t('openvpn.subnet')}</th>
                <th>${t('openvpn.mode')}</th>
                <th>${t('openvpn.clients')}</th>
                <th class="w-1"></th>
            </tr></thead>
            <tbody>${instances.map(i => `<tr class="instance-row" data-id="${i.id}" style="cursor: pointer;">
                <td>
                    <span class="status-dot ${i.status === 'running' ? 'status-dot-animated bg-success' : 'bg-secondary'}"
                          title="${i.status === 'running' ? t('openvpn.statusRunning') : t('openvpn.statusStopped')}"></span>
                </td>
                <td>
                    <a href="#openvpn/${i.id}" class="text-reset">
                        <strong>${escapeHtml(i.name)}</strong>
                    </a>
                    <div class="small text-muted">
                        ${i.status === 'running'
                ? `<span class="text-success">${t('openvpn.statusRunning')}</span>`
                : `<span class="text-secondary">${t('openvpn.statusStopped')}</span>`}
                    </div>
                </td>
                <td><code>${i.interface}</code></td>
                <td>${i.port}/${i.protocol.toUpperCase()}</td>
                <td><code>${i.subnet}</code></td>
                <td><span class="badge ${i.tunnel_mode === 'full' ? 'bg-blue' : 'bg-purple'}-lt">
                    ${i.tunnel_mode === 'full' ? t('openvpn.fullMode') : t('openvpn.splitMode')}
                </span></td>
                <td>${i.client_count}</td>
                <td>
                    <div class="btn-group btn-group-sm" onclick="event.stopPropagation();">
                        ${_canManage ? (i.status === 'running'
                ? `<button class="btn btn-ghost-warning btn-stop" data-id="${i.id}" title="${t('openvpn.stop')}"><i class="ti ti-player-stop"></i></button>`
                : `<button class="btn btn-ghost-success btn-start" data-id="${i.id}" title="${t('openvpn.start')}"><i class="ti ti-player-play"></i></button>`) : ''}
                        ${_canManage ? `<button class="btn btn-ghost-danger btn-delete" data-id="${i.id}" title="${t('openvpn.delete')}"><i class="ti ti-trash"></i></button>` : ''}
                    </div>
                </td>
            </tr>`).join('')}</tbody>
        </table></div>`;

        setupInstanceRowActions();
    } catch (err) {
        listEl.innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
    }
}

function setupInstanceRowActions() {
    // Row click navigates to detail
    document.querySelectorAll('.instance-row').forEach(row => {
        row.addEventListener('click', (e) => {
            if (e.target.closest('.btn-group')) return;
            window.location.hash = `#openvpn/${row.dataset.id}`;
        });
    });

    // Start instance
    document.querySelectorAll('.btn-start').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            try {
                await apiPost(`${MODULE_API}/instances/${id}/start`);
                showToast(t('openvpn.instanceStarted'), 'success');
                loadInstances();
            } catch (err) {
                showToast(err.message, 'error');
            }
        });
    });

    // Stop instance
    document.querySelectorAll('.btn-stop').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            try {
                await apiPost(`${MODULE_API}/instances/${id}/stop`);
                showToast(t('openvpn.instanceStopped'), 'success');
                loadInstances();
            } catch (err) {
                showToast(err.message, 'error');
            }
        });
    });

    // Delete instance
    document.querySelectorAll('.btn-delete').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            if (!await confirmDialog(t('openvpn.confirmDeleteInstance'), t('openvpn.confirmDeleteInstanceMsg'))) return;
            try {
                await apiDelete(`${MODULE_API}/instances/${id}`);
                showToast(t('openvpn.instanceDeleted'), 'success');
                loadInstances();
            } catch (err) {
                showToast(err.message, 'error');
            }
        });
    });
}

// ============================================================
//  CREATE FORM
// ============================================================

function setupCreateForm() {
    document.getElementById('btn-new-instance')?.addEventListener('click', async () => {
        new bootstrap.Modal(document.getElementById('modal-new-instance')).show();
    });

    // Toggle tunnel options
    document.querySelectorAll('input[name="tunnel-mode"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            const fullOpts = document.getElementById('full-tunnel-options');
            const splitOpts = document.getElementById('split-tunnel-options');
            if (e.target.value === 'full') {
                fullOpts.style.display = 'block';
                splitOpts.style.display = 'none';
            } else {
                fullOpts.style.display = 'none';
                splitOpts.style.display = 'block';
            }
        });
    });

    // Add route button
    document.querySelector('.btn-add-route')?.addEventListener('click', addRouteInput);

    document.getElementById('btn-create-instance')?.addEventListener('click', createInstance);
}

function addRouteInput() {
    const container = document.getElementById('routes-container');
    const div = document.createElement('div');
    div.className = 'route-row mb-2 d-flex gap-2 align-items-center';
    div.innerHTML = `
        <input type="text" class="form-control route-network" placeholder="192.168.1.0/24" style="flex: 2">
        <button class="btn btn-outline-danger btn-remove-route" type="button">
            <i class="ti ti-minus"></i>
        </button>
    `;
    div.querySelector('.btn-remove-route').addEventListener('click', () => div.remove());
    container.appendChild(div);
}

async function createInstance() {
    const name = document.getElementById('new-instance-name').value.trim();
    const port = parseInt(document.getElementById('new-instance-port').value);
    const protocol = document.getElementById('new-instance-protocol').value;
    const subnet = document.getElementById('new-instance-subnet').value.trim();
    const endpoint = document.getElementById('new-instance-endpoint').value.trim() || null;
    const tunnelMode = document.querySelector('input[name="tunnel-mode"]:checked').value;
    const cipher = document.getElementById('new-instance-cipher').value;
    const certDays = parseInt(document.getElementById('new-instance-cert-days').value) || 3650;

    if (!name || !port || !subnet) {
        showToast(t('openvpn.fillRequiredFields'), 'error');
        return;
    }

    // Collect DNS servers
    let dnsInput = tunnelMode === 'full'
        ? document.getElementById('new-instance-dns').value
        : document.getElementById('new-instance-dns-split').value;

    let dnsServers = dnsInput.split(',').map(s => s.trim()).filter(s => s);
    if (dnsServers.length === 0 && tunnelMode === 'full') {
        dnsServers = ['8.8.8.8', '1.1.1.1'];
    }

    // Collect routes for split tunnel
    let routes = [];
    if (tunnelMode === 'split') {
        document.querySelectorAll('.route-row').forEach(row => {
            const network = row.querySelector('.route-network')?.value.trim();
            if (network) {
                routes.push({ network });
            }
        });
    }

    try {
        await apiPost(`${MODULE_API}/instances`, {
            name, port, protocol, subnet, endpoint,
            tunnel_mode: tunnelMode,
            dns_servers: dnsServers,
            routes: routes,
            cipher: cipher,
            cert_duration_days: certDays
        });
        showToast(t('openvpn.instanceCreated'), 'success');
        bootstrap.Modal.getInstance(document.getElementById('modal-new-instance'))?.hide();
        await loadInstances();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

/**
 * WireGuard Module - Instance List View
 *
 * Displays WireGuard instances and provides the create instance modal.
 */

import { t } from '/static/js/i18n.js';
import { apiGet, apiPost, apiDelete } from '/static/js/api.js';
import { showToast, confirmDialog, loadingSpinner } from '/static/js/utils.js';

const MODULE_API = '/modules/wireguard';

let networkInterfaces = [];

export async function renderWgList(container, canManage) {
    container.innerHTML = `
        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h3 class="card-title"><i class="ti ti-brand-wire me-2"></i>${t('wireguard.instancesTitle')}</h3>
                ${canManage ? `
                <button class="btn btn-primary" id="btn-new-instance">
                    <i class="ti ti-plus me-1"></i>${t('wireguard.newInstance')}
                </button>` : ''}
            </div>
            <div class="card-body" id="instances-list">${loadingSpinner()}</div>
        </div>

        <!-- New Instance Modal -->
        <div class="modal fade" id="modal-new-instance" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${t('wireguard.newInstanceTitle')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">${t('wireguard.name')}</label>
                                <input type="text" class="form-control" id="new-instance-name" placeholder="Office VPN">
                            </div>
                            <div class="col-md-3 mb-3">
                                <label class="form-label">${t('wireguard.udpPort')}</label>
                                <input type="number" class="form-control" id="new-instance-port" value="51820">
                            </div>
                            <div class="col-md-3 mb-3">
                                <label class="form-label">${t('wireguard.subnet')}</label>
                                <input type="text" class="form-control" id="new-instance-subnet" placeholder="10.10.0.0/24">
                            </div>
                        </div>

                        <div class="mb-3">
                            <label class="form-label">${t('wireguard.tunnelMode')}</label>
                            <div class="row g-2">
                                <div class="col-6">
                                    <input type="radio" class="btn-check" name="tunnel-mode" id="tunnel-full" value="full" checked>
                                    <label class="btn btn-outline-primary w-100 text-start py-2 d-block" for="tunnel-full">
                                        <i class="ti ti-world me-2"></i><strong>${t('wireguard.fullTunnel')}</strong><br>
                                        <small class="opacity-75">${t('wireguard.fullTunnelDesc')}</small>
                                    </label>
                                </div>
                                <div class="col-6">
                                    <input type="radio" class="btn-check" name="tunnel-mode" id="tunnel-split" value="split">
                                    <label class="btn btn-outline-primary w-100 text-start py-2 d-block" for="tunnel-split">
                                        <i class="ti ti-route me-2"></i><strong>${t('wireguard.splitTunnel')}</strong><br>
                                        <small class="opacity-75">${t('wireguard.splitTunnelDesc')}</small>
                                    </label>
                                </div>
                            </div>
                        </div>

                        <!-- Full Tunnel Options -->
                        <div id="full-tunnel-options">
                            <div class="mb-3">
                                <label class="form-label">${t('wireguard.dnsServers')}</label>
                                <input type="text" class="form-control" id="new-instance-dns"
                                       placeholder="8.8.8.8, 1.1.1.1" value="8.8.8.8, 1.1.1.1">
                                <small class="form-hint">${t('wireguard.dnsHint')}</small>
                            </div>
                        </div>

                        <!-- Split Tunnel Options -->
                        <div id="split-tunnel-options" style="display: none;">
                            <div class="mb-3">
                                <label class="form-label">${t('wireguard.routesToForward')}</label>
                                <div id="routes-container">
                                    <div class="route-row mb-2 d-flex gap-2 align-items-center">
                                        <input type="text" class="form-control route-network" placeholder="192.168.1.0/24" style="flex: 2">
                                        <select class="form-select route-interface" style="flex: 1">
                                            <option value="">${t('wireguard.autoInterface')}</option>
                                        </select>
                                        <button class="btn btn-outline-success btn-add-route" type="button">
                                            <i class="ti ti-plus"></i>
                                        </button>
                                    </div>
                                </div>
                                <small class="form-hint">${t('wireguard.routesHint')}</small>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">${t('wireguard.dnsOptional')}</label>
                                <input type="text" class="form-control" id="new-instance-dns-split" placeholder="${t('wireguard.dnsOptionalHint')}">
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">${t('wireguard.cancel')}</button>
                        <button class="btn btn-primary" id="btn-create-instance">
                            <i class="ti ti-check me-1"></i>${t('wireguard.createInstance')}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    await loadInstances(canManage);
    setupCreateForm(canManage);
}

async function loadInstances(canManage) {
    const listEl = document.getElementById('instances-list');
    try {
        const instances = await apiGet(`${MODULE_API}/instances`);

        if (instances.length === 0) {
            listEl.innerHTML = `<div class="text-center py-5 text-muted">
                <i class="ti ti-server-off" style="font-size: 3rem;"></i>
                <p class="mt-2">${t('wireguard.noInstances')}</p>
                <small>${t('wireguard.noInstancesHint')}</small>
            </div>`;
            return;
        }

        listEl.innerHTML = `<div class="table-responsive"><table class="table table-vcenter card-table table-hover">
            <thead><tr>
                <th style="width: 30px;"></th>
                <th>${t('wireguard.name')}</th>
                <th>${t('wireguard.interface')}</th>
                <th>${t('wireguard.port')}</th>
                <th>${t('wireguard.subnet')}</th>
                <th>${t('wireguard.mode')}</th>
                <th>${t('wireguard.clients')}</th>
                <th class="w-1"></th>
            </tr></thead>
            <tbody>${instances.map(i => `<tr class="instance-row" data-id="${i.id}" style="cursor: pointer;">
                <td>
                    <span class="status-dot ${i.status === 'running' ? 'status-dot-animated bg-success' : 'bg-secondary'}"
                          title="${i.status === 'running' ? t('wireguard.statusRunning') : t('wireguard.statusStopped')}"></span>
                </td>
                <td>
                    <a href="#wireguard/${i.id}" class="text-reset">
                        <strong>${i.name}</strong>
                    </a>
                    <div class="small text-muted">
                        ${i.status === 'running'
                            ? `<span class="text-success">${t('wireguard.statusRunning')}</span>`
                            : `<span class="text-secondary">${t('wireguard.statusStopped')}</span>`}
                    </div>
                </td>
                <td><code>${i.interface}</code></td>
                <td>${i.port}/UDP</td>
                <td><code>${i.subnet}</code></td>
                <td><span class="badge ${i.tunnel_mode === 'full' ? 'bg-blue' : 'bg-purple'}-lt">
                    ${i.tunnel_mode === 'full' ? t('wireguard.fullTunnel') : t('wireguard.splitTunnel')}
                </span></td>
                <td>${i.client_count}</td>
                <td>
                    <div class="btn-group btn-group-sm" onclick="event.stopPropagation();">
                        ${canManage ? (i.status === 'running'
                            ? `<button class="btn btn-ghost-warning btn-stop" data-id="${i.id}" title="${t('wireguard.stop')}"><i class="ti ti-player-stop"></i></button>`
                            : `<button class="btn btn-ghost-success btn-start" data-id="${i.id}" title="${t('wireguard.start')}"><i class="ti ti-player-play"></i></button>`) : ''}
                        ${canManage ? `<button class="btn btn-ghost-danger btn-delete" data-id="${i.id}" title="${t('wireguard.delete')}"><i class="ti ti-trash"></i></button>` : ''}
                    </div>
                </td>
            </tr>`).join('')}</tbody>
        </table></div>`;

        setupInstanceRowActions(canManage);
    } catch (err) {
        listEl.innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
    }
}

function setupInstanceRowActions(canManage) {
    // Row click navigates to detail
    document.querySelectorAll('.instance-row').forEach(row => {
        row.addEventListener('click', (e) => {
            if (e.target.closest('.btn-group')) return;
            window.location.hash = `#wireguard/${row.dataset.id}`;
        });
    });

    // Start instance
    document.querySelectorAll('.btn-start').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const id = btn.dataset.id;
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            try {
                await apiPost(`${MODULE_API}/instances/${id}/start`);
                showToast(t('wireguard.instanceStarted'), 'success');
                await loadInstances(canManage);
            } catch (err) {
                showToast(err.message, 'error');
                btn.disabled = false;
                btn.innerHTML = '<i class="ti ti-player-play"></i>';
            }
        });
    });

    // Stop instance
    document.querySelectorAll('.btn-stop').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const id = btn.dataset.id;
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            try {
                await apiPost(`${MODULE_API}/instances/${id}/stop`);
                showToast(t('wireguard.instanceStopped'), 'success');
                await loadInstances(canManage);
            } catch (err) {
                showToast(err.message, 'error');
                btn.disabled = false;
                btn.innerHTML = '<i class="ti ti-player-stop"></i>';
            }
        });
    });

    // Delete instance
    document.querySelectorAll('.btn-delete').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const id = btn.dataset.id;
            if (!await confirmDialog(t('wireguard.confirmDeleteInstance'))) return;
            try {
                await apiDelete(`${MODULE_API}/instances/${id}`);
                showToast(t('wireguard.instanceDeleted'), 'success');
                await loadInstances(canManage);
            } catch (err) {
                showToast(err.message, 'error');
            }
        });
    });
}

function setupCreateForm(canManage) {
    document.getElementById('btn-new-instance')?.addEventListener('click', async () => {
        await loadNetworkInterfaces();
        populateInterfaceSelects();
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

    document.getElementById('btn-create-instance')?.addEventListener('click', () => createInstance(canManage));
}

async function loadNetworkInterfaces() {
    try {
        const data = await apiGet(`${MODULE_API}/system/interfaces`);
        networkInterfaces = data.interfaces || [];
    } catch (err) {
        console.warn('Could not load interfaces:', err);
        networkInterfaces = [{ name: 'eth0', state: 'unknown' }];
    }
}

function populateInterfaceSelects() {
    document.querySelectorAll('.route-interface').forEach(select => {
        const currentVal = select.value;
        select.innerHTML = `<option value="">${t('wireguard.autoInterface')}</option>` +
            networkInterfaces.map(iface =>
                `<option value="${iface.name}" ${iface.state === 'up' ? 'class="fw-bold"' : ''}>
                    ${iface.name} ${iface.state === 'up' ? '●' : ''}
                </option>`
            ).join('');
        if (currentVal) select.value = currentVal;
    });
}

function addRouteInput() {
    const container = document.getElementById('routes-container');
    const div = document.createElement('div');
    div.className = 'route-row mb-2 d-flex gap-2 align-items-center';
    div.innerHTML = `
        <input type="text" class="form-control route-network" placeholder="192.168.1.0/24" style="flex: 2">
        <select class="form-select route-interface" style="flex: 1">
            <option value="">${t('wireguard.autoInterface')}</option>
        </select>
        <button class="btn btn-outline-danger btn-remove-route" type="button">
            <i class="ti ti-minus"></i>
        </button>
    `;
    const select = div.querySelector('.route-interface');
    networkInterfaces.forEach(iface => {
        const opt = document.createElement('option');
        opt.value = iface.name;
        opt.textContent = `${iface.name} ${iface.state === 'up' ? '●' : ''}`;
        select.appendChild(opt);
    });
    div.querySelector('.btn-remove-route').addEventListener('click', () => div.remove());
    container.appendChild(div);
}

async function createInstance(canManage) {
    const name = document.getElementById('new-instance-name').value.trim();
    const port = parseInt(document.getElementById('new-instance-port').value);
    const subnet = document.getElementById('new-instance-subnet').value.trim();
    const tunnelMode = document.querySelector('input[name="tunnel-mode"]:checked').value;

    if (!name || !port || !subnet) {
        showToast(t('wireguard.fillAllFields'), 'error');
        return;
    }

    let dnsInput = tunnelMode === 'full'
        ? document.getElementById('new-instance-dns').value
        : document.getElementById('new-instance-dns-split').value;

    let dnsServers = dnsInput.split(',').map(s => s.trim()).filter(s => s);
    if (dnsServers.length === 0 && tunnelMode === 'full') {
        dnsServers = ['8.8.8.8', '1.1.1.1'];
    }

    let routes = [];
    if (tunnelMode === 'split') {
        document.querySelectorAll('.route-row').forEach(row => {
            const network = row.querySelector('.route-network')?.value.trim();
            const iface = row.querySelector('.route-interface')?.value;
            if (network) {
                routes.push({ network, interface: iface || null });
            }
        });
    }

    try {
        let defaultAllowedIps;
        if (tunnelMode === 'full') {
            defaultAllowedIps = '0.0.0.0/0, ::/0';
        } else {
            const routeNetworks = routes.map(r => r.network).filter(n => n);
            routeNetworks.push(subnet);
            defaultAllowedIps = routeNetworks.join(', ');
        }

        await apiPost(`${MODULE_API}/instances`, {
            name, port, subnet,
            tunnel_mode: tunnelMode,
            dns_servers: dnsServers,
            default_allowed_ips: defaultAllowedIps,
            routes: routes
        });
        showToast(t('wireguard.instanceCreated'), 'success');
        bootstrap.Modal.getInstance(document.getElementById('modal-new-instance'))?.hide();
        await loadInstances(canManage);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

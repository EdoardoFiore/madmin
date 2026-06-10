/**
 * WireGuard Module - Instance List View
 */

import { t } from '/static/js/i18n.js';
import { apiGet, apiPost, apiDelete } from '/static/js/api.js';
import { showToast, confirmDialog, escapeHtml } from '/static/js/utils.js';

const MODULE_API = '/modules/wireguard';

let _networkInterfaces = [];

async function apiPostForm(path, formData) {
    const token = localStorage.getItem('madmin_token');
    const resp = await fetch(`/api${path}`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || resp.statusText);
    }
    if (resp.status === 204) return null;
    return resp.json();
}

export async function renderWgList(container, canManage) {
    container.innerHTML = `
        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h3 class="card-title"><i class="ti ti-brand-wire me-2"></i>${t('wireguard.instancesTitle')}</h3>
                ${canManage ? `
                <div class="btn-group">
                    <button class="btn btn-primary" id="btn-new-instance">
                        <i class="ti ti-plus me-1"></i>${t('wireguard.newInstance')}
                    </button>
                    <button type="button" class="btn btn-primary dropdown-toggle dropdown-toggle-split" id="btn-new-instance-toggle" aria-expanded="false">
                        <span class="visually-hidden">Toggle</span>
                    </button>
                    <ul class="dropdown-menu dropdown-menu-end">
                        <li><a class="dropdown-item" href="#" id="btn-import-client">
                            <i class="ti ti-download me-2"></i>${t('wireguard.importClientItem')}
                        </a></li>
                    </ul>
                </div>` : ''}
            </div>
            <div class="card-body" id="instances-list"></div>
        </div>

        <!-- New Server Modal -->
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
                        <div id="full-tunnel-options">
                            <div class="mb-3">
                                <label class="form-label">${t('wireguard.dnsServers')}</label>
                                <input type="text" class="form-control" id="new-instance-dns"
                                       placeholder="8.8.8.8, 1.1.1.1" value="8.8.8.8, 1.1.1.1">
                                <small class="form-hint">${t('wireguard.dnsHint')}</small>
                            </div>
                        </div>
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

        <!-- Import Client Modal -->
        <div class="modal fade" id="modal-import-client" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title"><i class="ti ti-download me-2"></i>${t('wireguard.importClientTitle')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div id="import-step-1">
                            <div class="mb-3">
                                <label class="form-label">${t('wireguard.importNameLabel')}</label>
                                <input type="text" class="form-control" id="import-name" placeholder="my-wg-client">
                                <small class="form-hint">${t('wireguard.importNameHint')}</small>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">${t('wireguard.importFileLabel')}</label>
                                <input type="file" class="form-control" id="import-file" accept=".conf">
                            </div>
                            <div class="mb-3">
                                <label class="form-label">${t('wireguard.importLanLabel')}</label>
                                <div id="import-lan-interfaces" class="d-flex flex-wrap gap-2">
                                    <span class="text-muted small">${t('wireguard.loading')}</span>
                                </div>
                                <small class="form-hint">${t('wireguard.importLanHint')}</small>
                            </div>
                        </div>

                        <!-- Preview (shown after dry-run) -->
                        <div id="import-preview" style="display:none;">
                            <div class="alert alert-info mb-3" id="import-preview-info"></div>
                            <div class="alert alert-warning mb-3" id="import-preview-warnings" style="display:none;"></div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">${t('wireguard.cancel')}</button>
                        <button class="btn btn-secondary" id="btn-import-preview">
                            <i class="ti ti-eye me-1"></i>${t('wireguard.importPreviewBtn')}
                        </button>
                        <button class="btn btn-primary" id="btn-import-confirm" disabled>
                            <i class="ti ti-download me-1"></i>${t('wireguard.importConfirmBtn')}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Bootstrap 5: init split dropdown manually (data-bs-toggle removed to prevent data-api double-toggle)
    const ddToggle = container.querySelector('#btn-new-instance-toggle');
    if (ddToggle) {
        const dd = new bootstrap.Dropdown(ddToggle);
        ddToggle.addEventListener('click', () => dd.toggle());
    }

    await loadInstances(canManage);
    setupCreateForm(canManage);
    setupImportForm(canManage);
}

// ============================================================
//  LOAD & RENDER INSTANCES
// ============================================================

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
            <tbody>${instances.map(i => {
                const isClient = i.direction === 'client';
                const portCell = isClient
                    ? `<span class="text-muted">–</span>`
                    : (i.port ? `${i.port}/UDP` : `<span class="text-muted">–</span>`);
                const subnetCell = isClient
                    ? `<span class="text-muted small" title="${escapeHtml(i.upstream_endpoint || '')}">${escapeHtml((i.upstream_endpoint || '–').substring(0, 22))}</span>`
                    : (i.subnet ? `<code>${escapeHtml(i.subnet)}</code>` : `<span class="text-muted">–</span>`);
                const modeCell = isClient
                    ? `<span class="badge bg-orange-lt"><i class="ti ti-arrow-up-circle me-1"></i>Client</span>`
                    : `<span class="badge ${i.tunnel_mode === 'full' ? 'bg-blue' : 'bg-purple'}-lt">
                          ${i.tunnel_mode === 'full' ? t('wireguard.fullTunnel') : t('wireguard.splitTunnel')}
                       </span>`;
                const clientsCell = isClient
                    ? (i.upstream_status === 'connected'
                        ? `<span class="badge bg-success-lt">${t('wireguard.connected')}</span>`
                        : `<span class="badge bg-secondary-lt">${escapeHtml(i.upstream_status || t('wireguard.statusUnknown'))}</span>`)
                    : i.client_count;
                return `<tr class="instance-row" data-id="${i.id}" style="cursor: pointer;">
                    <td>
                        <span class="status-dot ${i.status === 'running' ? 'status-dot-animated bg-success' : 'bg-secondary'}"
                              title="${i.status === 'running' ? t('wireguard.statusRunning') : t('wireguard.statusStopped')}"></span>
                    </td>
                    <td>
                        <a href="#wireguard/${i.id}" class="text-reset">
                            <strong>${escapeHtml(i.name)}</strong>
                        </a>
                        <div class="small text-muted">
                            ${isClient ? '<span class="badge bg-orange-lt me-1">Client</span>' : ''}
                            ${i.status === 'running'
                                ? `<span class="text-success">${t('wireguard.statusRunning')}</span>`
                                : `<span class="text-secondary">${t('wireguard.statusStopped')}</span>`}
                        </div>
                    </td>
                    <td><code>${escapeHtml(i.interface)}</code></td>
                    <td>${portCell}</td>
                    <td>${subnetCell}</td>
                    <td>${modeCell}</td>
                    <td>${clientsCell}</td>
                    <td>
                        <div class="btn-group btn-group-sm" onclick="event.stopPropagation();">
                            ${canManage ? (i.status === 'running'
                                ? `<button class="btn btn-ghost-warning btn-stop" data-id="${i.id}" title="${t('wireguard.stop')}"><i class="ti ti-player-stop"></i></button>`
                                : `<button class="btn btn-ghost-success btn-start" data-id="${i.id}" title="${t('wireguard.start')}"><i class="ti ti-player-play"></i></button>`) : ''}
                            ${canManage ? `<button class="btn btn-ghost-danger btn-delete" data-id="${i.id}" title="${t('wireguard.delete')}"><i class="ti ti-trash"></i></button>` : ''}
                        </div>
                    </td>
                </tr>`;
            }).join('')}</tbody>
        </table></div>`;

        setupInstanceRowActions(canManage);
    } catch (err) {
        listEl.innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
    }
}

function setupInstanceRowActions(canManage) {
    document.querySelectorAll('.instance-row').forEach(row => {
        row.addEventListener('click', (e) => {
            if (e.target.closest('.btn-group')) return;
            window.location.hash = `#wireguard/${row.dataset.id}`;
        });
    });

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

// ============================================================
//  CREATE SERVER FORM
// ============================================================

function setupCreateForm(canManage) {
    document.getElementById('btn-new-instance')?.addEventListener('click', async () => {
        await loadNetworkInterfaces();
        populateInterfaceSelects();
        new bootstrap.Modal(document.getElementById('modal-new-instance')).show();
    });

    document.querySelectorAll('input[name="tunnel-mode"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            document.getElementById('full-tunnel-options').style.display = e.target.value === 'full' ? 'block' : 'none';
            document.getElementById('split-tunnel-options').style.display = e.target.value === 'split' ? 'block' : 'none';
        });
    });

    document.querySelector('.btn-add-route')?.addEventListener('click', addRouteInput);
    document.getElementById('btn-create-instance')?.addEventListener('click', () => createInstance(canManage));
}

async function loadNetworkInterfaces() {
    try {
        const data = await apiGet(`${MODULE_API}/system/interfaces`);
        _networkInterfaces = data.interfaces || [];
    } catch (err) {
        console.warn('Could not load interfaces:', err);
        _networkInterfaces = [{ name: 'eth0', state: 'unknown' }];
    }
}

function populateInterfaceSelects() {
    document.querySelectorAll('.route-interface').forEach(select => {
        const currentVal = select.value;
        select.innerHTML = `<option value="">${t('wireguard.autoInterface')}</option>` +
            _networkInterfaces.map(iface =>
                `<option value="${iface.name}" ${iface.state === 'up' ? 'class="fw-bold"' : ''}>${iface.name} ${iface.state === 'up' ? '●' : ''}</option>`
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
        <button class="btn btn-outline-danger btn-remove-route" type="button"><i class="ti ti-minus"></i></button>
    `;
    const select = div.querySelector('.route-interface');
    _networkInterfaces.forEach(iface => {
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
    if (dnsServers.length === 0 && tunnelMode === 'full') dnsServers = ['8.8.8.8', '1.1.1.1'];

    let routes = [];
    if (tunnelMode === 'split') {
        document.querySelectorAll('.route-row').forEach(row => {
            const network = row.querySelector('.route-network')?.value.trim();
            const iface = row.querySelector('.route-interface')?.value;
            if (network) routes.push({ network, interface: iface || null });
        });
    }

    try {
        let defaultAllowedIps = tunnelMode === 'full'
            ? '0.0.0.0/0, ::/0'
            : [...routes.map(r => r.network).filter(n => n), subnet].join(', ');

        await apiPost(`${MODULE_API}/instances`, {
            name, port, subnet, tunnel_mode: tunnelMode,
            dns_servers: dnsServers, default_allowed_ips: defaultAllowedIps, routes
        });
        showToast(t('wireguard.instanceCreated'), 'success');
        bootstrap.Modal.getInstance(document.getElementById('modal-new-instance'))?.hide();
        await loadInstances(canManage);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// ============================================================
//  IMPORT CLIENT FORM
// ============================================================

function setupImportForm(canManage) {
    document.getElementById('btn-import-client')?.addEventListener('click', async (e) => {
        e.preventDefault();
        document.getElementById('import-step-1').style.display = 'block';
        document.getElementById('import-preview').style.display = 'none';
        document.getElementById('btn-import-confirm').disabled = true;
        document.getElementById('import-name').value = '';
        document.getElementById('import-file').value = '';

        await loadImportInterfaces();
        new bootstrap.Modal(document.getElementById('modal-import-client')).show();
    });

    document.getElementById('btn-import-preview')?.addEventListener('click', runImportDryRun);
    document.getElementById('btn-import-confirm')?.addEventListener('click', () => runImport(canManage));
}

async function loadImportInterfaces() {
    try {
        const data = await apiGet(`${MODULE_API}/system/interfaces`);
        _networkInterfaces = data.interfaces || [];
    } catch {
        _networkInterfaces = [];
    }

    const container = document.getElementById('import-lan-interfaces');
    const phys = _networkInterfaces.filter(iface =>
        !iface.name.startsWith('lo') && !iface.name.startsWith('wg') &&
        !iface.name.startsWith('wcli') && !iface.name.startsWith('tcli')
    );
    if (!phys.length) {
        container.innerHTML = `<span class="text-muted small">${t('wireguard.importLanNone')}</span>`;
        return;
    }
    container.innerHTML = phys.map(iface => `
        <div class="form-check form-check-inline">
            <input class="form-check-input import-lan-iface" type="checkbox" id="iface-${iface.name}" value="${iface.name}">
            <label class="form-check-label" for="iface-${iface.name}">
                ${escapeHtml(iface.name)}
                ${iface.state === 'up' ? '<span class="badge bg-success-lt ms-1">up</span>' : ''}
            </label>
        </div>
    `).join('');
}

async function runImportDryRun() {
    const name = document.getElementById('import-name').value.trim();
    const fileInput = document.getElementById('import-file');

    if (!name) { showToast(t('wireguard.importEnterName'), 'error'); return; }
    if (!fileInput.files.length) { showToast(t('wireguard.importSelectFile'), 'error'); return; }

    const btn = document.getElementById('btn-import-preview');
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('wireguard.importAnalyzing')}`;

    try {
        const fd = new FormData();
        fd.append('config', fileInput.files[0]);
        fd.append('name', name);
        fd.append('tunnel_mode', 'split');
        fd.append('client_lan_interfaces', JSON.stringify([]));

        const preview = await apiPostForm(`${MODULE_API}/instances/import?dry_run=true`, fd);

        const infoEl = document.getElementById('import-preview-info');
        infoEl.innerHTML = `
            <strong>${t('wireguard.importPreviewTitle')}</strong><br>
            <ul class="mb-0 mt-1">
                <li>${t('wireguard.importPreviewPeerEndpoint')}: <code>${escapeHtml(preview.endpoint || '–')}</code></li>
                <li>${t('wireguard.importPreviewPeerKey')}: <code>${escapeHtml((preview.peer_public_key || '–').substring(0, 20))}…</code></li>
                <li>${t('wireguard.importPreviewPrivKey')}: ${preview.has_private_key
                    ? `<span class="text-success">✓ ${t('wireguard.importPreviewPresent')}</span>`
                    : `<span class="text-danger">✗ ${t('wireguard.importPreviewMissing')}</span>`}</li>
                <li>PSK: ${preview.has_psk
                    ? `<span class="text-success">✓ ${t('wireguard.importPreviewPresent')}</span>`
                    : `<span class="text-muted">– ${t('wireguard.importPreviewAbsent')}</span>`}</li>
                <li>AllowedIPs: <code>${escapeHtml((preview.peer_allowed_ips || '–').substring(0, 40))}</code></li>
            </ul>
        `;
        document.getElementById('import-preview').style.display = 'block';

        const warningsEl = document.getElementById('import-preview-warnings');
        if (preview.warnings && preview.warnings.length) {
            warningsEl.style.display = 'block';
            warningsEl.innerHTML = `<strong>${t('wireguard.importWarningsTitle')}</strong><ul class="mb-0 mt-1">` +
                preview.warnings.map(w => `<li>${escapeHtml(w)}</li>`).join('') + '</ul>';
        } else {
            warningsEl.style.display = 'none';
        }

        document.getElementById('btn-import-confirm').disabled = false;
    } catch (err) {
        showToast(t('wireguard.importAnalysisError', { error: err.message }), 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="ti ti-eye me-1"></i>${t('wireguard.importPreviewBtn')}`;
    }
}

async function runImport(canManage) {
    const name = document.getElementById('import-name').value.trim();
    const fileInput = document.getElementById('import-file');
    const tunnelMode = 'split';
    const selectedLans = [...document.querySelectorAll('.import-lan-iface:checked')].map(cb => cb.value);

    const btn = document.getElementById('btn-import-confirm');
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('wireguard.importImporting')}`;

    try {
        const fd = new FormData();
        fd.append('config', fileInput.files[0]);
        fd.append('name', name);
        fd.append('tunnel_mode', tunnelMode);
        fd.append('client_lan_interfaces', JSON.stringify(selectedLans));

        await apiPostForm(`${MODULE_API}/instances/import`, fd);
        showToast(t('wireguard.importSuccess'), 'success');
        bootstrap.Modal.getInstance(document.getElementById('modal-import-client'))?.hide();
        await loadInstances(canManage);
    } catch (err) {
        showToast(t('wireguard.importError', { error: err.message }), 'error');
        btn.disabled = false;
        btn.innerHTML = `<i class="ti ti-download me-1"></i>${t('wireguard.importConfirmBtn')}`;
    }
}

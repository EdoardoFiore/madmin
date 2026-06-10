/**
 * OpenVPN Module - Instance List View
 */

import { t } from '/static/js/i18n.js';
import { apiGet, apiPost, apiDelete } from '/static/js/api.js';
import { showToast, confirmDialog, escapeHtml } from '/static/js/utils.js';

const MODULE_API = '/modules/openvpn';

let _canManage = false;
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

// ============================================================
//  ENTRY POINT
// ============================================================

export async function renderOvpnList(container, canManage) {
    _canManage = canManage;

    // Pre-fetch before any DOM write
    let _instances = [];
    try { _instances = await apiGet(`${MODULE_API}/instances`); } catch (e) { /* shown inline */ }

    container.innerHTML = `
        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h3 class="card-title"><i class="ti ti-lock me-2"></i>${t('openvpn.instancesTitle')}</h3>
                ${canManage ? `
                <div class="btn-group">
                    <button class="btn btn-primary" id="btn-new-instance">
                        <i class="ti ti-plus me-1"></i>${t('openvpn.newInstance')}
                    </button>
                    <button type="button" class="btn btn-primary dropdown-toggle dropdown-toggle-split" id="btn-new-instance-toggle" aria-expanded="false">
                        <span class="visually-hidden">Toggle</span>
                    </button>
                    <ul class="dropdown-menu dropdown-menu-end">
                        <li><a class="dropdown-item" href="#" id="btn-import-client">
                            <i class="ti ti-download me-2"></i>${t('openvpn.importClientItem')}
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
                        <div id="full-tunnel-options">
                            <div class="mb-3">
                                <label class="form-label">${t('openvpn.dnsServers')}</label>
                                <input type="text" class="form-control" id="new-instance-dns"
                                       placeholder="8.8.8.8, 1.1.1.1" value="8.8.8.8, 1.1.1.1">
                                <small class="form-hint">${t('openvpn.dnsHint')}</small>
                            </div>
                        </div>
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

        <!-- Import Client Modal -->
        <div class="modal fade" id="modal-import-client" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title"><i class="ti ti-download me-2"></i>${t('openvpn.importClientTitle')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <!-- Step 1: Upload -->
                        <div id="import-step-1">
                            <div class="mb-3">
                                <label class="form-label">${t('openvpn.importNameLabel')}</label>
                                <input type="text" class="form-control" id="import-name" placeholder="my-vpn-client">
                                <small class="form-hint">${t('openvpn.importNameHint')}</small>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">${t('openvpn.importFileLabel')}</label>
                                <input type="file" class="form-control" id="import-file" accept=".ovpn,.conf">
                            </div>
                            <div class="mb-3">
                                <label class="form-label">${t('openvpn.importLanLabel')}</label>
                                <div id="import-lan-interfaces" class="d-flex flex-wrap gap-2">
                                    <span class="text-muted small">${t('openvpn.loading')}</span>
                                </div>
                                <small class="form-hint">${t('openvpn.importLanHint')}</small>
                            </div>
                            <details class="mb-3" id="import-credentials-section" style="display:none;">
                                <summary class="text-warning cursor-pointer">
                                    <i class="ti ti-lock me-1"></i>${t('openvpn.importCredsTitle')}
                                </summary>
                                <div class="mt-3 ps-3 row">
                                    <div class="col-md-6 mb-2">
                                        <label class="form-label">${t('openvpn.importUsernameLabel')}</label>
                                        <input type="text" class="form-control" id="import-auth-user" autocomplete="username">
                                    </div>
                                    <div class="col-md-6 mb-2">
                                        <label class="form-label">${t('openvpn.importPasswordLabel')}</label>
                                        <input type="password" class="form-control" id="import-auth-pass" autocomplete="current-password">
                                    </div>
                                </div>
                            </details>
                        </div>

                        <!-- Preview (shown after dry-run) -->
                        <div id="import-preview" style="display:none;">
                            <div class="alert alert-info mb-3" id="import-preview-info"></div>
                            <div class="alert alert-warning mb-3" id="import-preview-warnings" style="display:none;"></div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">${t('openvpn.cancel')}</button>
                        <button class="btn btn-secondary" id="btn-import-preview">
                            <i class="ti ti-eye me-1"></i>${t('openvpn.importPreviewBtn')}
                        </button>
                        <button class="btn btn-primary" id="btn-import-confirm" disabled>
                            <i class="ti ti-download me-1"></i>${t('openvpn.importConfirmBtn')}
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

    // Sync: no await between innerHTML and _fillInstancesList, so no intermediate paint
    _fillInstancesList(document.getElementById('instances-list'), _instances);
    setupCreateForm();
    setupImportForm();
}

// ============================================================
//  LOAD & RENDER INSTANCES
// ============================================================

function _fillInstancesList(listEl, instances) {
    if (!listEl) return;

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
            <tbody>${instances.map(i => {
                const isClient = i.direction === 'client';
                const portCell = isClient
                    ? `<span class="text-muted">–</span>`
                    : (i.port ? `${i.port}/${(i.protocol || 'udp').toUpperCase()}` : `<span class="text-muted">–</span>`);
                const subnetCell = isClient
                    ? `<span class="text-muted small" title="${escapeHtml(i.upstream_endpoint || '')}">${escapeHtml((i.upstream_endpoint || '–').substring(0, 22))}</span>`
                    : (i.subnet ? `<code>${escapeHtml(i.subnet)}</code>` : `<span class="text-muted">–</span>`);
                const modeCell = isClient
                    ? `<span class="badge bg-orange-lt"><i class="ti ti-arrow-up-circle me-1"></i>Client</span>`
                    : `<span class="badge ${i.tunnel_mode === 'full' ? 'bg-blue' : 'bg-purple'}-lt">
                          ${i.tunnel_mode === 'full' ? t('openvpn.fullMode') : t('openvpn.splitMode')}
                       </span>`;
                const clientsCell = isClient
                    ? (i.upstream_status === 'connected'
                        ? `<span class="badge bg-success-lt">${t('openvpn.connected')}</span>`
                        : `<span class="badge bg-secondary-lt">${escapeHtml(i.upstream_status || t('openvpn.statusUnknown'))}</span>`)
                    : i.client_count;
                return `<tr class="instance-row" data-id="${i.id}" style="cursor: pointer;">
                    <td>
                        <span class="status-dot ${i.status === 'running' ? 'status-dot-animated bg-success' : 'bg-secondary'}"
                              title="${i.status === 'running' ? t('openvpn.statusRunning') : t('openvpn.statusStopped')}"></span>
                    </td>
                    <td>
                        <a href="#openvpn/${i.id}" class="text-reset">
                            <strong>${escapeHtml(i.name)}</strong>
                        </a>
                        <div class="small text-muted">
                            ${isClient ? '<span class="badge bg-orange-lt me-1">Client</span>' : ''}
                            ${i.status === 'running'
                                ? `<span class="text-success">${t('openvpn.statusRunning')}</span>`
                                : `<span class="text-secondary">${t('openvpn.statusStopped')}</span>`}
                        </div>
                    </td>
                    <td><code>${escapeHtml(i.interface)}</code></td>
                    <td>${portCell}</td>
                    <td>${subnetCell}</td>
                    <td>${modeCell}</td>
                    <td>${clientsCell}</td>
                    <td>
                        <div class="btn-group btn-group-sm" onclick="event.stopPropagation();">
                            ${_canManage ? (i.status === 'running'
                                ? `<button class="btn btn-ghost-warning btn-stop" data-id="${i.id}" title="${t('openvpn.stop')}"><i class="ti ti-player-stop"></i></button>`
                                : `<button class="btn btn-ghost-success btn-start" data-id="${i.id}" title="${t('openvpn.start')}"><i class="ti ti-player-play"></i></button>`) : ''}
                            ${_canManage ? `<button class="btn btn-ghost-danger btn-delete" data-id="${i.id}" title="${t('openvpn.delete')}"><i class="ti ti-trash"></i></button>` : ''}
                        </div>
                    </td>
                </tr>`;
            }).join('')}</tbody>
        </table></div>`;

    setupInstanceRowActions();
}

async function loadInstances() {
    const listEl = document.getElementById('instances-list');
    if (!listEl) return;
    try {
        const instances = await apiGet(`${MODULE_API}/instances`);
        _fillInstancesList(listEl, instances);
    } catch (err) {
        listEl.innerHTML = `<div class="alert alert-danger">${escapeHtml(err.message)}</div>`;
    }
}

function setupInstanceRowActions() {
    document.querySelectorAll('.instance-row').forEach(row => {
        row.addEventListener('click', (e) => {
            if (e.target.closest('.btn-group')) return;
            window.location.hash = `#openvpn/${row.dataset.id}`;
        });
    });

    document.querySelectorAll('.btn-start').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            try {
                await apiPost(`${MODULE_API}/instances/${id}/start`);
                showToast(t('openvpn.instanceStarted'), 'success');
                loadInstances();
            } catch (err) {
                showToast(err.message, 'error');
                btn.disabled = false;
                btn.innerHTML = '<i class="ti ti-player-play"></i>';
            }
        });
    });

    document.querySelectorAll('.btn-stop').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            try {
                await apiPost(`${MODULE_API}/instances/${id}/stop`);
                showToast(t('openvpn.instanceStopped'), 'success');
                loadInstances();
            } catch (err) {
                showToast(err.message, 'error');
                btn.disabled = false;
                btn.innerHTML = '<i class="ti ti-player-stop"></i>';
            }
        });
    });

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
//  CREATE SERVER FORM
// ============================================================

function setupCreateForm() {
    document.getElementById('btn-new-instance')?.addEventListener('click', () => {
        new bootstrap.Modal(document.getElementById('modal-new-instance')).show();
    });

    document.querySelectorAll('input[name="tunnel-mode"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            document.getElementById('full-tunnel-options').style.display = e.target.value === 'full' ? 'block' : 'none';
            document.getElementById('split-tunnel-options').style.display = e.target.value === 'split' ? 'block' : 'none';
        });
    });

    document.querySelector('.btn-add-route')?.addEventListener('click', addRouteInput);
    document.getElementById('btn-create-instance')?.addEventListener('click', createInstance);
}

function addRouteInput() {
    const container = document.getElementById('routes-container');
    const div = document.createElement('div');
    div.className = 'route-row mb-2 d-flex gap-2 align-items-center';
    div.innerHTML = `
        <input type="text" class="form-control route-network" placeholder="192.168.1.0/24" style="flex: 2">
        <button class="btn btn-outline-danger btn-remove-route" type="button"><i class="ti ti-minus"></i></button>
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

    let dnsInput = tunnelMode === 'full'
        ? document.getElementById('new-instance-dns').value
        : document.getElementById('new-instance-dns-split').value;
    let dnsServers = dnsInput.split(',').map(s => s.trim()).filter(s => s);
    if (dnsServers.length === 0 && tunnelMode === 'full') dnsServers = ['8.8.8.8', '1.1.1.1'];

    let routes = [];
    if (tunnelMode === 'split') {
        document.querySelectorAll('.route-row').forEach(row => {
            const network = row.querySelector('.route-network')?.value.trim();
            if (network) routes.push({ network });
        });
    }

    try {
        await apiPost(`${MODULE_API}/instances`, {
            name, port, protocol, subnet, endpoint,
            tunnel_mode: tunnelMode, dns_servers: dnsServers,
            routes, cipher, cert_duration_days: certDays
        });
        showToast(t('openvpn.instanceCreated'), 'success');
        bootstrap.Modal.getInstance(document.getElementById('modal-new-instance'))?.hide();
        await loadInstances();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// ============================================================
//  IMPORT CLIENT FORM
// ============================================================

function setupImportForm() {
    document.getElementById('btn-import-client')?.addEventListener('click', async (e) => {
        e.preventDefault();
        // Reset modal state
        document.getElementById('import-step-1').style.display = 'block';
        document.getElementById('import-preview').style.display = 'none';
        document.getElementById('btn-import-confirm').disabled = true;
        document.getElementById('import-name').value = '';
        document.getElementById('import-file').value = '';
        document.getElementById('import-credentials-section').style.display = 'none';

        await loadImportInterfaces();
        new bootstrap.Modal(document.getElementById('modal-import-client')).show();
    });

    document.getElementById('btn-import-preview')?.addEventListener('click', runImportDryRun);
    document.getElementById('btn-import-confirm')?.addEventListener('click', runImport);
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
        !iface.name.startsWith('lo') && !iface.name.startsWith('tun') &&
        !iface.name.startsWith('wg') && !iface.name.startsWith('tcli') && !iface.name.startsWith('wcli')
    );
    if (!phys.length) {
        container.innerHTML = `<span class="text-muted small">${t('openvpn.importLanNone')}</span>`;
        return;
    }
    container.innerHTML = phys
        .map(iface => `
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

    if (!name) { showToast(t('openvpn.importEnterName'), 'error'); return; }
    if (!fileInput.files.length) { showToast(t('openvpn.importSelectFile'), 'error'); return; }

    const btn = document.getElementById('btn-import-preview');
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('openvpn.importAnalyzing')}`;

    try {
        const fd = new FormData();
        fd.append('config', fileInput.files[0]);
        fd.append('name', name);
        fd.append('tunnel_mode', 'split');
        fd.append('client_lan_interfaces', JSON.stringify([]));

        const preview = await apiPostForm(`${MODULE_API}/instances/import?dry_run=true`, fd);

        // Show credentials section if needed
        const credsSection = document.getElementById('import-credentials-section');
        if (preview.auth_required) {
            credsSection.style.display = '';
            credsSection.open = true;
        }

        // Build preview info
        const infoEl = document.getElementById('import-preview-info');
        infoEl.innerHTML = `
            <strong>${t('openvpn.importPreviewTitle')}</strong><br>
            <ul class="mb-0 mt-1">
                <li>${t('openvpn.publicEndpointLabel')}: <code>${escapeHtml(preview.endpoint || '–')}</code></li>
                <li>${t('openvpn.protocol')}: <code>${escapeHtml(preview.proto || '–')}</code></li>
                <li>CA: ${preview.has_ca ? '<span class="text-success">✓</span>' : `<span class="text-danger">✗ ${t('openvpn.importPreviewMissing')}</span>`}</li>
                <li>${t('openvpn.importPreviewClientCert')}: ${preview.has_cert ? '<span class="text-success">✓</span>' : '<span class="text-muted">–</span>'}</li>
                <li>${t('openvpn.importPreviewPrivKey')}: ${preview.has_key ? '<span class="text-success">✓</span>' : '<span class="text-muted">–</span>'}</li>
                <li>${t('openvpn.importPreviewTls')}: ${preview.has_tls ? '<span class="text-success">✓</span>' : '<span class="text-muted">–</span>'}</li>
                ${preview.auth_required ? `<li><span class="text-warning">${t('openvpn.importAuthRequired')}</span></li>` : ''}
            </ul>
        `;
        document.getElementById('import-preview').style.display = 'block';

        const warningsEl = document.getElementById('import-preview-warnings');
        if (preview.warnings && preview.warnings.length) {
            warningsEl.style.display = 'block';
            warningsEl.innerHTML = `<strong>${t('openvpn.importWarningsTitle')}</strong><ul class="mb-0 mt-1">` +
                preview.warnings.map(w => `<li>${escapeHtml(w)}</li>`).join('') + '</ul>';
        } else {
            warningsEl.style.display = 'none';
        }

        document.getElementById('btn-import-confirm').disabled = false;
    } catch (err) {
        showToast(t('openvpn.importAnalysisError', { error: err.message }), 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="ti ti-eye me-1"></i>${t('openvpn.importPreviewBtn')}`;
    }
}

async function runImport() {
    const name = document.getElementById('import-name').value.trim();
    const fileInput = document.getElementById('import-file');
    const tunnelMode = 'split';
    const selectedLans = [...document.querySelectorAll('.import-lan-iface:checked')].map(cb => cb.value);
    const authUser = document.getElementById('import-auth-user')?.value.trim();
    const authPass = document.getElementById('import-auth-pass')?.value;

    const btn = document.getElementById('btn-import-confirm');
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('openvpn.importImporting')}`;

    try {
        const fd = new FormData();
        fd.append('config', fileInput.files[0]);
        fd.append('name', name);
        fd.append('tunnel_mode', tunnelMode);
        fd.append('client_lan_interfaces', JSON.stringify(selectedLans));
        if (authUser) fd.append('auth_username', authUser);
        if (authPass) fd.append('auth_password', authPass);

        await apiPostForm(`${MODULE_API}/instances/import`, fd);
        showToast(t('openvpn.importSuccess'), 'success');
        bootstrap.Modal.getInstance(document.getElementById('modal-import-client'))?.hide();
        await loadInstances();
    } catch (err) {
        showToast(t('openvpn.importError', { error: err.message }), 'error');
        btn.disabled = false;
        btn.innerHTML = `<i class="ti ti-download me-1"></i>${t('openvpn.importConfirmBtn')}`;
    }
}

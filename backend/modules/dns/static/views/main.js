/**
 * DNS Module - Main View
 * 
 * Complete management UI for BIND9 DNS Server.
 * Three tabs: Zones, Forwarders, Settings.
 * Service control and DNS query testing.
 */

import { apiGet, apiPost, apiDelete, apiPatch, apiPut } from '/static/js/api.js';
import { showToast, confirmDialog, loadingSpinner, escapeHtml } from '/static/js/utils.js';
import { checkPermission } from '/static/js/app.js';

let canManage = false;
let canZones = false;
let canRecords = false;
let currentContainer = null;

const RECORD_TYPES = ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'SRV', 'NS', 'PTR'];
const MODE_LABELS = {
    recursive: 'Ricorsivo',
    forward_only: 'Solo Forwarding',
    non_recursive: 'Non Ricorsivo'
};

// ============================================================
//  ENTRY POINT
// ============================================================

export async function render(container, params) {
    currentContainer = container;
    canManage = checkPermission('dns.manage');
    canZones = checkPermission('dns.zones');
    canRecords = checkPermission('dns.records');

    if (params && params.length > 0) {
        await renderZoneDetail(container, params[0]);
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
        const [status, zones, forwarders, settings] = await Promise.all([
            apiGet('/modules/dns/status'),
            apiGet('/modules/dns/zones'),
            apiGet('/modules/dns/forwarders'),
            apiGet('/modules/dns/settings'),
        ]);

        container.innerHTML = `
            <!-- Status Cards -->
            <div class="row row-deck row-cards mb-3">
                <div class="col-sm-6 col-lg-3">
                    <div class="card">
                        <div class="card-body">
                            <div class="subheader">Stato Servizio</div>
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
                            <div class="subheader">Modalità</div>
                            <div class="h1 mb-0 mt-1">${MODE_LABELS[status.mode] || status.mode}</div>
                        </div>
                    </div>
                </div>
                <div class="col-sm-6 col-lg-3">
                    <div class="card">
                        <div class="card-body">
                            <div class="subheader">Zone DNS</div>
                            <div class="h1 mb-0 mt-1">${status.total_zones}</div>
                        </div>
                    </div>
                </div>
                <div class="col-sm-6 col-lg-3">
                    <div class="card">
                        <div class="card-body">
                            <div class="subheader">Record Totali</div>
                            <div class="h1 mb-0 mt-1">${status.total_records}</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Tabs -->
            <div class="card">
                <div class="card-header">
                    <ul class="nav nav-tabs card-header-tabs" id="dns-tabs">
                        <li class="nav-item">
                            <a class="nav-link active" href="#" data-tab="zones">
                                <i class="ti ti-world me-1"></i>Zone
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#" data-tab="forwarders">
                                <i class="ti ti-arrows-right me-1"></i>Forwarder
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#" data-tab="settings">
                                <i class="ti ti-settings me-1"></i>Impostazioni
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#" data-tab="test">
                                <i class="ti ti-search me-1"></i>Test DNS
                            </a>
                        </li>
                    </ul>
                </div>
                <div id="dns-tab-content"></div>
            </div>

            <!-- Modals -->
            ${renderNewZoneModal()}
            ${renderNewForwarderModal()}
        `;

        setupTabListeners(zones, forwarders, settings);
        setupServiceActions();
        renderZonesTab(zones);

    } catch (err) {
        container.innerHTML = `<div class="alert alert-danger"><i class="ti ti-alert-triangle me-2"></i>${err.message}</div>`;
    }
}

// ============================================================
//  TAB SYSTEM
// ============================================================

function setupTabListeners(zones, forwarders, settings) {
    document.getElementById('dns-tabs')?.addEventListener('click', (e) => {
        e.preventDefault();
        const tab = e.target.closest('[data-tab]');
        if (!tab) return;

        document.querySelectorAll('#dns-tabs .nav-link').forEach(l => l.classList.remove('active'));
        tab.classList.add('active');

        const tabName = tab.dataset.tab;
        if (tabName === 'zones') renderZonesTab(zones);
        else if (tabName === 'forwarders') renderForwardersTab(forwarders);
        else if (tabName === 'settings') renderSettingsTab(settings);
        else if (tabName === 'test') renderTestTab();
    });
}

// ============================================================
//  ZONES TAB
// ============================================================

function renderZonesTab(zones) {
    const content = document.getElementById('dns-tab-content');
    if (!content) return;

    content.innerHTML = `
        <div class="card-body">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h4 class="mb-0">Zone DNS</h4>
                <div class="d-flex gap-2">
                    ${canZones ? `
                    <button class="btn btn-primary" id="btn-new-zone">
                        <i class="ti ti-plus me-1"></i>Nuova Zona
                    </button>` : ''}
                </div>
            </div>
            ${zones.length === 0 ? `
                <div class="text-center py-5 text-muted">
                    <i class="ti ti-world-off" style="font-size: 3rem;"></i>
                    <p class="mt-2">Nessuna zona DNS configurata</p>
                    <small>Clicca "Nuova Zona" per crearne una</small>
                </div>
            ` : `
                <div class="table-responsive">
                    <table class="table table-vcenter table-hover">
                        <thead>
                            <tr>
                                <th style="width: 50px;">Attiva</th>
                                <th>Nome Zona</th>
                                <th>Tipo</th>
                                <th>Record</th>
                                <th>Descrizione</th>
                                <th class="w-1"></th>
                            </tr>
                        </thead>
                        <tbody>
                            ${zones.map(z => `
                                <tr class="zone-row ${!z.enabled ? 'text-muted' : ''}" data-id="${z.id}" style="cursor: pointer;">
                                    <td onclick="event.stopPropagation();">
                                        ${canZones ? `
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
                                        ${canZones ? `
                                        <button class="btn btn-sm btn-ghost-danger btn-delete-zone" 
                                                data-id="${z.id}" onclick="event.stopPropagation();" title="Elimina">
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
    `;

    setupZonesActions(zones);
}

function setupZonesActions(zones) {
    // New zone
    document.getElementById('btn-new-zone')?.addEventListener('click', () => {
        new bootstrap.Modal(document.getElementById('modal-new-zone')).show();
    });
    document.getElementById('btn-create-zone')?.addEventListener('click', createZone);

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
            if (!await confirmDialog('Eliminare questa zona?', 'Tutti i record associati saranno eliminati.')) return;
            try {
                await apiDelete(`/modules/dns/zones/${btn.dataset.id}`);
                showToast('Zona eliminata', 'success');
                await renderDashboard(currentContainer);
            } catch (err) { showToast(err.message, 'error'); }
        });
    });

    // Zone toggle (auto-apply)
    document.querySelectorAll('.zone-toggle').forEach(toggle => {
        toggle.addEventListener('change', async () => {
            const id = toggle.dataset.id;
            const enabled = toggle.checked;
            try {
                const res = await apiPatch(`/modules/dns/zones/${id}`, { enabled });
                if (res.applied) {
                    showToast(enabled ? 'Zona abilitata e configurazione applicata' : 'Zona disabilitata e configurazione applicata', 'success');
                } else {
                    showToast(`Zona ${enabled ? 'abilitata' : 'disabilitata'} — errore applicazione: ${res.apply_message}`, 'warning');
                }
                await renderDashboard(currentContainer);
            } catch (err) {
                toggle.checked = !enabled;
                showToast(err.message, 'error');
            }
        });
    });
}

async function createZone() {
    const name = document.getElementById('new-zone-name')?.value.trim();
    const zoneType = document.getElementById('new-zone-type')?.value;
    const description = document.getElementById('new-zone-desc')?.value.trim();
    const forwardServers = document.getElementById('new-zone-fwd-servers')?.value.trim();

    if (!name) {
        showToast('Il nome della zona è obbligatorio', 'error');
        return;
    }

    const data = { name, zone_type: zoneType, description };
    if (zoneType !== 'master' && forwardServers) {
        const servers = forwardServers.split(',').map(s => s.trim()).filter(Boolean);
        data.forward_servers = JSON.stringify(servers);
    }

    try {
        const result = await apiPost('/modules/dns/zones', data);
        if (result.applied) {
            showToast('Zona creata e configurazione applicata', 'success');
        } else {
            showToast(`Zona creata — attenzione: ${result.apply_message}`, 'warning');
        }
        bootstrap.Modal.getInstance(document.getElementById('modal-new-zone'))?.hide();
        await renderDashboard(currentContainer);
    } catch (err) { showToast(err.message, 'error'); }
}

// ============================================================
//  FORWARDERS TAB
// ============================================================

function renderForwardersTab(forwarders) {
    const content = document.getElementById('dns-tab-content');
    if (!content) return;

    content.innerHTML = `
        <div class="card-body">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <div>
                    <h4 class="mb-0">Forwarder Condizionali</h4>
                    <small class="text-muted">Instrada le query DNS per domini specifici verso server dedicati</small>
                </div>
                ${canManage ? `
                <button class="btn btn-primary" id="btn-new-fwd">
                    <i class="ti ti-plus me-1"></i>Nuovo Forwarder
                </button>` : ''}
            </div>
            ${forwarders.length === 0 ? `
                <div class="text-center py-5 text-muted">
                    <i class="ti ti-arrows-right" style="font-size: 3rem;"></i>
                    <p class="mt-2">Nessun forwarder condizionale configurato</p>
                    <small>I forwarder permettono di instradare query per domini specifici verso DNS dedicati</small>
                </div>
            ` : `
                <div class="table-responsive">
                    <table class="table table-vcenter">
                        <thead>
                            <tr>
                                <th style="width: 50px;">Attivo</th>
                                <th>Dominio</th>
                                <th>Server DNS</th>
                                <th>Descrizione</th>
                                <th class="w-1"></th>
                            </tr>
                        </thead>
                        <tbody>
                            ${forwarders.map(f => {
        let servers = [];
        try { servers = JSON.parse(f.servers); } catch (e) { servers = [f.servers]; }
        return `
                                <tr class="${!f.enabled ? 'text-muted' : ''}">
                                    <td>
                                        ${canManage ? `
                                        <label class="form-check form-switch mb-0">
                                            <input class="form-check-input fwd-toggle" type="checkbox"
                                                   data-id="${f.id}" ${f.enabled ? 'checked' : ''}>
                                        </label>` : `
                                        <span class="status-dot ${f.enabled ? 'bg-success' : 'bg-secondary'}"></span>`}
                                    </td>
                                    <td><strong>${escapeHtml(f.domain)}</strong></td>
                                    <td>${servers.map(s => `<code>${escapeHtml(s)}</code>`).join(', ')}</td>
                                    <td><small class="text-muted">${escapeHtml(f.description || '—')}</small></td>
                                    <td>
                                        ${canManage ? `
                                        <button class="btn btn-sm btn-ghost-danger btn-delete-fwd" data-id="${f.id}" title="Elimina">
                                            <i class="ti ti-trash"></i>
                                        </button>` : ''}
                                    </td>
                                </tr>`;
    }).join('')}
                        </tbody>
                    </table>
                </div>
            `}
        </div>
    `;

    // New forwarder
    document.getElementById('btn-new-fwd')?.addEventListener('click', () => {
        new bootstrap.Modal(document.getElementById('modal-new-fwd')).show();
    });
    document.getElementById('btn-create-fwd')?.addEventListener('click', createForwarder);

    // Delete forwarder
    document.querySelectorAll('.btn-delete-fwd').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!await confirmDialog('Eliminare questo forwarder?')) return;
            try {
                await apiDelete(`/modules/dns/forwarders/${btn.dataset.id}`);
                showToast('Forwarder eliminato', 'success');
                await renderDashboard(currentContainer);
            } catch (err) { showToast(err.message, 'error'); }
        });
    });

    // Toggle
    document.querySelectorAll('.fwd-toggle').forEach(toggle => {
        toggle.addEventListener('change', async () => {
            try {
                await apiPatch(`/modules/dns/forwarders/${toggle.dataset.id}`, { enabled: toggle.checked });
                showToast(toggle.checked ? 'Forwarder abilitato' : 'Forwarder disabilitato', toggle.checked ? 'success' : 'warning');
            } catch (err) {
                toggle.checked = !toggle.checked;
                showToast(err.message, 'error');
            }
        });
    });
}

async function createForwarder() {
    const domain = document.getElementById('new-fwd-domain')?.value.trim();
    const serversStr = document.getElementById('new-fwd-servers')?.value.trim();
    const description = document.getElementById('new-fwd-desc')?.value.trim();

    if (!domain || !serversStr) {
        showToast('Dominio e server sono obbligatori', 'error');
        return;
    }

    const servers = serversStr.split(',').map(s => s.trim()).filter(Boolean);

    try {
        await apiPost('/modules/dns/forwarders', {
            domain,
            servers: JSON.stringify(servers),
            description
        });
        showToast('Forwarder creato', 'success');
        bootstrap.Modal.getInstance(document.getElementById('modal-new-fwd'))?.hide();
        await renderDashboard(currentContainer);
    } catch (err) { showToast(err.message, 'error'); }
}

// ============================================================
//  SETTINGS TAB
// ============================================================

function renderSettingsTab(settings) {
    const content = document.getElementById('dns-tab-content');
    if (!content) return;

    let listenIfaces = [];
    try { listenIfaces = JSON.parse(settings.listen_interfaces || '[]'); } catch (e) { }
    let sysForwarders = [];
    try { sysForwarders = JSON.parse(settings.system_forwarders || '[]'); } catch (e) { }

    content.innerHTML = `
        <div class="card-body">
            <h4 class="mb-3">Impostazioni Globali DNS</h4>
            <div class="row">
                <div class="col-md-6 mb-3">
                    <label class="form-label">Modalità operativa</label>
                    <select class="form-select" id="setting-mode" ${!canManage ? 'disabled' : ''}>
                        <option value="recursive" ${settings.mode === 'recursive' ? 'selected' : ''}>Ricorsivo — risolvi localmente, poi forward</option>
                        <option value="forward_only" ${settings.mode === 'forward_only' ? 'selected' : ''}>Solo Forwarding — inoltra tutto ai forwarder</option>
                        <option value="non_recursive" ${settings.mode === 'non_recursive' ? 'selected' : ''}>Non Ricorsivo — solo zone locali</option>
                    </select>
                    <small class="form-hint">
                        <strong>Ricorsivo:</strong> controlla le zone locali, poi inoltra.<br>
                        <strong>Solo Forwarding:</strong> inoltra tutte le query ai forwarder di sistema.<br>
                        <strong>Non Ricorsivo:</strong> risponde solo dalle zone locali, non inoltra.
                    </small>
                </div>
                <div class="col-md-6 mb-3">
                    <label class="form-label">Forwarder di sistema</label>
                    <input type="text" class="form-control" id="setting-forwarders" 
                           value="${sysForwarders.join(', ')}" placeholder="8.8.8.8, 1.1.1.1"
                           ${!canManage ? 'disabled' : ''}>
                    <small class="form-hint">Server DNS upstream separati da virgola</small>
                </div>
            </div>
            <div class="row">
                <div class="col-md-6 mb-3">
                    <label class="form-label">Allow Query</label>
                    <select class="form-select" id="setting-allow-query" ${!canManage ? 'disabled' : ''}>
                        <option value="localnets" ${settings.allow_query === 'localnets' ? 'selected' : ''}>Solo reti locali (localnets)</option>
                        <option value="any" ${settings.allow_query === 'any' ? 'selected' : ''}>Qualsiasi (any)</option>
                    </select>
                    <small class="form-hint">Chi può effettuare query al DNS server</small>
                </div>
                <div class="col-md-6 mb-3">
                    <label class="form-label">DNSSEC Validation</label>
                    <div class="form-check form-switch mt-2">
                        <input class="form-check-input" type="checkbox" id="setting-dnssec" 
                               ${settings.dnssec_validation ? 'checked' : ''} ${!canManage ? 'disabled' : ''}>
                        <label class="form-check-label" for="setting-dnssec">Abilita validazione DNSSEC</label>
                    </div>
                </div>
            </div>
            ${canManage ? `
            <div class="mt-3">
                <button class="btn btn-primary" id="btn-save-settings">
                    <i class="ti ti-check me-1"></i>Salva Impostazioni
                </button>
            </div>` : ''}
        </div>
    `;

    document.getElementById('btn-save-settings')?.addEventListener('click', saveSettings);
}

async function saveSettings() {
    const mode = document.getElementById('setting-mode')?.value;
    const forwardersStr = document.getElementById('setting-forwarders')?.value.trim();
    const allowQuery = document.getElementById('setting-allow-query')?.value;
    const dnssec = document.getElementById('setting-dnssec')?.checked;

    const forwarders = forwardersStr ? forwardersStr.split(',').map(s => s.trim()).filter(Boolean) : [];

    try {
        const result = await apiPut('/modules/dns/settings', {
            mode,
            system_forwarders: JSON.stringify(forwarders),
            allow_query: allowQuery,
            dnssec_validation: dnssec,
        });
        if (result.applied) {
            showToast('Impostazioni salvate e applicate', 'success');
        } else {
            showToast(`Impostazioni salvate — errore applicazione: ${result.apply_message}`, 'warning');
        }
    } catch (err) { showToast(err.message, 'error'); }
}

// ============================================================
//  TEST DNS TAB
// ============================================================

function renderTestTab() {
    const content = document.getElementById('dns-tab-content');
    if (!content) return;

    content.innerHTML = `
        <div class="card-body">
            <h4 class="mb-3">Test Query DNS</h4>
            <p class="text-muted">Esegui una query DNS contro il server locale per verificare la risoluzione.</p>
            <div class="row align-items-end">
                <div class="col-md-5 mb-3">
                    <label class="form-label">Dominio</label>
                    <input type="text" class="form-control" id="test-domain" placeholder="es. www.lab.local">
                </div>
                <div class="col-md-3 mb-3">
                    <label class="form-label">Tipo Record</label>
                    <select class="form-select" id="test-type">
                        ${RECORD_TYPES.map(t => `<option value="${t}" ${t === 'A' ? 'selected' : ''}>${t}</option>`).join('')}
                    </select>
                </div>
                <div class="col-md-2 mb-3">
                    <button class="btn btn-primary w-100" id="btn-test-query">
                        <i class="ti ti-search me-1"></i>Test
                    </button>
                </div>
            </div>
            <div id="test-result" class="mt-2"></div>
        </div>
    `;

    document.getElementById('btn-test-query')?.addEventListener('click', testDnsQuery);
    document.getElementById('test-domain')?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') testDnsQuery();
    });
}

async function testDnsQuery() {
    const domain = document.getElementById('test-domain')?.value.trim();
    const recordType = document.getElementById('test-type')?.value;
    const resultDiv = document.getElementById('test-result');

    if (!domain) {
        showToast('Inserisci un dominio', 'error');
        return;
    }

    resultDiv.innerHTML = `<div class="text-center py-3">${loadingSpinner()}</div>`;

    try {
        const result = await apiPost('/modules/dns/test', { domain, record_type: recordType });
        const isSuccess = result.success;

        resultDiv.innerHTML = `
            <div class="alert ${isSuccess ? 'alert-success' : 'alert-warning'}">
                <div class="d-flex align-items-center">
                    <i class="ti ti-${isSuccess ? 'check' : 'alert-triangle'} me-2"></i>
                    <div>
                        <strong>Query:</strong> ${escapeHtml(result.query)}<br>
                        <strong>Risultato:</strong> <code>${escapeHtml(result.result)}</code>
                        ${result.error ? `<br><strong>Errore:</strong> ${escapeHtml(result.error)}` : ''}
                    </div>
                </div>
            </div>
        `;
    } catch (err) {
        resultDiv.innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
    }
}

// ============================================================
//  SERVICE ACTIONS
// ============================================================

function setupServiceActions() {
    document.getElementById('btn-start')?.addEventListener('click', async () => {
        try {
            await apiPost('/modules/dns/start');
            showToast('Servizio DNS avviato', 'success');
            await renderDashboard(currentContainer);
        } catch (err) { showToast(err.message, 'error'); }
    });

    document.getElementById('btn-stop')?.addEventListener('click', async () => {
        if (!await confirmDialog('Fermare il servizio DNS?', 'Le query DNS non verranno più risolte.')) return;
        try {
            await apiPost('/modules/dns/stop');
            showToast('Servizio DNS fermato', 'success');
            await renderDashboard(currentContainer);
        } catch (err) { showToast(err.message, 'error'); }
    });
}

// ============================================================
//  ZONE DETAIL VIEW
// ============================================================

async function renderZoneDetail(container, zoneId) {
    container.innerHTML = `<div class="text-center py-5">${loadingSpinner()}</div>`;

    try {
        const zone = await apiGet(`/modules/dns/zones/${zoneId}`);

        container.innerHTML = `
            <!-- Back Link -->
            <div class="mb-3">
                <a href="#dns" class="text-muted">
                    <i class="ti ti-arrow-left me-1"></i>Torna alle zone
                </a>
            </div>

            <!-- Zone Info -->
            <div class="card mb-3">
                <div class="card-header">
                    <div class="d-flex justify-content-between align-items-center w-100">
                        <div>
                            <h3 class="card-title mb-0">
                                <span class="status-dot ${zone.enabled ? 'bg-success' : 'bg-secondary'} me-2"></span>
                                ${escapeHtml(zone.name)}
                            </h3>
                            <small class="text-muted">
                                Tipo: <span class="badge bg-blue-lt">${zone.zone_type}</span>
                                — TTL default: ${zone.ttl_default}s
                                ${zone.description ? ` — ${escapeHtml(zone.description)}` : ''}
                            </small>
                        </div>
                        ${canZones ? `
                        <div class="btn-group">
                            <button class="btn btn-outline-primary" id="btn-edit-zone">
                                <i class="ti ti-edit me-1"></i>Modifica
                            </button>
                            <button class="btn btn-outline-danger" id="btn-delete-zone">
                                <i class="ti ti-trash me-1"></i>Elimina
                            </button>
                        </div>` : ''}
                    </div>
                </div>
            </div>

            ${zone.zone_type === 'master' ? `
            <!-- Records -->
            <div class="card">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h3 class="card-title"><i class="ti ti-list me-2"></i>Record DNS (${zone.records.length})</h3>
                        ${canRecords ? `
                    <button class="btn btn-primary" id="btn-new-record">
                        <i class="ti ti-plus me-1"></i>Nuovo Record
                    </button>` : ''}
                </div>
                <div class="card-body" id="records-list">
                    ${renderRecordsTable(zone.records)}
                </div>
            </div>

            <!-- New Record Modal -->
            ${renderNewRecordModal(zone)}
            <!-- Edit Record Modal -->
            ${renderEditRecordModal()}
            ` : `
            <div class="card">
                <div class="card-body text-center text-muted py-4">
                    <i class="ti ti-arrows-right" style="font-size: 2rem;"></i>
                    <p class="mt-2">Questa è una zona di tipo <strong>${zone.zone_type}</strong> — i record sono gestiti dal server remoto.</p>
                    ${zone.forward_servers ? `<p>Server: <code>${escapeHtml(zone.forward_servers)}</code></p>` : ''}
                </div>
            </div>
            `}

            <!-- Edit Zone Modal -->
            ${renderEditZoneModal(zone)}
        `;

        setupZoneDetailActions(zone, zoneId);

    } catch (err) {
        container.innerHTML = `
            <div class="mb-3"><a href="#dns" class="text-muted"><i class="ti ti-arrow-left me-1"></i>Torna alle zone</a></div>
            <div class="alert alert-danger"><i class="ti ti-alert-triangle me-2"></i>${err.message}</div>`;
    }
}

function renderRecordsTable(records) {
    if (records.length === 0) {
        return `
            <div class="text-center py-4 text-muted">
                <i class="ti ti-list" style="font-size: 2rem;"></i>
                <p class="mt-2">Nessun record in questa zona</p>
            </div>`;
    }

    return `
        <div class="table-responsive">
            <table class="table table-vcenter">
                <thead>
                    <tr>
                        <th>Tipo</th>
                        <th>Nome</th>
                        <th>Valore</th>
                        <th>TTL</th>
                        <th>Priorità</th>
                        <th class="w-1">Azioni</th>
                    </tr>
                </thead>
                <tbody>
                    ${records.map(r => `
                        <tr>
                            <td>
                                <span class="badge bg-azure-lt">${escapeHtml(r.record_type)}</span>
                            </td>
                            <td><strong>${escapeHtml(r.name)}</strong></td>
                            <td><code>${escapeHtml(r.value)}</code></td>
                            <td><small>${r.ttl || 'default'}</small></td>
                            <td><small>${r.priority !== null && r.priority !== undefined ? r.priority : '—'}</small></td>
                            <td>
                                ${canRecords ? `
                                <div class="btn-group btn-group-sm">
                                    <button class="btn btn-ghost-primary btn-edit-record" 
                                            data-record='${JSON.stringify(r).replace(/'/g, "&#39;")}' title="Modifica">
                                        <i class="ti ti-edit"></i>
                                    </button>
                                    <button class="btn btn-ghost-danger btn-delete-record" data-id="${r.id}" title="Elimina">
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

function setupZoneDetailActions(zone, zoneId) {
    // New record
    document.getElementById('btn-new-record')?.addEventListener('click', () => {
        new bootstrap.Modal(document.getElementById('modal-new-record')).show();
        setupRecordTypeSegmented('new');
    });
    document.getElementById('btn-create-record')?.addEventListener('click', () => createRecord(zoneId));

    // Edit record
    document.querySelectorAll('.btn-edit-record').forEach(btn => {
        btn.addEventListener('click', () => {
            const record = JSON.parse(btn.dataset.record);
            showEditRecordModal(record, zoneId);
        });
    });

    // Delete record
    document.querySelectorAll('.btn-delete-record').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!await confirmDialog('Eliminare questo record?')) return;
            try {
                await apiDelete(`/modules/dns/records/${btn.dataset.id}`);
                showToast('Record eliminato e zona aggiornata', 'success');
                await renderZoneDetail(currentContainer, zoneId);
            } catch (err) { showToast(err.message, 'error'); }
        });
    });

    // Edit zone
    document.getElementById('btn-edit-zone')?.addEventListener('click', () => {
        new bootstrap.Modal(document.getElementById('modal-edit-zone')).show();
    });
    document.getElementById('btn-save-zone')?.addEventListener('click', () => saveZone(zoneId));

    // Delete zone
    document.getElementById('btn-delete-zone')?.addEventListener('click', async () => {
        if (!await confirmDialog('Eliminare questa zona?', 'Tutti i record saranno eliminati.')) return;
        try {
            await apiDelete(`/modules/dns/zones/${zoneId}`);
            showToast('Zona eliminata', 'success');
            window.location.hash = '#dns';
        } catch (err) { showToast(err.message, 'error'); }
    });
}

async function createRecord(zoneId) {
    const recordType = document.getElementById('new-record-type')?.value;
    const name = document.getElementById('new-record-name')?.value.trim();
    const value = document.getElementById('new-record-value')?.value.trim();
    const ttl = document.getElementById('new-record-ttl')?.value.trim();
    const priority = document.getElementById('new-record-priority')?.value.trim();
    const weight = document.getElementById('new-record-weight')?.value.trim();
    const port = document.getElementById('new-record-port')?.value.trim();

    if (!name || !value) {
        showToast('Nome e valore sono obbligatori', 'error');
        return;
    }

    const data = { record_type: recordType, name, value };
    if (ttl) data.ttl = parseInt(ttl);
    if (priority) data.priority = parseInt(priority);
    if (weight) data.weight = parseInt(weight);
    if (port) data.port = parseInt(port);

    try {
        const result = await apiPost(`/modules/dns/zones/${zoneId}/records`, data);
        if (result.applied) {
            showToast('Record creato e zona validata con successo', 'success');
        } else {
            showToast(`Record creato — attenzione: ${result.apply_message}`, 'warning');
        }
        bootstrap.Modal.getInstance(document.getElementById('modal-new-record'))?.hide();
        await renderZoneDetail(currentContainer, zoneId);
    } catch (err) { showToast(err.message, 'error'); }
}

async function saveZone(zoneId) {
    const data = {};
    const desc = document.getElementById('edit-zone-desc')?.value.trim();
    const ttl = document.getElementById('edit-zone-ttl')?.value;
    const enabled = document.getElementById('edit-zone-enabled')?.checked;

    data.description = desc;
    if (ttl) data.ttl_default = parseInt(ttl);
    data.enabled = enabled;

    try {
        const result = await apiPatch(`/modules/dns/zones/${zoneId}`, data);
        if (result.applied) {
            showToast('Zona aggiornata e configurazione applicata', 'success');
        } else {
            showToast(`Zona aggiornata — errore applicazione: ${result.apply_message}`, 'warning');
        }
        bootstrap.Modal.getInstance(document.getElementById('modal-edit-zone'))?.hide();
        await renderZoneDetail(currentContainer, zoneId);
    } catch (err) { showToast(err.message, 'error'); }
}

// ============================================================
//  RECORD TYPE SEGMENTED CONTROL & HELPERS
// ============================================================

const VALUE_HINTS = {
    A: { placeholder: '192.168.1.1', hint: 'Indirizzo IPv4' },
    AAAA: { placeholder: '2001:db8::1', hint: 'Indirizzo IPv6' },
    CNAME: { placeholder: 'target.example.com.', hint: 'Hostname canonico (con punto finale)' },
    MX: { placeholder: 'mail.example.com.', hint: 'Mail server (con punto finale)' },
    TXT: { placeholder: 'v=spf1 include:...', hint: 'Testo libero (SPF, DKIM, verifica…)' },
    SRV: { placeholder: 'target.example.com.', hint: 'Host del servizio (con punto finale)' },
    NS: { placeholder: 'ns1.example.com.', hint: 'Name server (con punto finale)' },
    PTR: { placeholder: 'host.example.com.', hint: 'Hostname per reverse lookup' },
};

function setupRecordTypeSegmented(prefix) {
    const nav = document.getElementById(`${prefix}-record-type-nav`);
    const hiddenInput = document.getElementById(`${prefix}-record-type`);
    const valueInput = document.getElementById(`${prefix}-record-value`);
    const valueHint = document.getElementById(`${prefix}-record-value-hint`);
    const priorityRow = document.getElementById(`${prefix}-record-priority-row`);
    const srvRow = document.getElementById(`${prefix}-record-srv-row`);

    if (!nav) return;

    function updateFieldsForType(type) {
        // Update hidden input
        hiddenInput.value = type;

        // Update value placeholder and hint
        const info = VALUE_HINTS[type] || { placeholder: '', hint: '' };
        if (valueInput) valueInput.placeholder = info.placeholder;
        if (valueHint) valueHint.textContent = info.hint;

        // Show/hide priority
        if (priorityRow) priorityRow.style.display = ['MX', 'SRV'].includes(type) ? '' : 'none';
        // Show/hide SRV fields
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

    // Apply initial state
    updateFieldsForType(hiddenInput.value);
}

function showEditRecordModal(record, zoneId) {
    // Populate fields
    document.getElementById('edit-record-id').value = record.id;
    document.getElementById('edit-record-name').value = record.name;
    document.getElementById('edit-record-value').value = record.value;
    document.getElementById('edit-record-type').value = record.record_type;
    document.getElementById('edit-record-ttl').value = record.ttl || '';
    document.getElementById('edit-record-priority').value = record.priority ?? 10;
    document.getElementById('edit-record-weight').value = record.weight ?? 0;
    document.getElementById('edit-record-port').value = record.port || '';

    // Activate the correct segmented tab
    const nav = document.getElementById('edit-record-type-nav');
    nav.querySelectorAll('.nav-link').forEach(l => {
        l.classList.toggle('active', l.dataset.type === record.record_type);
    });

    // Setup segmented control
    setupRecordTypeSegmented('edit');

    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('modal-edit-record'));
    modal.show();

    // Wire up save button (remove old listener to avoid duplicates)
    const saveBtn = document.getElementById('btn-save-record');
    const newBtn = saveBtn.cloneNode(true);
    saveBtn.parentNode.replaceChild(newBtn, saveBtn);
    newBtn.addEventListener('click', () => editRecord(zoneId));
}

async function editRecord(zoneId) {
    const id = document.getElementById('edit-record-id')?.value;
    const recordType = document.getElementById('edit-record-type')?.value;
    const name = document.getElementById('edit-record-name')?.value.trim();
    const value = document.getElementById('edit-record-value')?.value.trim();
    const ttl = document.getElementById('edit-record-ttl')?.value.trim();
    const priority = document.getElementById('edit-record-priority')?.value.trim();
    const weight = document.getElementById('edit-record-weight')?.value.trim();
    const port = document.getElementById('edit-record-port')?.value.trim();

    if (!name || !value) {
        showToast('Nome e valore sono obbligatori', 'error');
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
        if (result.applied) {
            showToast('Record aggiornato e zona validata', 'success');
        } else {
            showToast(`Record aggiornato — attenzione: ${result.apply_message}`, 'warning');
        }
        bootstrap.Modal.getInstance(document.getElementById('modal-edit-record'))?.hide();
        await renderZoneDetail(currentContainer, zoneId);
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
                        <h5 class="modal-title">Nuova Zona DNS</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">Nome Zona</label>
                            <input type="text" class="form-control" id="new-zone-name" placeholder="es. lab.local">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Tipo</label>
                            <select class="form-select" id="new-zone-type">
                                <option value="master">Master — gestisci i record manualmente</option>
                                <option value="forward">Forward — inoltra a un DNS remoto</option>
                                <option value="stub">Stub — delega a un DNS remoto</option>
                            </select>
                        </div>
                        <div class="mb-3" id="new-zone-fwd-group" style="display:none;">
                            <label class="form-label">Server DNS remoti</label>
                            <input type="text" class="form-control" id="new-zone-fwd-servers" placeholder="10.0.0.1, 10.0.0.2">
                            <small class="form-hint">IP separati da virgola</small>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Descrizione (opzionale)</label>
                            <input type="text" class="form-control" id="new-zone-desc" placeholder="es. Zona interna laboratorio">
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">Annulla</button>
                        <button class="btn btn-primary" id="btn-create-zone">
                            <i class="ti ti-check me-1"></i>Crea Zona
                        </button>
                    </div>
                </div>
            </div>
        </div>
        <script>
            document.addEventListener('change', (e) => {
                if (e.target.id === 'new-zone-type') {
                    const fwdGroup = document.getElementById('new-zone-fwd-group');
                    if (fwdGroup) fwdGroup.style.display = e.target.value !== 'master' ? '' : 'none';
                }
            });
        </script>`;
}

function renderNewForwarderModal() {
    return `
        <div class="modal fade" id="modal-new-fwd" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Nuovo Forwarder Condizionale</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">Dominio</label>
                            <input type="text" class="form-control" id="new-fwd-domain" placeholder="es. corp.internal">
                            <small class="form-hint">Le query per questo dominio saranno instradate ai server specificati</small>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Server DNS</label>
                            <input type="text" class="form-control" id="new-fwd-servers" placeholder="10.0.0.1, 10.0.0.2">
                            <small class="form-hint">IP separati da virgola</small>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Descrizione (opzionale)</label>
                            <input type="text" class="form-control" id="new-fwd-desc" placeholder="es. DNS aziendale">
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">Annulla</button>
                        <button class="btn btn-primary" id="btn-create-fwd">
                            <i class="ti ti-check me-1"></i>Crea Forwarder
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
                        <h5 class="modal-title"><i class="ti ti-plus me-2"></i>Nuovo Record — ${escapeHtml(zone.name)}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <!-- Record Type Segmented Control -->
                        <div class="mb-4">
                            <label class="form-label">Tipo Record</label>
                            <nav class="nav nav-segmented nav-8" role="tablist" id="new-record-type-nav">
                                ${RECORD_TYPES.map((t, i) => `
                                    <button class="nav-link ${i === 0 ? 'active' : ''}" role="tab" data-bs-toggle="tab"
                                            data-type="${t}" aria-selected="${i === 0}" ${i !== 0 ? 'tabindex="-1"' : ''}>${t}</button>
                                `).join('')}
                            </nav>
                            <input type="hidden" id="new-record-type" value="A">
                        </div>
                        <!-- Name + Value -->
                        <div class="row">
                            <div class="col-md-5 mb-3">
                                <label class="form-label">Nome</label>
                                <div class="input-group">
                                    <input type="text" class="form-control" id="new-record-name" placeholder="@">
                                    <span class="input-group-text">.${escapeHtml(zone.name)}</span>
                                </div>
                                <small class="form-hint">Usa <code>@</code> per la zona root, <code>www</code>, <code>mail</code>, ecc.</small>
                            </div>
                            <div class="col-md-7 mb-3">
                                <label class="form-label">Valore</label>
                                <input type="text" class="form-control" id="new-record-value" placeholder="192.168.1.1">
                                <small class="form-hint" id="new-record-value-hint">Indirizzo IPv4</small>
                            </div>
                        </div>
                        <!-- TTL -->
                        <div class="row">
                            <div class="col-md-4 mb-3">
                                <label class="form-label">TTL <span class="text-muted">(opzionale)</span></label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="new-record-ttl" placeholder="${zone.ttl_default}">
                                    <span class="input-group-text">sec</span>
                                </div>
                            </div>
                            <!-- Priority (MX/SRV) -->
                            <div class="col-md-4 mb-3" id="new-record-priority-row" style="display:none;">
                                <label class="form-label">Priorità</label>
                                <input type="number" class="form-control" id="new-record-priority" value="10">
                            </div>
                        </div>
                        <!-- SRV extra fields -->
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
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">Annulla</button>
                        <button class="btn btn-primary" id="btn-create-record">
                            <i class="ti ti-check me-1"></i>Crea Record
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
                        <h5 class="modal-title"><i class="ti ti-edit me-2"></i>Modifica Record</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <input type="hidden" id="edit-record-id">
                        <!-- Record Type Segmented Control -->
                        <div class="mb-4">
                            <label class="form-label">Tipo Record</label>
                            <nav class="nav nav-segmented nav-8" role="tablist" id="edit-record-type-nav">
                                ${RECORD_TYPES.map(t => `
                                    <button class="nav-link" role="tab" data-bs-toggle="tab"
                                            data-type="${t}" aria-selected="false" tabindex="-1">${t}</button>
                                `).join('')}
                            </nav>
                            <input type="hidden" id="edit-record-type" value="A">
                        </div>
                        <!-- Name + Value -->
                        <div class="row">
                            <div class="col-md-5 mb-3">
                                <label class="form-label">Nome</label>
                                <input type="text" class="form-control" id="edit-record-name" placeholder="@">
                            </div>
                            <div class="col-md-7 mb-3">
                                <label class="form-label">Valore</label>
                                <input type="text" class="form-control" id="edit-record-value">
                                <small class="form-hint" id="edit-record-value-hint"></small>
                            </div>
                        </div>
                        <!-- TTL -->
                        <div class="row">
                            <div class="col-md-4 mb-3">
                                <label class="form-label">TTL <span class="text-muted">(opzionale)</span></label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="edit-record-ttl">
                                    <span class="input-group-text">sec</span>
                                </div>
                            </div>
                            <div class="col-md-4 mb-3" id="edit-record-priority-row" style="display:none;">
                                <label class="form-label">Priorità</label>
                                <input type="number" class="form-control" id="edit-record-priority" value="10">
                            </div>
                        </div>
                        <!-- SRV extra fields -->
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
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">Annulla</button>
                        <button class="btn btn-primary" id="btn-save-record">
                            <i class="ti ti-check me-1"></i>Salva Record
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
                        <h5 class="modal-title"><i class="ti ti-edit me-2"></i>Modifica Zona</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">Descrizione</label>
                            <input type="text" class="form-control" id="edit-zone-desc" value="${escapeHtml(zone.description || '')}">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">TTL Default (secondi)</label>
                            <input type="number" class="form-control" id="edit-zone-ttl" value="${zone.ttl_default}">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Stato</label>
                            <div class="form-check form-switch">
                                <input class="form-check-input" type="checkbox" id="edit-zone-enabled" ${zone.enabled ? 'checked' : ''}>
                                <label class="form-check-label">Abilitata</label>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-outline-secondary" data-bs-dismiss="modal">Annulla</button>
                        <button class="btn btn-primary" id="btn-save-zone">
                            <i class="ti ti-check me-1"></i>Salva
                        </button>
                    </div>
                </div>
            </div>
        </div>`;
}

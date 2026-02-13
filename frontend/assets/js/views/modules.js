/**
 * MADMIN - Modules View
 * 
 * Manages installed modules, ZIP upload, staging installation, and Store.
 */

import { apiGet, apiPost, apiDelete, apiPatch, apiPut } from '../api.js';
import { showToast, confirmDialog, formatDate, emptyState, escapeHtml, statusBadge } from '../utils.js';
import { checkPermission } from '../app.js';

/**
 * Render icon - supports both Tabler icon names and custom URLs (SVG/PNG)
 * @param {string} icon - Tabler icon name or URL
 * @param {string} className - Additional CSS classes
 * @returns {string} HTML for the icon
 */
function renderIcon(icon, className = '') {
    if (!icon) return `<i class="ti ti-puzzle ${className}"></i>`;
    if (icon.startsWith('http://') || icon.startsWith('https://')) {
        return `<img src="${icon}" alt="icon" class="module-icon ${className}" style="width: 24px; height: 24px;">`;
    }
    return `<i class="ti ti-${icon} ${className}"></i>`;
}

let modules = [];
let stagingModules = [];
let storeModules = [];
let moduleChains = [];
let availableUpdates = {};  // Map of module_id -> update info

export async function render(container) {
    const canManage = checkPermission('modules.manage');

    container.innerHTML = `
        <div class="card">
            <div class="card-header">
                <ul class="nav nav-tabs card-header-tabs" data-bs-toggle="tabs">
                    <li class="nav-item">
                        <a href="#tab-installed" class="nav-link active" data-bs-toggle="tab">
                            <i class="ti ti-package me-1"></i>Installati
                            <span class="badge bg-green ms-1" id="updates-badge" style="display:none;">0</span>
                        </a>
                    </li>
                    <li class="nav-item">
                        <a href="#tab-store" class="nav-link" data-bs-toggle="tab">
                            <i class="ti ti-building-store me-1"></i>Store
                        </a>
                    </li>
                    ${canManage ? `
                    <li class="nav-item">
                        <a href="#tab-upload" class="nav-link" data-bs-toggle="tab">
                            <i class="ti ti-upload me-1"></i>Carica ZIP
                        </a>
                    </li>
                    <li class="nav-item">
                        <a href="#tab-staging" class="nav-link" data-bs-toggle="tab">
                            <i class="ti ti-folder me-1"></i>Staging
                            <span class="badge bg-blue ms-1" id="staging-badge" style="display:none;">0</span>
                        </a>
                    </li>
                    ` : ''}
                </ul>
                ${canManage ? `
                <div class="card-actions">
                    <button class="btn btn-outline-primary btn-sm" id="btn-check-updates">
                        <i class="ti ti-refresh me-1"></i>Verifica Aggiornamenti
                    </button>
                </div>
                ` : ''}
            </div>
            <div class="card-body">
                <div class="tab-content">
                    <div class="tab-pane active show" id="tab-installed">
                        <div id="installed-container">
                            <div class="text-center py-4">
                                <div class="spinner-border spinner-border-sm"></div>
                            </div>
                        </div>
                        <div id="firewall-priority-section" class="mt-4"></div>
                    </div>
                    <div class="tab-pane" id="tab-store">
                        <div id="store-container">
                            <div class="text-center py-4">
                                <div class="spinner-border spinner-border-sm"></div>
                                <p class="text-muted mt-2">Caricamento store...</p>
                            </div>
                        </div>
                    </div>
                    ${canManage ? `
                    <div class="tab-pane" id="tab-upload">
                        <div class="upload-area text-center py-5 border border-dashed rounded" id="upload-area">
                            <i class="ti ti-cloud-upload text-muted" style="font-size: 4rem;"></i>
                            <h4 class="mt-3">Carica Modulo</h4>
                            <p class="text-muted">Trascina un file .zip o clicca per selezionare</p>
                            <input type="file" id="module-file-input" class="d-none" accept=".zip">
                            <button class="btn btn-primary" id="btn-select-file">
                                <i class="ti ti-file-plus me-1"></i>Seleziona File
                            </button>
                        </div>
                        <div id="upload-progress" class="d-none mt-3">
                            <div class="progress">
                                <div class="progress-bar progress-bar-striped progress-bar-animated" style="width: 100%"></div>
                            </div>
                            <p class="text-center mt-2">Caricamento in corso...</p>
                        </div>
                        <div id="upload-result" class="d-none mt-3"></div>
                    </div>
                    <div class="tab-pane" id="tab-staging">
                        <div id="staging-container">
                            <div class="text-center py-4">
                                <div class="spinner-border spinner-border-sm"></div>
                            </div>
                        </div>
                    </div>
                    ` : ''}
                </div>
            </div>
        </div>
    `;

    setupEventListeners();
    await loadModules();
    await checkForUpdates();  // Check updates on load
    loadStoreModules(); // Load async without await
    if (canManage) {
        await loadStagingModules();
        await loadModuleChains();
    }
}

function setupEventListeners() {
    // File upload handlers
    const uploadArea = document.getElementById('upload-area');
    const fileInput = document.getElementById('module-file-input');
    const selectBtn = document.getElementById('btn-select-file');

    if (selectBtn) {
        selectBtn.addEventListener('click', () => fileInput?.click());
    }

    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                uploadModuleFile(e.target.files[0]);
            }
        });
    }

    if (uploadArea) {
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('border-primary');
        });

        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('border-primary');
        });

        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('border-primary');
            if (e.dataTransfer.files.length > 0) {
                uploadModuleFile(e.dataTransfer.files[0]);
            }
        });
    }

    // Check updates button
    const checkUpdatesBtn = document.getElementById('btn-check-updates');
    if (checkUpdatesBtn) {
        checkUpdatesBtn.addEventListener('click', async () => {
            checkUpdatesBtn.disabled = true;
            checkUpdatesBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Verifica...';
            await checkForUpdates(true);  // Force refresh to bypass cache
            checkUpdatesBtn.disabled = false;
            checkUpdatesBtn.innerHTML = '<i class="ti ti-refresh me-1"></i>Verifica Aggiornamenti';

            const count = Object.keys(availableUpdates).length;
            if (count > 0) {
                showToast(`${count} aggiornamento/i disponibile/i`, 'info');
            } else {
                showToast('Nessun aggiornamento disponibile', 'success');
            }
        });
    }
}

async function loadModules() {
    try {
        modules = await apiGet('/modules/');
        renderModules();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function checkForUpdates(forceRefresh = false) {
    try {
        const url = forceRefresh ? '/modules/store/updates?refresh=true' : '/modules/store/updates';
        const response = await apiGet(url);
        availableUpdates = {};

        if (response.updates && response.updates.length > 0) {
            response.updates.forEach(u => {
                availableUpdates[u.id] = u;
            });

            // Update badge
            const badge = document.getElementById('updates-badge');
            if (badge) {
                badge.textContent = response.updates.length;
                badge.style.display = 'inline';
            }

            // Re-render to show update buttons
            renderModules();
        } else {
            // No updates - hide badge
            const badge = document.getElementById('updates-badge');
            if (badge) {
                badge.style.display = 'none';
            }
        }
    } catch (e) {
        console.error('Failed to check for updates:', e);
    }
}

async function loadModuleChains() {
    try {
        moduleChains = await apiGet('/firewall/chains');
        renderFirewallPriority();
    } catch (e) {
        console.error('Failed to load module chains:', e);
    }
}

async function loadStoreModules(forceRefresh = false) {
    const container = document.getElementById('store-container');
    if (!container) return;

    try {
        const url = forceRefresh ? '/modules/store/available?refresh=true' : '/modules/store/available';
        const response = await apiGet(url);
        storeModules = response.modules || [];
        renderStore();
    } catch (e) {
        container.innerHTML = `
            <div class="alert alert-warning">
                <i class="ti ti-alert-circle me-2"></i>
                Impossibile caricare lo store: ${escapeHtml(e.message)}
            </div>
        `;
    }
}

/**
 * Unified module update function - used by both Installed and Store tabs
 * @param {string} moduleId 
 * @param {object} updateInfo - {current_version, available_version, changelog}
 * @returns {Promise<boolean>} - true if update was initiated
 */
async function updateModule(moduleId, updateInfo) {
    const newVersion = updateInfo.available_version || updateInfo.version;
    const currentVersion = updateInfo.current_version || updateInfo.installed_version;

    // Build changelog HTML if available
    let changelogHtml = '';
    if (updateInfo.changelog && Object.keys(updateInfo.changelog).length > 0) {
        changelogHtml = `
            <div class="mt-2">
                <strong>Changelog:</strong>
                <ul class="mb-0 mt-1">
                    ${Object.entries(updateInfo.changelog).slice(0, 3).map(([v, desc]) =>
            `<li><code>${escapeHtml(v)}</code>: ${escapeHtml(desc)}</li>`
        ).join('')}
                </ul>
            </div>`;
    }

    const message = `
        <p>Aggiornare <strong>${escapeHtml(moduleId)}</strong> alla versione <span class="badge bg-green">${escapeHtml(newVersion)}</span>?</p>
        ${currentVersion ? `<p>Versione attuale: <span class="badge bg-secondary">${escapeHtml(currentVersion)}</span></p>` : ''}
        ${changelogHtml}
        <div class="alert alert-info mt-2">
            <i class="ti ti-info-circle me-1"></i>
            I dati esterni (es. configurazioni WireGuard) saranno preservati.
        </div>
        <p class="text-warning"><i class="ti ti-refresh me-1"></i>Richiede riavvio di MADMIN</p>`;

    const confirmed = await confirmDialog(
        'Aggiorna Modulo',
        message,
        'Aggiorna',
        'btn-success',
        true  // htmlContent = true
    );

    if (!confirmed) return false;

    try {
        const result = await apiPost(`/modules/${moduleId}/update`);
        showToast(result.message || 'Modulo aggiornato!', 'success');

        // Clean up local state
        delete availableUpdates[moduleId];

        // Update badge
        const badge = document.getElementById('updates-badge');
        const count = Object.keys(availableUpdates).length;
        if (badge) {
            if (count > 0) {
                badge.textContent = count;
                badge.style.display = 'inline';
            } else {
                badge.style.display = 'none';
            }
        }

        // Refresh data
        await loadModules();
        await loadStoreModules();

        return true;
    } catch (e) {
        showToast(e.message, 'error');
        return false;
    }
}

function renderStore() {
    const container = document.getElementById('store-container');
    if (!container) return;
    const canManage = checkPermission('modules.manage');

    if (storeModules.length === 0) {
        container.innerHTML = emptyState('ti-building-store', 'Nessun modulo disponibile', 'Lo store è vuoto al momento.');
        return;
    }

    container.innerHTML = `
        <div class="mb-3">
            <div class="row align-items-center">
                <div class="col">
                    <span class="text-muted">${storeModules.length} moduli disponibili</span>
                </div>
                <div class="col-auto">
                    <button class="btn btn-ghost-primary btn-sm" id="btn-refresh-store">
                        <i class="ti ti-refresh me-1"></i>Aggiorna
                    </button>
                </div>
            </div>
        </div>
        <div class="row">
            ${storeModules.map(m => `
                <div class="col-md-6 col-lg-4 mb-3">
                    <div class="card h-100">
                        <div class="card-body">
                            <div class="d-flex align-items-start mb-2">
                                <span class="avatar bg-azure-lt me-3">
                                    ${renderIcon(m.icon)}
                                </span>
                                <div class="flex-fill">
                                    <h4 class="card-title mb-0">${escapeHtml(m.name)}</h4>
                                    <small class="text-muted">${m.author?.name || 'Autore sconosciuto'}</small>
                                </div>
                                ${m.verified ? '<span class="badge bg-green-lt" title="Verificato"><i class="ti ti-check"></i></span>' : ''}
                            </div>
                            <p class="text-muted small mb-2" style="min-height: 40px;">
                                ${escapeHtml(m.description?.substring(0, 100) || 'Nessuna descrizione')}${m.description?.length > 100 ? '...' : ''}
                            </p>
                            <div class="mb-2">
                                ${(m.tags || []).slice(0, 3).map(t => `<span class="badge bg-azure-lt me-1">${escapeHtml(t)}</span>`).join('')}
                            </div>
                            <div class="d-flex align-items-center text-muted small mb-3">
                                <span class="me-3"><i class="ti ti-star me-1"></i>${m.stars || 0}</span>
                                <span><i class="ti ti-download me-1"></i>${m.downloads || 0}</span>
                                <span class="ms-auto badge bg-azure-lt">v${m.version || '0.0.0'}</span>
                            </div>
                        </div>
                        <div class="card-footer">
                            ${renderStoreButton(m, canManage)}
                        </div>
                    </div>
                </div>
            `).join('')}
        </div>
    `;

    // Refresh button - forces cache bypass
    document.getElementById('btn-refresh-store')?.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Aggiornamento...';
        try {
            await loadStoreModules(true);  // force refresh
            showToast('Dati store aggiornati dal cloud', 'success');
        } catch (e) {
            showToast('Errore aggiornamento store', 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    });

    // Install buttons
    container.querySelectorAll('.btn-store-install').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            const originalHtml = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

            try {
                await apiPost('/modules/store/install', { module_id: id });
                showToast('Modulo scaricato! Vai su Staging per installarlo.', 'success');
                await loadStoreModules();
                await loadStagingModules();
                // Switch to staging tab
                document.querySelector('[href="#tab-staging"]')?.click();
            } catch (e) {
                showToast(e.message, 'error');
                btn.disabled = false;
                btn.innerHTML = originalHtml;
            }
        });
    });

    // Store update buttons - use unified updateModule function
    container.querySelectorAll('.btn-store-update').forEach(btn => {
        btn.addEventListener('click', async () => {
            const moduleId = btn.dataset.id;
            const newVersion = btn.dataset.version;
            const originalHtml = btn.innerHTML;

            // Find full module info from storeModules or create minimal info
            const storeModule = storeModules.find(m => m.id === moduleId);
            const updateInfo = {
                available_version: newVersion,
                current_version: storeModule?.installed_version,
                changelog: storeModule?.changelog || {}
            };

            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

            const success = await updateModule(moduleId, updateInfo);

            if (!success) {
                btn.disabled = false;
                btn.innerHTML = originalHtml;
            }
        });
    });
}

function renderStoreButton(module, canManage) {
    const status = module.install_status;

    switch (status) {
        case 'installed':
            return `<span class="btn btn-success w-100 disabled">
                <i class="ti ti-check me-1"></i>Installato
            </span>`;
        case 'update_available':
            return canManage
                ? `<button class="btn btn-warning w-100 btn-store-update" data-id="${module.id}" data-version="${module.version}">
                    <i class="ti ti-refresh me-1"></i>Aggiorna a v${module.version}
                </button>`
                : `<span class="btn btn-outline-warning w-100 disabled">Aggiornamento disponibile</span>`;
        case 'in_staging':
            return `<span class="btn btn-outline-secondary w-100 disabled">
                <i class="ti ti-folder me-1"></i>In Staging
            </span>`;
        default:
            return canManage
                ? `<button class="btn btn-primary w-100 btn-store-install" data-id="${module.id}">
                    <i class="ti ti-download me-1"></i>Scarica
                </button>`
                : `<span class="btn btn-outline-primary w-100 disabled">Disponibile</span>`;
    }
}

async function loadStagingModules() {
    try {
        stagingModules = await apiGet('/modules/staging');
        renderStagingModules();

        // Update badge
        const badge = document.getElementById('staging-badge');
        if (badge) {
            if (stagingModules.length > 0) {
                badge.textContent = stagingModules.length;
                badge.style.display = 'inline';
            } else {
                badge.style.display = 'none';
            }
        }
    } catch (e) {
        console.error('Failed to load staging modules:', e);
    }
}

function renderModules() {
    const container = document.getElementById('installed-container');
    const canManage = checkPermission('modules.manage');

    if (modules.length === 0) {
        container.innerHTML = emptyState('ti-puzzle', 'Nessun modulo installato', canManage ? 'Carica un modulo dalla tab "Carica ZIP"' : '');
        return;
    }

    container.innerHTML = `
        <div class="table-responsive">
            <table class="table table-vcenter">
                <thead>
                    <tr>
                        <th>Modulo</th>
                        <th>Versione</th>
                        <th>Autore</th>
                        <th>Stato</th>
                        <th>Installato</th>
                        ${canManage ? '<th class="w-1"></th>' : ''}
                    </tr>
                </thead>
                <tbody>
                    ${modules.map(m => `
                        <tr>
                            <td>
                                <div class="font-weight-medium">${escapeHtml(m.name)}</div>
                                <small class="text-muted">${m.id}</small>
                            </td>
                            <td><span class="badge bg-azure-lt">${m.version}</span></td>
                            <td>${m.author ? escapeHtml(m.author) : '-'}</td>
                            <td>${statusBadge(m.enabled)}</td>
                            <td>${formatDate(m.installed_at)}</td>
                            ${canManage ? `
                            <td>
                                <div class="btn-group btn-group-sm">
                                    ${availableUpdates[m.id] ? `
                                    <button class="btn btn-success btn-update" data-id="${m.id}" title="Aggiorna a ${availableUpdates[m.id].available_version}">
                                        <i class="ti ti-refresh"></i>
                                    </button>` : ''}
                                    <button class="btn ${m.enabled ? 'btn-ghost-warning' : 'btn-ghost-success'} btn-toggle" 
                                            data-id="${m.id}" data-enabled="${m.enabled}">
                                        <i class="ti ti-${m.enabled ? 'player-pause' : 'player-play'}"></i>
                                    </button>
                                    <button class="btn btn-ghost-danger btn-uninstall" data-id="${m.id}">
                                        <i class="ti ti-trash"></i>
                                    </button>
                                </div>
                            </td>
                            ` : ''}
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;

    // Toggle buttons
    container.querySelectorAll('.btn-toggle').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            const enabled = btn.dataset.enabled === 'true';
            try {
                await apiPatch(`/modules/${id}/${enabled ? 'disable' : 'enable'}`);
                showToast(`Modulo ${enabled ? 'disabilitato' : 'abilitato'}. Riavvio richiesto.`, 'success');
                await loadModules();
            } catch (e) {
                showToast(e.message, 'error');
            }
        });
    });

    // Uninstall buttons
    container.querySelectorAll('.btn-uninstall').forEach(btn => {
        btn.addEventListener('click', async () => {
            const moduleId = btn.dataset.id;
            const message = `
                <p>Sei sicuro di voler disinstallare <strong>${escapeHtml(moduleId)}</strong>?</p>
                <div class="alert alert-warning">
                    <i class="ti ti-alert-triangle me-1"></i>
                    <strong>Attenzione:</strong> Verranno rimossi:
                    <ul class="mb-0 mt-1">
                        <li>File del modulo</li>
                        <li>Pacchetti apt/pip (se non usati da altri moduli)</li>
                        <li>Permessi e configurazioni</li>
                    </ul>
                </div>
                <p class="text-danger"><i class="ti ti-refresh me-1"></i>Richiede riavvio di MADMIN</p>`;

            const confirmed = await confirmDialog(
                'Disinstalla Modulo',
                message,
                'Disinstalla',
                'btn-danger',
                true  // htmlContent = true
            );
            if (confirmed) {
                try {
                    btn.disabled = true;
                    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
                    await apiDelete(`/modules/${moduleId}`);
                    showToast('Modulo disinstallato. Riavvia MADMIN per applicare.', 'success');
                    await loadModules();
                    await loadStagingModules();
                } catch (e) {
                    showToast(e.message, 'error');
                    btn.disabled = false;
                    btn.innerHTML = '<i class="ti ti-trash"></i>';
                }
            }
        });
    });

    // Update buttons - use unified updateModule function
    container.querySelectorAll('.btn-update').forEach(btn => {
        btn.addEventListener('click', async () => {
            const moduleId = btn.dataset.id;
            const updateInfo = availableUpdates[moduleId];
            if (!updateInfo) return;

            const originalHtml = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

            const success = await updateModule(moduleId, updateInfo);

            if (!success) {
                btn.disabled = false;
                btn.innerHTML = originalHtml;
            }
        });
    });
}

function renderFirewallPriority() {
    const container = document.getElementById('firewall-priority-section');
    if (!container) return;

    if (moduleChains.length === 0) {
        container.innerHTML = '';
        return;
    }

    // Group chains by table, then by parent
    const chainsStructure = {};
    moduleChains.forEach(c => {
        const table = c.table_name || 'filter';
        const parent = c.parent_chain;

        if (!chainsStructure[table]) {
            chainsStructure[table] = {};
        }
        if (!chainsStructure[table][parent]) {
            chainsStructure[table][parent] = [];
        }
        chainsStructure[table][parent].push(c);
    });

    // Sort by priority within each group
    Object.values(chainsStructure).forEach(parents => {
        Object.values(parents).forEach(chains => {
            chains.sort((a, b) => a.priority - b.priority);
        });
    });

    container.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h4 class="card-title mb-0">
                    <i class="ti ti-shield me-2"></i>Priorità Firewall Moduli
                </h4>
            </div>
            <div class="card-body">
                <p class="text-muted small mb-3">
                    L'ordine dei moduli determina la priorità delle loro regole firewall all'interno di ogni tabella e catena.
                    Trascina per riordinare. Le regole MADMIN (firewall macchina) hanno sempre priorità massima.
                </p>
                <div class="row">
                    ${Object.entries(chainsStructure).map(([table, parents]) => `
                        <div class="col-12 mb-3">
                            <h5 class="text-uppercase text-muted font-weight-bold mb-2">
                                Tabella: <span class="text-primary">${escapeHtml(table)}</span>
                            </h5>
                            <div class="row">
                                ${Object.entries(parents).map(([parent, chains]) => `
                                    <div class="col-md-6 mb-3">
                                        <label class="form-label font-monospace bg-light px-2 py-1 rounded small">
                                            ${escapeHtml(parent)}
                                        </label>
                                        <ul class="list-group" id="priority-list-${table}-${parent}" data-table="${table}" data-parent="${parent}">
                                            ${chains.map((c, idx) => `
                                                <li class="list-group-item d-flex align-items-center" 
                                                    data-chain-id="${c.id}" data-priority="${c.priority}">
                                                    <i class="ti ti-grip-vertical cursor-move text-muted me-2"></i>
                                                    <span class="badge bg-azure-lt me-2">${idx + 1}</span>
                                                    <span>${escapeHtml(c.chain_name.replace('MOD_', '').replace('_', ' '))}</span>
                                                    <small class="ms-auto text-muted font-monospace" style="font-size: 0.7rem;">${c.priority}</small>
                                                </li>
                                            `).join('')}
                                        </ul>
                                    </div>
                                `).join('')}
                            </div>
                            <hr class="my-2 border-light">
                        </div>
                    `).join('')}
                </div>
            </div>
        </div>
    `;

    // Initialize Sortable for each list
    Object.keys(chainsStructure).forEach(table => {
        Object.keys(chainsStructure[table]).forEach(parent => {
            const listId = `priority-list-${table}-${parent}`;
            const list = document.getElementById(listId);

            if (list && typeof Sortable !== 'undefined') {
                new Sortable(list, {
                    animation: 150,
                    handle: '.cursor-move',
                    onEnd: async (evt) => {
                        const items = list.querySelectorAll('li[data-chain-id]');
                        const orders = [];
                        items.forEach((item, index) => {
                            // Calculate new priority (offset by existing logic or just relative index?)
                            // Backend uses absolute priority. Let's use 10-step increments or just 1-based index + base?
                            // For simplicity, let's just use index * 10 + 10 to leave gaps, or similar.
                            // Currently backend uses int. Let's re-normalize to 10, 20, 30...
                            const newPriority = (index + 1) * 10;
                            orders.push({ id: item.dataset.chainId, priority: newPriority });

                            // Update UI badge
                            item.querySelector('.badge').textContent = index + 1;
                            // Update debug small text
                            item.querySelector('small').textContent = newPriority;
                        });

                        try {
                            await apiPut('/firewall/chains/order', orders);
                            showToast('Priorità aggiornata', 'success');
                        } catch (e) {
                            showToast(e.message, 'error');
                            await loadModuleChains();
                        }
                    }
                });
            }
        });
    });
}

function renderStagingModules() {
    const container = document.getElementById('staging-container');
    if (!container) return;

    if (stagingModules.length === 0) {
        container.innerHTML = emptyState('ti-folder-off', 'Nessun modulo in staging', 'Carica un file .zip dalla tab "Carica ZIP"');
        return;
    }

    container.innerHTML = `
        <div class="row">
            ${stagingModules.map(m => `
                <div class="col-md-6 col-lg-4 mb-3">
                    <div class="card">
                        <div class="card-body">
                            <h4 class="card-title">${escapeHtml(m.name)}</h4>
                            <p class="text-muted small">${m.description || 'Nessuna descrizione'}</p>
                            <div class="d-flex justify-content-between align-items-center">
                                <span class="badge bg-azure-lt">v${m.version}</span>
                                <div class="btn-group btn-group-sm">
                                    <button class="btn btn-primary btn-install" data-id="${m.id}">
                                        <i class="ti ti-download me-1"></i>Installa
                                    </button>
                                    <button class="btn btn-outline-danger btn-delete-staging" data-id="${m.id}" data-name="${escapeHtml(m.name)}" title="Elimina da staging">
                                        <i class="ti ti-trash"></i>
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `).join('')}
        </div>
    `;

    // Install buttons
    container.querySelectorAll('.btn-install').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            try {
                btn.disabled = true;
                btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
                await apiPost('/modules/install', { source: 'staging', module_id: id });
                showToast('Modulo installato! Riavvia il servizio.', 'success');
                await loadModules();
                await loadStagingModules();
            } catch (e) {
                showToast(e.message, 'error');
                btn.disabled = false;
                btn.innerHTML = '<i class="ti ti-download me-1"></i>Installa';
            }
        });
    });

    // Delete staging buttons
    container.querySelectorAll('.btn-delete-staging').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            const name = btn.dataset.name;

            const confirmed = await confirmDialog(
                'Elimina Modulo da Staging',
                `<p>Eliminare <strong>${escapeHtml(name || id)}</strong> dalla cartella staging?</p>
                <p class="text-muted small">La cartella del modulo verrà rimossa completamente. I moduli installati non saranno influenzati.</p>`,
                'Elimina',
                'btn-danger',
                true
            );

            if (confirmed) {
                try {
                    btn.disabled = true;
                    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
                    await apiDelete(`/modules/staging/${id}`);
                    showToast('Modulo rimosso da staging', 'success');
                    await loadStagingModules();
                    await loadStoreModules();  // Refresh store to update status
                } catch (e) {
                    showToast(e.message, 'error');
                    btn.disabled = false;
                    btn.innerHTML = '<i class="ti ti-trash"></i>';
                }
            }
        });
    });
}

async function uploadModuleFile(file) {
    if (!file.name.endsWith('.zip')) {
        showToast('Il file deve essere un .zip', 'error');
        return;
    }

    const uploadProgress = document.getElementById('upload-progress');
    const uploadResult = document.getElementById('upload-result');
    const uploadArea = document.getElementById('upload-area');

    uploadArea.classList.add('d-none');
    uploadProgress.classList.remove('d-none');
    uploadResult.classList.add('d-none');

    try {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch('/api/modules/upload', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('madmin_token')}`
            },
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Upload fallito');
        }

        const result = await response.json();

        uploadProgress.classList.add('d-none');
        uploadResult.classList.remove('d-none');
        uploadResult.innerHTML = `
            <div class="alert alert-success">
                <h4><i class="ti ti-check me-2"></i>Modulo caricato!</h4>
                <p><strong>${escapeHtml(result.name)}</strong> v${result.version} è stato estratto in staging.</p>
                <button class="btn btn-primary btn-install-now" data-id="${result.id}">
                    <i class="ti ti-download me-1"></i>Installa Ora
                </button>
                <button class="btn btn-outline-secondary ms-2 btn-reset-upload">
                    Carica Altro
                </button>
            </div>
        `;

        uploadResult.querySelector('.btn-install-now')?.addEventListener('click', async (e) => {
            const btn = e.target;
            try {
                btn.disabled = true;
                await apiPost('/modules/install', { source: 'staging', module_id: result.id });
                showToast('Modulo installato! Riavvia il servizio.', 'success');
                await loadModules();
                await loadStagingModules();
                resetUploadArea();
            } catch (err) {
                showToast(err.message, 'error');
                btn.disabled = false;
            }
        });

        uploadResult.querySelector('.btn-reset-upload')?.addEventListener('click', resetUploadArea);

        await loadStagingModules();

    } catch (err) {
        uploadProgress.classList.add('d-none');
        uploadArea.classList.remove('d-none');
        showToast('Errore: ' + err.message, 'error');
    }
}

function resetUploadArea() {
    const uploadProgress = document.getElementById('upload-progress');
    const uploadResult = document.getElementById('upload-result');
    const uploadArea = document.getElementById('upload-area');
    const fileInput = document.getElementById('module-file-input');

    uploadProgress?.classList.add('d-none');
    uploadResult?.classList.add('d-none');
    uploadArea?.classList.remove('d-none');
    if (fileInput) fileInput.value = '';
}

/**
 * MADMIN - Module Management View
 * 
 * Card-based module management with enable/disable toggles and firewall chain priority.
 * All modules are pre-installed. This view manages activation and ordering.
 */

import { apiGet, apiPost, apiPut } from '../api.js';
import { showToast, escapeHtml, emptyState } from '../utils.js';
import { checkPermission } from '../app.js';

/**
 * Render icon - supports both Tabler icon names and custom URLs (SVG/PNG)
 */
function renderIcon(icon, className = '') {
    if (!icon) return `<i class="ti ti-puzzle ${className}"></i>`;
    if (icon.startsWith('http://') || icon.startsWith('https://')) {
        return `<img src="${icon}" alt="icon" class="module-icon ${className}" style="width: 24px; height: 24px;">`;
    }
    return `<i class="ti ti-${icon} ${className}"></i>`;
}

let availableModules = [];
let moduleChains = [];

export async function render(container) {
    const canManage = checkPermission('modules.manage');

    container.innerHTML = `
        <div class="page-header d-flex justify-content-between align-items-center mb-4">
            <div>
                <h2 class="page-title mb-1">
                    <i class="ti ti-puzzle me-2"></i>Gestione Moduli
                </h2>
                <p class="text-muted mb-0">Attiva o disattiva i moduli disponibili. Tutti i moduli sono pre-installati.</p>
            </div>
        </div>

        <div id="modules-grid" class="row mb-4">
            <div class="text-center py-4">
                <div class="spinner-border spinner-border-sm"></div>
                <p class="text-muted mt-2">Caricamento moduli...</p>
            </div>
        </div>

        <div id="firewall-priority-section"></div>
    `;

    await loadModules();
    await loadModuleChains();
}

async function loadModules() {
    try {
        availableModules = await apiGet('/modules/available');
        renderModuleCards();
    } catch (e) {
        document.getElementById('modules-grid').innerHTML =
            emptyState('ti-alert-circle', 'Errore caricamento moduli', e.message);
    }
}

async function loadModuleChains() {
    try {
        moduleChains = await apiGet('/modules/chains/priority');
        renderFirewallPriority();
    } catch (e) {
        console.error('Failed to load chains:', e);
    }
}

function renderModuleCards() {
    const container = document.getElementById('modules-grid');
    if (!container) return;
    const canManage = checkPermission('modules.manage');

    if (availableModules.length === 0) {
        container.innerHTML = `<div class="col-12">${emptyState('ti-puzzle-off', 'Nessun modulo disponibile', 'Nessun modulo trovato nella directory dei moduli.')}</div>`;
        return;
    }

    container.innerHTML = availableModules.map(m => `
        <div class="col-md-6 col-lg-4 mb-3">
            <div class="card ${m.enabled ? 'border-primary' : ''}" id="module-card-${m.id}">
                <div class="card-body">
                    <div class="d-flex align-items-start justify-content-between mb-3">
                        <div class="d-flex align-items-center">
                            <span class="avatar avatar-sm bg-primary-lt me-3">
                                ${renderIcon(m.icon)}
                            </span>
                            <div>
                                <h4 class="card-title mb-0">${escapeHtml(m.name)}</h4>
                                <small class="text-muted">v${escapeHtml(m.version)}</small>
                            </div>
                        </div>
                        ${getStatusBadge(m)}
                    </div>
                    
                    <p class="text-muted small mb-3">${escapeHtml(m.description || 'Nessuna descrizione')}</p>
                    
                    <div class="d-flex align-items-center justify-content-between">
                        <div class="text-muted small">
                            ${m.firewall_chains > 0 ? `<i class="ti ti-shield me-1"></i>${m.firewall_chains} chain` : ''}
                            ${m.permissions.length > 0 ? `<i class="ti ti-lock ms-2 me-1"></i>${m.permissions.length} permessi` : ''}
                        </div>
                        ${canManage ? `
                            <div class="form-check form-switch">
                                <input class="form-check-input" type="checkbox" 
                                    id="toggle-${m.id}" 
                                    ${m.enabled ? 'checked' : ''}
                                    onchange="window._moduleToggle('${m.id}', this.checked)">
                                <label class="form-check-label" for="toggle-${m.id}">
                                    ${m.enabled ? 'Attivo' : 'Disattivo'}
                                </label>
                            </div>
                        ` : `
                            <span class="badge ${m.enabled ? 'bg-green' : 'bg-secondary'}">${m.enabled ? 'Attivo' : 'Disattivo'}</span>
                        `}
                    </div>
                </div>
            </div>
        </div>
    `).join('');

    // Register global toggle handler
    window._moduleToggle = async (moduleId, enable) => {
        const toggle = document.getElementById(`toggle-${moduleId}`);
        const card = document.getElementById(`module-card-${moduleId}`);
        const label = toggle?.parentElement?.querySelector('label');

        try {
            toggle.disabled = true;

            if (enable) {
                const result = await apiPost(`/modules/${moduleId}/activate`);
                showToast(result.message || 'Modulo attivato', 'success');
                card?.classList.add('border-primary');
                if (label) label.textContent = 'Attivo';
            } else {
                const result = await apiPost(`/modules/${moduleId}/deactivate`);
                showToast(result.message || 'Modulo disattivato', 'success');
                card?.classList.remove('border-primary');
                if (label) label.textContent = 'Disattivo';
            }

            // Update local state
            const mod = availableModules.find(m => m.id === moduleId);
            if (mod) {
                mod.enabled = enable;
                mod.activated = true;
            }

            // Update badge
            const badgeContainer = card?.querySelector('.badge');
            if (badgeContainer) {
                updateStatusBadge(badgeContainer, { ...mod, enabled: enable, activated: true });
            }

        } catch (e) {
            showToast(e.message || 'Operazione fallita', 'error');
            toggle.checked = !enable; // Revert
        } finally {
            toggle.disabled = false;
        }
    };
}

function getStatusBadge(mod) {
    if (mod.enabled) {
        return '<span class="badge bg-green">Attivo</span>';
    } else if (mod.activated) {
        return '<span class="badge bg-yellow">Disabilitato</span>';
    } else {
        return '<span class="badge bg-secondary">Mai attivato</span>';
    }
}

function updateStatusBadge(element, mod) {
    if (mod.enabled) {
        element.className = 'badge bg-green';
        element.textContent = 'Attivo';
    } else if (mod.activated) {
        element.className = 'badge bg-yellow';
        element.textContent = 'Disabilitato';
    }
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
                    Trascina per riordinare.
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
                                                    data-chain-name="${c.chain_name}" data-priority="${c.priority}">
                                                    <i class="ti ti-grip-vertical cursor-move text-muted me-2"></i>
                                                    <span class="badge bg-azure-lt me-2">${idx + 1}</span>
                                                    <span>${escapeHtml(c.chain_name.replace('MOD_', '').replace(/_/g, ' '))}</span>
                                                    <small class="ms-auto text-muted font-monospace" style="font-size: 0.7rem;">${c.priority}</small>
                                                </li>
                                            `).join('')}
                                        </ul>
                                    </div>
                                `).join('')}
                            </div>
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
                        const items = list.querySelectorAll('li[data-chain-name]');
                        const chains = [];
                        items.forEach((item, index) => {
                            const newPriority = (index + 1) * 10;
                            chains.push({
                                chain_name: item.dataset.chainName,
                                priority: newPriority
                            });

                            // Update UI
                            item.querySelector('.badge').textContent = index + 1;
                            item.querySelector('small').textContent = newPriority;
                        });

                        try {
                            await apiPut('/modules/chains/priority', { chains });
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

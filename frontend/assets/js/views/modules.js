/**
 * MADMIN - Module Management View
 *
 * Card-based module management with detail modal, confirmation dialogs,
 * and firewall chain priority drag-and-drop.
 */

import { apiGet, apiPost, apiPut } from '../api.js';
import { showToast, escapeHtml, emptyState, confirmDialog } from '../utils.js';
import { checkPermission } from '../app.js';
import { t } from '../i18n.js';

/**
 * Render icon - supports both Tabler icon names and custom URLs (SVG/PNG)
 */
function renderIcon(icon, size = 24) {
    if (!icon) return `<i class="ti ti-puzzle" style="font-size: ${size}px;"></i>`;
    if (icon.startsWith('http://') || icon.startsWith('https://')) {
        return `<img src="${icon}" alt="icon" style="width: ${size}px; height: ${size}px;">`;
    }
    return `<i class="ti ti-${icon}" style="font-size: ${size}px;"></i>`;
}

let availableModules = [];
let moduleChains = [];

export async function render(container) {
    const canManage = checkPermission('modules.manage');

    container.innerHTML = `
        <div class="card mb-3">
            <div class="card-header">
                <h3 class="card-title"><i class="ti ti-puzzle me-2"></i>${t('modules.title')}</h3>
            </div>
            <div class="card-body">
                <div id="modules-grid" class="row g-3">
                    <div class="col-12 text-center py-4">
                        <div class="spinner-border spinner-border-sm"></div>
                        <p class="text-muted mt-2">${t('modules.loadingModules')}</p>
                    </div>
                </div>
            </div>
        </div>

        <div id="firewall-priority-section"></div>

        <!-- Module Detail Modal -->
        <div class="modal modal-blur fade" id="module-detail-modal" tabindex="-1">
            <div class="modal-dialog modal-lg modal-dialog-scrollable">
                <div class="modal-content" id="module-detail-content"></div>
            </div>
        </div>
    `;

    await loadModules();
    await loadModuleChains();
}

async function loadModules() {
    try {
        availableModules = await apiGet('/modules/available');
        renderModuleCards();
        await loadCardConfigs();
    } catch (e) {
        document.getElementById('modules-grid').innerHTML =
            `<div class="col-12">${emptyState('ti-alert-circle', t('modules.errorLoadingModules'), e.message)}</div>`;
    }
}

async function loadCardConfigs() {
    for (const m of availableModules) {
        if (!m.enabled || !m.card_config_view) continue;
        const el = document.getElementById(`card-config-${m.id}`);
        if (!el) continue;
        try {
            const mod = await import(m.card_config_view);
            await mod.render(el, m.id);
        } catch (e) {
            console.error(`card_config_view load failed for ${m.id}:`, e);
            el.innerHTML = `<div class="border-top pt-1 mt-1 text-danger small">Config non disponibile</div>`;
        }
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
        container.innerHTML = `<div class="col-12">${emptyState('ti-puzzle-off', t('modules.noModules'), t('modules.noModulesHint'))}</div>`;
        return;
    }

    container.innerHTML = availableModules.map(m => {
        const statusInfo = getStatusInfo(m);
        const chainsCount = m.firewall_chains?.length || 0;
        const permsCount = m.permissions?.length || 0;

        return `
        <div class="col-md-6 col-xl-4">
            <div class="card card-sm h-100 module-card ${m.enabled ? 'border-primary border-2' : ''}"
                 id="module-card-${m.id}" style="cursor: pointer;"
                 onclick="window._openModuleDetail('${m.id}')">
                <div class="card-body">
                    <div class="d-flex align-items-start mb-3">
                        <span class="avatar ${m.enabled ? 'bg-primary' : 'bg-secondary-lt'} me-3" style="min-width: 42px;">
                            ${renderIcon(m.icon, 20)}
                        </span>
                        <div class="flex-fill min-width-0">
                            <div class="d-flex align-items-center justify-content-between">
                                <h3 class="card-title mb-0 text-truncate">${escapeHtml(m.name)}</h3>
                                <div class="d-flex gap-1 ms-2">
                                    ${m.default_enabled ? `<span class="badge bg-teal-lt" title="Modulo consigliato, attivo di default"><i class="ti ti-star-filled me-1"></i>Raccomandato</span>` : ''}
                                    <span class="badge ${statusInfo.class}">${statusInfo.label}</span>
                                </div>
                            </div>
                            <div class="text-muted small mt-1">v${escapeHtml(m.version)} ${m.author ? '· ' + escapeHtml(m.author) : ''}</div>
                        </div>
                    </div>

                    <p class="text-secondary small mb-3" style="min-height: 2.5em;">${escapeHtml(m.description || t('modules.noDescription'))}</p>

                    <div class="d-flex align-items-center justify-content-between">
                        <div class="d-flex gap-3">
                            ${chainsCount > 0 ? `
                                <span class="d-inline-flex align-items-center text-muted small" title="${t('modules.firewallChains')}">
                                    <i class="ti ti-shield me-1" style="font-size: 14px;"></i>${chainsCount}
                                </span>
                            ` : ''}
                            ${permsCount > 0 ? `
                                <span class="d-inline-flex align-items-center text-muted small" title="${t('modules.permissionsLabel')}">
                                    <i class="ti ti-lock me-1" style="font-size: 14px;"></i>${permsCount}
                                </span>
                            ` : ''}
                            ${m.has_readme ? `
                                <span class="d-inline-flex align-items-center text-muted small" title="${t('modules.docTab')}">
                                    <i class="ti ti-file-text me-1" style="font-size: 14px;"></i>Docs
                                </span>
                            ` : ''}
                        </div>
                        ${canManage ? getActionButton(m) : ''}
                    </div>

                    ${m.enabled && m.card_config_view ? `
                    <div id="card-config-${m.id}" data-agent-card-config
                         onclick="event.stopPropagation()">
                    </div>` : ''}
                </div>
            </div>
        </div>`;
    }).join('');
}

function getStatusInfo(mod) {
    if (mod.enabled) {
        return { label: t('common.active'), class: 'bg-green-lt' };
    } else {
        return { label: t('common.available'), class: 'bg-secondary-lt' };
    }
}

function getActionButton(mod) {
    if (mod.enabled) {
        return `<button class="btn btn-sm btn-outline-danger" onclick="event.stopPropagation(); window._confirmDeactivate('${mod.id}', '${escapeHtml(mod.name)}')">
            <i class="ti ti-player-stop me-1"></i>${t('modules.deactivate')}
        </button>`;
    } else {
        return `<button class="btn btn-sm btn-primary" onclick="event.stopPropagation(); window._confirmActivate('${mod.id}', '${escapeHtml(mod.name)}')">
            <i class="ti ti-player-play me-1"></i>${t('modules.activate')}
        </button>`;
    }
}

// === Confirmation Dialogs ===

window._confirmActivate = async (moduleId, moduleName) => {
    const message = t('modules.activateConfirmMsg', { name: `<strong>${moduleName}</strong>` });

    const confirmed = await confirmDialog(
        t('modules.activateConfirmTitle', { name: moduleName }),
        message,
        t('modules.activateModule'),
        'btn-primary',
        true
    );

    if (!confirmed) return;

    const btn = document.querySelector(`#module-card-${moduleId} .btn-primary`);
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<div class="spinner-border spinner-border-sm me-1"></div>${t('modules.activating')}`;
    }

    try {
        const result = await apiPost(`/modules/${moduleId}/activate`);
        showToast(result.message || t('modules.moduleActivated'), 'success');
        if (result.warnings && result.warnings.length > 0) {
            showToast(t('modules.warnings', { warnings: result.warnings.join('; ') }), 'warning');
        }
    } catch (e) {
        const detail = e?.response?.detail || e?.detail || e.message || t('modules.activationFailed');
        showToast(detail, 'error');
    } finally {
        try { await loadModules(); await loadModuleChains(); } catch (_) { }
    }
};

window._confirmDeactivate = async (moduleId, moduleName) => {
    const mod = availableModules.find(m => m.id === moduleId);
    const customWarning = mod?.disable_warning;

    const warningBody = customWarning
        ? `<div class="alert alert-danger mb-3">
               <div class="d-flex">
                   <div><i class="ti ti-alert-triangle icon me-2 text-danger"></i></div>
                   <div><h4 class="alert-title">Attenzione</h4><div>${escapeHtml(customWarning)}</div></div>
               </div>
           </div>`
        : `<div class="alert alert-warning">
               <div class="d-flex">
                   <div><i class="ti ti-alert-triangle icon me-2"></i></div>
                   <div>
                       <h4 class="alert-title">${t('modules.deactivateWarning')}</h4>
                       <div class="text-secondary">
                           ${t('modules.deactivateDetails', { name: `<strong>${moduleName}</strong>` })}
                           <ul class="mt-2 mb-0">
                               <li>${t('modules.deactivateList1')}</li>
                               <li>${t('modules.deactivateList2')}</li>
                               <li>${t('modules.deactivateList3')}</li>
                               <li>${t('modules.deactivateList4')}</li>
                           </ul>
                       </div>
                   </div>
               </div>
           </div>`;

    const confirmed = await confirmDialog(
        t('modules.deactivateConfirmTitle', { name: moduleName }),
        `${warningBody}<p class="text-muted small">${t('modules.deactivateNote')}</p>`,
        t('modules.deactivateAndRemove'),
        'btn-danger',
        true
    );

    if (!confirmed) return;

    const btn = document.querySelector(`#module-card-${moduleId} .btn-outline-danger`);
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<div class="spinner-border spinner-border-sm me-1"></div>${t('modules.deactivating')}`;
    }

    try {
        const result = await apiPost(`/modules/${moduleId}/deactivate`);
        showToast(result.message || t('modules.moduleDeactivated'), 'success');
        if (result.warnings && result.warnings.length > 0) {
            showToast(t('modules.warnings', { warnings: result.warnings.join('; ') }), 'warning');
        }
    } catch (e) {
        const detail = e?.response?.detail || e?.detail || e.message || t('modules.deactivationFailed');
        showToast(detail, 'error');
    } finally {
        try { await loadModules(); await loadModuleChains(); } catch (_) { }
    }
};

// === Module Detail Modal ===

window._openModuleDetail = async (moduleId) => {
    const mod = availableModules.find(m => m.id === moduleId);
    if (!mod) return;
    const canManage = checkPermission('modules.manage');
    const statusInfo = getStatusInfo(mod);

    // Build tabs content
    let readmeTab = '';
    if (mod.has_readme) {
        readmeTab = `
            <li class="nav-item">
                <a href="#detail-readme" class="nav-link" data-bs-toggle="tab">
                    <i class="ti ti-file-text me-1"></i>${t('modules.docTab')}
                </a>
            </li>`;
    }

    const content = document.getElementById('module-detail-content');
    content.innerHTML = `
        <div class="modal-header">
            <div class="d-flex align-items-center">
                <span class="avatar ${mod.enabled ? 'bg-primary' : 'bg-secondary-lt'} me-3">
                    ${renderIcon(mod.icon, 20)}
                </span>
                <div>
                    <h3 class="modal-title mb-0">${escapeHtml(mod.name)}</h3>
                    <div class="text-muted small">v${escapeHtml(mod.version)} ${mod.author ? '· ' + escapeHtml(mod.author) : ''}</div>
                </div>
            </div>
            <div class="d-flex align-items-center gap-2">
                <span class="badge ${statusInfo.class}">${statusInfo.label}</span>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
        </div>
        <div class="modal-body p-0">
            <ul class="nav nav-tabs nav-fill px-3 pt-3" data-bs-toggle="tabs">
                <li class="nav-item">
                    <a href="#detail-info" class="nav-link active" data-bs-toggle="tab">
                        <i class="ti ti-info-circle me-1"></i>${t('modules.infoTab')}
                    </a>
                </li>
                ${readmeTab}
            </ul>
            <div class="tab-content p-3">
                <div class="tab-pane active show" id="detail-info">
                    ${renderDetailInfoTab(mod)}
                </div>
                ${mod.has_readme ? `
                <div class="tab-pane" id="detail-readme">
                    <div class="text-center py-3" id="readme-loading">
                        <div class="spinner-border spinner-border-sm"></div>
                        <p class="text-muted mt-2">${t('modules.loadingDoc')}</p>
                    </div>
                    <div id="readme-content" class="d-none markdown-body" style="max-height: 500px; overflow-y: auto;"></div>
                </div>
                ` : ''}
            </div>
        </div>
        ${canManage ? `
        <div class="modal-footer">
            ${mod.enabled
                ? `<button class="btn btn-danger" onclick="bootstrap.Modal.getInstance(document.getElementById('module-detail-modal')).hide(); window._confirmDeactivate('${mod.id}', '${escapeHtml(mod.name)}')">
                    <i class="ti ti-player-stop me-1"></i>${t('modules.deactivateModule')}
                </button>`
                : `<button class="btn btn-primary" onclick="bootstrap.Modal.getInstance(document.getElementById('module-detail-modal')).hide(); window._confirmActivate('${mod.id}', '${escapeHtml(mod.name)}')">
                    <i class="ti ti-player-play me-1"></i>${t('modules.activateModule')}
                </button>`
            }
        </div>
        ` : ''}
    `;

    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('module-detail-modal'));
    modal.show();

    // Load README on tab switch
    if (mod.has_readme) {
        const readmeTabEl = content.querySelector('a[href="#detail-readme"]');
        if (readmeTabEl) {
            readmeTabEl.addEventListener('shown.bs.tab', async () => {
                const readmeContent = document.getElementById('readme-content');
                const readmeLoading = document.getElementById('readme-loading');
                if (readmeContent.classList.contains('d-none')) {
                    try {
                        const data = await apiGet(`/modules/${moduleId}/readme`);
                        readmeContent.innerHTML = renderMarkdown(data.content);
                        readmeContent.classList.remove('d-none');
                        readmeLoading.classList.add('d-none');
                    } catch (e) {
                        readmeLoading.innerHTML = `<p class="text-danger">${t('common.errorPrefix')}${escapeHtml(e.message)}</p>`;
                    }
                }
            });
        }
    }
};

function renderDetailInfoTab(mod) {
    const chainsCount = mod.firewall_chains?.length || 0;
    const permsCount = mod.permissions?.length || 0;
    const aptDeps = mod.system_dependencies?.apt || [];
    const pipDeps = mod.system_dependencies?.pip || [];

    return `
        <p class="text-secondary">${escapeHtml(mod.description || t('modules.noDescription'))}</p>

        <div class="row g-3 mt-2">
            ${permsCount > 0 ? `
            <div class="col-12">
                <h4 class="mb-2"><i class="ti ti-lock me-1"></i>${t('modules.permissionsLabel')} (${permsCount})</h4>
                <div class="table-responsive">
                    <table class="table table-sm table-vcenter">
                        <thead><tr><th>Slug</th><th>${t('common.description')}</th></tr></thead>
                        <tbody>
                            ${mod.permissions.map(p => `
                                <tr>
                                    <td><code>${escapeHtml(p.slug)}</code></td>
                                    <td class="text-muted">${escapeHtml(p.description)}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
            ` : ''}

            ${chainsCount > 0 ? `
            <div class="col-12">
                <h4 class="mb-2"><i class="ti ti-shield me-1"></i>${t('modules.firewallChains')} (${chainsCount})</h4>
                <div class="table-responsive">
                    <table class="table table-sm table-vcenter">
                        <thead><tr><th>Chain</th><th>Parent</th><th>${t('common.table')}</th><th>Priority</th></tr></thead>
                        <tbody>
                            ${mod.firewall_chains.map(c => `
                                <tr>
                                    <td><code>${escapeHtml(c.name)}</code></td>
                                    <td>${escapeHtml(c.parent)}</td>
                                    <td><span class="badge bg-azure-lt">${escapeHtml(c.table)}</span></td>
                                    <td>${c.priority}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
            ` : ''}

            ${(aptDeps.length > 0 || pipDeps.length > 0) ? `
            <div class="col-12">
                <h4 class="mb-2"><i class="ti ti-package me-1"></i>${t('modules.dependencies')}</h4>
                ${aptDeps.length > 0 ? `
                    <div class="mb-2">
                        <small class="text-muted text-uppercase fw-bold">APT</small>
                        <div class="mt-1">${aptDeps.map(d => `<span class="badge bg-blue-lt me-1 mb-1">${escapeHtml(d)}</span>`).join('')}</div>
                    </div>
                ` : ''}
                ${pipDeps.length > 0 ? `
                    <div>
                        <small class="text-muted text-uppercase fw-bold">PIP</small>
                        <div class="mt-1">${pipDeps.map(d => `<span class="badge bg-purple-lt me-1 mb-1">${escapeHtml(d)}</span>`).join('')}</div>
                    </div>
                ` : ''}
            </div>
            ` : ''}
        </div>
    `;
}

/** Simple markdown to HTML (headings, bold, code, links, lists) */
function renderMarkdown(md) {
    let html = escapeHtml(md);
    // Headers
    html = html.replace(/^### (.+)$/gm, '<h5>$1</h5>');
    html = html.replace(/^## (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^# (.+)$/gm, '<h3>$1</h3>');
    // Bold and italic
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Links
    html = html.replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" target="_blank">$1</a>');
    // Unordered lists
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
    // Line breaks (double newline = paragraph)
    html = html.replace(/\n\n/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');
    return `<div style="line-height: 1.7;"><p>${html}</p></div>`;
}

// === Firewall Chain Priority ===

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
        if (!chainsStructure[table]) chainsStructure[table] = {};
        if (!chainsStructure[table][parent]) chainsStructure[table][parent] = [];
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
                <h3 class="card-title mb-0">
                    <i class="ti ti-shield me-2"></i>${t('modules.firewallPriority')}
                </h3>
            </div>
            <div class="card-body">
                <p class="text-muted small mb-3">
                    ${t('modules.firewallPriorityDesc')}
                </p>
                <div class="row">
                    ${Object.entries(chainsStructure).map(([table, parents]) => `
                        <div class="col-12 mb-3">
                            <h5 class="text-uppercase text-muted small mb-2">
                                ${t('common.table')}: <span class="text-primary fw-bold">${escapeHtml(table)}</span>
                            </h5>
                            <div class="row g-3">
                                ${Object.entries(parents).map(([parent, chains]) => `
                                    <div class="col-md-6">
                                        <label class="form-label font-monospace bg-light px-2 py-1 rounded small">
                                            ${escapeHtml(parent)}
                                        </label>
                                        <ul class="list-group" id="priority-list-${table}-${parent}">
                                            ${chains.map((c, idx) => `
                                                <li class="list-group-item d-flex align-items-center py-2"
                                                    data-chain-name="${c.chain_name}" data-priority="${c.priority}">
                                                    <i class="ti ti-grip-vertical cursor-move text-muted me-2"></i>
                                                    <span class="badge bg-azure-lt me-2">${idx + 1}</span>
                                                    <span class="small">${escapeHtml(c.chain_name.replace('MOD_', '').replace(/_/g, ' '))}</span>
                                                    <small class="ms-auto text-muted font-monospace" style="font-size: 0.65rem;">${c.priority}</small>
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

    // Initialize Sortable
    Object.keys(chainsStructure).forEach(table => {
        Object.keys(chainsStructure[table]).forEach(parent => {
            const list = document.getElementById(`priority-list-${table}-${parent}`);
            if (list && typeof Sortable !== 'undefined') {
                new Sortable(list, {
                    animation: 150,
                    handle: '.cursor-move',
                    onEnd: async () => {
                        const items = list.querySelectorAll('li[data-chain-name]');
                        const chains = [];
                        items.forEach((item, index) => {
                            const newPriority = (index + 1) * 10;
                            chains.push({ chain_name: item.dataset.chainName, priority: newPriority });
                            item.querySelector('.badge').textContent = index + 1;
                            item.querySelector('small').textContent = newPriority;
                        });
                        try {
                            await apiPut('/modules/chains/priority', { chains });
                            showToast(t('modules.priorityUpdated'), 'success');
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

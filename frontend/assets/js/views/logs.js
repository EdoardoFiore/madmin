/**
 * MADMIN - Logs View
 * 
 * Two-tab log viewer:
 * - Audit Log: structured API call log from DB (with user info)
 * - System Log: raw journalctl output
 */

import { apiGet } from '../api.js';
import { showToast, escapeHtml } from '../utils.js';

// State
let currentTab = 'audit';
let auditPage = 1;
let auditFilters = { category: 'write', user: '', method: '', search: '' };
let auditUsers = [];

/**
 * Render the logs view
 */
export async function render(container) {
    container.innerHTML = `
        <div class="row row-deck row-cards">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <ul class="nav nav-tabs card-header-tabs" id="logs-tabs">
                            <li class="nav-item">
                                <a class="nav-link active" href="#" data-tab="audit">
                                    <i class="ti ti-list-search me-1"></i>Audit Log
                                </a>
                            </li>
                            <li class="nav-item">
                                <a class="nav-link" href="#" data-tab="system">
                                    <i class="ti ti-terminal me-1"></i>System Log
                                </a>
                            </li>
                        </ul>
                    </div>
                    <div id="logs-tab-content"></div>
                </div>
            </div>
        </div>
    `;

    setupTabListeners();

    // Load initial data
    try {
        const usersData = await apiGet('/logs/audit/users');
        auditUsers = usersData.users || [];
    } catch (e) {
        auditUsers = [];
    }

    renderAuditTab();
}

/**
 * Setup tab click listeners
 */
function setupTabListeners() {
    document.getElementById('logs-tabs')?.addEventListener('click', (e) => {
        e.preventDefault();
        const tab = e.target.closest('[data-tab]');
        if (!tab) return;

        // Update active tab
        document.querySelectorAll('#logs-tabs .nav-link').forEach(l => l.classList.remove('active'));
        tab.classList.add('active');

        currentTab = tab.dataset.tab;
        if (currentTab === 'audit') {
            renderAuditTab();
        } else {
            renderSystemTab();
        }
    });
}

// ==========================================
//  AUDIT LOG TAB
// ==========================================

async function renderAuditTab() {
    const content = document.getElementById('logs-tab-content');
    if (!content) return;

    content.innerHTML = `
        <div class="card-body border-bottom py-3">
            <div class="row g-2 align-items-end">
                <div class="col-md-3">
                    <label class="form-label small mb-1">Ricerca path</label>
                    <input type="text" class="form-control form-control-sm" id="audit-search" 
                           placeholder="es. /api/firewall" value="${escapeHtml(auditFilters.search)}">
                </div>
                <div class="col-md-2">
                    <label class="form-label small mb-1">Utente</label>
                    <select class="form-select form-select-sm" id="audit-user-filter">
                        <option value="">Tutti</option>
                        ${auditUsers.map(u => `<option value="${escapeHtml(u)}" ${auditFilters.user === u ? 'selected' : ''}>${escapeHtml(u)}</option>`).join('')}
                    </select>
                </div>
                <div class="col-md-2">
                    <label class="form-label small mb-1">Metodo</label>
                    <select class="form-select form-select-sm" id="audit-method-filter">
                        <option value="">Tutti</option>
                        <option value="GET" ${auditFilters.method === 'GET' ? 'selected' : ''}>GET</option>
                        <option value="POST" ${auditFilters.method === 'POST' ? 'selected' : ''}>POST</option>
                        <option value="PUT" ${auditFilters.method === 'PUT' ? 'selected' : ''}>PUT</option>
                        <option value="PATCH" ${auditFilters.method === 'PATCH' ? 'selected' : ''}>PATCH</option>
                        <option value="DELETE" ${auditFilters.method === 'DELETE' ? 'selected' : ''}>DELETE</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-check form-switch mb-0 mt-3">
                        <input class="form-check-input" type="checkbox" id="audit-show-reads" 
                               ${auditFilters.category === '' ? 'checked' : ''}>
                        <span class="form-check-label">Mostra anche letture (GET)</span>
                    </label>
                </div>
                <div class="col-md-2 text-end">
                    <button class="btn btn-sm btn-primary" id="btn-audit-search">
                        <i class="ti ti-search me-1"></i>Filtra
                    </button>
                    <button class="btn btn-sm btn-ghost-secondary" id="btn-audit-refresh" title="Aggiorna">
                        <i class="ti ti-refresh"></i>
                    </button>
                </div>
            </div>
        </div>
        <div id="audit-table-container">
            <div class="card-body text-center py-4 text-muted">
                <i class="ti ti-loader ti-spin" style="font-size: 2rem;"></i>
                <p class="mt-2">Caricamento audit log...</p>
            </div>
        </div>
    `;

    // Setup filter listeners
    document.getElementById('btn-audit-search')?.addEventListener('click', applyAuditFilters);
    document.getElementById('btn-audit-refresh')?.addEventListener('click', () => loadAuditData());
    document.getElementById('audit-search')?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') applyAuditFilters();
    });
    document.getElementById('audit-show-reads')?.addEventListener('change', (e) => {
        auditFilters.category = e.target.checked ? '' : 'write';
        auditPage = 1;
        loadAuditData();
    });

    await loadAuditData();
}

function applyAuditFilters() {
    auditFilters.search = document.getElementById('audit-search')?.value || '';
    auditFilters.user = document.getElementById('audit-user-filter')?.value || '';
    auditFilters.method = document.getElementById('audit-method-filter')?.value || '';
    auditPage = 1;
    loadAuditData();
}

async function loadAuditData() {
    const container = document.getElementById('audit-table-container');
    if (!container) return;

    try {
        // Build query params
        const params = new URLSearchParams();
        params.set('page', auditPage);
        params.set('per_page', '50');
        if (auditFilters.category) params.set('category', auditFilters.category);
        if (auditFilters.user) params.set('user', auditFilters.user);
        if (auditFilters.method) params.set('method', auditFilters.method);
        if (auditFilters.search) params.set('search', auditFilters.search);

        const data = await apiGet(`/logs/audit?${params.toString()}`);
        const items = data.items || [];

        if (items.length === 0) {
            container.innerHTML = `
                <div class="card-body text-center py-4 text-muted">
                    <i class="ti ti-list-search" style="font-size: 2rem;"></i>
                    <p class="mt-2">Nessun log trovato con i filtri attuali</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="table-responsive">
                <table class="table table-vcenter card-table table-hover table-sm">
                    <thead>
                        <tr>
                            <th>Timestamp</th>
                            <th>Utente</th>
                            <th>Metodo</th>
                            <th>Percorso</th>
                            <th>Status</th>
                            <th>Durata</th>
                            <th>IP</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${items.map(renderAuditRow).join('')}
                    </tbody>
                </table>
            </div>
            ${renderPagination(data.page, data.pages, data.total)}
        `;

        // Setup pagination listeners
        container.querySelectorAll('[data-audit-page]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                auditPage = parseInt(btn.dataset.auditPage);
                loadAuditData();
            });
        });

    } catch (error) {
        container.innerHTML = `
            <div class="card-body text-center py-4 text-danger">
                <i class="ti ti-alert-circle" style="font-size: 2rem;"></i>
                <p class="mt-2">Errore caricamento log: ${escapeHtml(error.message)}</p>
            </div>
        `;
    }
}

function renderAuditRow(log) {
    const methodColors = {
        'GET': 'azure', 'POST': 'green', 'PUT': 'orange',
        'PATCH': 'yellow', 'DELETE': 'red'
    };
    const methodColor = methodColors[log.method] || 'secondary';

    let statusColor = 'green';
    if (log.status_code >= 400 && log.status_code < 500) statusColor = 'yellow';
    if (log.status_code >= 500) statusColor = 'red';

    const ts = new Date(log.timestamp);
    const timeStr = ts.toLocaleString('it-IT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    });

    return `
        <tr>
            <td class="text-nowrap">
                <small class="text-muted">${timeStr}</small>
            </td>
            <td>
                <span class="badge bg-cyan-lt">${escapeHtml(log.username)}</span>
            </td>
            <td>
                <span class="badge bg-${methodColor}-lt">${log.method}</span>
            </td>
            <td>
                <code class="text-truncate d-inline-block" style="max-width: 350px;" title="${escapeHtml(log.path)}">
                    ${escapeHtml(log.path)}
                </code>
            </td>
            <td>
                <span class="badge bg-${statusColor}-lt">${log.status_code}</span>
            </td>
            <td class="text-nowrap">
                <small class="text-muted">${log.duration_ms}ms</small>
            </td>
            <td>
                <small class="text-muted">${escapeHtml(log.client_ip)}</small>
            </td>
        </tr>
    `;
}

function renderPagination(currentPage, totalPages, totalItems) {
    if (totalPages <= 1) {
        return `<div class="card-footer"><small class="text-muted">${totalItems} risultati</small></div>`;
    }

    let pages = '';
    const maxVisible = 5;
    let start = Math.max(1, currentPage - Math.floor(maxVisible / 2));
    let end = Math.min(totalPages, start + maxVisible - 1);
    if (end - start < maxVisible - 1) start = Math.max(1, end - maxVisible + 1);

    if (start > 1) {
        pages += `<li class="page-item"><a class="page-link" href="#" data-audit-page="1">1</a></li>`;
        if (start > 2) pages += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
    }

    for (let i = start; i <= end; i++) {
        pages += `<li class="page-item ${i === currentPage ? 'active' : ''}">
            <a class="page-link" href="#" data-audit-page="${i}">${i}</a>
        </li>`;
    }

    if (end < totalPages) {
        if (end < totalPages - 1) pages += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        pages += `<li class="page-item"><a class="page-link" href="#" data-audit-page="${totalPages}">${totalPages}</a></li>`;
    }

    return `
        <div class="card-footer d-flex align-items-center justify-content-between">
            <small class="text-muted">${totalItems} risultati — Pagina ${currentPage} di ${totalPages}</small>
            <ul class="pagination m-0">
                <li class="page-item ${currentPage <= 1 ? 'disabled' : ''}">
                    <a class="page-link" href="#" data-audit-page="${currentPage - 1}" tabindex="-1">
                        <i class="ti ti-chevron-left"></i>
                    </a>
                </li>
                ${pages}
                <li class="page-item ${currentPage >= totalPages ? 'disabled' : ''}">
                    <a class="page-link" href="#" data-audit-page="${currentPage + 1}">
                        <i class="ti ti-chevron-right"></i>
                    </a>
                </li>
            </ul>
        </div>
    `;
}


// ==========================================
//  SYSTEM LOG TAB
// ==========================================

async function renderSystemTab() {
    const content = document.getElementById('logs-tab-content');
    if (!content) return;

    content.innerHTML = `
        <div class="card-body border-bottom py-3">
            <div class="row g-2 align-items-end">
                <div class="col-md-3">
                    <label class="form-label small mb-1">Righe</label>
                    <select class="form-select form-select-sm" id="syslog-lines">
                        <option value="100">100</option>
                        <option value="200" selected>200</option>
                        <option value="500">500</option>
                        <option value="1000">1000</option>
                    </select>
                </div>
                <div class="col-md-4">
                    <label class="form-label small mb-1">Ricerca (grep)</label>
                    <input type="text" class="form-control form-control-sm" id="syslog-search" 
                           placeholder="Filtra righe...">
                </div>
                <div class="col-md-5 text-end">
                    <button class="btn btn-sm btn-primary" id="btn-syslog-load">
                        <i class="ti ti-search me-1"></i>Carica
                    </button>
                    <button class="btn btn-sm btn-ghost-secondary" id="btn-syslog-refresh" title="Aggiorna">
                        <i class="ti ti-refresh"></i>
                    </button>
                </div>
            </div>
        </div>
        <div id="syslog-container">
            <div class="card-body text-center py-4 text-muted">
                <i class="ti ti-loader ti-spin" style="font-size: 2rem;"></i>
                <p class="mt-2">Caricamento system log...</p>
            </div>
        </div>
    `;

    document.getElementById('btn-syslog-load')?.addEventListener('click', loadSystemLog);
    document.getElementById('btn-syslog-refresh')?.addEventListener('click', loadSystemLog);
    document.getElementById('syslog-search')?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') loadSystemLog();
    });

    await loadSystemLog();
}

async function loadSystemLog() {
    const container = document.getElementById('syslog-container');
    if (!container) return;

    const lines = document.getElementById('syslog-lines')?.value || '200';
    const search = document.getElementById('syslog-search')?.value || '';

    try {
        const params = new URLSearchParams();
        params.set('lines', lines);
        if (search) params.set('search', search);

        const data = await apiGet(`/logs/system?${params.toString()}`);
        const logLines = data.lines || [];

        if (logLines.length === 0) {
            container.innerHTML = `
                <div class="card-body text-center py-4 text-muted">
                    <i class="ti ti-file-off" style="font-size: 2rem;"></i>
                    <p class="mt-2">Nessun log trovato</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="card-body p-0">
                <pre class="p-3 mb-0" style="max-height: 600px; overflow-y: auto; font-size: 0.78rem; line-height: 1.5; background: var(--tblr-bg-surface-secondary, #f4f6fa);" id="syslog-output">${logLines.map(formatSystemLogLine).join('\n')}</pre>
            </div>
            <div class="card-footer">
                <small class="text-muted">${logLines.length} righe — journalctl -u madmin</small>
            </div>
        `;

        // Scroll to bottom
        const output = document.getElementById('syslog-output');
        if (output) output.scrollTop = output.scrollHeight;

    } catch (error) {
        container.innerHTML = `
            <div class="card-body text-center py-4 text-danger">
                <i class="ti ti-alert-circle" style="font-size: 2rem;"></i>
                <p class="mt-2">Errore caricamento log: ${escapeHtml(error.message)}</p>
            </div>
        `;
    }
}

function formatSystemLogLine(line) {
    const escaped = escapeHtml(line);

    // Highlight based on log level
    if (/\bERROR\b/i.test(line) || /\bCRITICAL\b/i.test(line)) {
        return `<span style="color: var(--tblr-red, #d63939);">${escaped}</span>`;
    }
    if (/\bWARNING\b/i.test(line) || /\bWARN\b/i.test(line)) {
        return `<span style="color: var(--tblr-yellow, #f59f00);">${escaped}</span>`;
    }
    if (/\bAUDIT\b/.test(line)) {
        return `<span style="color: var(--tblr-cyan, #17a2b8);">${escaped}</span>`;
    }

    return escaped;
}

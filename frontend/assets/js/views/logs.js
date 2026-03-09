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

    // Load user list for filter
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

    // Build user options
    const userOptions = auditUsers.map(u =>
        `<option value="${escapeHtml(u)}" ${auditFilters.user === u ? 'selected' : ''}>${escapeHtml(u)}</option>`
    ).join('');

    content.innerHTML = `
        <div class="card-body border-bottom py-3">
            <div class="d-flex flex-wrap gap-2 align-items-center">
                <div class="input-icon flex-grow-1" style="max-width: 250px;">
                    <span class="input-icon-addon"><i class="ti ti-search"></i></span>
                    <input type="text" class="form-control form-control-sm" id="audit-search" 
                           placeholder="Cerca nel percorso..." value="${escapeHtml(auditFilters.search)}">
                </div>
                <select class="form-select form-select-sm w-auto" id="audit-user-filter">
                    <option value="">Tutti gli utenti</option>
                    ${userOptions}
                </select>
                <select class="form-select form-select-sm w-auto" id="audit-category-filter">
                    <option value="write" ${auditFilters.category === 'write' ? 'selected' : ''}>Solo scritture</option>
                    <option value="" ${auditFilters.category === '' ? 'selected' : ''}>Tutte le operazioni</option>
                    <option value="read" ${auditFilters.category === 'read' ? 'selected' : ''}>Solo letture</option>
                </select>
                <button class="btn btn-sm btn-ghost-secondary" id="btn-audit-refresh" title="Aggiorna">
                    <i class="ti ti-refresh"></i>
                </button>
            </div>
        </div>
        <div id="audit-table-container">
            <div class="card-body text-center py-4 text-muted">
                <div class="spinner-border spinner-border-sm me-2"></div>
                Caricamento...
            </div>
        </div>
    `;

    // Listeners
    document.getElementById('audit-search')?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') applyAuditFilters();
    });
    document.getElementById('audit-search')?.addEventListener('change', applyAuditFilters);
    document.getElementById('audit-user-filter')?.addEventListener('change', applyAuditFilters);
    document.getElementById('audit-category-filter')?.addEventListener('change', applyAuditFilters);
    document.getElementById('btn-audit-refresh')?.addEventListener('click', () => loadAuditData());

    await loadAuditData();
}

function applyAuditFilters() {
    auditFilters.search = document.getElementById('audit-search')?.value || '';
    auditFilters.user = document.getElementById('audit-user-filter')?.value || '';
    auditFilters.category = document.getElementById('audit-category-filter')?.value ?? 'write';
    auditPage = 1;
    loadAuditData();
}

async function loadAuditData() {
    const container = document.getElementById('audit-table-container');
    if (!container) return;

    try {
        const params = new URLSearchParams();
        params.set('page', auditPage);
        params.set('per_page', '50');
        // Always send category — empty string = all
        params.set('category', auditFilters.category);
        if (auditFilters.user) params.set('user', auditFilters.user);
        if (auditFilters.search) params.set('search', auditFilters.search);

        const data = await apiGet(`/logs/audit?${params.toString()}`);
        const items = data.items || [];

        if (items.length === 0) {
            container.innerHTML = `
                <div class="card-body text-center py-4 text-muted">
                    <i class="ti ti-list-search" style="font-size: 2rem;"></i>
                    <p class="mt-2 mb-0">Nessun log trovato con i filtri attuali</p>
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
                            <th>Richiesta</th>
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

        // Pagination listeners
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
                <p class="mt-2 mb-0">Errore: ${escapeHtml(error.message)}</p>
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
        day: '2-digit', month: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    });

    let payloadHtml = '';
    if (log.request_body) {
        // Store payload in a global map or simply pass it escaped. To avoid escaping quotes in HTML, we'll store it on window.
        window._auditPayloads = window._auditPayloads || {};
        window._auditPayloads[log.id] = log.request_body;

        payloadHtml = `
            <button class="btn btn-icon btn-sm btn-ghost-primary ms-1" onclick="showAuditPayload('${log.id}')" title="Vedi payload">
                <i class="ti ti-eye"></i>
            </button>
        `;
    }

    return `
        <tr>
            <td class="text-nowrap text-muted" style="font-size: .8125rem;">${timeStr}</td>
            <td><span class="badge bg-cyan-lt">${escapeHtml(log.username)}</span></td>
            <td>
                <span class="badge bg-${methodColor}-lt me-1">${log.method}</span>
                <code title="${escapeHtml(log.path)}">${escapeHtml(truncatePath(log.path))}</code>
                ${payloadHtml}
            </td>
            <td><span class="badge bg-${statusColor}-lt">${log.status_code}</span></td>
            <td class="text-muted" style="font-size: .8125rem;">${log.duration_ms}ms</td>
            <td class="text-muted" style="font-size: .8125rem;">${escapeHtml(log.client_ip)}</td>
        </tr>
    `;
}

window.showAuditPayload = function (logId) {
    const payload = window._auditPayloads && window._auditPayloads[logId];
    if (!payload) return;

    let formattedHtml = escapeHtml(payload);
    try {
        const parsed = JSON.parse(payload);
        formattedHtml = escapeHtml(JSON.stringify(parsed, null, 2));
    } catch (e) { }

    const modalHtml = `
        <div class="modal fade" id="modal-audit-payload" tabindex="-1">
            <div class="modal-dialog modal-lg modal-dialog-centered modal-dialog-scrollable">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title"><i class="ti ti-code me-2"></i>Payload Richiesta</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body p-0">
                        <pre style="margin:0; padding:1.5rem; background: #1e293b; color: #c8d3e0; border-radius: 0 0 4px 4px;"><code>${formattedHtml}</code></pre>
                    </div>
                </div>
            </div>
        </div>
    `;

    document.getElementById('modal-audit-payload')?.remove();
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    const modal = new bootstrap.Modal(document.getElementById('modal-audit-payload'));
    modal.show();
};

function truncatePath(path) {
    if (path.length <= 50) return path;
    return path.substring(0, 47) + '...';
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
        if (start > 2) pages += `<li class="page-item disabled"><span class="page-link">…</span></li>`;
    }
    for (let i = start; i <= end; i++) {
        pages += `<li class="page-item ${i === currentPage ? 'active' : ''}">
            <a class="page-link" href="#" data-audit-page="${i}">${i}</a></li>`;
    }
    if (end < totalPages) {
        if (end < totalPages - 1) pages += `<li class="page-item disabled"><span class="page-link">…</span></li>`;
        pages += `<li class="page-item"><a class="page-link" href="#" data-audit-page="${totalPages}">${totalPages}</a></li>`;
    }

    return `
        <div class="card-footer d-flex align-items-center justify-content-between">
            <small class="text-muted">Pagina ${currentPage} di ${totalPages} (${totalItems} totali)</small>
            <ul class="pagination m-0 ms-auto">
                <li class="page-item ${currentPage <= 1 ? 'disabled' : ''}">
                    <a class="page-link" href="#" data-audit-page="${currentPage - 1}"><i class="ti ti-chevron-left"></i></a>
                </li>
                ${pages}
                <li class="page-item ${currentPage >= totalPages ? 'disabled' : ''}">
                    <a class="page-link" href="#" data-audit-page="${currentPage + 1}"><i class="ti ti-chevron-right"></i></a>
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
            <div class="d-flex flex-wrap gap-2 align-items-center">
                <select class="form-select form-select-sm w-auto" id="syslog-lines">
                    <option value="100">100 righe</option>
                    <option value="200" selected>200 righe</option>
                    <option value="500">500 righe</option>
                    <option value="1000">1000 righe</option>
                </select>
                <div class="input-icon flex-grow-1" style="max-width: 300px;">
                    <span class="input-icon-addon"><i class="ti ti-search"></i></span>
                    <input type="text" class="form-control form-control-sm" id="syslog-search" 
                           placeholder="Filtra (grep)...">
                </div>
                <button class="btn btn-sm btn-primary" id="btn-syslog-load">
                    <i class="ti ti-refresh me-1"></i>Carica
                </button>
            </div>
        </div>
        <div id="syslog-container">
            <div class="card-body text-center py-4 text-muted">
                <div class="spinner-border spinner-border-sm me-2"></div>
                Caricamento...
            </div>
        </div>
    `;

    document.getElementById('btn-syslog-load')?.addEventListener('click', loadSystemLog);
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
                    <p class="mt-2 mb-0">Nessun log trovato</p>
                </div>
            `;
            return;
        }

        // Use a dark background for the terminal-like viewer regardless of theme
        container.innerHTML = `
            <div class="card-body p-0">
                <pre id="syslog-output" style="
                    max-height: 600px; overflow-y: auto; margin: 0; padding: 1rem;
                    font-size: 0.75rem; line-height: 1.6;
                    background: #1e293b; color: #c8d3e0;
                    border-radius: 0;
                ">${logLines.map(formatSystemLogLine).join('\n')}</pre>
            </div>
            <div class="card-footer">
                <small class="text-muted">${logLines.length} righe — <code>journalctl -u madmin</code></small>
            </div>
        `;

        // Scroll to bottom
        const output = document.getElementById('syslog-output');
        if (output) output.scrollTop = output.scrollHeight;

    } catch (error) {
        container.innerHTML = `
            <div class="card-body text-center py-4 text-danger">
                <i class="ti ti-alert-circle" style="font-size: 2rem;"></i>
                <p class="mt-2 mb-0">Errore: ${escapeHtml(error.message)}</p>
            </div>
        `;
    }
}

function formatSystemLogLine(line) {
    const escaped = escapeHtml(line);

    // Error / Critical → red
    if (/\bERROR\b/i.test(line) || /\bCRITICAL\b/i.test(line) || /\bTraceback\b/.test(line)) {
        return `<span style="color:#f87171">${escaped}</span>`;
    }
    // Warning → amber
    if (/\bWARNING\b/i.test(line) || /\bWARN\b/i.test(line)) {
        return `<span style="color:#fbbf24">${escaped}</span>`;
    }
    // Audit lines → cyan
    if (/\bAUDIT\b/.test(line)) {
        return `<span style="color:#67e8f9">${escaped}</span>`;
    }
    // Uvicorn access log (INFO: IP - "METHOD /path") → dimmed
    if (/^INFO:\s+\d/.test(line)) {
        return `<span style="color:#64748b">${escaped}</span>`;
    }

    // Default → light gray (visible on dark bg)
    return escaped;
}

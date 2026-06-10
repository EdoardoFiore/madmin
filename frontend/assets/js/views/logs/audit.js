/**
 * MADMIN - Logs View / Audit tab
 *
 * Filterable, paginated audit log with payload/error detail modals.
 */

import { apiGet } from '../../api.js';
import { showToast, escapeHtml, debounce } from '../../utils.js';
import { t } from '../../i18n.js';
import { openModal } from '../../components/modal.js';
import { pagination, bindPagination } from '../../components/pagination.js';

// Detail payloads for the currently rendered page, keyed by log id.
// Module-level Map instead of the old window._auditPayloads/_auditErrors.
const _payloads = new Map();
const _errors = new Map();

export async function renderAuditTab(state) {
    const content = state.contentEl;
    if (!content) return;

    const userOptions = state.auditUsers.map(u =>
        `<option value="${escapeHtml(u)}" ${state.auditFilters.user === u ? 'selected' : ''}>${escapeHtml(u)}</option>`
    ).join('');

    content.innerHTML = `
        <div class="card-body border-bottom py-3">
            <div class="d-flex flex-wrap gap-2 align-items-center">
                <div class="input-icon flex-grow-1" style="max-width: 250px;">
                    <span class="input-icon-addon"><i class="ti ti-search"></i></span>
                    <input type="text" class="form-control form-control-sm" id="audit-search"
                           placeholder="${t('logs.searchPath')}" value="${escapeHtml(state.auditFilters.search)}">
                </div>
                <select class="form-select form-select-sm w-auto" id="audit-user-filter">
                    <option value="">${t('logs.allUsers')}</option>
                    ${userOptions}
                </select>
                <select class="form-select form-select-sm w-auto" id="audit-category-filter">
                    <option value="write" ${state.auditFilters.category === 'write' ? 'selected' : ''}>${t('logs.writesOnly')}</option>
                    <option value="" ${state.auditFilters.category === '' ? 'selected' : ''}>${t('logs.allOperations')}</option>
                    <option value="read" ${state.auditFilters.category === 'read' ? 'selected' : ''}>${t('logs.readsOnly')}</option>
                </select>
                <div class="d-flex align-items-center gap-1">
                    <span class="text-muted" style="font-size: .75rem;">${t('logs.from')}</span>
                    <input type="date" class="form-control form-control-sm" id="audit-from-date"
                           value="${state.auditFilters.from_date}" style="width: 130px;">
                    <span class="text-muted" style="font-size: .75rem;">${t('logs.to')}</span>
                    <input type="date" class="form-control form-control-sm" id="audit-to-date"
                           value="${state.auditFilters.to_date}" style="width: 130px;">
                </div>
                <button class="btn btn-sm btn-ghost-secondary" id="btn-audit-export" title="${t('logs.exportCsv')}">
                    <i class="ti ti-download"></i>
                </button>
                <button class="btn btn-sm btn-ghost-secondary" id="btn-audit-refresh" title="${t('common.refresh')}">
                    <i class="ti ti-refresh"></i>
                </button>
            </div>
        </div>
        <div id="audit-table-container"></div>
    `;

    const applyFilters = () => applyAuditFilters(state);

    document.getElementById('audit-search')?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') applyFilters();
    });
    document.getElementById('audit-search')?.addEventListener('input', debounce(applyFilters, 300));
    document.getElementById('audit-user-filter')?.addEventListener('change', applyFilters);
    document.getElementById('audit-category-filter')?.addEventListener('change', applyFilters);
    document.getElementById('audit-from-date')?.addEventListener('change', applyFilters);
    document.getElementById('audit-to-date')?.addEventListener('change', applyFilters);
    document.getElementById('btn-audit-refresh')?.addEventListener('click', () => loadAuditData(state));
    document.getElementById('btn-audit-export')?.addEventListener('click', () => exportAuditCsv(state));

    // One delegated listener for payload/error detail buttons (idempotent per render)
    const tableContainer = document.getElementById('audit-table-container');
    tableContainer.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-detail]');
        if (!btn) return;
        const logId = btn.dataset.key;
        if (btn.dataset.detail === 'payload') showDetailModal(t('logs.requestPayload'), _payloads.get(logId));
        else showDetailModal(t('logs.errorDetailTitle'), _errors.get(logId));
    });
    bindPagination(tableContainer, (page) => {
        state.auditPage = page;
        loadAuditData(state);
    });

    await loadAuditData(state);
}

/**
 * Export audit logs as CSV (opens download)
 */
function exportAuditCsv(state) {
    const params = new URLSearchParams();
    if (state.auditFilters.category) params.set('category', state.auditFilters.category);
    if (state.auditFilters.user) params.set('user', state.auditFilters.user);
    if (state.auditFilters.search) params.set('search', state.auditFilters.search);
    if (state.auditFilters.from_date) params.set('from_date', state.auditFilters.from_date);
    if (state.auditFilters.to_date) params.set('to_date', state.auditFilters.to_date);

    const token = localStorage.getItem('madmin_token');
    // Use fetch + blob to include auth header
    fetch(`/api/logs/audit/export?${params.toString()}`, {
        headers: { 'Authorization': `Bearer ${token}` }
    })
        .then(resp => {
            if (!resp.ok) throw new Error(t('logs.exportFailed'));
            const filename = resp.headers.get('content-disposition')?.match(/filename="(.+)"/)?.[1] || 'audit_log.csv';
            return resp.blob().then(blob => ({ blob, filename }));
        })
        .then(({ blob, filename }) => {
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
        })
        .catch(err => {
            showToast(t('logs.exportError', { error: err.message }), 'error');
        });
}

function applyAuditFilters(state) {
    state.auditFilters.search = document.getElementById('audit-search')?.value || '';
    state.auditFilters.user = document.getElementById('audit-user-filter')?.value || '';
    state.auditFilters.category = document.getElementById('audit-category-filter')?.value ?? 'write';
    state.auditFilters.from_date = document.getElementById('audit-from-date')?.value || '';
    state.auditFilters.to_date = document.getElementById('audit-to-date')?.value || '';
    state.auditPage = 1;
    loadAuditData(state);
}

async function loadAuditData(state) {
    const container = document.getElementById('audit-table-container');
    if (!container) return;

    try {
        const params = new URLSearchParams();
        params.set('page', state.auditPage);
        params.set('per_page', '50');
        // Always send category — empty string = all
        params.set('category', state.auditFilters.category);
        if (state.auditFilters.user) params.set('user', state.auditFilters.user);
        if (state.auditFilters.search) params.set('search', state.auditFilters.search);
        if (state.auditFilters.from_date) params.set('from_date', state.auditFilters.from_date);
        if (state.auditFilters.to_date) params.set('to_date', state.auditFilters.to_date);

        const data = await apiGet(`/logs/audit?${params.toString()}`);
        const items = data.items || [];

        _payloads.clear();
        _errors.clear();

        if (items.length === 0) {
            container.innerHTML = `
                <div class="card-body text-center py-4 text-muted">
                    <i class="ti ti-list-search" style="font-size: 2rem;"></i>
                    <p class="mt-2 mb-0">${t('logs.noLogsFound')}</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="table-responsive">
                <table class="table table-vcenter card-table table-hover table-sm">
                    <thead>
                        <tr>
                            <th>${t('logs.timestamp')}</th>
                            <th>${t('logs.user')}</th>
                            <th>${t('logs.request')}</th>
                            <th>Status</th>
                            <th>${t('logs.duration')}</th>
                            <th>${t('logs.ip')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${items.map(renderAuditRow).join('')}
                    </tbody>
                </table>
            </div>
            ${pagination({ page: data.page, pages: data.pages, total: data.total, summaryKey: 'logs.pageOf' })}
        `;

    } catch (error) {
        container.innerHTML = `
            <div class="card-body text-center py-4 text-danger">
                <i class="ti ti-alert-circle" style="font-size: 2rem;"></i>
                <p class="mt-2 mb-0">${t('common.errorPrefix')}${escapeHtml(error.message)}</p>
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
    const timeStr = ts.toLocaleString(undefined, {
        day: '2-digit', month: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    });

    // Payload button — only show if request_body is meaningful (not null/empty/{})
    let payloadHtml = '';
    if (log.request_body && log.request_body !== '{}' && log.request_body !== '[]') {
        _payloads.set(String(log.id), log.request_body);
        payloadHtml = `
            <button class="btn btn-icon btn-sm btn-ghost-primary ms-1" data-detail="payload" data-key="${escapeHtml(String(log.id))}" title="${t('logs.viewPayload')}">
                <i class="ti ti-eye"></i>
            </button>
        `;
    }

    // Response error indicator — show for 4xx/5xx with response_summary
    let errorHtml = '';
    if (log.response_summary && log.status_code >= 400) {
        _errors.set(String(log.id), log.response_summary);
        errorHtml = `
            <button class="btn btn-icon btn-sm btn-ghost-danger ms-1" data-detail="error" data-key="${escapeHtml(String(log.id))}" title="${t('logs.errorDetail')}">
                <i class="ti ti-alert-triangle"></i>
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
                ${errorHtml}
            </td>
            <td><span class="badge bg-${statusColor}-lt">${log.status_code}</span></td>
            <td class="text-muted" style="font-size: .8125rem;">${log.duration_ms}ms</td>
            <td class="text-muted" style="font-size: .8125rem;">${escapeHtml(log.client_ip)}</td>
        </tr>
    `;
}

/**
 * Code-style detail modal with a copy button (payload / error detail)
 */
function showDetailModal(title, raw) {
    if (!raw) return;

    let text = raw;
    try {
        text = JSON.stringify(JSON.parse(raw), null, 2);
    } catch (e) { }

    const ctx = openModal({
        title,
        size: 'lg',
        body: `<pre style="margin:0; padding:1.5rem; background: #1e293b; color: #c8d3e0;"><code>${escapeHtml(text)}</code></pre>`,
        footer: `
            <button type="button" class="btn btn-sm btn-ghost-primary" data-action="copy">
                <i class="ti ti-copy me-1"></i>${t('common.copy')}
            </button>
            <button type="button" class="btn btn-sm btn-link" data-bs-dismiss="modal">${t('common.close')}</button>
        `,
        onAction(action, ctx) {
            if (action !== 'copy') return;
            navigator.clipboard.writeText(text).then(() => {
                const btn = ctx.el.querySelector('[data-action="copy"]');
                if (btn) {
                    btn.innerHTML = `<i class="ti ti-check me-1"></i>${t('common.copied')}`;
                    setTimeout(() => { btn.innerHTML = `<i class="ti ti-copy me-1"></i>${t('common.copy')}`; }, 2000);
                }
            }).catch(() => {
                showToast(t('logs.copyError'), 'error');
            });
        },
    });

    // Strip the body padding so the <pre> fills the modal like the old viewer
    ctx.bodyEl.classList.add('p-0');
    ctx.el.querySelector('.modal-dialog').classList.add('modal-dialog-centered', 'modal-dialog-scrollable');
}

function truncatePath(path) {
    if (path.length <= 50) return path;
    return path.substring(0, 47) + '...';
}

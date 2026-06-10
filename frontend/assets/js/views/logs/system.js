/**
 * MADMIN - Logs View / System tab
 *
 * Terminal-like journalctl viewer with line count, grep filter and
 * audit-noise toggle.
 */

import { apiGet } from '../../api.js';
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';

export async function renderSystemTab(state) {
    const content = state.contentEl;
    if (!content) return;

    content.innerHTML = `
        <div class="card-body border-bottom py-3">
            <div class="d-flex flex-wrap gap-2 align-items-center">
                <select class="form-select form-select-sm w-auto" id="syslog-lines">
                    <option value="100">100 ${t('logs.lines')}</option>
                    <option value="200" selected>200 ${t('logs.lines')}</option>
                    <option value="500">500 ${t('logs.lines')}</option>
                    <option value="1000">1000 ${t('logs.lines')}</option>
                </select>
                <div class="input-icon flex-grow-1" style="max-width: 300px;">
                    <span class="input-icon-addon"><i class="ti ti-search"></i></span>
                    <input type="text" class="form-control form-control-sm" id="syslog-search"
                           placeholder="${t('logs.filterGrep')}">
                </div>
                <div class="form-check form-switch ms-2">
                    <input class="form-check-input" type="checkbox" id="syslog-hide-audit" checked>
                    <label class="form-check-label" for="syslog-hide-audit" style="font-size: .8125rem;">
                        ${t('logs.hideAudit')}
                    </label>
                </div>
                <button class="btn btn-sm btn-primary" id="btn-syslog-load">
                    <i class="ti ti-refresh me-1"></i>${t('logs.load')}
                </button>
            </div>
        </div>
        <div id="syslog-container">
            <div class="card-body text-center py-4 text-muted">
                <div class="spinner-border spinner-border-sm me-2"></div>
                ${t('common.loading')}
            </div>
        </div>
    `;

    document.getElementById('btn-syslog-load')?.addEventListener('click', loadSystemLog);
    document.getElementById('syslog-search')?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') loadSystemLog();
    });
    document.getElementById('syslog-hide-audit')?.addEventListener('change', loadSystemLog);

    await loadSystemLog();
}

async function loadSystemLog() {
    const container = document.getElementById('syslog-container');
    if (!container) return;

    const lines = document.getElementById('syslog-lines')?.value || '200';
    const search = document.getElementById('syslog-search')?.value || '';
    const hideAudit = document.getElementById('syslog-hide-audit')?.checked ?? true;

    try {
        const params = new URLSearchParams();
        params.set('lines', lines);
        if (search) params.set('search', search);

        const data = await apiGet(`/logs/system?${params.toString()}`);
        let logLines = data.lines || [];

        // Filter out AUDIT lines if toggle is on
        if (hideAudit) {
            logLines = logLines.filter(line => !/\bAUDIT\b/.test(line));
        }

        if (logLines.length === 0) {
            container.innerHTML = `
                <div class="card-body text-center py-4 text-muted">
                    <i class="ti ti-file-off" style="font-size: 2rem;"></i>
                    <p class="mt-2 mb-0">${t('logs.noLogFound')}</p>
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
                <small class="text-muted">${t('logs.linesLabel', { count: logLines.length })} — <code>journalctl -u madmin</code></small>
            </div>
        `;

        // Scroll to bottom
        const output = document.getElementById('syslog-output');
        if (output) output.scrollTop = output.scrollHeight;

    } catch (error) {
        container.innerHTML = `
            <div class="card-body text-center py-4 text-danger">
                <i class="ti ti-alert-circle" style="font-size: 2rem;"></i>
                <p class="mt-2 mb-0">${t('common.errorPrefix')}${escapeHtml(error.message)}</p>
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

/**
 * Reverse Proxy - Logs tab
 *
 * Access / error logs per proxy host (one nginx log file pair per host) plus
 * the general logs of the dedicated reverse proxy instance, which collect
 * traffic that matched no host. Rotated
 * archives (.1, .N.gz) are selectable so older events can be inspected too.
 */
import { apiGet } from '/static/js/api.js';
import { loadingSpinner, escapeHtml, escapeAttr, emptyState, debounce, formatDate } from '/static/js/utils.js';
import { t } from '/static/js/i18n.js';

const MODULE_API = '/modules/reverseproxy';
const AUTO_REFRESH_MS = 10000;

let _state = { source: 'global', kind: 'access', file: 0, lines: 500, search: '', status: '' };
let _timer = null;

export async function renderLogsTab(container) {
    container.innerHTML = `
        <div class="d-flex flex-wrap gap-2 align-items-end px-3 pt-3 pb-3">
            <div style="min-width: 240px; flex: 1 1 240px; max-width: 420px;">
                <label class="form-label small mb-1">${t('reverseproxy.logSource')}</label>
                <select id="revproxy-log-source" class="form-select"></select>
            </div>
            <div>
                <label class="form-label small mb-1">${t('reverseproxy.logType')}</label>
                <div class="btn-group w-100" role="group">
                    <input type="radio" class="btn-check" name="revproxy-log-kind" id="revproxy-log-kind-access" value="access" checked>
                    <label class="btn" for="revproxy-log-kind-access"><i class="ti ti-world me-1"></i>${t('reverseproxy.logAccess')}</label>
                    <input type="radio" class="btn-check" name="revproxy-log-kind" id="revproxy-log-kind-error" value="error">
                    <label class="btn" for="revproxy-log-kind-error"><i class="ti ti-alert-triangle me-1"></i>${t('reverseproxy.logError')}</label>
                </div>
            </div>
            <div style="min-width: 200px;">
                <label class="form-label small mb-1">${t('reverseproxy.logFile')}</label>
                <select id="revproxy-log-file" class="form-select"></select>
            </div>
            <div style="min-width: 200px; flex: 1 1 200px;">
                <label class="form-label small mb-1">${t('reverseproxy.logSearch')}</label>
                <div class="input-icon">
                    <span class="input-icon-addon"><i class="ti ti-search"></i></span>
                    <input type="text" id="revproxy-log-search" class="form-control" placeholder="${t('reverseproxy.search')}">
                </div>
            </div>
            <div id="revproxy-log-status-wrap">
                <label class="form-label small mb-1">${t('reverseproxy.logStatus')}</label>
                <select id="revproxy-log-status" class="form-select">
                    <option value="">${t('reverseproxy.logAll')}</option>
                    <option value="2">2xx</option>
                    <option value="3">3xx</option>
                    <option value="4">4xx</option>
                    <option value="5">5xx</option>
                </select>
            </div>
            <div>
                <label class="form-label small mb-1">${t('reverseproxy.logLines')}</label>
                <select id="revproxy-log-lines" class="form-select">
                    ${[100, 500, 1000, 2000].map(n => `<option value="${n}" ${n === _state.lines ? 'selected' : ''}>${n}</option>`).join('')}
                </select>
            </div>
            <div class="d-flex gap-2 align-items-center">
                <button class="btn btn-icon" id="revproxy-log-refresh" title="${escapeAttr(t('reverseproxy.logRefresh'))}">
                    <i class="ti ti-refresh"></i>
                </button>
                <label class="form-check form-switch mb-0">
                    <input class="form-check-input" type="checkbox" id="revproxy-log-auto">
                    <span class="form-check-label small">${t('reverseproxy.logAutoRefresh')}</span>
                </label>
            </div>
        </div>
        <div id="revproxy-log-hint" class="px-3 pb-2 small text-secondary"></div>
        <div id="revproxy-log-table">${loadingSpinner()}</div>
    `;

    const $ = (id) => document.getElementById(id);

    $('revproxy-log-source').addEventListener('change', async (e) => {
        _state.source = e.target.value;
        _state.file = 0;
        await reloadFiles();
        await reloadEntries();
    });
    container.querySelectorAll('input[name="revproxy-log-kind"]').forEach(r => {
        r.addEventListener('change', async (e) => {
            _state.kind = e.target.value;
            _state.file = 0;
            await reloadFiles();
            await reloadEntries();
        });
    });
    $('revproxy-log-file').addEventListener('change', (e) => {
        _state.file = parseInt(e.target.value, 10) || 0;
        reloadEntries();
    });
    $('revproxy-log-search').addEventListener('input', debounce((e) => {
        _state.search = e.target.value.trim();
        reloadEntries();
    }, 400));
    $('revproxy-log-status').addEventListener('change', (e) => {
        _state.status = e.target.value;
        reloadEntries();
    });
    $('revproxy-log-lines').addEventListener('change', (e) => {
        _state.lines = parseInt(e.target.value, 10) || 500;
        reloadEntries();
    });
    $('revproxy-log-refresh').addEventListener('click', async () => {
        await reloadFiles();
        await reloadEntries();
    });
    $('revproxy-log-auto').addEventListener('change', (e) => {
        clearInterval(_timer);
        _timer = null;
        if (e.target.checked) {
            _timer = setInterval(() => {
                // Stop once the view has been navigated away from
                if (!document.getElementById('revproxy-log-table')) {
                    clearInterval(_timer);
                    _timer = null;
                    return;
                }
                if (_state.file === 0) reloadEntries();
            }, AUTO_REFRESH_MS);
        }
    });

    await reloadSources();
    await reloadFiles();
    await reloadEntries();
}

async function reloadSources() {
    const select = document.getElementById('revproxy-log-source');
    let sources = [];
    try {
        sources = await apiGet(`${MODULE_API}/logs/sources`);
    } catch {
        sources = [{ id: 'global', name: null, domains: [], enabled: true }];
    }
    if (!sources.some(s => s.id === _state.source)) _state.source = 'global';

    select.innerHTML = sources.map(s => {
        const label = s.id === 'global'
            ? t('reverseproxy.logGlobal')
            : `${s.name}${s.domains.length ? ` — ${s.domains.join(', ')}` : ''}${s.enabled ? '' : ` (${t('reverseproxy.offline')})`}`;
        return `<option value="${escapeAttr(s.id)}" ${s.id === _state.source ? 'selected' : ''}>${escapeHtml(label)}</option>`;
    }).join('');
}

async function reloadFiles() {
    const select = document.getElementById('revproxy-log-file');
    if (!select) return;
    let files = [];
    try {
        files = await apiGet(`${MODULE_API}/logs/${encodeURIComponent(_state.source)}/${_state.kind}/files`);
    } catch {
        files = [];
    }
    if (!files.some(f => f.index === _state.file)) _state.file = 0;

    select.innerHTML = files.length
        ? files.map(f => {
            const label = f.index === 0
                ? t('reverseproxy.logCurrent')
                : t('reverseproxy.logArchive', { n: f.index, date: formatDate(f.modified) });
            return `<option value="${f.index}" ${f.index === _state.file ? 'selected' : ''}>${escapeHtml(label)} · ${formatSize(f.size)}</option>`;
        }).join('')
        : `<option value="0">${t('reverseproxy.logCurrent')}</option>`;

    document.getElementById('revproxy-log-status-wrap').hidden = _state.kind !== 'access';
    document.getElementById('revproxy-log-hint').textContent = _state.source === 'global'
        ? t('reverseproxy.logGlobalHint')
        : '';
}

async function reloadEntries() {
    const root = document.getElementById('revproxy-log-table');
    if (!root) return;

    const params = new URLSearchParams({ file: _state.file, lines: _state.lines });
    if (_state.search) params.set('search', _state.search);
    if (_state.kind === 'access' && _state.status) params.set('status', _state.status);

    let data;
    try {
        data = await apiGet(`${MODULE_API}/logs/${encodeURIComponent(_state.source)}/${_state.kind}?${params}`);
    } catch (err) {
        root.innerHTML = `<div class="alert alert-danger m-3">${escapeHtml(err.message)}</div>`;
        return;
    }

    if (!data.exists) {
        root.innerHTML = `<div class="p-3">${emptyState('ti-file-off', t('reverseproxy.logNoFile'), t('reverseproxy.logNoFileHint'))}</div>`;
        return;
    }
    if (!data.entries.length) {
        root.innerHTML = `<div class="p-3">${emptyState('ti-file-search', t('reverseproxy.logEmpty'))}</div>`;
        return;
    }

    const table = _state.kind === 'access' ? renderAccessTable(data.entries) : renderErrorTable(data.entries);
    root.innerHTML = `
        <div class="table-responsive">${table}</div>
        <div class="card-footer small text-secondary">
            ${t('reverseproxy.logShown', { n: data.entries.length, file: escapeHtml(data.file) })}
            ${data.truncated ? ` · ${t('reverseproxy.logTruncated')}` : ''}
        </div>`;
}

function renderAccessTable(entries) {
    return `<table class="table table-vcenter card-table table-sm table-hover">
        <thead><tr>
            <th>${t('reverseproxy.logTime')}</th>
            <th>${t('reverseproxy.logClient')}</th>
            <th>${t('reverseproxy.logRequest')}</th>
            <th>${t('reverseproxy.logStatus')}</th>
            <th class="text-end">${t('reverseproxy.logBytes')}</th>
            <th>${t('reverseproxy.logAgent')}</th>
        </tr></thead>
        <tbody>${entries.map(e => e.status === undefined ? rawRow(e, 6) : `
            <tr>
                <td class="text-nowrap small">${escapeHtml(e.time)}</td>
                <td class="text-nowrap font-monospace small">${escapeHtml(e.ip)}${e.user ? ` <span class="text-secondary">(${escapeHtml(e.user)})</span>` : ''}</td>
                <td class="font-monospace small text-break">
                    ${e.method ? `<span class="badge bg-secondary-lt me-1">${escapeHtml(e.method)}</span>` : ''}${escapeHtml(e.path)}
                </td>
                <td><span class="badge ${statusClass(e.status)}">${e.status}</span></td>
                <td class="text-end text-nowrap small">${formatSize(e.bytes)}</td>
                <td class="small text-secondary text-truncate" style="max-width: 260px;" title="${escapeAttr(e.agent || '')}">${escapeHtml(e.agent || '–')}</td>
            </tr>`).join('')}
        </tbody>
    </table>`;
}

function renderErrorTable(entries) {
    return `<table class="table table-vcenter card-table table-sm table-hover">
        <thead><tr>
            <th>${t('reverseproxy.logTime')}</th>
            <th>${t('reverseproxy.logLevel')}</th>
            <th>${t('reverseproxy.logClient')}</th>
            <th>${t('reverseproxy.logMessage')}</th>
        </tr></thead>
        <tbody>${entries.map(e => e.level === undefined ? rawRow(e, 4) : `
            <tr>
                <td class="text-nowrap small">${escapeHtml(e.time)}</td>
                <td><span class="badge ${levelClass(e.level)}">${escapeHtml(e.level)}</span></td>
                <td class="text-nowrap font-monospace small">${escapeHtml(e.client || '–')}</td>
                <td class="font-monospace small text-break">${escapeHtml(e.message)}</td>
            </tr>`).join('')}
        </tbody>
    </table>`;
}

// Lines that do not match the expected nginx format are shown verbatim
function rawRow(e, colspan) {
    return `<tr><td colspan="${colspan}" class="font-monospace small text-break text-secondary">${escapeHtml(e.raw)}</td></tr>`;
}

function statusClass(status) {
    if (status >= 500) return 'bg-danger-lt';
    if (status >= 400) return 'bg-warning-lt';
    if (status >= 300) return 'bg-info-lt';
    return 'bg-success-lt';
}

function levelClass(level) {
    if (['emerg', 'alert', 'crit', 'error'].includes(level)) return 'bg-danger-lt';
    if (level === 'warn') return 'bg-warning-lt';
    return 'bg-secondary-lt';
}

function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

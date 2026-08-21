/**
 * MADMIN - Crontab Management View
 *
 * UI for viewing and managing crontab entries.
 */

import { apiGet, apiPost, apiPut, apiDelete, apiPatch } from '../api.js';
import { showToast, escapeHtml, escapeAttr, confirmDialog } from '../utils.js';
import { getUser } from '../app.js';
import { t } from '../i18n.js';

let presets = {};
let scripts = [];
let scriptContents = new Map();
let editingEntryId = null;

/**
 * Render the crontab view
 */
export async function render(container) {
    // Scheduling a job runs a command as root: superuser only, not a delegable
    // permission. cron.view governs the read-only side of this page.
    const canManage = getUser()?.is_superuser || false;

    container.innerHTML = `
        <div class="row row-deck row-cards">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">
                            <i class="ti ti-clock me-2"></i>${t('crontab.title')}
                        </h3>
                        <div class="card-actions">
                            ${canManage ? `
                            <button class="btn btn-primary" id="btn-add-cron">
                                <i class="ti ti-plus me-1"></i>${t('crontab.newJob')}
                            </button>
                            ` : ''}
                            <button class="btn btn-ghost-primary ms-2" id="btn-refresh-cron" title="${t('common.refresh')}">
                                <i class="ti ti-refresh"></i>
                            </button>
                        </div>
                    </div>
                    <div class="card-body" id="cron-container">
                        <div class="text-center py-4 text-muted">
                            <i class="ti ti-loader ti-spin" style="font-size: 2rem;"></i>
                            <p class="mt-2">${t('crontab.loadingCrontab')}</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Add Cron Modal -->
        <div class="modal" id="modal-add-cron" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="modal-add-cron-title">${t('crontab.newCronJob')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="row g-3">
                            <div class="col-12">
                                <label class="form-label">${t('crontab.preset')}</label>
                                <select class="form-select" id="cron-preset">
                                    <option value="">${t('crontab.custom')}</option>
                                </select>
                            </div>
                            <div class="col-12">
                                <label class="form-label">${t('crontab.schedule')}</label>
                                <div class="row g-2">
                                    <div class="col">
                                        <input type="text" class="form-control" id="cron-minute" placeholder="*" value="*">
                                        <small class="form-hint text-center">${t('crontab.minute')}</small>
                                    </div>
                                    <div class="col">
                                        <input type="text" class="form-control" id="cron-hour" placeholder="*" value="*">
                                        <small class="form-hint text-center">${t('crontab.hour')}</small>
                                    </div>
                                    <div class="col">
                                        <input type="text" class="form-control" id="cron-day" placeholder="*" value="*">
                                        <small class="form-hint text-center">${t('crontab.day')}</small>
                                    </div>
                                    <div class="col">
                                        <input type="text" class="form-control" id="cron-month" placeholder="*" value="*">
                                        <small class="form-hint text-center">${t('crontab.month')}</small>
                                    </div>
                                    <div class="col">
                                        <input type="text" class="form-control" id="cron-weekday" placeholder="*" value="*">
                                        <small class="form-hint text-center">${t('crontab.weekday')}</small>
                                    </div>
                                </div>
                            </div>
                            <div class="col-12">
                                <div class="alert alert-info mb-0" id="cron-preview">
                                    <i class="ti ti-clock me-2"></i>
                                    <code id="cron-preview-text">* * * * *</code>
                                </div>
                            </div>
                            <div class="col-12">
                                <label class="form-label">${t('crontab.script')}</label>
                                <div class="input-group">
                                    <select class="form-select" id="cron-script">
                                        <option value="">${t('crontab.selectScript')}</option>
                                    </select>
                                    <button type="button" class="btn btn-outline-secondary" id="btn-toggle-script-preview"
                                            title="${t('crontab.viewScript')}" disabled>
                                        <i class="ti ti-eye"></i>
                                    </button>
                                </div>
                                <small class="form-hint">${t('crontab.scriptHint')}</small>
                            </div>
                            <div class="col-12 d-none" id="cron-script-preview-wrap">
                                <label class="form-label d-flex justify-content-between align-items-center">
                                    <span>${t('crontab.scriptPreview')}</span>
                                    <code class="text-muted small" id="cron-script-preview-name"></code>
                                </label>
                                <pre id="cron-script-preview" class="p-3 bg-dark text-light rounded mb-0" style="max-height: 300px; overflow: auto; font-size: 0.85rem;"></pre>
                            </div>
                            <div class="col-12">
                                <label class="form-label">${t('crontab.arguments')}</label>
                                <input type="text" class="form-control" id="cron-args" placeholder="--verbose /tmp/out">
                                <small class="form-hint">${t('crontab.argumentsHint')}</small>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">${t('common.cancel')}</button>
                        <button type="button" class="btn btn-primary" id="btn-save-cron">${t('common.save')}</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Setup event listeners
    setupEventListeners();

    // Load crontab
    await loadCrontab();
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Refresh button
    document.getElementById('btn-refresh-cron')?.addEventListener('click', loadCrontab);

    // Add button
    document.getElementById('btn-add-cron')?.addEventListener('click', () => openCronModal());

    // Preset selector
    document.getElementById('cron-preset')?.addEventListener('change', (e) => {
        const value = e.target.value;
        if (value && presets[value]) {
            const parts = presets[value].split(' ');
            document.getElementById('cron-minute').value = parts[0];
            document.getElementById('cron-hour').value = parts[1];
            document.getElementById('cron-day').value = parts[2];
            document.getElementById('cron-month').value = parts[3];
            document.getElementById('cron-weekday').value = parts[4];
            updatePreview();
        }
    });

    // Schedule field changes
    ['cron-minute', 'cron-hour', 'cron-day', 'cron-month', 'cron-weekday'].forEach(id => {
        document.getElementById(id)?.addEventListener('input', updatePreview);
    });

    // Selecting a script only arms the eye: the preview is long and would
    // push the rest of the form off screen if it opened by itself.
    document.getElementById('cron-script')?.addEventListener('change', (e) => {
        const btn = document.getElementById('btn-toggle-script-preview');
        if (btn) btn.disabled = !e.target.value;
        closeScriptPreview();
    });

    document.getElementById('btn-toggle-script-preview')?.addEventListener('click', () => {
        const wrap = document.getElementById('cron-script-preview-wrap');
        if (!wrap) return;
        if (wrap.classList.contains('d-none')) {
            showScriptPreview(document.getElementById('cron-script')?.value || '');
        } else {
            closeScriptPreview();
        }
    });

    // Save button
    document.getElementById('btn-save-cron')?.addEventListener('click', saveCronJob);
}

/**
 * Update schedule preview
 */
function updatePreview() {
    const schedule = [
        document.getElementById('cron-minute')?.value || '*',
        document.getElementById('cron-hour')?.value || '*',
        document.getElementById('cron-day')?.value || '*',
        document.getElementById('cron-month')?.value || '*',
        document.getElementById('cron-weekday')?.value || '*'
    ].join(' ');

    document.getElementById('cron-preview-text').textContent = schedule;
}

/**
 * Load crontab entries
 */
async function loadCrontab() {
    const container = document.getElementById('cron-container');
    if (!container) return;

    try {
        const data = await apiGet('/cron/entries');
        const entries = data.entries || [];
        // The API returns presets as [{label, value}]; index them by label so the
        // preset <select> can look a schedule up by its key.
        presets = Object.fromEntries((data.presets || []).map(p => [p.label, p.value]));

        await loadScripts();

        // Populate preset dropdown
        const presetSelect = document.getElementById('cron-preset');
        if (presetSelect) {
            presetSelect.innerHTML = `<option value="">${t('crontab.custom')}</option>`;
            for (const [key, value] of Object.entries(presets)) {
                const i18nKey = `crontab.presetLabels.${key}`;
                const translated = t(i18nKey);
                const label = translated === i18nKey ? key : translated;
                presetSelect.innerHTML += `<option value="${key}">${label} (${value})</option>`;
            }
        }

        if (entries.length === 0) {
            container.innerHTML = `
                <div class="text-center py-4 text-muted">
                    <i class="ti ti-clock-off" style="font-size: 2rem;"></i>
                    <p class="mt-2">${t('crontab.noCronJobs')}</p>
                </div>
            `;
            return;
        }

        const canManage = getUser()?.is_superuser || false;

        container.innerHTML = `
            <div class="table-responsive">
                <table class="table table-vcenter">
                    <thead>
                        <tr>
                            <th>${t('crontab.state')}</th>
                            <th>${t('crontab.schedule')}</th>
                            <th>${t('common.description')}</th>
                            <th>${t('common.command')}</th>
                            <th class="w-1"></th>
                            ${canManage ? `<th class="w-1">${t('common.actions')}</th>` : ''}
                        </tr>
                    </thead>
                    <tbody>
                        ${entries.map((entry, index) => renderCronRow(entry, index, canManage)).join('')}
                    </tbody>
                </table>
            </div>
        `;

        // Setup row actions
        document.querySelectorAll('[data-toggle-cron]').forEach(btn => {
            btn.addEventListener('click', () => toggleCronJob(parseInt(btn.dataset.toggleCron)));
        });

        document.querySelectorAll('[data-delete-cron]').forEach(btn => {
            btn.addEventListener('click', () => deleteCronJob(parseInt(btn.dataset.deleteCron)));
        });

        document.querySelectorAll('[data-peek-cron]').forEach(btn => {
            btn.addEventListener('click', () => togglePeek(parseInt(btn.dataset.peekCron), btn.dataset.script));
        });

        document.querySelectorAll('[data-edit-cron]').forEach(btn => {
            btn.addEventListener('click', () => openCronModal(entries[parseInt(btn.dataset.editCron)], parseInt(btn.dataset.editCron)));
        });

    } catch (error) {
        console.error('Error loading crontab:', error);
        container.innerHTML = `
            <div class="text-center py-4 text-danger">
                <i class="ti ti-alert-circle" style="font-size: 2rem;"></i>
                <p class="mt-2">${t('crontab.errorLoadingCrontab', { error: error.message })}</p>
            </div>
        `;
    }
}

/**
 * Render a cron entry row
 */
function renderCronRow(entry, index, canManage) {
    const isEnabled = entry.enabled;
    // Entries added by hand over SSH may not point at an allowlisted script:
    // those stay read-only, with no eye and no edit button.
    const job = parseJobCommand(entry.command);
    const statusClass = isEnabled ? 'bg-success-lt' : 'bg-secondary-lt';
    const statusText = isEnabled ? t('common.active') : t('common.disabled');

    if (entry.comment && !entry.schedule) {
        // Comment-only row
        return `
            <tr class="text-muted">
                <td colspan="${canManage ? 6 : 5}">
                    <i class="ti ti-message-circle me-1"></i> ${escapeHtml(entry.comment)}
                </td>
            </tr>
        `;
    }

    return `
        <tr class="${isEnabled ? '' : 'table-secondary'}">
            <td>
                <span class="badge ${statusClass}">${statusText}</span>
            </td>
            <td>
                <code>${escapeHtml(entry.schedule || entry.raw || '')}</code>
            </td>
            <td>
                <small class="text-muted">${escapeHtml(entry.description || '')}</small>
            </td>
            <td>
                <code class="text-truncate d-inline-block" style="max-width: 300px;" title="${escapeHtml(entry.command || '')}">
                    ${escapeHtml(entry.command || '')}
                </code>
            </td>
            <td class="w-1">
                ${job ? `
                <button class="btn btn-sm btn-ghost-secondary" data-peek-cron="${index}"
                        data-script="${escapeAttr(job.script)}" title="${t('crontab.viewScript')}">
                    <i class="ti ti-eye"></i>
                </button>
                ` : ''}
            </td>
            ${canManage ? `
            <td>
                <div class="btn-group">
                    ${job ? `
                    <button class="btn btn-sm btn-outline-primary" data-edit-cron="${index}" title="${t('common.edit')}">
                        <i class="ti ti-pencil"></i>
                    </button>
                    ` : ''}
                    <button class="btn btn-sm btn-outline-${isEnabled ? 'warning' : 'success'}"
                            data-toggle-cron="${index}" title="${isEnabled ? t('crontab.disable') : t('crontab.enable')}">
                        <i class="ti ti-${isEnabled ? 'player-pause' : 'player-play'}"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger" data-delete-cron="${index}" title="${t('common.delete')}">
                        <i class="ti ti-trash"></i>
                    </button>
                </div>
            </td>
            ` : ''}
        </tr>
        <tr class="d-none" id="cron-peek-${index}">
            <td colspan="${canManage ? 6 : 5}" class="p-0">
                <pre class="p-3 mb-0 bg-dark text-light" style="max-height: 300px; overflow: auto; font-size: 0.85rem;"></pre>
            </td>
        </tr>
    `;
}

/**
 * Show or hide the script behind a job, inline under its row.
 */
async function togglePeek(index, name) {
    const row = document.getElementById(`cron-peek-${index}`);
    if (!row) return;

    const btn = document.querySelector(`[data-peek-cron="${index}"] i`);
    if (!row.classList.contains('d-none')) {
        row.classList.add('d-none');
        if (btn) btn.className = 'ti ti-eye';
        return;
    }

    row.classList.remove('d-none');
    if (btn) btn.className = 'ti ti-eye-off';

    const pre = row.querySelector('pre');
    if (scriptContents.has(name)) {
        pre.textContent = scriptContents.get(name);
        return;
    }

    pre.textContent = t('crontab.loadingScript');
    try {
        const data = await apiGet(`/cron/scripts/${encodeURIComponent(name)}`);
        scriptContents.set(name, data.content || '');
        pre.textContent = data.content || '';
    } catch (error) {
        pre.textContent = t('crontab.scriptLoadError', { error: error.message });
    }
}

/**
 * Load the scripts a job may run.
 *
 * The list comes from a directory MADMIN only reads: an operator with shell
 * access puts scripts there, which is what keeps the scheduler from running
 * arbitrary commands.
 */
async function loadScripts() {
    const select = document.getElementById('cron-script');
    if (!select) return;

    // A refresh may have changed the scripts on disk: drop the cached contents
    scriptContents = new Map();
    showScriptPreview('');

    try {
        scripts = await apiGet('/cron/scripts');
    } catch (error) {
        scripts = [];
    }

    if (scripts.length === 0) {
        select.innerHTML = `<option value="">${t('crontab.noScripts')}</option>`;
        return;
    }

    select.innerHTML = `<option value="">${t('crontab.selectScript')}</option>` +
        scripts.map(sc => {
            const label = sc.description ? `${sc.name} — ${sc.description}` : sc.name;
            return `<option value="${escapeHtml(sc.name)}">${escapeHtml(label)}</option>`;
        }).join('');
}

/**
 * Show the contents of the selected script.
 *
 * Read-only: the endpoint has no write counterpart, and the directory stays
 * off-limits to MADMIN. Contents are cached per script name for the lifetime
 * of the view so re-selecting does not refetch.
 */
async function showScriptPreview(name) {
    const wrap = document.getElementById('cron-script-preview-wrap');
    const pre = document.getElementById('cron-script-preview');
    const label = document.getElementById('cron-script-preview-name');
    if (!wrap || !pre) return;

    if (!name) {
        closeScriptPreview();
        return;
    }

    wrap.classList.remove('d-none');
    setPreviewIcon(true);
    if (label) label.textContent = name;
    pre.textContent = t('crontab.loadingScript');

    if (scriptContents.has(name)) {
        pre.textContent = scriptContents.get(name);
        return;
    }

    try {
        const data = await apiGet(`/cron/scripts/${encodeURIComponent(name)}`);
        const content = data.content || '';
        scriptContents.set(name, content);
        // The select may have moved on while the request was in flight
        if (document.getElementById('cron-script')?.value !== name) return;
        pre.textContent = content;
    } catch (error) {
        if (document.getElementById('cron-script')?.value !== name) return;
        pre.textContent = t('crontab.scriptLoadError', { error: error.message });
    }
}

function closeScriptPreview() {
    const wrap = document.getElementById('cron-script-preview-wrap');
    const pre = document.getElementById('cron-script-preview');
    const label = document.getElementById('cron-script-preview-name');
    if (!wrap) return;
    wrap.classList.add('d-none');
    if (pre) pre.textContent = '';
    if (label) label.textContent = '';
    setPreviewIcon(false);
}

function setPreviewIcon(open) {
    const icon = document.querySelector('#btn-toggle-script-preview i');
    if (icon) icon.className = open ? 'ti ti-eye-off' : 'ti ti-eye';
}

/**
 * Recover script + arguments from a crontab command line.
 *
 * The line was written by build_command, so it is the absolute script path
 * followed by shell-quoted arguments. Entries added by hand over SSH may not
 * match the scripts directory at all — those return null and stay read-only.
 */
function parseJobCommand(command) {
    if (!command) return null;

    const tokens = [];
    const re = /'([^']*)'|"([^"]*)"|(\S+)/g;
    let m;
    while ((m = re.exec(command)) !== null) {
        tokens.push(m[1] ?? m[2] ?? m[3]);
    }
    if (tokens.length === 0) return null;

    const name = tokens[0].split('/').pop();
    if (!scripts.some(sc => sc.name === name)) return null;

    return { script: name, args: tokens.slice(1) };
}

/**
 * Open the job modal, empty for a new job or filled in for an existing one.
 */
function openCronModal(entry = null, index = null) {
    editingEntryId = entry ? index : null;

    const title = document.getElementById('modal-add-cron-title');
    if (title) title.textContent = entry ? t('crontab.editCronJob') : t('crontab.newCronJob');

    const parts = (entry?.schedule || '* * * * *').split(/\s+/);
    const fields = ['cron-minute', 'cron-hour', 'cron-day', 'cron-month', 'cron-weekday'];
    fields.forEach((id, i) => {
        const el = document.getElementById(id);
        if (el) el.value = parts[i] || '*';
    });

    const job = entry ? parseJobCommand(entry.command) : null;
    const scriptSelect = document.getElementById('cron-script');
    if (scriptSelect) scriptSelect.value = job?.script || '';

    const argsInput = document.getElementById('cron-args');
    if (argsInput) argsInput.value = (job?.args || []).join(' ');

    const previewBtn = document.getElementById('btn-toggle-script-preview');
    if (previewBtn) previewBtn.disabled = !job?.script;
    closeScriptPreview();

    const presetSelect = document.getElementById('cron-preset');
    if (presetSelect) presetSelect.value = '';

    updatePreview();
    new bootstrap.Modal(document.getElementById('modal-add-cron')).show();
}

/**
 * Save the job — creating a new one or replacing the one being edited.
 */
async function saveCronJob() {
    const schedule = [
        document.getElementById('cron-minute')?.value || '*',
        document.getElementById('cron-hour')?.value || '*',
        document.getElementById('cron-day')?.value || '*',
        document.getElementById('cron-month')?.value || '*',
        document.getElementById('cron-weekday')?.value || '*'
    ].join(' ');

    const script = document.getElementById('cron-script')?.value;

    if (!script) {
        showToast(t('crontab.selectScript'), 'error');
        return;
    }

    // Split on whitespace; the backend quotes each argument for /bin/sh
    const rawArgs = document.getElementById('cron-args')?.value.trim() || '';
    const args = rawArgs ? rawArgs.split(/\s+/) : [];

    try {
        if (editingEntryId === null) {
            await apiPost('/cron/entries', { schedule, script, args });
            showToast(t('crontab.cronJobAdded'), 'success');
        } else {
            await apiPut(`/cron/entries/${editingEntryId}`, { schedule, script, args });
            showToast(t('crontab.cronJobUpdated'), 'success');
        }
        bootstrap.Modal.getInstance(document.getElementById('modal-add-cron'))?.hide();
        editingEntryId = null;
        await loadCrontab();
    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
    }
}

/**
 * Toggle cron job enabled/disabled
 */
async function toggleCronJob(entryId) {
    try {
        await apiPatch(`/cron/entries/${entryId}/toggle`, {});
        showToast(t('crontab.statusUpdated'), 'success');
        await loadCrontab();
    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
    }
}

/**
 * Delete a cron job
 */
async function deleteCronJob(entryId) {
    const confirmed = await confirmDialog(
        t('crontab.deleteCronJob'),
        t('crontab.deleteCronJobConfirm'),
        t('common.delete'),
        'btn-danger'
    );
    if (!confirmed) return;

    try {
        await apiDelete(`/cron/entries/${entryId}`);
        showToast(t('crontab.cronJobDeleted'), 'success');
        await loadCrontab();
    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
    }
}

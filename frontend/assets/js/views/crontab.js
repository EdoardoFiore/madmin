/**
 * MADMIN - Crontab Management View
 *
 * UI for viewing and managing crontab entries.
 */

import { apiGet, apiPost, apiDelete, apiPatch } from '../api.js';
import { showToast, escapeHtml, confirmDialog } from '../utils.js';
import { checkPermission } from '../app.js';
import { t } from '../i18n.js';

let presets = {};

/**
 * Render the crontab view
 */
export async function render(container) {
    const canManage = checkPermission('settings.manage');

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
                        <h5 class="modal-title">${t('crontab.newCronJob')}</h5>
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
                                <label class="form-label">${t('common.command')}</label>
                                <input type="text" class="form-control" id="cron-command" placeholder="/usr/bin/script.sh">
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
    document.getElementById('btn-add-cron')?.addEventListener('click', () => {
        const modal = new bootstrap.Modal(document.getElementById('modal-add-cron'));
        modal.show();
    });

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
        presets = data.presets || {};

        // Populate preset dropdown
        const presetSelect = document.getElementById('cron-preset');
        if (presetSelect) {
            presetSelect.innerHTML = `<option value="">${t('crontab.custom')}</option>`;
            for (const [key, value] of Object.entries(presets)) {
                const label = t(`crontab.presetLabels.${key}`) || key;
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

        const canManage = checkPermission('settings.manage');

        container.innerHTML = `
            <div class="table-responsive">
                <table class="table table-vcenter">
                    <thead>
                        <tr>
                            <th>${t('crontab.state')}</th>
                            <th>${t('crontab.schedule')}</th>
                            <th>${t('common.description')}</th>
                            <th>${t('common.command')}</th>
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
    const statusClass = isEnabled ? 'bg-success-lt' : 'bg-secondary-lt';
    const statusText = isEnabled ? t('common.active') : t('common.disabled');

    if (entry.comment && !entry.schedule) {
        // Comment-only row
        return `
            <tr class="text-muted">
                <td colspan="${canManage ? 5 : 4}">
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
            ${canManage ? `
            <td>
                <div class="btn-group">
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
    `;
}

/**
 * Save a new cron job
 */
async function saveCronJob() {
    const schedule = [
        document.getElementById('cron-minute')?.value || '*',
        document.getElementById('cron-hour')?.value || '*',
        document.getElementById('cron-day')?.value || '*',
        document.getElementById('cron-month')?.value || '*',
        document.getElementById('cron-weekday')?.value || '*'
    ].join(' ');

    const command = document.getElementById('cron-command')?.value.trim();

    if (!command) {
        showToast(t('crontab.enterCommand'), 'error');
        return;
    }

    try {
        await apiPost('/cron/entries', { schedule, command });
        showToast(t('crontab.cronJobAdded'), 'success');
        bootstrap.Modal.getInstance(document.getElementById('modal-add-cron'))?.hide();
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

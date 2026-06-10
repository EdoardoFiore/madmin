/**
 * MADMIN - Crontab Management View
 *
 * UI for viewing and managing crontab entries.
 * Pilot view for the shared component layer (modal, data-table, skeleton).
 */

import { apiGet, apiPost, apiDelete, apiPatch } from '../api.js';
import { showToast, escapeHtml, confirmDialog, emptyState, statusBadge } from '../utils.js';
import { checkPermission } from '../app.js';
import { t } from '../i18n.js';
import { openModal } from '../components/modal.js';
import { createTable } from '../components/data-table.js';
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
                    <div class="card-body" id="cron-container"></div>
                </div>
            </div>
        </div>
    `;

    document.getElementById('btn-refresh-cron')?.addEventListener('click', loadCrontab);
    document.getElementById('btn-add-cron')?.addEventListener('click', openAddCronModal);

    await loadCrontab();
}

/**
 * Load crontab entries and render the table
 */
async function loadCrontab() {
    const container = document.getElementById('cron-container');
    if (!container) return;

    try {
        const data = await apiGet('/cron/entries');
        presets = data.presets || {};
        const canManage = checkPermission('settings.manage');
        // The backend addresses entries by their position in the list
        const entries = (data.entries || []).map((entry, index) => ({ ...entry, _index: index }));

        const table = createTable({
            columns: [
                { key: 'enabled', label: t('crontab.state'), render: (e) => statusBadge(e.enabled) },
                { key: 'schedule', label: t('crontab.schedule'), render: (e) => `<code>${escapeHtml(e.schedule || e.raw || '')}</code>` },
                { key: 'description', label: t('common.description'), render: (e) => `<small class="text-muted">${escapeHtml(e.description || '')}</small>` },
                {
                    key: 'command', label: t('common.command'),
                    render: (e) => `<code class="text-truncate d-inline-block" style="max-width: 300px;" title="${escapeHtml(e.command || '')}">${escapeHtml(e.command || '')}</code>`,
                },
            ],
            rows: entries,
            rowKey: '_index',
            rowClass: (e) => e.enabled ? '' : 'table-secondary',
            rowRender: (e, idx, colCount) => {
                if (e.comment && !e.schedule) {
                    return `
                        <tr class="text-muted">
                            <td colspan="${colCount}">
                                <i class="ti ti-message-circle me-1"></i> ${escapeHtml(e.comment)}
                            </td>
                        </tr>`;
                }
                return null;
            },
            rowActions: canManage ? [
                {
                    action: 'toggle',
                    icon: 'ti-player-pause',
                    className: 'btn-outline-warning',
                    title: t('crontab.disable'),
                    visible: (e) => e.enabled,
                },
                {
                    action: 'toggle',
                    icon: 'ti-player-play',
                    className: 'btn-outline-success',
                    title: t('crontab.enable'),
                    visible: (e) => !e.enabled,
                },
                { action: 'delete', icon: 'ti-trash', className: 'btn-outline-danger', title: t('common.delete') },
            ] : null,
            empty: { icon: 'ti-clock-off', title: t('crontab.noCronJobs') },
        });

        container.innerHTML = table.html;
        table.mount(container, {
            onAction(action, entry) {
                if (action === 'toggle') toggleCronJob(entry._index);
                else if (action === 'delete') deleteCronJob(entry._index);
            },
        });

    } catch (error) {
        console.error('Error loading crontab:', error);
        container.innerHTML = `
            <div class="text-center py-4 text-danger">
                <i class="ti ti-alert-circle" style="font-size: 2rem;"></i>
                <p class="mt-2">${t('crontab.errorLoadingCrontab', { error: escapeHtml(error.message) })}</p>
            </div>
        `;
    }
}

/**
 * Open the add-job modal: preset selector, 5 schedule fields, live preview
 */
function openAddCronModal() {
    const presetOptions = Object.entries(presets).map(([key, value]) => {
        const label = t(`crontab.presetLabels.${key}`) || key;
        return `<option value="${escapeHtml(key)}">${escapeHtml(label)} (${escapeHtml(value)})</option>`;
    }).join('');

    const scheduleField = (id, hint) => `
        <div class="col">
            <input type="text" class="form-control" data-cron="${id}" placeholder="*" value="*">
            <small class="form-hint text-center">${hint}</small>
        </div>`;

    openModal({
        title: t('crontab.newCronJob'),
        size: 'lg',
        body: `
            <div class="row g-3">
                <div class="col-12">
                    <label class="form-label">${t('crontab.preset')}</label>
                    <select class="form-select" data-cron="preset">
                        <option value="">${t('crontab.custom')}</option>
                        ${presetOptions}
                    </select>
                </div>
                <div class="col-12">
                    <label class="form-label">${t('crontab.schedule')}</label>
                    <div class="row g-2">
                        ${scheduleField('minute', t('crontab.minute'))}
                        ${scheduleField('hour', t('crontab.hour'))}
                        ${scheduleField('day', t('crontab.day'))}
                        ${scheduleField('month', t('crontab.month'))}
                        ${scheduleField('weekday', t('crontab.weekday'))}
                    </div>
                </div>
                <div class="col-12">
                    <div class="alert alert-info mb-0">
                        <i class="ti ti-clock me-2"></i>
                        <code data-cron="preview">* * * * *</code>
                    </div>
                </div>
                <div class="col-12">
                    <label class="form-label">${t('common.command')}</label>
                    <input type="text" class="form-control" data-cron="command" placeholder="/usr/bin/script.sh">
                </div>
            </div>
        `,
        footer: `
            <button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.cancel')}</button>
            <button type="button" class="btn btn-primary" data-action="save">${t('common.save')}</button>
        `,
        onShown(ctx) {
            const field = (id) => ctx.bodyEl.querySelector(`[data-cron="${id}"]`);
            const parts = ['minute', 'hour', 'day', 'month', 'weekday'];
            const updatePreview = () => {
                field('preview').textContent = parts.map(p => field(p).value || '*').join(' ');
            };

            field('preset').addEventListener('change', (e) => {
                const preset = presets[e.target.value];
                if (!preset) return;
                preset.split(' ').forEach((value, i) => { field(parts[i]).value = value; });
                updatePreview();
            });
            parts.forEach(p => field(p).addEventListener('input', updatePreview));
        },
        async onAction(action, ctx) {
            if (action !== 'save') return;
            const field = (id) => ctx.bodyEl.querySelector(`[data-cron="${id}"]`);
            const schedule = ['minute', 'hour', 'day', 'month', 'weekday']
                .map(p => field(p).value || '*').join(' ');
            const command = field('command').value.trim();

            if (!command) {
                showToast(t('crontab.enterCommand'), 'error');
                return;
            }

            ctx.setBusy('[data-action="save"]', true);
            try {
                await apiPost('/cron/entries', { schedule, command });
                showToast(t('crontab.cronJobAdded'), 'success');
                ctx.hide();
                await loadCrontab();
            } catch (error) {
                ctx.setBusy('[data-action="save"]', false);
                showToast(t('common.errorPrefix') + error.message, 'error');
            }
        },
    });
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

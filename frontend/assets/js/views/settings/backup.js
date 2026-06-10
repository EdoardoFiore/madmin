/**
 * MADMIN - Settings View / backup & restore (scheduled config, local history,
 * restore-from-local preview). Remote history lives in remote-backup.js.
 */

import { apiGet, apiPatch, apiPost } from '../../api.js';
import { showToast, confirmDialog, escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';
import { openModal } from '../../components/modal.js';
import { loadRemoteBackupHistory, formatFileSize } from './remote-backup.js';

export function backupHtml(canManage) {
    return `
        <div class="col-12">
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title"><i class="ti ti-database-export me-2"></i>Backup & ${t('settings.restore')}</h3>
                    <div class="card-actions">
                        ${canManage ? `
                        <div class="btn-group">
                            <button class="btn btn-primary btn-sm" id="backup-local-btn">
                                <i class="ti ti-device-floppy me-1"></i>${t('settings.localBackup')}
                            </button>
                            <button class="btn btn-cyan btn-sm" id="backup-remote-btn" style="display:none">
                                <i class="ti ti-cloud-upload me-1"></i>${t('settings.remoteBackup')}
                            </button>
                        </div>
                        <button class="btn btn-warning btn-sm ms-2" id="open-import-modal-btn">
                            <i class="ti ti-file-import me-1"></i>${t('settings.restore')}...
                        </button>
                        ` : ''}
                    </div>
                </div>
                <div class="card-body">
                    <!-- Last backup status -->
                    <div class="alert alert-info mb-3" id="backup-status-alert">
                        <div class="d-flex align-items-center">
                            <i class="ti ti-info-circle me-2"></i>
                            <span id="backup-last-status">${t('common.loading')}</span>
                        </div>
                    </div>

                    <!-- Scheduled Backup Settings -->
                    <h4 class="mb-3"><i class="ti ti-clock me-2"></i>${t('settings.scheduledBackup')}</h4>
                    <div class="row g-3">
                        <div class="col-md-2">
                            <label class="form-check form-switch">
                                <input class="form-check-input" type="checkbox" id="backup-enabled" ${canManage ? '' : 'disabled'}>
                                <span class="form-check-label">${t('settings.automatic')}</span>
                            </label>
                        </div>
                        <div class="col-md-2">
                            <label class="form-label">${t('settings.backupFrequency')}</label>
                            <select class="form-select" id="backup-frequency" ${canManage ? '' : 'disabled'}>
                                <option value="daily">${t('settings.daily')}</option>
                                <option value="weekly">${t('settings.weekly')}</option>
                            </select>
                        </div>
                        <div class="col-md-2">
                            <label class="form-label">${t('settings.backupTime')}</label>
                            <input type="time" class="form-control" id="backup-time" ${canManage ? '' : 'disabled'}>
                        </div>
                        <div class="col-md-2">
                            <label class="form-label">${t('settings.retention')}</label>
                            <input type="number" class="form-control" id="backup-retention" min="0" placeholder="30" ${canManage ? '' : 'disabled'}>
                            <small class="form-hint">${t('settings.retentionUnlimited')}</small>
                        </div>
                        <div class="col-md-2">
                            <label class="form-label">${t('settings.remoteProtocol')}</label>
                            <select class="form-select" id="backup-protocol" ${canManage ? '' : 'disabled'}>
                                <option value="sftp">SFTP</option>
                                <option value="ftp">FTP</option>
                            </select>
                        </div>
                        <div class="col-md-2">
                            <label class="form-label">${t('settings.remotePort')}</label>
                            <input type="number" class="form-control" id="backup-port" ${canManage ? '' : 'disabled'}>
                        </div>
                        <div class="col-md-4">
                            <label class="form-label">${t('settings.remoteHost')}</label>
                            <input type="text" class="form-control" id="backup-host" ${canManage ? '' : 'disabled'}>
                        </div>
                        <div class="col-md-4">
                            <label class="form-label">${t('settings.remotePath')}</label>
                            <input type="text" class="form-control" id="backup-path" ${canManage ? '' : 'disabled'}>
                        </div>
                        <div class="col-md-2">
                            <label class="form-label">${t('settings.remoteUser')}</label>
                            <input type="text" class="form-control" id="backup-user" ${canManage ? '' : 'disabled'}>
                        </div>
                        <div class="col-md-2">
                            <label class="form-label">${t('settings.remotePassword')}</label>
                            <input type="password" class="form-control" id="backup-password" placeholder="••••••••" ${canManage ? '' : 'disabled'}>
                        </div>
                        <div class="col-12">
                            ${canManage ? `<button class="btn btn-primary" id="save-backup">${t('settings.saveConfig')}</button>` : ''}
                        </div>
                    </div>

                    <!-- Local Backup History -->
                    <hr class="my-4">
                    <h4 class="mb-3"><i class="ti ti-history me-2"></i>${t('settings.localBackups')}</h4>
                    <div class="table-responsive">
                        <table class="table table-vcenter">
                            <thead>
                                <tr>
                                    <th>${t('settings.backupTableFile')}</th>
                                    <th>${t('settings.fileSize')}</th>
                                    <th>${t('settings.fileDate')}</th>
                                    <th class="text-end">${t('common.actions')}</th>
                                </tr>
                            </thead>
                            <tbody id="backup-history-body">
                                <tr><td colspan="4" class="text-center text-muted">${t('common.loading')}</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- Remote Backup History -->
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h4 class="card-title m-0"><i class="ti ti-cloud me-2"></i>${t('settings.remoteBackups')}</h4>
                    ${canManage ? `
                    <button class="btn btn-sm btn-outline-warning" id="cleanup-remote-btn" title="${t('settings.cleanupBtn')}">
                        <i class="ti ti-trash me-1"></i>${t('settings.cleanupBtn')}
                    </button>` : ''}
                </div>
                <div class="card-body pt-2">
                    <div class="table-responsive">
                        <table class="table table-vcenter card-table">
                            <thead>
                                <tr>
                                    <th>${t('settings.backupTableFile')}</th>
                                    <th>${t('settings.fileSize')}</th>
                                    <th>${t('settings.fileDate')}</th>
                                    <th class="text-end">${t('common.actions')}</th>
                                </tr>
                            </thead>
                            <tbody id="remote-backup-history-body">
                                <tr><td colspan="4" class="text-center text-muted">${t('common.loading')}</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    `;
}

export function fillBackup(backup) {
    document.getElementById('backup-enabled').checked = backup.enabled;
    document.getElementById('backup-frequency').value = backup.frequency || 'daily';
    document.getElementById('backup-time').value = backup.time || '03:00';
    document.getElementById('backup-retention').value = backup.retention_days || 30;
    document.getElementById('backup-protocol').value = backup.remote_protocol || 'sftp';
    document.getElementById('backup-host').value = backup.remote_host || '';
    document.getElementById('backup-port').value = backup.remote_port || 22;
    document.getElementById('backup-path').value = backup.remote_path || '/';
    document.getElementById('backup-user').value = backup.remote_user || '';

    // Last backup status
    const statusEl = document.getElementById('backup-last-status');
    const alertEl = document.getElementById('backup-status-alert');
    if (backup.last_run_time) {
        const date = new Date(backup.last_run_time).toLocaleString(undefined);
        const status = backup.last_run_status === 'success' ? t('common.success').toLowerCase() : backup.last_run_status;
        statusEl.textContent = t('settings.lastBackupStatus', { date, status });
        alertEl.className = backup.last_run_status === 'success' ? 'alert alert-success mb-3' : 'alert alert-warning mb-3';
    } else {
        statusEl.textContent = t('settings.noBackupRun');
    }

    // Show remote backup button only if remote is configured
    const remoteBtn = document.getElementById('backup-remote-btn');
    if (remoteBtn) {
        remoteBtn.style.display = (backup.remote_host && backup.remote_user) ? '' : 'none';
    }
}

export function bindBackup() {
    // Save backup settings
    document.getElementById('save-backup')?.addEventListener('click', async () => {
        try {
            const data = {
                enabled: document.getElementById('backup-enabled').checked,
                frequency: document.getElementById('backup-frequency').value,
                time: document.getElementById('backup-time').value,
                retention_days: parseInt(document.getElementById('backup-retention').value) || 30,
                remote_protocol: document.getElementById('backup-protocol').value,
                remote_host: document.getElementById('backup-host').value,
                remote_port: parseInt(document.getElementById('backup-port').value),
                remote_path: document.getElementById('backup-path').value,
                remote_user: document.getElementById('backup-user').value
            };
            const pwd = document.getElementById('backup-password').value;
            if (pwd) data.remote_password = pwd;

            await apiPatch('/settings/backup', data);
            showToast(t('settings.backupSaved'), 'success');
        } catch (e) { showToast(e.message, 'error'); }
    });

    // Local backup - exports and saves on server
    document.getElementById('backup-local-btn')?.addEventListener('click', async () => {
        const btn = document.getElementById('backup-local-btn');
        const originalText = btn.innerHTML;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('settings.backupInProgress')}`;
        btn.disabled = true;

        try {
            await apiPost('/backup/export', {});
            showToast(t('settings.backupCompleted'), 'success');
            await loadBackupHistory();
        } catch (e) {
            showToast(t('settings.backupError', { error: e.message }), 'error');
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });

    // Remote backup - exports + uploads to configured remote
    document.getElementById('backup-remote-btn')?.addEventListener('click', async () => {
        const btn = document.getElementById('backup-remote-btn');
        const originalText = btn.innerHTML;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('settings.backupInProgress')}`;
        btn.disabled = true;

        try {
            const result = await apiPost('/backup/run', {});
            if (result.success) {
                showToast(t('settings.remoteBackupCompleted'), 'success');
                await loadBackupHistory();
                await loadRemoteBackupHistory();
            } else {
                showToast(t('settings.remoteBackupWithErrors', { errors: (result.errors || []).join(', ') }), 'warning');
            }
        } catch (e) {
            showToast(t('settings.remoteBackupError', { error: e.message }), 'error');
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });

    // Local backup history: one delegated listener for restore/download/delete
    document.getElementById('backup-history-body')?.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        const filename = btn.dataset.filename;
        if (btn.dataset.action === 'restore') restoreFromLocalBackup(filename);
        else if (btn.dataset.action === 'download') downloadLocalBackup(filename);
        else if (btn.dataset.action === 'delete') deleteBackup(filename);
    });
}

export async function loadBackupHistory() {
    const tbody = document.getElementById('backup-history-body');
    if (!tbody) return;

    try {
        const history = await apiGet('/backup/history');

        if (history.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">${t('settings.noLocalBackups')}</td></tr>`;
            return;
        }

        tbody.innerHTML = history.map(backup => `
            <tr>
                <td><i class="ti ti-file-zip me-2"></i>${escapeHtml(backup.filename)}</td>
                <td>${formatFileSize(backup.size_bytes)}</td>
                <td>${new Date(backup.created_at).toLocaleString(undefined)}</td>
                <td class="text-end">
                    <button class="btn btn-sm btn-ghost-warning" data-action="restore" data-filename="${escapeHtml(backup.filename)}" title="${t('settings.restore')}">
                        <i class="ti ti-refresh"></i>
                    </button>
                    <button class="btn btn-sm btn-ghost-primary" data-action="download" data-filename="${escapeHtml(backup.filename)}" title="${t('common.download')}">
                        <i class="ti ti-download"></i>
                    </button>
                    <button class="btn btn-sm btn-ghost-danger" data-action="delete" data-filename="${escapeHtml(backup.filename)}" title="${t('common.delete')}">
                        <i class="ti ti-trash"></i>
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="4" class="text-center text-danger">${t('settings.backupHistoryError')}</td></tr>`;
    }
}

async function downloadLocalBackup(filename) {
    try {
        const response = await fetch(`/api/backup/download/${filename}`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` }
        });

        if (!response.ok) throw new Error('Download failed');

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function deleteBackup(filename) {
    const confirmed = await confirmDialog(
        t('settings.deleteFileTitle'),
        t('settings.deleteFileConfirm', { filename }),
        t('common.delete'),
        'btn-danger'
    );
    if (!confirmed) return;

    try {
        await fetch(`/api/backup/delete/${filename}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` }
        });
        showToast(t('settings.fileDeleted'), 'success');
        await loadBackupHistory();
    } catch (e) {
        showToast(t('settings.fileDeleteError', { error: e.message }), 'error');
    }
}

// ============== RESTORE FROM LOCAL BACKUP ==============

async function restoreFromLocalBackup(filename) {
    try {
        const response = await fetch(`/api/backup/restore/preview/${encodeURIComponent(filename)}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` }
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Preview failed');
        }

        const preview = await response.json();
        showRestorePreviewModal(preview, filename);
    } catch (e) {
        showToast(t('settings.previewError', { error: e.message }), 'error');
    }
}

function showRestorePreviewModal(preview, filename) {
    const versionWarning = preview.source_version !== preview.current_version
        ? `<div class="alert alert-warning mb-3">
            <i class="ti ti-alert-triangle me-2"></i>
            ${t('settings.versionMismatch', { source: preview.source_version, current: preview.current_version })}
           </div>`
        : '';

    const coreUsers = (preview.core?.users || []).map(u => {
        const roleLabel = u.is_superuser ? 'Super Admin' : t('logs.user');
        const roleColor = u.is_superuser ? 'bg-red-lt' : 'bg-blue-lt';
        return `<tr>
            <td><i class="ti ti-user me-1"></i>${escapeHtml(u.username)}</td>
            <td><span class="badge ${roleColor}">${roleLabel}</span></td>
        </tr>`;
    }).join('');

    const modulesHtml = Object.entries(preview.modules || {}).map(([modId, modData]) => {
        const tablesHtml = Object.entries(modData.tables || {}).map(([table, count]) =>
            `<div class="d-flex justify-content-between"><span class="text-muted small">${escapeHtml(table)}</span><span class="badge bg-blue-lt">${count}</span></div>`
        ).join('');

        return `
            <div class="col-md-6">
                <div class="card card-sm">
                    <div class="card-body py-2">
                        <div class="d-flex align-items-center mb-1">
                            <span class="avatar avatar-xs bg-purple-lt me-2"><i class="ti ti-puzzle"></i></span>
                            <strong class="small">${escapeHtml(modId)}</strong>
                            ${modData.has_files ? '<span class="badge bg-cyan-lt ms-auto">+ file</span>' : ''}
                        </div>
                        ${tablesHtml}
                    </div>
                </div>
            </div>`;
    }).join('');

    const ctx = openModal({
        title: t('settings.restoreConfirmTitle'),
        size: 'lg',
        body: `
            ${versionWarning}

            <div class="d-flex gap-2 mb-3">
                <span class="badge bg-blue-lt">v${escapeHtml(String(preview.source_version))}</span>
                <span class="badge bg-secondary-lt">${new Date(preview.timestamp).toLocaleString(undefined)}</span>
                <span class="badge bg-secondary-lt">${escapeHtml(filename)}</span>
            </div>

            <div class="row g-2 mb-3">
                <div class="col-12">
                    <div class="card card-sm">
                        <div class="card-body py-2">
                            <div class="d-flex align-items-center">
                                <span class="avatar avatar-xs bg-green-lt me-2"><i class="ti ti-users"></i></span>
                                <strong class="small">${t('settings.importUsers', { count: preview.core?.users?.length || 0 })}</strong>
                            </div>
                            ${coreUsers ? `<table class="table table-sm mb-0 mt-1"><tbody>${coreUsers}</tbody></table>` : ''}
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card card-sm">
                        <div class="card-body py-2 d-flex align-items-center">
                            <span class="avatar avatar-xs bg-orange-lt me-2"><i class="ti ti-shield"></i></span>
                            <strong class="small">Firewall</strong>
                            <span class="badge bg-orange-lt ms-auto">${preview.core?.firewall_rules || 0}</span>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card card-sm">
                        <div class="card-body py-2 d-flex align-items-center">
                            <span class="avatar avatar-xs bg-cyan-lt me-2"><i class="ti ti-adjustments"></i></span>
                            <strong class="small">${t('settings.importCoreSettings')}</strong>
                            <span class="badge bg-cyan-lt ms-auto">${escapeHtml(preview.core?.settings?.company_name || '-')}</span>
                        </div>
                    </div>
                </div>
            </div>

            ${modulesHtml ? `
            <h4 class="mb-2"><i class="ti ti-puzzle me-1"></i>${t('settings.importModules')}</h4>
            <div class="row g-2">${modulesHtml}</div>
            ` : ''}

            <div class="alert alert-danger mt-3 mb-0">
                <i class="ti ti-alert-circle me-2"></i>
                <strong>${t('common.warning')}!</strong> ${t('settings.restoreWarning')}
            </div>
        `,
        footer: `
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">${t('common.cancel')}</button>
            <button type="button" class="btn btn-warning" data-action="restore">
                <i class="ti ti-refresh me-1"></i>${t('settings.restoreConfirmBtn')}
            </button>
        `,
        async onAction(action, mctx) {
            if (action !== 'restore') return;
            mctx.hide();
            showToast(t('settings.restoreInProgress'), 'info');

            try {
                const result = await apiPost(`/backup/restore/${encodeURIComponent(filename)}`, {});

                if (result.success !== false) {
                    showToast(
                        t('settings.restoreCompleted', {
                            users: result.users_imported || 0,
                            rules: result.firewall_rules_imported || 0,
                            modules: result.modules_imported?.length || 0
                        }) + '. ' + t('settings.importRestarting'),
                        'success'
                    );
                    setTimeout(() => location.reload(), 5000);
                } else {
                    showToast(t('settings.restoreFailed', { errors: (result.errors || []).join(', ') }), 'error');
                }
            } catch (err) {
                showToast(t('settings.restoreError', { error: err.message }), 'error');
            }
        },
    });

    ctx.el.querySelector('.modal-header').classList.add('bg-warning-lt');
    ctx.el.querySelector('.modal-dialog').classList.add('modal-dialog-centered', 'modal-dialog-scrollable');
}

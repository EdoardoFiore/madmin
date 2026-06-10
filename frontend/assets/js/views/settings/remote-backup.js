/**
 * MADMIN - Settings View / remote backup history (list, download, delete, cleanup)
 */

import { apiGet, apiPost, apiDelete } from '../../api.js';
import { showToast, confirmDialog, escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';

export function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

export async function loadRemoteBackupHistory() {
    const tbody = document.getElementById('remote-backup-history-body');
    if (!tbody) return;

    // Pre-flight check: avoid 400 Bad Request if remote is obviously not configured
    const protocol = document.getElementById('backup-protocol')?.value;
    const host = document.getElementById('backup-host')?.value;
    if (!protocol || protocol === 'none' || !host) {
        tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">${t('settings.remoteNotConfigured')}</td></tr>`;
        return;
    }

    try {
        const history = await apiGet('/backup/remote/list');

        if (history.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">${t('settings.noRemoteBackups')}</td></tr>`;
            return;
        }

        tbody.innerHTML = history.map(backup => `
            <tr>
                <td><i class="ti ti-cloud me-2"></i>${escapeHtml(backup.filename)}</td>
                <td>${formatFileSize(backup.size_bytes)}</td>
                <td>${backup.mtime ? new Date(backup.mtime).toLocaleString(undefined) : '-'}</td>
                <td class="text-end">
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
        tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">${t('settings.remoteNotConfigured')}</td></tr>`;
    }
}

/**
 * Bind the remote history delegated actions and the cleanup button.
 * onLocalHistoryChanged is called after a remote download lands a new local file.
 */
export function bindRemoteBackup({ onLocalHistoryChanged }) {
    document.getElementById('remote-backup-history-body')?.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        const filename = btn.dataset.filename;

        if (btn.dataset.action === 'download') {
            try {
                showToast(t('settings.downloadInProgress'), 'info');
                await apiPost(`/backup/remote/download/${filename}`, {});
                showToast(t('settings.downloadedLocally'), 'success');
                await onLocalHistoryChanged();
            } catch (err) {
                showToast(t('settings.downloadError', { error: err.message }), 'error');
            }
        } else if (btn.dataset.action === 'delete') {
            const confirmed = await confirmDialog(
                t('settings.deleteRemoteConfirmTitle'),
                t('settings.deleteRemoteConfirmMsg', { filename }),
                t('common.delete'),
                'btn-danger'
            );
            if (!confirmed) return;

            try {
                await apiDelete(`/backup/remote/delete/${filename}`);
                showToast(t('settings.remoteBackupDeleted'), 'success');
                await loadRemoteBackupHistory();
            } catch (err) {
                showToast(t('settings.fileDeleteError', { error: err.message }), 'error');
            }
        }
    });

    document.getElementById('cleanup-remote-btn')?.addEventListener('click', async () => {
        const confirmed = await confirmDialog(
            t('settings.cleanupConfirmTitle'),
            t('settings.cleanupConfirmMsg'),
            t('settings.cleanupApply'),
            'btn-warning'
        );
        if (!confirmed) return;

        try {
            const result = await apiPost('/backup/remote/cleanup', {});
            showToast(t('settings.cleanupDone', { count: result.deleted_count }), 'success');
            await loadRemoteBackupHistory();
        } catch (e) {
            showToast(t('settings.cleanupError', { error: e.message }), 'error');
        }
    });
}

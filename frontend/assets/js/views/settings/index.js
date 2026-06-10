/**
 * MADMIN - Settings View
 *
 * Composed from independent section submodules, each exporting
 * <section>Html(), fill<Section>(data) and bind<Section>():
 * appearance, preferences, security (port/password/SSL), smtp,
 * backup (+ remote-backup), export-import (restore modal).
 */

import { apiGet } from '../../api.js';
import { showToast } from '../../utils.js';
import { checkPermission } from '../../app.js';
import { t } from '../../i18n.js';
import { apiPost } from '../../api.js';
import { confirmDialog } from '../../utils.js';
import { appearanceHtml, fillAppearance, bindAppearance } from './appearance.js';
import { preferencesHtml, fillPreferences, bindPreferences } from './preferences.js';
import { securityHtml, sslModalHtml, fillSecurity, bindSecurity } from './security.js';
import { smtpHtml, fillSmtp, bindSmtp } from './smtp.js';
import { backupHtml, fillBackup, bindBackup, loadBackupHistory } from './backup.js';
import { loadRemoteBackupHistory, bindRemoteBackup } from './remote-backup.js';
import { importModalHtml, bindImportModal } from './export-import.js';

/**
 * Render the settings view
 */
export async function render(container) {
    const canManage = checkPermission('settings.manage');

    container.innerHTML = `
        <div class="row row-deck row-cards">
            ${appearanceHtml(canManage)}
            ${preferencesHtml()}
            ${securityHtml(canManage)}
            ${smtpHtml(canManage)}
            ${backupHtml(canManage)}
            ${importModalHtml()}
            ${systemManagementHtml(canManage)}
        </div>
        ${sslModalHtml()}
    `;

    await loadSettings();

    bindAppearance();
    bindPreferences();
    bindSecurity();
    bindSmtp();
    bindBackup();
    bindRemoteBackup({ onLocalHistoryChanged: loadBackupHistory });
    bindImportModal();
    bindSystemManagement();
}

async function loadSettings() {
    try {
        const [system, smtp, backup, network] = await Promise.all([
            apiGet('/settings/system'),
            apiGet('/settings/smtp'),
            apiGet('/settings/backup'),
            apiGet('/settings/network')
        ]);

        fillAppearance(system);
        fillPreferences();
        fillSecurity(system, network);
        fillSmtp(smtp);
        fillBackup(backup);

        await loadBackupHistory();
        await loadRemoteBackupHistory();

    } catch (error) {
        showToast(t('settings.settingsLoadError'), 'error');
    }
}

// ============== SYSTEM MANAGEMENT (service restart) ==============

function systemManagementHtml(canManage) {
    return `
        <div class="col-12">
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title"><i class="ti ti-server me-2"></i>${t('settings.systemManagement')}</h3>
                </div>
                <div class="card-body">
                    <div class="row g-3 align-items-center">
                        <div class="col-md-8">
                            <h4 class="mb-1">${t('settings.restartMadmin')}</h4>
                            <p class="text-muted mb-0">${t('settings.restartService')}</p>
                        </div>
                        <div class="col-md-4 text-end">
                            ${canManage ? `
                            <button class="btn btn-warning" id="btn-restart-madmin">
                                <i class="ti ti-refresh me-1"></i>${t('settings.restartMadmin')}
                            </button>
                            ` : `<span class="text-muted">${t('settings.insufficientPerms')}</span>`}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function bindSystemManagement() {
    document.getElementById('btn-restart-madmin')?.addEventListener('click', async () => {
        const confirmed = await confirmDialog(
            t('settings.restartMadmin'),
            t('settings.restartConfirm'),
            t('settings.restartMadmin'),
            'btn-warning'
        );
        if (!confirmed) return;

        const btn = document.getElementById('btn-restart-madmin');
        const originalText = btn.innerHTML;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('settings.portChanging')}`;
        btn.disabled = true;

        try {
            await apiPost('/services/madmin.service/restart', {});
            showToast(t('settings.serviceRestarted'), 'success');
            setTimeout(() => {
                location.reload();
            }, 5000);
        } catch (e) {
            showToast(t('settings.restartError', { error: e.message }), 'error');
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });
}

/**
 * MADMIN - Firewall View / rules export-import
 */

import { apiFetch } from '../../api.js';
import { showToast } from '../../utils.js';
import { t } from '../../i18n.js';
import { openModal } from '../../components/modal.js';

/**
 * Download all rules as JSON
 */
export async function handleExport() {
    try {
        const response = await apiFetch('/firewall/export');
        if (!response.ok) throw new Error('Export failed');

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'firewall_rules.json';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();
    } catch (error) {
        showToast(t('firewall.exportError', { error: error.message }), 'error');
    }
}

/**
 * Open the import modal (file + append/replace mode)
 */
export function openImportModal(state) {
    openModal({
        title: t('firewall.importRules'),
        body: `
            <div class="mb-3">
                <label class="form-label required">${t('firewall.importFile')}</label>
                <input type="file" class="form-control" id="import-file" accept=".json" required>
            </div>
            <div class="mb-3">
                <label class="form-label required">${t('firewall.importMode')}</label>
                <div class="form-selectgroup">
                    <label class="form-selectgroup-item">
                        <input type="radio" name="import-mode" value="append" class="form-selectgroup-input" checked>
                        <span class="form-selectgroup-label d-flex align-items-center p-3">
                            <span class="me-3">
                                <span class="form-selectgroup-check"></span>
                            </span>
                            <span class="form-selectgroup-label-content">
                                <span class="form-selectgroup-title strong mb-1">${t('firewall.importAppend')}</span>
                                <span class="d-block text-muted">${t('firewall.importAppendDesc')}</span>
                            </span>
                        </span>
                    </label>
                    <label class="form-selectgroup-item">
                        <input type="radio" name="import-mode" value="replace" class="form-selectgroup-input">
                        <span class="form-selectgroup-label d-flex align-items-center p-3">
                            <span class="me-3">
                                <span class="form-selectgroup-check"></span>
                            </span>
                            <span class="form-selectgroup-label-content">
                                <span class="form-selectgroup-title strong mb-1">${t('firewall.importReplace')}</span>
                                <span class="d-block text-muted">${t('firewall.importReplaceDesc')}</span>
                            </span>
                        </span>
                    </label>
                </div>
            </div>
            <div class="alert alert-warning">
                <i class="ti ti-alert-triangle me-2"></i>
                ${t('firewall.importWarning')}
            </div>
        `,
        footer: `
            <button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.cancel')}</button>
            <button type="button" class="btn btn-primary" data-action="import">${t('firewall.importBtn')}</button>
        `,
        async onAction(action, ctx) {
            if (action !== 'import') return;

            const fileInput = ctx.bodyEl.querySelector('#import-file');
            const file = fileInput.files[0];
            if (!file) return;

            const mode = ctx.bodyEl.querySelector('input[name="import-mode"]:checked').value;

            const formData = new FormData();
            formData.append('file', file);

            ctx.setBusy('[data-action="import"]', true);
            try {
                // Use apiFetch directly to handle FormData (apiPost forces JSON)
                const response = await apiFetch(`/firewall/import?mode=${mode}`, {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    const error = await response.json().catch(() => ({ detail: 'Import failed' }));
                    throw new Error(error.detail || 'Import failed');
                }

                const result = await response.json();

                showToast(result.message || t('firewall.importSuccess'), 'success');

                if (result.errors && result.errors.length > 0) {
                    console.warn('Import warnings:', result.errors);
                    showToast(t('firewall.importWithErrors', { count: result.errors.length }), 'warning');
                }

                ctx.hide();
                await state.reload();
            } catch (error) {
                ctx.setBusy('[data-action="import"]', false);
                showToast(t('firewall.importError', { error: error.message }), 'error');
            }
        },
    });
}

/**
 * MADMIN - Settings View / configuration import (upload, SCP files, preview)
 */

import { apiGet } from '../../api.js';
import { showToast, escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';
import { openModal } from '../../components/modal.js';
import { formatFileSize } from './remote-backup.js';

export function importModalHtml() {
    return `
        <div class="modal modal-blur fade" id="modal-import-config" tabindex="-1" role="dialog" aria-hidden="true">
            <div class="modal-dialog modal-dialog-centered" role="document">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title"><i class="ti ti-file-import me-2"></i>${t('settings.restoreConfig')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <!-- Upload -->
                        <h4 class="mb-2">${t('settings.uploadFile')}</h4>
                        <div class="border border-2 border-dashed rounded-3 p-3 text-center mb-3" id="import-dropzone"
                             style="cursor: pointer; transition: all 0.2s;">
                            <i class="ti ti-file-upload" style="font-size: 1.5rem; color: var(--tblr-primary);"></i>
                            <p class="mt-1 mb-0 text-muted small">${t('settings.dropzoneHint')}</p>
                            <input type="file" id="import-file-input" accept=".tar.gz" class="d-none">
                        </div>

                        <!-- SCP Files -->
                        <h4 class="mb-2"><i class="ti ti-server me-1"></i>${t('settings.scpFiles')}</h4>
                        <p class="text-muted small mb-2">
                            ${t('settings.scpUploadHint')} <code>/opt/madmin/data/imports/</code>
                        </p>
                        <div id="scp-files-list">
                            <div class="text-muted small">${t('common.loading')}</div>
                        </div>

                        <div id="import-progress" class="d-none mt-3">
                            <div class="progress">
                                <div class="progress-bar progress-bar-indeterminate"></div>
                            </div>
                            <small class="text-muted">${t('settings.importProgress')}</small>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-link link-secondary" data-bs-dismiss="modal">${t('common.close')}</button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

/**
 * Bind the import modal: open button, dropzone, file input, SCP file list.
 */
export function bindImportModal() {
    document.getElementById('open-import-modal-btn')?.addEventListener('click', () => {
        new bootstrap.Modal(document.getElementById('modal-import-config')).show();
    });

    // Import - Drag & Drop
    const dropzone = document.getElementById('import-dropzone');
    const fileInput = document.getElementById('import-file-input');

    if (dropzone && fileInput) {
        dropzone.addEventListener('click', () => fileInput.click());

        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.style.borderColor = 'var(--tblr-primary)';
            dropzone.style.background = 'var(--tblr-bg-surface-secondary)';
        });

        dropzone.addEventListener('dragleave', () => {
            dropzone.style.borderColor = '';
            dropzone.style.background = '';
        });

        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.style.borderColor = '';
            dropzone.style.background = '';
            const file = e.dataTransfer.files[0];
            if (file && file.name.endsWith('.tar.gz')) {
                handleImportFile(file);
            } else {
                showToast(t('settings.fileNotTarGz'), 'warning');
            }
        });

        fileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) handleImportFile(file);
        });
    }

    // SCP files: one delegated listener
    document.getElementById('scp-files-list')?.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-action="import-scp"]');
        if (btn) importScpFile(btn.dataset.filename);
    });

    loadScpFiles();
}

async function handleImportFile(file) {
    // First, preview
    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/api/backup/import/preview', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` },
            body: formData
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Preview failed');
        }

        const preview = await response.json();
        showImportPreviewModal(preview, file);
    } catch (e) {
        showToast(t('settings.previewError', { error: e.message }), 'error');
    }
}

async function loadScpFiles() {
    const container = document.getElementById('scp-files-list');
    if (!container) return;

    try {
        const files = await apiGet('/backup/import/files');

        if (files.length === 0) {
            container.innerHTML = `<div class="text-muted small">${t('settings.noScpFiles')}</div>`;
            return;
        }

        container.innerHTML = files.map(f => `
            <div class="d-flex align-items-center justify-content-between mb-2 p-2 bg-surface-secondary rounded">
                <div>
                    <i class="ti ti-file-zip me-1"></i>
                    <span class="small">${escapeHtml(f.filename)}</span>
                    <span class="badge bg-secondary-lt ms-1">${formatFileSize(f.size_bytes)}</span>
                </div>
                <button class="btn btn-sm btn-outline-primary" data-action="import-scp" data-filename="${escapeHtml(f.filename)}">
                    <i class="ti ti-file-import me-1"></i>${t('common.import')}
                </button>
            </div>
        `).join('');
    } catch (e) {
        container.innerHTML = `<div class="text-muted small">${t('settings.scpLoadError')}</div>`;
    }
}

async function importScpFile(filename) {
    try {
        const response = await fetch(`/api/backup/import/preview/from-file?filename=${encodeURIComponent(filename)}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` }
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Preview failed');
        }

        const preview = await response.json();
        showImportPreviewModal(preview, null, filename);
    } catch (e) {
        showToast(t('settings.previewError', { error: e.message }), 'error');
    }
}

function showImportPreviewModal(preview, file, scpFilename = null) {
    const versionWarning = preview.source_version !== preview.current_version
        ? `<div class="alert alert-warning mb-3">
            <i class="ti ti-alert-triangle me-2"></i>
            <strong>${t('settings.versionMismatch', { source: preview.source_version, current: preview.current_version })}</strong>
           </div>`
        : '';

    // Build core section
    const coreUsers = (preview.core?.users || []).map(u =>
        `<tr>
            <td><i class="ti ti-user me-1"></i>${escapeHtml(u.username)}</td>
            <td>${u.is_superuser ? '<span class="badge bg-red-lt">Super Admin</span>' : `<span class="badge bg-blue-lt">${t('menu.users')}</span>`}</td>
            <td>${u.is_active ? `<span class="badge bg-green-lt">${t('common.active')}</span>` : `<span class="badge bg-secondary-lt">${t('common.inactive')}</span>`}</td>
        </tr>`
    ).join('');

    // Build modules section
    const modulesHtml = Object.entries(preview.modules || {}).map(([modId, modData]) => {
        const tablesHtml = Object.entries(modData.tables || {}).map(([table, count]) =>
            `<div class="d-flex justify-content-between"><span class="text-muted">${escapeHtml(table)}</span><span class="badge bg-blue-lt">${count}</span></div>`
        ).join('');

        return `
            <div class="col-md-6">
                <div class="card card-sm">
                    <div class="card-body">
                        <div class="d-flex align-items-center mb-2">
                            <span class="avatar avatar-sm bg-purple-lt me-2"><i class="ti ti-puzzle"></i></span>
                            <strong>${escapeHtml(modId)}</strong>
                            ${modData.has_files ? '<span class="badge bg-cyan-lt ms-2">+ file</span>' : ''}
                        </div>
                        ${tablesHtml}
                    </div>
                </div>
            </div>`;
    }).join('');

    const ctx = openModal({
        title: t('settings.importPreviewTitle'),
        size: 'lg',
        body: `
            ${versionWarning}

            <div class="d-flex gap-3 mb-3">
                <span class="badge bg-blue-lt">v${escapeHtml(String(preview.source_version))}</span>
                <span class="badge bg-secondary-lt">${new Date(preview.timestamp).toLocaleString(undefined)}</span>
            </div>

            <!-- Core Section -->
            <h4 class="mb-2"><i class="ti ti-settings me-2"></i>Core</h4>

            <div class="row g-3 mb-3">
                <div class="col-12">
                    <div class="card card-sm">
                        <div class="card-body">
                            <div class="d-flex align-items-center mb-2">
                                <span class="avatar avatar-sm bg-green-lt me-2"><i class="ti ti-users"></i></span>
                                <strong>${t('settings.importUsers', { count: preview.core?.users?.length || 0 })}</strong>
                            </div>
                            ${coreUsers ? `
                            <table class="table table-sm table-vcenter mb-0">
                                <thead><tr><th>Username</th><th>${t('users.role')}</th><th>${t('common.status')}</th></tr></thead>
                                <tbody>${coreUsers}</tbody>
                            </table>` : `<span class="text-muted">${t('settings.importNoUsers')}</span>`}
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card card-sm">
                        <div class="card-body">
                            <div class="d-flex align-items-center">
                                <span class="avatar avatar-sm bg-orange-lt me-2"><i class="ti ti-shield"></i></span>
                                <strong>${t('settings.importFirewallRules')}</strong>
                                <span class="badge bg-orange-lt ms-auto">${preview.core?.firewall_rules || 0}</span>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card card-sm">
                        <div class="card-body">
                            <div class="d-flex align-items-center">
                                <span class="avatar avatar-sm bg-cyan-lt me-2"><i class="ti ti-adjustments"></i></span>
                                <strong>${t('settings.importCoreSettings')}</strong>
                                <span class="badge bg-cyan-lt ms-auto">${escapeHtml(preview.core?.settings?.company_name || '-')}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Modules Section -->
            ${modulesHtml ? `
            <h4 class="mb-2"><i class="ti ti-puzzle me-2"></i>${t('settings.importModules')}</h4>
            <div class="row g-3">${modulesHtml}</div>
            ` : ''}

            <div class="alert alert-warning mt-3 mb-0">
                <i class="ti ti-alert-circle me-2"></i>
                ${t('settings.importWarningOverwrite')}
            </div>
        `,
        footer: `
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">${t('common.cancel')}</button>
            <button type="button" class="btn btn-primary" data-action="confirm-import">
                <i class="ti ti-file-import me-1"></i>${t('settings.importConfirm')}
            </button>
        `,
        async onAction(action, mctx) {
            if (action !== 'confirm-import') return;
            mctx.hide();

            const progressEl = document.getElementById('import-progress');
            if (progressEl) progressEl.classList.remove('d-none');

            try {
                let response;

                if (scpFilename) {
                    // Import from SCP file
                    response = await fetch(`/api/backup/import/from-file?filename=${encodeURIComponent(scpFilename)}`, {
                        method: 'POST',
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` }
                    });
                } else {
                    // Import from uploaded file
                    const formData = new FormData();
                    formData.append('file', file);

                    response = await fetch('/api/backup/import', {
                        method: 'POST',
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` },
                        body: formData
                    });
                }

                const result = await response.json();

                if (progressEl) progressEl.classList.add('d-none');

                if (result.success || response.ok) {
                    const summary = t('settings.importCompleted', {
                        users: result.users_imported || 0,
                        rules: result.firewall_rules_imported || 0,
                        modules: result.modules_imported?.length || 0
                    });
                    const warnings = result.warnings?.length > 0 ? '. ' + result.warnings.join(', ') : '';
                    showToast(summary + warnings + '. ' + t('settings.importRestarting'), 'success');
                    setTimeout(() => location.reload(), 5000);
                } else {
                    const errors = result.result?.errors || result.errors || [t('common.error')];
                    showToast(t('settings.importFailed', { errors: errors.join(', ') }), 'error');
                }
            } catch (err) {
                if (progressEl) progressEl.classList.add('d-none');
                showToast(t('settings.importError', { error: err.message }), 'error');
            }
        },
    });

    ctx.el.querySelector('.modal-header').classList.add('bg-primary-lt');
    ctx.el.querySelector('.modal-dialog').classList.add('modal-dialog-centered', 'modal-dialog-scrollable');
}

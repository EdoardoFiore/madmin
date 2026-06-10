/**
 * MADMIN - Users View / own 2FA management
 *
 * Status card, setup (QR modal), disable (password prompt), backup code
 * regeneration (OTP prompt). Password/OTP prompts and the new-codes display
 * use openModal instead of static modals with clone-node listener resets.
 */

import { apiGet, apiPost, apiDeleteWithBody } from '../../api.js';
import { showToast, confirmDialog, escapeHtml } from '../../utils.js';
import { getUser } from '../../app.js';
import { t } from '../../i18n.js';
import { openModal } from '../../components/modal.js';

let twoFaSetupData = null;

function downloadBackupCodes(codes) {
    const content = [
        t('users.2faBackupTitle'),
        t('users.2faBackupSeparator'),
        t('users.2faBackupGenerated', { date: new Date().toLocaleString(undefined) }),
        '',
        t('users.2faBackupKeepSafe'),
        t('users.2faBackupSingleUse'),
        '',
        ...codes
    ].join('\n');
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `madmin-backup-codes-${new Date().toISOString().slice(0, 10)}.txt`;
    document.body.appendChild(a);
    a.click();
    URL.revokeObjectURL(url);
    document.body.removeChild(a);
}

/**
 * Load and render 2FA status
 */
export async function load2FAStatus(state) {
    const container = document.getElementById('2fa-status-container');
    if (!container) return;

    try {
        const status = await apiGet('/auth/me/2fa/status');
        const currentUser = getUser();
        const isSuperuser = currentUser?.is_superuser || false;
        const isEnforced = status.enforced || false;

        if (status.enabled) {
            // Show disable button only if: superuser OR not enforced
            const canDisable = isSuperuser || !isEnforced;

            container.innerHTML = `
                <div class="alert alert-success mb-3">
                    <div class="d-flex align-items-center">
                        <i class="ti ti-shield-check me-2" style="font-size: 1.5rem;"></i>
                        <div>
                            <strong>${t('users.2faActive')}</strong>
                            <div class="text-muted small">${isEnforced ? t('users.accountProtectedEnforced') : t('users.accountProtected')}</div>
                        </div>
                    </div>
                </div>
                ${canDisable ? `
                    <button class="btn btn-outline-danger btn-sm" id="btn-disable-2fa">
                        <i class="ti ti-shield-off me-1"></i>${t('users.disable2fa')}
                    </button>
                ` : ''}
                <button class="btn btn-outline-secondary btn-sm ${canDisable ? 'ms-2' : ''}" id="btn-regenerate-codes">
                    <i class="ti ti-key me-1"></i>${t('users.regenerateCodes')}
                </button>
            `;
            if (canDisable) {
                document.getElementById('btn-disable-2fa')?.addEventListener('click', () => disable2FA(state));
            }
            document.getElementById('btn-regenerate-codes')?.addEventListener('click', regenerateCodes);
        } else {
            // 2FA not enabled
            const localRequired = localStorage.getItem('madmin_2fa_setup_required') === 'true';
            // Only consider required if both localStorage flag AND backend enforced flag are true
            const isRequired = localRequired && isEnforced;

            // Clear stale localStorage flag if backend says not enforced
            if (localRequired && !isEnforced) {
                localStorage.removeItem('madmin_2fa_setup_required');
            }

            container.innerHTML = `
                <div class="alert ${isRequired || isEnforced ? 'alert-danger' : 'alert-warning'} mb-3">
                    <div class="d-flex align-items-center">
                        <i class="ti ti-${isRequired || isEnforced ? 'alert-triangle' : 'shield-exclamation'} me-2" style="font-size: 1.5rem;"></i>
                        <div>
                            <strong>${isRequired || isEnforced ? t('users.2faMandatory') : t('users.2faNotActive')}</strong>
                            <div class="text-muted small">${isRequired || isEnforced ? t('users.mustActivate2fa') : t('users.addSecurity')}</div>
                        </div>
                    </div>
                </div>
                <button class="btn btn-primary btn-sm" id="btn-setup-2fa">
                    <i class="ti ti-shield-plus me-1"></i>${t('users.activate2faBtn')}
                </button>
            `;
            document.getElementById('btn-setup-2fa')?.addEventListener('click', () => startSetup(state));
        }
    } catch (error) {
        container.innerHTML = `
            <div class="alert alert-danger">
                <i class="ti ti-alert-circle me-2"></i>${t('users.2faStatusLoadError')}
            </div>
        `;
    }
}

/**
 * Start 2FA setup: fetch secret/QR and open the setup modal (static HTML)
 */
async function startSetup(state) {
    const btn = document.getElementById('btn-setup-2fa');
    const originalText = btn.innerHTML;
    btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('app.generating')}`;
    btn.disabled = true;

    try {
        twoFaSetupData = await apiPost('/auth/me/2fa/setup', {});

        // Populate modal
        document.getElementById('qr-code-img').src = `data:image/png;base64,${twoFaSetupData.qr_code}`;
        document.getElementById('secret-key').value = twoFaSetupData.secret;
        document.getElementById('verify-setup-code').value = '';

        // Show backup codes
        const codesList = document.getElementById('backup-codes-list');
        codesList.innerHTML = twoFaSetupData.backup_codes.map(c => `
            <div class="col-6 col-md-4">
                <span class="badge bg-secondary-lt font-monospace w-100 py-2">${c}</span>
            </div>
        `).join('');

        // Download button for setup backup codes
        document.getElementById('btn-download-setup-codes').onclick = () => {
            downloadBackupCodes(twoFaSetupData.backup_codes);
        };

        bindSetupModal(state);

        new bootstrap.Modal(document.getElementById('2fa-setup-modal')).show();
    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

/**
 * Bind verify button inside the setup modal
 */
function bindSetupModal(state) {
    const verifyBtn = document.getElementById('btn-verify-2fa');
    if (!verifyBtn) return;

    // Remove old listeners
    const newVerifyBtn = verifyBtn.cloneNode(true);
    verifyBtn.parentNode.replaceChild(newVerifyBtn, verifyBtn);

    newVerifyBtn.addEventListener('click', async () => {
        const code = document.getElementById('verify-setup-code').value;
        if (!code || code.length !== 6) {
            showToast(t('users.enterValidCode'), 'error');
            return;
        }

        const originalText = newVerifyBtn.innerHTML;
        newVerifyBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('app.verificationInProgress')}`;
        newVerifyBtn.disabled = true;

        try {
            await apiPost('/auth/me/2fa/enable', { code });
            showToast(t('app.2faActivatedSuccess'), 'success');

            // Clear the setup required flag if it was set
            localStorage.removeItem('madmin_2fa_setup_required');

            // Close modal and refresh
            bootstrap.Modal.getInstance(document.getElementById('2fa-setup-modal'))?.hide();
            await load2FAStatus(state);
            await state.reload(); // Refresh users table
        } catch (error) {
            showToast(t('common.errorPrefix') + error.message, 'error');
        } finally {
            newVerifyBtn.innerHTML = originalText;
            newVerifyBtn.disabled = false;
        }
    });

    // Enter key on verification code
    document.getElementById('verify-setup-code')?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            document.getElementById('btn-verify-2fa')?.click();
        }
    });
}

/**
 * Disable own 2FA: confirm, then password prompt
 */
async function disable2FA(state) {
    const confirmed = await confirmDialog(
        t('users.disable2fa'),
        t('users.disable2faConfirm'),
        t('users.disable2fa'),
        'btn-danger'
    );
    if (!confirmed) return;

    openModal({
        title: t('users.confirmPasswordTitle'),
        size: 'sm',
        body: `
            <p class="text-muted">${t('users.confirmPasswordDesc')}</p>
            <input type="password" class="form-control" data-prompt-input placeholder="${t('auth.password')}">
        `,
        footer: `
            <button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.cancel')}</button>
            <button type="button" class="btn btn-danger" data-action="confirm">${t('common.confirm')}</button>
        `,
        onShown(ctx) {
            ctx.bodyEl.querySelector('[data-prompt-input]').addEventListener('keypress', (e) => {
                if (e.key === 'Enter') ctx.el.querySelector('[data-action="confirm"]').click();
            });
        },
        async onAction(action, ctx) {
            if (action !== 'confirm') return;
            const password = ctx.bodyEl.querySelector('[data-prompt-input]').value;
            if (!password) {
                showToast(t('users.enterPassword'), 'error');
                return;
            }

            ctx.setBusy('[data-action="confirm"]', true, t('app.verificationInProgress'));
            try {
                await apiDeleteWithBody('/auth/me/2fa/disable', { password });
                ctx.hide();
                showToast(t('users.2faDisabled'), 'success');
                await load2FAStatus(state);
                await state.reload();
            } catch (error) {
                ctx.setBusy('[data-action="confirm"]', false);
                showToast(t('common.errorPrefix') + error.message, 'error');
            }
        },
    });
}

/**
 * Regenerate backup codes: OTP prompt, then show the new codes
 */
function regenerateCodes() {
    openModal({
        title: t('users.verify2fa'),
        size: 'sm',
        body: `
            <p class="text-muted">${t('users.verify2faDesc')}</p>
            <input type="text" class="form-control form-control-lg text-center font-monospace"
                   data-prompt-input maxlength="12" pattern="[0-9A-Za-z]{6,12}"
                   placeholder="000000" inputmode="numeric">
        `,
        footer: `
            <button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.cancel')}</button>
            <button type="button" class="btn btn-primary" data-action="confirm">${t('common.confirm')}</button>
        `,
        onShown(ctx) {
            ctx.bodyEl.querySelector('[data-prompt-input]').addEventListener('keypress', (e) => {
                if (e.key === 'Enter') ctx.el.querySelector('[data-action="confirm"]').click();
            });
        },
        async onAction(action, ctx) {
            if (action !== 'confirm') return;
            const code = ctx.bodyEl.querySelector('[data-prompt-input]').value.trim();
            if (!code || (code.length !== 6 && code.length !== 8)) {
                showToast(t('users.enterValidCodeOtp'), 'error');
                return;
            }

            ctx.setBusy('[data-action="confirm"]', true, t('app.generating'));
            try {
                const result = await apiPost('/auth/me/2fa/backup-codes', { code });
                ctx.hide();
                showNewBackupCodes(result.backup_codes);
                showToast(t('users.newCodesGenerated'), 'success');
            } catch (error) {
                ctx.setBusy('[data-action="confirm"]', false);
                showToast(t('common.errorPrefix') + error.message, 'error');
            }
        },
    });
}

/**
 * Display freshly generated backup codes with a download button
 */
function showNewBackupCodes(codes) {
    openModal({
        title: t('users.newBackupCodes'),
        body: `
            <div class="alert alert-warning">
                <i class="ti ti-alert-triangle me-2"></i>
                ${t('users.backupCodesWarning')}
            </div>
            <div class="row g-2">
                ${codes.map(c => `<div class="col-6"><code class="fs-4">${escapeHtml(c)}</code></div>`).join('')}
            </div>
        `,
        footer: `
            <button type="button" class="btn btn-outline-primary" data-action="download">
                <i class="ti ti-download me-1"></i>${t('common.download')}
            </button>
            <button type="button" class="btn btn-primary" data-bs-dismiss="modal">${t('users.savedCodes')}</button>
        `,
        onAction(action) {
            if (action === 'download') downloadBackupCodes(codes);
        },
    });
}

/**
 * MADMIN - Global 2FA Enforcement (internal, not part of the module contract)
 *
 * When 2FA is enforced system-wide but not enabled for the current user,
 * shows the undismissable setup modal defined in index.html.
 */

import { showToast } from '../utils.js';
import { t } from '../i18n.js';

/**
 * Check if 2FA is enforced but not enabled - show global setup modal if needed
 */
export async function check2FAEnforcement() {
    try {
        const response = await fetch('/api/auth/me/2fa/status', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('madmin_token')}`
            }
        });

        if (!response.ok) return;

        const status = await response.json();

        // If 2FA is enforced but not enabled, show global modal
        if (status.enforced && !status.enabled) {
            showGlobal2FAModal();
        }
    } catch (error) {
        console.error('Failed to check 2FA status:', error);
    }
}

/**
 * Show global 2FA setup modal (cannot be dismissed until setup complete)
 */
function showGlobal2FAModal() {
    const modal = new bootstrap.Modal(document.getElementById('global-2fa-modal'));
    modal.show();

    // Setup button handlers
    document.getElementById('btn-start-global-2fa')?.addEventListener('click', startGlobal2FASetup);
    document.getElementById('btn-global-verify-2fa')?.addEventListener('click', verifyGlobal2FA);
    document.getElementById('global-verify-code')?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') verifyGlobal2FA();
    });
}

/**
 * Start global 2FA setup - call API to generate secret and QR
 */
async function startGlobal2FASetup() {
    const btn = document.getElementById('btn-start-global-2fa');
    btn.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>${t('app.generating')}`;
    btn.disabled = true;

    try {
        const response = await fetch('/api/auth/me/2fa/setup', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('madmin_token')}`,
                'Content-Type': 'application/json'
            },
            body: '{}'
        });

        if (!response.ok) throw new Error(t('app.2faGenerationError'));

        const data = await response.json();

        // Show QR content
        document.getElementById('global-2fa-setup-content').classList.add('d-none');
        document.getElementById('global-2fa-qr-content').classList.remove('d-none');

        // Populate data
        document.getElementById('global-qr-code-img').src = `data:image/png;base64,${data.qr_code}`;
        document.getElementById('global-secret-key').value = data.secret;

        // Show backup codes
        const codesContainer = document.getElementById('global-backup-codes');
        codesContainer.innerHTML = data.backup_codes.map(c =>
            `<div class="col-6 col-md-4"><code class="fs-5">${c}</code></div>`
        ).join('');

    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
        btn.innerHTML = `<i class="ti ti-shield-plus me-2"></i>${t('app.configure2fa')}`;
        btn.disabled = false;
    }
}

/**
 * Verify global 2FA code and enable
 */
async function verifyGlobal2FA() {
    const code = document.getElementById('global-verify-code').value.trim();
    if (!code || code.length !== 6) {
        showToast(t('app.enter6digitCode'), 'error');
        return;
    }

    const btn = document.getElementById('btn-global-verify-2fa');
    btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('app.verificationInProgress')}`;
    btn.disabled = true;

    try {
        const response = await fetch('/api/auth/me/2fa/enable', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('madmin_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ code })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || t('auth.invalidCode'));
        }

        showToast(t('app.2faActivatedSuccess'), 'success');

        // Clear localStorage flag and close modal
        localStorage.removeItem('madmin_2fa_setup_required');
        bootstrap.Modal.getInstance(document.getElementById('global-2fa-modal'))?.hide();

        // Reload page to refresh state
        window.location.reload();

    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
        btn.innerHTML = `<i class="ti ti-check me-1"></i>${t('app.activate2fa')}`;
        btn.disabled = false;
    }
}

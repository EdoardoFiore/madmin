/**
 * MADMIN - Users View / own password change form
 */

import { apiPost } from '../../api.js';
import { showToast } from '../../utils.js';
import { t } from '../../i18n.js';

/**
 * Bind the "change my password" form in the profile card.
 */
export function bindPasswordChangeForm() {
    const form = document.getElementById('change-password-form');
    form?.addEventListener('submit', async (e) => {
        e.preventDefault();

        const currentPassword = document.getElementById('current-password').value;
        const newPassword = document.getElementById('new-password').value;
        const confirmPassword = document.getElementById('confirm-password').value;

        if (newPassword !== confirmPassword) {
            showToast(t('users.passwordsDoNotMatch'), 'error');
            return;
        }

        if (newPassword.length < 8) {
            showToast(t('users.passwordMinLength'), 'error');
            return;
        }

        const btn = form.querySelector('button[type="submit"]');
        const originalText = btn.innerHTML;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('users.saving')}`;
        btn.disabled = true;

        try {
            await apiPost('/auth/me/password', {
                current_password: currentPassword,
                new_password: newPassword
            });
            showToast(t('users.passwordUpdated'), 'success');
            form.reset();
        } catch (error) {
            showToast(t('common.errorPrefix') + error.message, 'error');
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });
}

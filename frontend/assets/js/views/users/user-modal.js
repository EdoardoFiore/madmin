/**
 * MADMIN - Users View / create-edit modal
 */

import { apiPost, apiPatch, apiDelete, apiPut } from '../../api.js';
import { showToast, confirmDialog } from '../../utils.js';
import { getUser } from '../../app.js';
import { t } from '../../i18n.js';
import { renderGroupedPermissions } from './list.js';

/**
 * Bind the static user-modal listeners once per view render.
 */
export function bindUserModal(state) {
    document.getElementById('user-form')?.addEventListener('submit', (e) => handleUserSubmit(state, e));

    document.getElementById('user-superuser')?.addEventListener('change', (e) => {
        const permSection = document.getElementById('permissions-section');
        permSection.style.display = e.target.checked ? 'none' : 'block';
    });

    // Password confirmation check
    document.getElementById('user-password-confirm')?.addEventListener('input', validatePasswordMatch);
    document.getElementById('user-password')?.addEventListener('input', validatePasswordMatch);
}

function validatePasswordMatch() {
    const password = document.getElementById('user-password').value;
    const confirm = document.getElementById('user-password-confirm').value;
    const mismatch = document.getElementById('password-mismatch');

    if (confirm && password !== confirm) {
        mismatch.classList.remove('d-none');
        return false;
    } else {
        mismatch.classList.add('d-none');
        return true;
    }
}

/**
 * Open the modal for creating (user = null) or editing a user.
 */
export function openUserModal(state, user = null) {
    state.editingUser = user;
    const currentUser = getUser();
    const isSuperuser = currentUser?.is_superuser || false;

    document.getElementById('user-modal-title').textContent = user ? t('users.editUser') : t('users.newUser');
    document.getElementById('user-username').value = user?.username || '';
    document.getElementById('user-username').disabled = !!user;
    document.getElementById('user-email').value = user?.email || '';
    document.getElementById('user-password').value = '';
    document.getElementById('user-password-confirm').value = '';
    document.getElementById('user-password').required = !user;
    document.getElementById('user-password-confirm').required = !user;
    document.getElementById('password-label').classList.toggle('required', !user);
    document.getElementById('password-confirm-label').classList.toggle('required', !user);
    document.getElementById('password-hint').textContent = user ? t('users.passwordHintEdit') : t('users.passwordHintNew');
    document.getElementById('password-mismatch').classList.add('d-none');
    document.getElementById('user-superuser').checked = user?.is_superuser || false;
    document.getElementById('user-active').checked = user?.is_active ?? true;
    document.getElementById('user-totp-enforced').checked = user?.totp_enforced || false;

    // Password policy fields (only meaningful when editing an existing user)
    const pwdPolicyContainer = document.getElementById('pwd-policy-container');
    document.getElementById('user-must-change-password').checked = user?.must_change_password || false;
    // datetime-local needs "YYYY-MM-DDTHH:mm"; API returns a naive ISO timestamp
    document.getElementById('user-password-expires-at').value =
        user?.password_expires_at ? user.password_expires_at.slice(0, 16) : '';
    pwdPolicyContainer.classList.toggle('d-none', !user);

    // Show "Force 2FA" option only for superusers editing other users
    const force2faContainer = document.getElementById('force-2fa-container');
    if (isSuperuser && user && user.username !== currentUser?.username) {
        force2faContainer.classList.remove('d-none');
    } else {
        force2faContainer.classList.add('d-none');
    }

    // Show "Reset 2FA" button for superusers editing users with 2FA enabled or locked
    const reset2faBtn = document.getElementById('btn-reset-user-2fa');
    if (isSuperuser && user && (user.totp_enabled || user.totp_locked) && user.username !== currentUser?.username && !user.is_protected) {
        reset2faBtn.classList.remove('d-none');
        // Remove old listeners by cloning
        const newBtn = reset2faBtn.cloneNode(true);
        reset2faBtn.parentNode.replaceChild(newBtn, reset2faBtn);
        newBtn.addEventListener('click', () => handleReset2FA(state, user.username));
    } else {
        reset2faBtn.classList.add('d-none');
    }

    const permSection = document.getElementById('permissions-section');
    permSection.style.display = user?.is_superuser ? 'none' : 'block';

    renderGroupedPermissions(state, user?.permissions || []);

    new bootstrap.Modal(document.getElementById('user-modal')).show();
}

async function handleUserSubmit(state, e) {
    e.preventDefault();

    const username = document.getElementById('user-username').value;
    const password = document.getElementById('user-password').value;
    const passwordConfirm = document.getElementById('user-password-confirm').value;

    // Validate password match
    if (password && password !== passwordConfirm) {
        showToast(t('users.passwordMismatch'), 'error');
        return;
    }

    try {
        if (state.editingUser) {
            const updateData = {
                email: document.getElementById('user-email').value || null,
                is_superuser: document.getElementById('user-superuser').checked,
                is_active: document.getElementById('user-active').checked,
                must_change_password: document.getElementById('user-must-change-password').checked
            };

            // Only send totp_enforced if the container is visible (superuser editing another user)
            const force2faContainer = document.getElementById('force-2fa-container');
            if (!force2faContainer.classList.contains('d-none')) {
                updateData.totp_enforced = document.getElementById('user-totp-enforced').checked;
            }

            // Manual password expiry override (empty = leave unchanged)
            const expiresAt = document.getElementById('user-password-expires-at').value;
            if (expiresAt) updateData.password_expires_at = expiresAt;

            if (password) updateData.password = password;

            await apiPatch(`/auth/users/${state.editingUser.username}`, updateData);

            if (!document.getElementById('user-superuser').checked) {
                const selectedPerms = [...document.querySelectorAll('.perm-check:checked')].map(c => c.value);
                await apiPut(`/auth/users/${state.editingUser.username}/permissions`, selectedPerms);
            }

            showToast(t('users.userUpdated'), 'success');
        } else {
            // Create new user
            await apiPost('/auth/users', {
                username,
                password,
                email: document.getElementById('user-email').value || null,
                is_superuser: document.getElementById('user-superuser').checked
            });

            // Save permissions if not superuser
            if (!document.getElementById('user-superuser').checked) {
                const selectedPerms = [...document.querySelectorAll('.perm-check:checked')].map(c => c.value);
                await apiPut(`/auth/users/${username}/permissions`, selectedPerms);
            }

            showToast(t('users.userCreated'), 'success');
        }

        bootstrap.Modal.getInstance(document.getElementById('user-modal')).hide();
        await state.reload();
    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
    }
}

/**
 * Handle admin reset of user 2FA
 */
async function handleReset2FA(state, username) {
    const confirmed = await confirmDialog(
        t('users.reset2fa'),
        t('users.reset2faConfirm', { username }),
        t('users.reset2fa'),
        'btn-danger'
    );

    if (!confirmed) return;

    try {
        await apiDelete(`/auth/users/${username}/2fa`);
        showToast(t('users.2faDisabledSuccess'), 'success');

        // Hide modal and refresh
        bootstrap.Modal.getInstance(document.getElementById('user-modal'))?.hide();
        await state.reload();
    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
    }
}

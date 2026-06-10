/**
 * MADMIN - Users View
 *
 * Profile security (password change, own 2FA) + user management table.
 * Submodules: list.js (table), user-modal.js (create/edit), twofa.js (own
 * 2FA flows), password.js (own password change).
 */

import { apiGet } from '../../api.js';
import { showToast } from '../../utils.js';
import { setPageActions, checkPermission } from '../../app.js';
import { t } from '../../i18n.js';
import { skeletonTable } from '../../components/skeleton.js';
import { renderUsers } from './list.js';
import { bindUserModal, openUserModal } from './user-modal.js';
import { load2FAStatus } from './twofa.js';
import { bindPasswordChangeForm } from './password.js';

/**
 * Render the users view
 */
export async function render(container) {
    const state = {
        users: [],
        permissions: [],
        editingUser: null,
        reload: loadData,
    };

    if (checkPermission('users.manage')) {
        setPageActions(`
            <button class="btn btn-primary" id="btn-add-user">
                <i class="ti ti-user-plus me-2"></i>${t('users.newUser')}
            </button>
        `);
    }

    container.innerHTML = `
        <!-- My Profile Security Section -->
        <div class="card mb-3">
            <div class="card-header">
                <h3 class="card-title"><i class="ti ti-user-cog me-2"></i>${t('users.myProfile')}</h3>
            </div>
            <div class="card-body">
                <div class="row g-4">
                    <!-- Change Password -->
                    <div class="col-lg-6">
                        <h4><i class="ti ti-lock me-2"></i>${t('users.changePassword')}</h4>
                        <form id="change-password-form" class="mt-3">
                            <div class="row g-2">
                                <div class="col-12">
                                    <input type="password" class="form-control" id="current-password"
                                           placeholder="${t('users.currentPassword')}" required>
                                </div>
                                <div class="col-md-6">
                                    <input type="password" class="form-control" id="new-password"
                                           placeholder="${t('users.newPassword')}" required minlength="8">
                                </div>
                                <div class="col-md-6">
                                    <input type="password" class="form-control" id="confirm-password"
                                           placeholder="${t('users.confirmPassword')}" required>
                                </div>
                                <div class="col-12">
                                    <button type="submit" class="btn btn-primary">
                                        <i class="ti ti-check me-1"></i>${t('users.changePasswordBtn')}
                                    </button>
                                </div>
                            </div>
                        </form>
                    </div>

                    <!-- 2FA Management -->
                    <div class="col-lg-6">
                        <h4><i class="ti ti-shield-lock me-2"></i>${t('users.auth2fa')}</h4>
                        <div id="2fa-status-container" class="mt-3">
                            <div class="d-flex justify-content-center py-3">
                                <div class="spinner-border spinner-border-sm text-primary"></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Users Table Card -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-users me-2"></i>${t('users.registeredUsers')}
                </h3>
            </div>
            <div id="users-table-container">${skeletonTable(4, 6)}</div>
        </div>

        <!-- 2FA Setup Modal -->
        <div class="modal modal-blur fade" id="2fa-setup-modal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${t('users.configure2fa')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="row">
                            <div class="col-md-6 text-center">
                                <h5 class="mb-3">${t('users.scanQrCode')}</h5>
                                <div id="qr-code-container" class="mb-3 p-3 bg-white rounded d-inline-block">
                                    <img id="qr-code-img" src="" alt="QR Code" style="width: 180px; height: 180px;">
                                </div>
                                <p class="text-muted small">Google Authenticator, Authy, etc.</p>
                            </div>
                            <div class="col-md-6">
                                <h5 class="mb-3">${t('users.orManually')}</h5>
                                <div class="mb-3">
                                    <input type="text" class="form-control font-monospace text-center" id="secret-key" readonly>
                                </div>
                                <hr>
                                <h5 class="mb-3">${t('users.verifyCode')}</h5>
                                <input type="text" class="form-control form-control-lg text-center font-monospace mb-3"
                                       id="verify-setup-code" maxlength="6" pattern="[0-9]{6}"
                                       placeholder="000000" inputmode="numeric">
                                <button class="btn btn-primary w-100" id="btn-verify-2fa">
                                    <i class="ti ti-check me-1"></i>${t('users.activate2fa')}
                                </button>
                            </div>
                        </div>
                        <hr>
                        <div class="d-flex justify-content-between align-items-center">
                            <h5 class="mb-0"><i class="ti ti-key me-2"></i>${t('users.backupCodes')}</h5>
                            <button type="button" class="btn btn-sm btn-outline-primary" id="btn-download-setup-codes">
                                <i class="ti ti-download me-1"></i>${t('common.download')}
                            </button>
                        </div>
                        <div id="backup-codes-list" class="row g-2 mt-2"></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- User Modal -->
        <div class="modal modal-blur fade" id="user-modal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="user-modal-title">${t('users.newUser')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <form id="user-form">
                        <div class="modal-body">
                            <div class="row g-3">
                                <div class="col-md-6">
                                    <label class="form-label required">Username</label>
                                    <input type="text" class="form-control" id="user-username" required
                                           minlength="3" maxlength="50" pattern="[a-zA-Z0-9_-]+">
                                    <small class="form-hint">${t('users.lettersNumbersDashes')}</small>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Email</label>
                                    <input type="email" class="form-control" id="user-email">
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label" id="password-label">Password</label>
                                    <input type="password" class="form-control" id="user-password" minlength="8">
                                    <small class="form-hint" id="password-hint">${t('users.passwordHintNew')}</small>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label" id="password-confirm-label">${t('users.confirmPassword')}</label>
                                    <input type="password" class="form-control" id="user-password-confirm" minlength="8">
                                    <small class="form-hint text-danger d-none" id="password-mismatch">${t('users.passwordsDoNotMatch')}</small>
                                </div>
                                <div class="col-12">
                                    <label class="form-check form-switch">
                                        <input class="form-check-input" type="checkbox" id="user-superuser">
                                        <span class="form-check-label"><strong>Superuser</strong> ${t('users.superuserNote')}</span>
                                    </label>
                                </div>
                                <div class="col-6">
                                    <label class="form-check form-switch">
                                        <input class="form-check-input" type="checkbox" id="user-active" checked>
                                        <span class="form-check-label">${t('users.activeLabel')}</span>
                                    </label>
                                    <small class="form-hint text-muted">${t('users.disabledUsersNote')}</small>
                                </div>
                                <div class="col-6 d-none" id="force-2fa-container">
                                    <label class="form-check form-switch">
                                        <input class="form-check-input" type="checkbox" id="user-totp-enforced">
                                        <span class="form-check-label"><i class="ti ti-shield-check me-1"></i>${t('users.force2fa')}</span>
                                    </label>
                                    <small class="form-hint text-muted">${t('users.force2faNote')}</small>
                                </div>
                                <div class="col-12 d-none" id="pwd-policy-container">
                                    <div class="row g-3">
                                        <div class="col-md-6">
                                            <label class="form-check form-switch">
                                                <input class="form-check-input" type="checkbox" id="user-must-change-password">
                                                <span class="form-check-label"><i class="ti ti-key me-1"></i>${t('users.forcePasswordChange')}</span>
                                            </label>
                                            <small class="form-hint text-muted">${t('users.forcePasswordChangeNote')}</small>
                                        </div>
                                        <div class="col-md-6">
                                            <label class="form-label">${t('users.passwordExpiresAt')}</label>
                                            <input type="datetime-local" class="form-control" id="user-password-expires-at">
                                            <small class="form-hint text-muted">${t('users.passwordExpiresAtNote')}</small>
                                        </div>
                                    </div>
                                </div>
                                <div class="col-12" id="permissions-section">
                                    <label class="form-label">${t('users.permissions')}</label>
                                    <div id="permissions-list" class="row g-3">
                                        <!-- Permissions will be loaded here grouped -->
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-danger me-auto d-none" id="btn-reset-user-2fa">
                                <i class="ti ti-shield-off me-1"></i>${t('users.reset2fa')}
                            </button>
                            <button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.cancel')}</button>
                            <button type="submit" class="btn btn-primary">${t('common.save')}</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    `;

    document.getElementById('btn-add-user')?.addEventListener('click', () => openUserModal(state));
    bindUserModal(state);
    bindPasswordChangeForm();
    load2FAStatus(state);

    await loadData(state);

    async function loadData() {
        try {
            [state.users, state.permissions] = await Promise.all([
                apiGet('/auth/users'),
                apiGet('/auth/permissions').catch(() => [])
            ]);
            renderUsers(state);
        } catch (error) {
            showToast(t('common.errorPrefix') + error.message, 'error');
        }
    }
}

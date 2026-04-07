/**
 * MADMIN - Users View
 */

import { apiGet, apiPost, apiPatch, apiDelete, apiDeleteWithBody, apiPut } from '../api.js';
import { showToast, confirmDialog, formatDate, emptyState, escapeHtml, statusBadge, copyToClipboard } from '../utils.js';
import { setPageActions, checkPermission, getUser } from '../app.js';
import { t } from '../i18n.js';

let users = [];
let permissions = [];
let editingUser = null;

/**
 * Render the users view
 */
export async function render(container) {
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
            <div class="table-responsive">
                <table class="table table-vcenter card-table">
                    <thead>
                        <tr>
                            <th>${t('users.user')}</th>
                            <th>${t('users.email')}</th>
                            <th>${t('users.role')}</th>
                            <th>2FA</th>
                            <th>${t('users.status')}</th>
                            <th>${t('users.lastLogin')}</th>
                            <th class="w-1"></th>
                        </tr>
                    </thead>
                    <tbody id="users-table-body">
                        <tr><td colspan="7" class="text-center py-4">
                            <div class="spinner-border spinner-border-sm"></div>
                        </td></tr>
                    </tbody>
                </table>
            </div>
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
        
        <!-- Password Input Modal -->
        <div class="modal modal-blur fade" id="password-input-modal" tabindex="-1">
            <div class="modal-dialog modal-sm">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${t('users.confirmPasswordTitle')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <p class="text-muted">${t('users.confirmPasswordDesc')}</p>
                        <input type="password" class="form-control" id="modal-password-input"
                               placeholder="${t('auth.password')}" autofocus>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.cancel')}</button>
                        <button type="button" class="btn btn-danger" id="modal-password-confirm">${t('common.confirm')}</button>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- OTP Input Modal -->
        <div class="modal modal-blur fade" id="otp-input-modal" tabindex="-1">
            <div class="modal-dialog modal-sm">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${t('users.verify2fa')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <p class="text-muted">${t('users.verify2faDesc')}</p>
                        <input type="text" class="form-control form-control-lg text-center font-monospace"
                               id="modal-otp-input" maxlength="12" pattern="[0-9A-Za-z]{6,12}"
                               placeholder="000000" inputmode="numeric" autofocus>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.cancel')}</button>
                        <button type="button" class="btn btn-primary" id="modal-otp-confirm">${t('common.confirm')}</button>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Backup Codes Display Modal -->
        <div class="modal modal-blur fade" id="backup-codes-display-modal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title"><i class="ti ti-key me-2"></i>${t('users.newBackupCodes')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="alert alert-warning">
                            <i class="ti ti-alert-triangle me-2"></i>
                            ${t('users.backupCodesWarning')}
                        </div>
                        <div id="backup-codes-display" class="row g-2"></div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-outline-primary" id="download-displayed-codes">
                            <i class="ti ti-download me-1"></i>${t('common.download')}
                        </button>
                        <button type="button" class="btn btn-primary" data-bs-dismiss="modal">${t('users.savedCodes')}</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    setupEventListeners();
    await loadData();
}

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
    a.download = `madmin-backup-codes-${new Date().toISOString().slice(0,10)}.txt`;
    document.body.appendChild(a);
    a.click();
    URL.revokeObjectURL(url);
    document.body.removeChild(a);
}

function setupEventListeners() {
    const addBtn = document.getElementById('btn-add-user');
    if (addBtn) {
        addBtn.addEventListener('click', () => openUserModal());
    }

    const form = document.getElementById('user-form');
    if (form) {
        form.addEventListener('submit', handleUserSubmit);
    }

    const superuserCheck = document.getElementById('user-superuser');
    if (superuserCheck) {
        superuserCheck.addEventListener('change', (e) => {
            const permSection = document.getElementById('permissions-section');
            permSection.style.display = e.target.checked ? 'none' : 'block';
        });
    }

    // Password confirmation check
    const passwordConfirm = document.getElementById('user-password-confirm');
    if (passwordConfirm) {
        passwordConfirm.addEventListener('input', validatePasswordMatch);
    }

    const password = document.getElementById('user-password');
    if (password) {
        password.addEventListener('input', validatePasswordMatch);
    }

    // Setup password change form
    setupPasswordChangeForm();

    // Load 2FA status
    load2FAStatus();
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

async function loadData() {
    try {
        [users, permissions] = await Promise.all([
            apiGet('/auth/users'),
            apiGet('/auth/permissions').catch(() => [])
        ]);
        renderUsers();
    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
    }
}

function renderUsers() {
    const tbody = document.getElementById('users-table-body');
    const canManage = checkPermission('users.manage');
    const currentUser = getUser();

    if (users.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7">${emptyState('ti-users', t('users.noUsers'))}</td></tr>`;
        return;
    }

    tbody.innerHTML = users.map(user => {
        // Determine if we should show action buttons
        const isSelf = user.username === currentUser?.username;

        // Protected user (first setup user): no one else can edit or delete
        const showActions = canManage && !isSelf && !user.is_protected;

        // 2FA status icon
        const twoFaIcon = user.totp_locked
            ? `<span class="badge bg-orange-lt" title="${t('users.2faActive')} — Reset"><i class="ti ti-shield-x"></i></span>`
            : user.totp_enabled
                ? `<span class="badge bg-green-lt" title="${t('users.2faActive')}"><i class="ti ti-shield-check"></i></span>`
                : `<span class="badge bg-secondary-lt" title="${t('users.2faNotActive')}"><i class="ti ti-shield-off"></i></span>`;

        return `
            <tr>
                <td>
                    <div class="d-flex align-items-center">
                        <span class="avatar avatar-sm bg-${user.is_superuser ? 'red' : 'blue'}-lt me-2">
                            <i class="ti ti-${user.is_superuser ? 'crown' : 'user'}"></i>
                        </span>
                        <div>
                            <div class="font-weight-medium">${escapeHtml(user.username)}</div>
                            ${user.is_superuser ? '<small class="text-muted">Superuser</small>' : ''}
                        </div>
                    </div>
                </td>
                <td>${user.email ? escapeHtml(user.email) : '<span class="text-muted">-</span>'}</td>
                <td>${user.is_superuser ? '<span class="badge bg-red-lt">Admin</span>' : `<span class="badge bg-blue-lt">${t('users.user')}</span>`}</td>
                <td>${twoFaIcon}</td>
                <td>${statusBadge(user.is_active)}</td>
                <td>${user.last_login ? formatDate(user.last_login) : `<span class="text-muted">${t('users.never')}</span>`}</td>
                <td>
                    ${showActions ? `
                        <div class="btn-group btn-group-sm">
                            <button class="btn btn-ghost-primary btn-edit" data-username="${user.username}" title="${t('common.edit')}">
                                <i class="ti ti-edit"></i>
                            </button>
                            <button class="btn btn-ghost-danger btn-delete" data-username="${user.username}" title="${t('common.delete')}">
                                <i class="ti ti-trash"></i>
                            </button>
                        </div>
                    ` : ''}
                </td>
            </tr>
        `;
    }).join('');

    tbody.querySelectorAll('.btn-edit').forEach(btn => {
        btn.addEventListener('click', () => {
            const user = users.find(u => u.username === btn.dataset.username);
            if (user) openUserModal(user);
        });
    });

    tbody.querySelectorAll('.btn-delete').forEach(btn => {
        btn.addEventListener('click', async () => {
            const confirmed = await confirmDialog(t('users.deleteUser'), t('users.deleteUserConfirm'), t('common.delete'), 'btn-danger');
            if (confirmed) {
                try {
                    await apiDelete(`/auth/users/${btn.dataset.username}`);
                    showToast(t('users.userDeleted'), 'success');
                    await loadData();
                } catch (error) {
                    showToast(t('common.errorPrefix') + error.message, 'error');
                }
            }
        });
    });
}

function renderGroupedPermissions(userPerms) {
    const permList = document.getElementById('permissions-list');
    let html = '';

    // Define display names for core groups
    const coreGroupNames = {
        'users': t('users.coreGroupNames.users'),
        'firewall': t('users.coreGroupNames.firewall'),
        'settings': t('users.coreGroupNames.settings'),
        'modules': t('users.coreGroupNames.modules'),
        'permissions': t('users.coreGroupNames.permissions')
    };

    // Group permissions dynamically by prefix (module name)
    const groups = {};
    for (const perm of permissions) {
        const prefix = perm.slug.split('.')[0];
        if (!groups[prefix]) {
            groups[prefix] = [];
        }
        groups[prefix].push(perm);
    }

    // Sort groups: core groups first, then module groups alphabetically
    const coreOrder = ['users', 'firewall', 'settings', 'modules', 'permissions'];
    const sortedGroupKeys = Object.keys(groups).sort((a, b) => {
        const aIsCore = coreOrder.includes(a);
        const bIsCore = coreOrder.includes(b);
        if (aIsCore && !bIsCore) return -1;
        if (!aIsCore && bIsCore) return 1;
        if (aIsCore && bIsCore) return coreOrder.indexOf(a) - coreOrder.indexOf(b);
        return a.localeCompare(b);
    });

    // Render each group
    for (const groupKey of sortedGroupKeys) {
        const groupPerms = groups[groupKey];
        // Determine display name: core names or capitalize module name
        const displayName = coreGroupNames[groupKey] ||
            groupKey.charAt(0).toUpperCase() + groupKey.slice(1);

        // Determine icon based on group
        let icon = 'ti-folder';
        if (groupKey === 'users') icon = 'ti-users';
        else if (groupKey === 'firewall') icon = 'ti-shield';
        else if (groupKey === 'settings') icon = 'ti-settings';
        else if (groupKey === 'modules') icon = 'ti-puzzle';
        else if (groupKey === 'permissions') icon = 'ti-lock';
        else if (groupKey === 'wireguard') icon = 'ti-lock';
        // Modules get puzzle-2 icon by default
        else icon = 'ti-puzzle-2';

        html += `
            <div class="col-md-6">
                <div class="card card-sm">
                    <div class="card-header py-2">
                        <h4 class="card-title m-0"><i class="ti ${icon} me-2"></i>${displayName}</h4>
                    </div>
                    <div class="card-body py-2">
                        ${groupPerms.map(p => {
            const action = p.slug.split('.').slice(1).join('.');
            return `
                            <label class="form-check mb-1">
                                <input class="form-check-input perm-check" type="checkbox" value="${p.slug}"
                                       ${userPerms.includes(p.slug) ? 'checked' : ''}>
                                <span class="form-check-label">${action}</span>
                            </label>
                        `;
        }).join('')}
                    </div>
                </div>
            </div>
        `;
    }

    permList.innerHTML = html;
}

function openUserModal(user = null) {
    editingUser = user;
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
        newBtn.addEventListener('click', () => handleReset2FA(user.username));
    } else {
        reset2faBtn.classList.add('d-none');
    }

    const permSection = document.getElementById('permissions-section');
    permSection.style.display = user?.is_superuser ? 'none' : 'block';

    const userPerms = user?.permissions || [];
    renderGroupedPermissions(userPerms);

    new bootstrap.Modal(document.getElementById('user-modal')).show();
}

async function handleUserSubmit(e) {
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
        if (editingUser) {
            const updateData = {
                email: document.getElementById('user-email').value || null,
                is_superuser: document.getElementById('user-superuser').checked,
                is_active: document.getElementById('user-active').checked
            };

            // Only send totp_enforced if the container is visible (superuser editing another user)
            const force2faContainer = document.getElementById('force-2fa-container');
            if (!force2faContainer.classList.contains('d-none')) {
                updateData.totp_enforced = document.getElementById('user-totp-enforced').checked;
            }

            if (password) updateData.password = password;

            await apiPatch(`/auth/users/${editingUser.username}`, updateData);

            if (!document.getElementById('user-superuser').checked) {
                const selectedPerms = [...document.querySelectorAll('.perm-check:checked')].map(c => c.value);
                await apiPut(`/auth/users/${editingUser.username}/permissions`, selectedPerms);
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
        await loadData();
    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
    }
}


// ========== PASSWORD CHANGE & 2FA MANAGEMENT ==========

let twoFaSetupData = null;

/**
 * Setup password change form handler
 */
function setupPasswordChangeForm() {
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

/**
 * Load and render 2FA status
 */
async function load2FAStatus() {
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
            if (canDisable) setupDisable2FA();
            setupRegenerateCodes();
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
            setupEnable2FA();
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
 * Setup enable 2FA button
 */
function setupEnable2FA() {
    document.getElementById('btn-setup-2fa')?.addEventListener('click', async () => {
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

            // Setup modal event listeners
            setup2FAModalListeners();

            // Show modal
            const modal = new bootstrap.Modal(document.getElementById('2fa-setup-modal'));
            modal.show();
        } catch (error) {
            showToast(t('common.errorPrefix') + error.message, 'error');
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });
}

/**
 * Setup 2FA modal listeners
 */
function setup2FAModalListeners() {
    // Copy button removed

    // Verify and enable 2FA
    const verifyBtn = document.getElementById('btn-verify-2fa');
    if (verifyBtn) {
        // Remove old listeners
        const newVerifyBtn = verifyBtn.cloneNode(true);
        verifyBtn.parentNode.replaceChild(newVerifyBtn, verifyBtn);

        newVerifyBtn.addEventListener('click', async () => {
            const code = document.getElementById('verify-setup-code').value;
            if (!code || code.length !== 6) {
                showToast(t('users.enterValidCode'), 'error');
                return;
            }

            const originalText = verifyBtn.innerHTML;
            verifyBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('app.verificationInProgress')}`;
            verifyBtn.disabled = true;

            try {
                await apiPost('/auth/me/2fa/enable', { code });
                showToast(t('app.2faActivatedSuccess'), 'success');

                // Clear the setup required flag if it was set
                localStorage.removeItem('madmin_2fa_setup_required');

                // Close modal and refresh
                const modal = bootstrap.Modal.getInstance(document.getElementById('2fa-setup-modal'));
                modal?.hide();
                await load2FAStatus();
                await loadData(); // Refresh users table
            } catch (error) {
                showToast(t('common.errorPrefix') + error.message, 'error');
            } finally {
                verifyBtn.innerHTML = originalText;
                verifyBtn.disabled = false;
            }
        });

        // Enter key on verification code
        document.getElementById('verify-setup-code')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                document.getElementById('btn-verify-2fa')?.click();
            }
        });
    }
}

/**
 * Setup disable 2FA button
 */
function setupDisable2FA() {
    document.getElementById('btn-disable-2fa')?.addEventListener('click', async () => {
        const confirmed = await confirmDialog(
            t('users.disable2fa'),
            t('users.disable2faConfirm'),
            t('users.disable2fa'),
            'btn-danger'
        );
        if (!confirmed) return;

        // Show password input modal
        const passwordModal = new bootstrap.Modal(document.getElementById('password-input-modal'));
        const passwordInput = document.getElementById('modal-password-input');
        const confirmBtn = document.getElementById('modal-password-confirm');

        passwordInput.value = '';
        passwordModal.show();

        // Wait for modal to be shown before focusing
        document.getElementById('password-input-modal').addEventListener('shown.bs.modal', () => {
            passwordInput.focus();
        }, { once: true });

        // Handle confirm button click
        const handleConfirm = async () => {
            const password = passwordInput.value;
            if (!password) {
                showToast(t('users.enterPassword'), 'error');
                return;
            }

            confirmBtn.disabled = true;
            confirmBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('app.verificationInProgress')}`;

            try {
                await apiDeleteWithBody('/auth/me/2fa/disable', { password });
                passwordModal.hide();
                showToast(t('users.2faDisabled'), 'success');
                await load2FAStatus();
                await loadData();
            } catch (error) {
                showToast(t('common.errorPrefix') + error.message, 'error');
            } finally {
                confirmBtn.disabled = false;
                confirmBtn.innerHTML = t('common.confirm');
            }
        };

        // Remove old listener and add new one
        const newConfirmBtn = confirmBtn.cloneNode(true);
        confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
        newConfirmBtn.addEventListener('click', handleConfirm);

        // Enter key support
        passwordInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') handleConfirm();
        }, { once: true });
    });
}

/**
 * Setup regenerate backup codes button
 */
function setupRegenerateCodes() {
    document.getElementById('btn-regenerate-codes')?.addEventListener('click', async () => {
        // Show OTP input modal
        const otpModal = new bootstrap.Modal(document.getElementById('otp-input-modal'));
        const otpInput = document.getElementById('modal-otp-input');
        const confirmBtn = document.getElementById('modal-otp-confirm');

        otpInput.value = '';
        otpModal.show();

        // Wait for modal to be shown before focusing
        document.getElementById('otp-input-modal').addEventListener('shown.bs.modal', () => {
            otpInput.focus();
        }, { once: true });

        // Handle confirm button click
        const handleConfirm = async () => {
            const code = otpInput.value.trim();
            if (!code || (code.length !== 6 && code.length !== 8)) {
                showToast(t('users.enterValidCodeOtp'), 'error');
                return;
            }

            confirmBtn.disabled = true;
            confirmBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('app.generating')}`;

            try {
                const result = await apiPost('/auth/me/2fa/backup-codes', { code });
                otpModal.hide();

                // Show backup codes in Tabler modal
                const codesContainer = document.getElementById('backup-codes-display');
                codesContainer.innerHTML = result.backup_codes.map(c =>
                    `<div class="col-6"><code class="fs-4">${c}</code></div>`
                ).join('');

                // Download button
                document.getElementById('download-displayed-codes').onclick = () => {
                    downloadBackupCodes(result.backup_codes);
                };

                new bootstrap.Modal(document.getElementById('backup-codes-display-modal')).show();
                showToast(t('users.newCodesGenerated'), 'success');
            } catch (error) {
                showToast(t('common.errorPrefix') + error.message, 'error');
            } finally {
                confirmBtn.disabled = false;
                confirmBtn.innerHTML = t('common.confirm');
            }
        };

        // Remove old listener and add new one
        const newConfirmBtn = confirmBtn.cloneNode(true);
        confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
        newConfirmBtn.addEventListener('click', handleConfirm);

        // Enter key support
        otpInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') handleConfirm();
        }, { once: true });
    });
}

/**
 * Handle admin reset of user 2FA
 */
async function handleReset2FA(username) {
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
        const modal = bootstrap.Modal.getInstance(document.getElementById('user-modal'));
        modal.hide();
        await loadData();
    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
    }
}

/**
 * MADMIN - Users View / table
 */

import { apiDelete } from '../../api.js';
import { showToast, confirmDialog, formatDate, escapeHtml, statusBadge } from '../../utils.js';
import { checkPermission, getUser } from '../../app.js';
import { t } from '../../i18n.js';
import { createTable } from '../../components/data-table.js';
import { openUserModal } from './user-modal.js';

/**
 * Render the users table into #users-table-container
 */
export function renderUsers(state) {
    const container = document.getElementById('users-table-container');
    if (!container) return;

    const canManage = checkPermission('users.manage');
    const currentUser = getUser();

    // Protected user (first setup user): no one else can edit or delete
    const showActions = (user) =>
        canManage && user.username !== currentUser?.username && !user.is_protected;

    const table = createTable({
        columns: [
            {
                key: 'username', label: t('users.user'),
                render: (user) => {
                    // Password status badge: force-change takes priority, then expired
                    const pwdExpired = user.password_expires_at && new Date(user.password_expires_at) < new Date();
                    const pwdBadge = user.must_change_password
                        ? `<span class="badge bg-orange-lt ms-1" title="${t('users.forcePasswordChange')}"><i class="ti ti-key"></i></span>`
                        : pwdExpired
                            ? `<span class="badge bg-red-lt ms-1" title="${t('users.passwordExpired')}"><i class="ti ti-clock-exclamation"></i></span>`
                            : '';
                    return `
                        <div class="d-flex align-items-center">
                            <span class="avatar avatar-sm bg-${user.is_superuser ? 'red' : 'blue'}-lt me-2">
                                <i class="ti ti-${user.is_superuser ? 'crown' : 'user'}"></i>
                            </span>
                            <div>
                                <div class="font-weight-medium">${escapeHtml(user.username)}${pwdBadge}</div>
                                ${user.is_superuser ? '<small class="text-muted">Superuser</small>' : ''}
                            </div>
                        </div>`;
                },
            },
            {
                key: 'email', label: t('users.email'),
                render: (user) => user.email ? escapeHtml(user.email) : '<span class="text-muted">-</span>',
            },
            {
                key: 'is_superuser', label: t('users.role'),
                render: (user) => user.is_superuser
                    ? '<span class="badge bg-red-lt">Admin</span>'
                    : `<span class="badge bg-blue-lt">${t('users.user')}</span>`,
            },
            {
                key: 'totp_enabled', label: '2FA',
                render: (user) => user.totp_locked
                    ? `<span class="badge bg-orange-lt" title="${t('users.2faActive')} — Reset"><i class="ti ti-shield-x"></i></span>`
                    : user.totp_enabled
                        ? `<span class="badge bg-green-lt" title="${t('users.2faActive')}"><i class="ti ti-shield-check"></i></span>`
                        : `<span class="badge bg-secondary-lt" title="${t('users.2faNotActive')}"><i class="ti ti-shield-off"></i></span>`,
            },
            { key: 'is_active', label: t('users.status'), render: (user) => statusBadge(user.is_active) },
            {
                key: 'last_login', label: t('users.lastLogin'),
                render: (user) => user.last_login ? formatDate(user.last_login) : `<span class="text-muted">${t('users.never')}</span>`,
            },
        ],
        rows: state.users,
        rowKey: 'username',
        rowActions: [
            { action: 'edit', icon: 'ti-edit', className: 'btn-ghost-primary', title: t('common.edit'), visible: showActions },
            { action: 'delete', icon: 'ti-trash', className: 'btn-ghost-danger', title: t('common.delete'), visible: showActions },
        ],
        empty: { icon: 'ti-users', title: t('users.noUsers') },
    });

    container.innerHTML = table.html;
    table.mount(container, {
        async onAction(action, user) {
            if (action === 'edit') {
                openUserModal(state, user);
            } else if (action === 'delete') {
                const confirmed = await confirmDialog(t('users.deleteUser'), t('users.deleteUserConfirm'), t('common.delete'), 'btn-danger');
                if (!confirmed) return;
                try {
                    await apiDelete(`/auth/users/${user.username}`);
                    showToast(t('users.userDeleted'), 'success');
                    await state.reload();
                } catch (error) {
                    showToast(t('common.errorPrefix') + error.message, 'error');
                }
            }
        },
    });
}

/**
 * Render grouped permission checkboxes inside the user modal
 */
export function renderGroupedPermissions(state, userPerms) {
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
    for (const perm of state.permissions) {
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

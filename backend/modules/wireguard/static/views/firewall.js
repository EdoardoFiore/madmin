/**
 * WireGuard Module - Firewall View
 *
 * Manages client groups and firewall rules for WireGuard instances.
 */

import { t } from '/static/js/i18n.js';
import { apiGet, apiPost, apiPatch, apiDelete, apiPut } from '/static/js/api.js';
import { showToast, confirmDialog, loadingSpinner, isValidCIDR, escapeHtml } from '/static/js/utils.js';
import { checkPermission } from '/static/js/app.js';

let currentInstanceId = null;
let currentGroupId = null;
let groups = [];
let clients = [];
let instance = null;
let canManageGroups = false;

export async function init(container, instanceId) {
    currentInstanceId = instanceId;
    canManageGroups = checkPermission('wireguard.groups');
    container.innerHTML = loadingSpinner();

    try {
        [instance, groups, clients] = await Promise.all([
            apiGet(`/modules/wireguard/instances/${instanceId}`),
            apiGet(`/modules/wireguard/instances/${instanceId}/groups`),
            apiGet(`/modules/wireguard/instances/${instanceId}/clients`)
        ]);

        if (groups.length > 0 && !currentGroupId) {
            currentGroupId = groups[0].id;
        }

        render(container);
        setupGroupOrdering();

        if (currentGroupId) {
            loadGroupDetails();
        }
    } catch (err) {
        container.innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
    }
}

function render(container) {
    container.innerHTML = `
        <!-- Instance Default Policy -->
        <div class="card mb-3">
            <div class="card-body py-2 d-flex align-items-center gap-3">
                <strong>${t('wireguard.defaultPolicy')}</strong>
                ${canManageGroups ? `
                <div class="btn-group" role="group">
                    <input type="radio" class="btn-check" name="default-policy" id="policy-accept" value="ACCEPT"
                           ${instance?.firewall_default_policy !== 'DROP' ? 'checked' : ''}>
                    <label class="btn btn-outline-success btn-sm" for="policy-accept">ACCEPT</label>
                    <input type="radio" class="btn-check" name="default-policy" id="policy-drop" value="DROP"
                           ${instance?.firewall_default_policy === 'DROP' ? 'checked' : ''}>
                    <label class="btn btn-outline-danger btn-sm" for="policy-drop">DROP</label>
                </div>` : `
                <span class="badge ${instance?.firewall_default_policy === 'DROP' ? 'bg-danger-lt' : 'bg-success-lt'} fs-6">
                    ${instance?.firewall_default_policy || 'ACCEPT'}
                </span>`}
            </div>
        </div>

        <div class="row">
            <!-- Groups List -->
            <div class="col-md-4">
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <div class="d-flex align-items-center gap-2">
                            <h4 class="card-title mb-0">${t('wireguard.groups')}</h4>
                            <i class="ti ti-info-circle text-muted" data-bs-toggle="tooltip"
                               title="${t('wireguard.groupsOrderTooltip')}"></i>
                        </div>
                        ${canManageGroups ? `
                        <button class="btn btn-sm btn-primary" id="btn-new-group">
                            <i class="ti ti-plus me-1"></i>${t('wireguard.newGroup')}
                        </button>` : ''}
                    </div>
                    <div class="list-group list-group-flush" id="groups-list">
                        ${renderGroupsList()}
                    </div>
                </div>
            </div>

            <!-- Group Details -->
            <div class="col-md-8">
                <div id="group-details">
                    ${currentGroupId ? renderGroupDetails() : renderNoGroupSelected()}
                </div>
            </div>
        </div>

        <!-- Create Group Modal -->
        <div class="modal fade" id="modal-new-group" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${t('wireguard.newGroupTitle')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">${t('wireguard.groupName')}</label>
                            <input type="text" class="form-control" id="new-group-name" placeholder="${t('wireguard.groupNamePlaceholder')}">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">${t('wireguard.groupDescription')}</label>
                            <input type="text" class="form-control" id="new-group-desc" placeholder="${t('wireguard.groupDescPlaceholder')}">
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" data-bs-dismiss="modal">${t('wireguard.cancel')}</button>
                        <button class="btn btn-primary" id="btn-create-group">${t('wireguard.createGroup')}</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Add Member Modal -->
        <div class="modal fade" id="modal-add-member" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${t('wireguard.addMemberTitle')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <select class="form-select" id="member-client-select">
                            <option value="">${t('wireguard.selectClient')}</option>
                            ${clients.map(c => `<option value="${c.id}">${escapeHtml(c.name)} (${c.allocated_ip})</option>`).join('')}
                        </select>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" data-bs-dismiss="modal">${t('wireguard.cancel')}</button>
                        <button class="btn btn-primary" id="btn-confirm-add-member">${t('wireguard.confirmAddMember')}</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Add Rule Modal -->
        <div class="modal fade" id="modal-add-rule" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${t('wireguard.newRuleTitle')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="row mb-3">
                            <div class="col-6">
                                <label class="form-label">${t('wireguard.action')}</label>
                                <select class="form-select" id="rule-action">
                                    <option value="ACCEPT">ACCEPT</option>
                                    <option value="DROP">DROP</option>
                                </select>
                            </div>
                            <div class="col-6">
                                <label class="form-label">${t('wireguard.protocol')}</label>
                                <select class="form-select" id="rule-protocol">
                                    <option value="all">${t('wireguard.allProtocols')}</option>
                                    <option value="tcp">TCP</option>
                                    <option value="udp">UDP</option>
                                    <option value="icmp">ICMP</option>
                                </select>
                            </div>
                        </div>
                        <div class="row mb-3">
                            <div class="col-8">
                                <label class="form-label">${t('wireguard.destination')}</label>
                                <input type="text" class="form-control" id="rule-destination" placeholder="0.0.0.0/0">
                            </div>
                            <div class="col-4" id="port-field-container">
                                <label class="form-label">${t('wireguard.portLabel')}</label>
                                <input type="text" class="form-control" id="rule-port" placeholder="80">
                            </div>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">${t('wireguard.notes')}</label>
                            <input type="text" class="form-control" id="rule-description" placeholder="${t('wireguard.groupDescPlaceholder')}">
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" data-bs-dismiss="modal">${t('wireguard.cancel')}</button>
                        <button class="btn btn-primary" id="btn-create-rule">${t('wireguard.createRule')}</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    setupEventHandlers(container);
}

function renderGroupsList() {
    if (groups.length === 0) {
        return `<div class="list-group-item text-muted text-center py-3">${t('wireguard.noGroups')}</div>`;
    }

    return groups.map(g => `
        <div class="list-group-item list-group-item-action ${g.id === currentGroupId ? 'active' : ''} d-flex align-items-center p-0" data-group-id="${g.id}">
            ${canManageGroups ? `<div class="px-2 py-3 cursor-move group-drag-handle ${g.id === currentGroupId ? 'text-reset' : 'text-muted'}"><i class="ti ti-grip-vertical"></i></div>` : ''}
            <a href="#" class="flex-grow-1 p-3 text-decoration-none text-reset" onclick="event.preventDefault(); selectGroup('${escapeHtml(g.id)}')">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <strong>${escapeHtml(g.name)}</strong>
                        <small class="d-block ${g.id === currentGroupId ? 'text-reset opacity-75' : 'text-muted'}">${g.description || t('wireguard.noDescription')}</small>
                    </div>
                    <div class="d-flex gap-1">
                        <span class="badge ${g.id === currentGroupId ? 'bg-white text-primary' : 'bg-blue-lt text-blue'}">${g.member_count} <i class="ti ti-users"></i></span>
                        <span class="badge ${g.id === currentGroupId ? 'bg-white text-primary' : 'bg-green-lt text-green'}">${g.rule_count} <i class="ti ti-shield"></i></span>
                    </div>
                </div>
            </a>
        </div>
    `).join('');
}

function renderNoGroupSelected() {
    return `
        <div class="card">
            <div class="card-body text-center py-5 text-muted">
                <i class="ti ti-users-group" style="font-size: 3rem;"></i>
                <p class="mt-3 mb-0">${t('wireguard.noGroupSelected')}</p>
            </div>
        </div>
    `;
}

function renderGroupDetails() {
    const group = groups.find(g => g.id === currentGroupId);
    if (!group) return renderNoGroupSelected();

    return `
        <div class="card mb-3">
            <div class="card-header d-flex justify-content-between align-items-center">
                <div>
                    <h4 class="card-title mb-0">${escapeHtml(group.name)}</h4>
                    <small class="text-muted">${group.description || ''}</small>
                </div>
                ${canManageGroups ? `
                <button class="btn btn-sm btn-outline-danger" id="btn-delete-group">
                    <i class="ti ti-trash"></i>
                </button>` : ''}
            </div>
        </div>

        <!-- Members -->
        <div class="card mb-3">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h5 class="card-title mb-0"><i class="ti ti-users me-2"></i>${t('wireguard.members')}</h5>
                ${canManageGroups ? `
                <button class="btn btn-sm btn-primary" id="btn-show-add-member">
                    <i class="ti ti-user-plus me-1"></i>${t('wireguard.addMember')}
                </button>` : ''}
            </div>
            <div class="card-body" id="members-container">${loadingSpinner()}</div>
        </div>

        <!-- Rules -->
        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h5 class="card-title mb-0"><i class="ti ti-shield me-2"></i>${t('wireguard.firewallRules')}</h5>
                ${canManageGroups ? `
                <button class="btn btn-sm btn-primary" id="btn-add-rule">
                    <i class="ti ti-plus me-1"></i>${t('wireguard.newRule')}
                </button>` : ''}
            </div>
            <div class="card-body" id="rules-container">${loadingSpinner()}</div>
        </div>
    `;
}

async function loadGroupDetails() {
    if (!currentGroupId) return;

    try {
        const [members, rules] = await Promise.all([
            apiGet(`/modules/wireguard/instances/${currentInstanceId}/groups/${currentGroupId}/members`),
            apiGet(`/modules/wireguard/instances/${currentInstanceId}/groups/${currentGroupId}/rules`)
        ]);

        renderMembers(members);
        renderRules(rules);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderMembers(members) {
    const container = document.getElementById('members-container');
    if (!container) return;

    if (members.length === 0) {
        container.innerHTML = `<p class="text-muted mb-0">${t('wireguard.noMembers')}</p>`;
        return;
    }

    container.innerHTML = `
        <div class="d-flex flex-wrap gap-2">
            ${members.map(m => `
                <span class="badge bg-primary-lt d-inline-flex align-items-center gap-2">
                    ${escapeHtml(m.client_name)} <small class="opacity-75">(${m.client_ip})</small>
                    ${canManageGroups ? `
                    <button class="btn btn-ghost-danger btn-sm p-0" onclick="removeMember('${escapeHtml(m.client_id)}')">
                        <i class="ti ti-x"></i>
                    </button>` : ''}
                </span>
            `).join('')}
        </div>
    `;
}

function renderRules(rules) {
    const container = document.getElementById('rules-container');
    if (!container) return;

    if (rules.length === 0) {
        container.innerHTML = `<p class="text-muted mb-0">${t('wireguard.noRules')}</p>`;
        return;
    }

    container.innerHTML = `
        <table class="table table-vcenter table-sm">
            <thead>
                <tr>
                    ${canManageGroups ? '<th style="width: 30px"></th>' : ''}
                    <th style="width: 40px">#</th>
                    <th>${t('wireguard.action')}</th>
                    <th>${t('wireguard.protocol')}</th>
                    <th>${t('wireguard.destination')}</th>
                    <th>${t('wireguard.portLabel')}</th>
                    <th>${t('wireguard.notes')}</th>
                    ${canManageGroups ? '<th class="w-1"></th>' : ''}
                </tr>
            </thead>
            <tbody id="rules-tbody">
                ${rules.map((r, i) => `
                    <tr data-rule-id="${r.id}" data-order="${r.order}">
                        ${canManageGroups ? '<td class="cursor-move text-muted" style="cursor: grab;"><i class="ti ti-grip-vertical"></i></td>' : ''}
                        <td class="text-muted">${i + 1}</td>
                        <td><span class="badge ${r.action === 'ACCEPT' ? 'bg-success-lt' : 'bg-danger-lt'}">${r.action}</span></td>
                        <td><code>${r.protocol}</code></td>
                        <td><code>${r.destination}</code></td>
                        <td>${r.port || '*'}</td>
                        <td class="text-muted">${r.description || ''}</td>
                        ${canManageGroups ? `
                        <td>
                            <div class="btn-group btn-group-sm">
                                <button class="btn btn-ghost-primary" onclick="editRule('${escapeHtml(r.id)}')">
                                    <i class="ti ti-pencil"></i>
                                </button>
                                <button class="btn btn-ghost-danger" onclick="deleteRule('${escapeHtml(r.id)}')">
                                    <i class="ti ti-trash"></i>
                                </button>
                            </div>
                        </td>` : ''}
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;

    initRuleSorting();
}

function setupEventHandlers(container) {
    // New group button
    document.getElementById('btn-new-group')?.addEventListener('click', () => {
        new bootstrap.Modal(document.getElementById('modal-new-group')).show();
    });

    // Create group
    document.getElementById('btn-create-group')?.addEventListener('click', async () => {
        const name = document.getElementById('new-group-name').value.trim();
        const description = document.getElementById('new-group-desc').value.trim();

        if (!name) {
            showToast(t('wireguard.enterGroupName'), 'error');
            return;
        }

        try {
            await apiPost(`/modules/wireguard/instances/${currentInstanceId}/groups`, { name, description });
            showToast(t('wireguard.groupCreated'), 'success');
            bootstrap.Modal.getInstance(document.getElementById('modal-new-group'))?.hide();
            groups = await apiGet(`/modules/wireguard/instances/${currentInstanceId}/groups`);
            render(container);
        } catch (err) {
            showToast(err.message, 'error');
        }
    });

    // Delete group
    document.getElementById('btn-delete-group')?.addEventListener('click', async () => {
        if (await confirmDialog(t('wireguard.confirmDeleteGroupTitle'), t('wireguard.confirmDeleteGroupMsg'), t('wireguard.confirmDeleteBtn'))) {
            try {
                await apiDelete(`/modules/wireguard/instances/${currentInstanceId}/groups/${currentGroupId}`);
                showToast(t('wireguard.groupDeleted'), 'success');
                currentGroupId = null;
                groups = await apiGet(`/modules/wireguard/instances/${currentInstanceId}/groups`);
                render(container);
            } catch (err) {
                showToast(err.message, 'error');
            }
        }
    });

    // Show add member modal
    document.getElementById('btn-show-add-member')?.addEventListener('click', () => {
        new bootstrap.Modal(document.getElementById('modal-add-member')).show();
    });

    // Confirm add member
    document.getElementById('btn-confirm-add-member')?.addEventListener('click', async () => {
        const clientId = document.getElementById('member-client-select').value;
        if (!clientId) {
            showToast(t('wireguard.selectClientError'), 'error');
            return;
        }

        try {
            await apiPost(`/modules/wireguard/instances/${currentInstanceId}/groups/${currentGroupId}/members?client_id=${clientId}`);
            showToast(t('wireguard.memberAdded'), 'success');
            bootstrap.Modal.getInstance(document.getElementById('modal-add-member'))?.hide();
            loadGroupDetails();
        } catch (err) {
            showToast(err.message, 'error');
        }
    });

    // Add rule button
    document.getElementById('btn-add-rule')?.addEventListener('click', () => {
        document.getElementById('rule-protocol').value = 'all';
        document.getElementById('port-field-container').style.display = 'none';
        new bootstrap.Modal(document.getElementById('modal-add-rule')).show();
    });

    // Protocol change - toggle port field
    document.getElementById('rule-protocol')?.addEventListener('change', (e) => {
        const portContainer = document.getElementById('port-field-container');
        if (e.target.value === 'all' || e.target.value === 'icmp') {
            portContainer.style.display = 'none';
            document.getElementById('rule-port').value = '';
        } else {
            portContainer.style.display = 'block';
        }
    });

    // Create/Edit rule
    document.getElementById('btn-create-rule')?.addEventListener('click', async () => {
        const modal = document.getElementById('modal-add-rule');
        const editRuleId = modal?.dataset.editRuleId;
        const protocol = document.getElementById('rule-protocol').value;
        const destRaw = document.getElementById('rule-destination').value.trim();
        if (destRaw && !isValidCIDR(destRaw)) {
            showToast(t('wireguard.invalidDestination'), 'error');
            return;
        }
        const data = {
            action: document.getElementById('rule-action').value,
            protocol: protocol,
            destination: destRaw || '0.0.0.0/0',
            port: (protocol === 'tcp' || protocol === 'udp') ? (document.getElementById('rule-port').value.trim() || null) : null,
            description: document.getElementById('rule-description').value.trim()
        };

        try {
            if (editRuleId) {
                await apiPatch(`/modules/wireguard/instances/${currentInstanceId}/groups/${currentGroupId}/rules/${editRuleId}`, data);
                showToast(t('wireguard.ruleUpdated'), 'success');
            } else {
                await apiPost(`/modules/wireguard/instances/${currentInstanceId}/groups/${currentGroupId}/rules`, data);
                showToast(t('wireguard.ruleCreated'), 'success');
            }
            bootstrap.Modal.getInstance(modal)?.hide();
            loadGroupDetails();
            refreshGroupsList();
        } catch (err) {
            showToast(err.message, 'error');
        }
    });

    // Reset modal when closed
    document.getElementById('modal-add-rule')?.addEventListener('hidden.bs.modal', () => {
        const modal = document.getElementById('modal-add-rule');
        delete modal.dataset.editRuleId;
        modal.querySelector('.modal-title').textContent = t('wireguard.newRuleTitle');
        document.getElementById('btn-create-rule').textContent = t('wireguard.createRule');
        document.getElementById('rule-action').value = 'DROP';
        document.getElementById('rule-protocol').value = 'all';
        document.getElementById('rule-destination').value = '';
        document.getElementById('rule-port').value = '';
        document.getElementById('rule-description').value = '';
        document.getElementById('port-field-container').style.display = 'none';
    });
}

// Global functions for inline handlers
window.removeMember = async (clientId) => {
    if (await confirmDialog(t('wireguard.confirmRemoveMemberTitle'), t('wireguard.confirmRemoveMemberMsg'), t('wireguard.confirmRemoveBtn'))) {
        try {
            await apiDelete(`/modules/wireguard/instances/${currentInstanceId}/groups/${currentGroupId}/members/${clientId}`);
            showToast(t('wireguard.memberRemoved'), 'success');
            loadGroupDetails();
            refreshGroupsList();
        } catch (err) {
            showToast(err.message, 'error');
        }
    }
};

window.deleteRule = async (ruleId) => {
    if (await confirmDialog(t('wireguard.confirmDeleteRuleTitle'), t('wireguard.confirmDeleteRuleMsg'), t('wireguard.confirmDeleteBtn'))) {
        try {
            await apiDelete(`/modules/wireguard/instances/${currentInstanceId}/groups/${currentGroupId}/rules/${ruleId}`);
            showToast(t('wireguard.ruleDeleted'), 'success');
            loadGroupDetails();
            refreshGroupsList();
        } catch (err) {
            showToast(err.message, 'error');
        }
    }
};

window.editRule = async (ruleId) => {
    const rulesData = await apiGet(`/modules/wireguard/instances/${currentInstanceId}/groups/${currentGroupId}/rules`);
    const rule = rulesData.find(r => r.id === ruleId);
    if (!rule) return;

    document.getElementById('rule-action').value = rule.action;
    document.getElementById('rule-protocol').value = rule.protocol;
    document.getElementById('rule-destination').value = rule.destination || '';
    document.getElementById('rule-port').value = rule.port || '';
    document.getElementById('rule-description').value = rule.description || '';

    const portContainer = document.getElementById('port-field-container');
    if (portContainer) {
        portContainer.style.display = (rule.protocol === 'tcp' || rule.protocol === 'udp') ? '' : 'none';
    }

    const modal = document.getElementById('modal-add-rule');
    modal.dataset.editRuleId = ruleId;
    modal.querySelector('.modal-title').textContent = t('wireguard.editRuleTitle');
    document.getElementById('btn-create-rule').textContent = t('wireguard.save');

    new bootstrap.Modal(modal).show();
};

window.selectGroup = (groupId) => {
    currentGroupId = groupId;
    loadGroupDetails();
    refreshGroupsList();
};

function setupGroupOrdering() {
    const listEl = document.getElementById('groups-list');
    if (!listEl || typeof Sortable === 'undefined' || !canManageGroups) return;

    new Sortable(listEl, {
        animation: 150,
        handle: '.group-drag-handle',
        onEnd: async function (evt) {
            const items = listEl.querySelectorAll('[data-group-id]');
            const orders = [];
            items.forEach((item, index) => {
                orders.push({ group_id: item.dataset.groupId, order: index });
            });

            try {
                await apiPut(`/modules/wireguard/instances/${currentInstanceId}/groups/order`, orders);
                showToast(t('wireguard.groupsOrderUpdated'), 'success');
                const newGroups = [];
                items.forEach(item => {
                    const group = groups.find(g => g.id === item.dataset.groupId);
                    if (group) newGroups.push(group);
                });
                groups = newGroups;
            } catch (err) {
                showToast(err.message, 'error');
                refreshGroupsList();
            }
        }
    });
}

async function refreshGroupsList() {
    try {
        groups = await apiGet(`/modules/wireguard/instances/${currentInstanceId}/groups`);
        const listEl = document.getElementById('groups-list');
        if (listEl) {
            listEl.innerHTML = renderGroupsList();
            setupGroupOrdering();
        }
    } catch (err) {
        console.error('Failed to refresh groups list:', err);
    }
}

function initRuleSorting() {
    const tbody = document.getElementById('rules-tbody');
    if (!tbody || typeof Sortable === 'undefined') return;

    new Sortable(tbody, {
        animation: 150,
        handle: 'td.cursor-move',
        ghostClass: 'table-active',
        onEnd: async function (evt) {
            const rows = tbody.querySelectorAll('tr[data-rule-id]');
            const orders = [];
            rows.forEach((row, index) => {
                orders.push({ id: row.dataset.ruleId, order: index });
            });

            rows.forEach((row, index) => {
                row.querySelector('td:nth-child(2)').textContent = index + 1;
            });

            try {
                await apiPut(`/modules/wireguard/instances/${currentInstanceId}/groups/${currentGroupId}/rules/order`, orders);
                showToast(t('wireguard.orderUpdated'), 'success');
            } catch (err) {
                showToast(err.message, 'error');
                loadGroupDetails();
            }
        }
    });
}

// Handle policy change
document.addEventListener('change', async (e) => {
    if (e.target.name === 'default-policy') {
        const newPolicy = e.target.value;
        try {
            await apiPatch(`/modules/wireguard/instances/${currentInstanceId}/firewall-policy`, { policy: newPolicy });
            instance.firewall_default_policy = newPolicy;
            showToast(t('wireguard.policyUpdated').replace('{policy}', newPolicy), 'success');
        } catch (err) {
            showToast(err.message, 'error');
        }
    }
});

// Add CSS for cursor
const style = document.createElement('style');
style.textContent = '.cursor-move { cursor: move; }';
document.head.appendChild(style);

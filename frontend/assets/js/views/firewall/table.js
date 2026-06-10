/**
 * MADMIN - Firewall View / rules tables (render, row actions, drag-drop)
 */

import { apiPost, apiPatch, apiDelete } from '../../api.js';
import { showToast, confirmDialog, actionBadge, emptyState, escapeHtml } from '../../utils.js';
import { checkPermission } from '../../app.js';
import { t } from '../../i18n.js';
import { TABLES, ALL_COLUMNS, MANAGED_NAT_SENTINEL } from './constants.js';
import { getOrderedVisibleColumns } from './columns.js';
import { openRuleModal } from './rule-modal.js';

/**
 * Render rules in the per-chain tables
 */
export function renderRules(state) {
    const chains = TABLES[state.currentTable].chains;

    for (const chain of chains) {
        const chainRules = state.rules
            .filter(r => r.table_name === state.currentTable && r.chain === chain)
            .sort((a, b) => a.order - b.order);
        const containerId = `rules-${chain.toLowerCase()}`;
        const container = document.getElementById(containerId);

        // Update count
        const countEl = document.getElementById(`count-${chain.toLowerCase()}`);
        if (countEl) {
            countEl.textContent = chainRules.length;
        }

        if (!container) continue;

        if (chainRules.length === 0) {
            container.innerHTML = emptyState('ti-shield-off', t('firewall.noRules'), t('firewall.noRulesInChain', { chain }));
            continue;
        }

        const orderedColumns = getOrderedVisibleColumns(state);

        container.innerHTML = `
            <div class="table-responsive">
                <table class="table table-vcenter firewall-table" id="table-${chain.toLowerCase()}">
                    <thead>
                        <tr>
                            <th class="rule-order" style="width: 60px;">#</th>
                            <th>${t('firewall.action')}</th>
                            ${orderedColumns.map(col => `<th>${ALL_COLUMNS[col].label}</th>`).join('')}
                            <th class="rule-actions"></th>
                        </tr>
                    </thead>
                    <tbody class="sortable-container" data-chain="${chain}">
                        ${chainRules.map(rule => renderRuleRow(state, rule, orderedColumns)).join('')}
                    </tbody>
                </table>
            </div>
        `;

        // Setup row event listeners and drag-drop
        setupRowEvents(state, container);
        setupDragDrop(state, container.querySelector('.sortable-container'));
    }
}

/**
 * Render a single rule row
 */
function renderRuleRow(state, rule, orderedColumns) {
    const canManage = checkPermission('firewall.manage');
    const disabledClass = rule.enabled ? '' : 'disabled';
    const columns = orderedColumns;

    // Auto-generated companion rules (e.g. DNAT forward): read-only, no drag/edit/delete
    if (rule.auto_generated) {
        return `
            <tr class="auto-rule" data-id="${rule.id}">
                <td class="rule-order">
                    <span class="text-muted"><i class="ti ti-lock"></i></span>
                </td>
                <td>${actionBadge(rule.action)} <span class="badge bg-azure-lt" title="${t('firewall.autoRuleHint')}">${t('firewall.autoRule')}</span></td>
                ${columns.map(col => `<td>${renderCell(rule, col)}</td>`).join('')}
                <td class="rule-actions"></td>
            </tr>
        `;
    }

    // Managed LAN NAT rule: protected (needed for VM navigation), read-only
    if (rule.comment === MANAGED_NAT_SENTINEL) {
        return `
            <tr class="auto-rule" data-id="${rule.id}">
                <td class="rule-order">
                    <span class="text-muted"><i class="ti ti-lock"></i></span>
                </td>
                <td>${actionBadge(rule.action)} <span class="badge bg-azure-lt" title="${t('firewall.managedNatHint')}"><i class="ti ti-lock me-1"></i>${t('firewall.managedNat')}</span></td>
                ${columns.map(col => `<td>${renderCell(rule, col)}</td>`).join('')}
                <td class="rule-actions"></td>
            </tr>
        `;
    }

    return `
        <tr class="${disabledClass} draggable-row" data-id="${rule.id}" draggable="${canManage}">
            <td class="rule-order">
                <div style="display:flex;align-items:center;gap:4px;white-space:nowrap;">
                    ${canManage ? '<i class="ti ti-grip-vertical drag-handle" style="cursor: grab;"></i>' : ''}
                    <span>${rule.order + 1}</span>
                </div>
            </td>
            <td>${actionBadge(rule.action)}</td>
            ${columns.map(col => `<td>${renderCell(rule, col)}</td>`).join('')}
            <td class="rule-actions">
                ${canManage ? `
                    <div class="btn-group btn-group-sm">
                        ${['DROP', 'REJECT'].includes(rule.action) ? `
                        <button class="btn btn-ghost-warning btn-flush-conntrack"
                                title="${t('firewall.terminateSessionsHint')}">
                            <i class="ti ti-plug-x"></i>
                        </button>` : ''}
                        <button class="btn btn-ghost-secondary btn-duplicate" title="${t('common.copy')}">
                            <i class="ti ti-copy"></i>
                        </button>
                        <button class="btn btn-ghost-primary btn-edit" title="${t('common.edit')}">
                            <i class="ti ti-edit"></i>
                        </button>
                        <button class="btn btn-ghost-danger btn-delete" title="${t('common.delete')}">
                            <i class="ti ti-trash"></i>
                        </button>
                    </div>
                ` : ''}
            </td>
        </tr>
    `;
}

/**
 * Render a cell based on column type
 */
function renderCell(rule, column) {
    const esc = escapeHtml;
    switch (column) {
        case 'protocol': return rule.protocol ? `<code>${rule.protocol}</code>` : `<span class="text-muted">${t('firewall.allProtocols').toLowerCase()}</span>`;
        case 'source': return rule.source ? `<code>${esc(rule.source)}</code>` : '<span class="text-muted">-</span>';
        case 'destination': return rule.destination ? `<code>${esc(rule.destination)}</code>` : '<span class="text-muted">-</span>';
        case 'port': return rule.port ? `<code>${esc(rule.port)}</code>` : '<span class="text-muted">-</span>';
        case 'state': return rule.state ? `<span class="badge bg-secondary-lt">${rule.state}</span>` : '-';
        case 'comment': return `<span class="text-muted">${rule.comment ? esc(rule.comment) : '-'}</span>`;
        case 'in_interface': return rule.in_interface ? `<code>${esc(rule.in_interface)}</code>` : '-';
        case 'out_interface': return rule.out_interface ? `<code>${esc(rule.out_interface)}</code>` : '-';
        case 'to_destination': return rule.to_destination ? `<code>${esc(rule.to_destination)}</code>` : '-';
        case 'to_source': return rule.to_source ? `<code>${esc(rule.to_source)}</code>` : '-';
        case 'to_ports': return rule.to_ports ? `<code>${esc(rule.to_ports)}</code>` : '-';
        case 'log_prefix': return rule.log_prefix ? `<code>${esc(rule.log_prefix)}</code>` : '-';
        case 'limit_rate': return rule.limit_rate ? `${esc(rule.limit_rate)}${rule.limit_burst ? ` (burst: ${rule.limit_burst})` : ''}` : '-';
        default: return '-';
    }
}

/**
 * Setup drag and drop for rule ordering
 */
function setupDragDrop(state, tbody) {
    if (!tbody || !checkPermission('firewall.manage')) return;

    let draggedRow = null;

    tbody.querySelectorAll('.draggable-row').forEach(row => {
        row.addEventListener('dragstart', (e) => {
            draggedRow = row;
            row.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', row.dataset.id);
        });

        row.addEventListener('dragend', () => {
            row.classList.remove('dragging');
            draggedRow = null;
            // Remove all drag-over states
            tbody.querySelectorAll('.drag-over').forEach(r => r.classList.remove('drag-over'));
        });

        row.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            if (row !== draggedRow) {
                row.classList.add('drag-over');
            }
        });

        row.addEventListener('dragleave', () => {
            row.classList.remove('drag-over');
        });

        row.addEventListener('drop', async (e) => {
            e.preventDefault();
            row.classList.remove('drag-over');

            if (draggedRow && row !== draggedRow) {
                const draggedId = draggedRow.dataset.id;
                const targetId = row.dataset.id;

                // Find indices
                const draggedRule = state.rules.find(r => r.id === draggedId);
                const targetRule = state.rules.find(r => r.id === targetId);

                if (draggedRule && targetRule) {
                    try {
                        await apiPatch(`/firewall/rules/${draggedId}/reorder`, {
                            new_order: targetRule.order
                        });
                        showToast(t('firewall.orderUpdated'), 'success');
                        await state.reload();
                    } catch (error) {
                        showToast(t('common.errorPrefix') + error.message, 'error');
                    }
                }
            }
        });
    });
}

/**
 * Setup row event listeners
 */
function setupRowEvents(state, container) {
    // Flush conntrack buttons
    container.querySelectorAll('.btn-flush-conntrack').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const row = e.target.closest('tr');
            const ruleId = row.dataset.id;
            const rule = state.rules.find(r => r.id === ruleId);

            const confirmed = await confirmDialog(
                t('firewall.terminateSessionsTitle'),
                t('firewall.terminateSessionsDesc', { action: rule?.action || '' }),
                t('firewall.terminateBtn'),
                'btn-warning'
            );
            if (!confirmed) return;

            btn.disabled = true;
            const icon = btn.querySelector('i');
            icon.className = 'ti ti-loader-2 spin';
            try {
                const result = await apiPost(`/firewall/rules/${ruleId}/flush-conntrack`, {});
                const count = result.flushed ?? 0;
                showToast(
                    count > 0
                        ? (count === 1 ? t('firewall.sessionTerminated') : t('firewall.sessionsTerminated', { count }))
                        : t('firewall.noActiveSessions'),
                    'success'
                );
            } catch (error) {
                showToast(t('common.errorPrefix') + error.message, 'error');
            } finally {
                btn.disabled = false;
                icon.className = 'ti ti-plug-x';
            }
        });
    });

    // Edit buttons
    container.querySelectorAll('.btn-edit').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const row = e.target.closest('tr');
            const rule = state.rules.find(r => r.id === row.dataset.id);
            if (rule) {
                openRuleModal(state, rule);
            }
        });
    });

    // Duplicate buttons
    container.querySelectorAll('.btn-duplicate').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const ruleId = e.target.closest('tr').dataset.id;
            const rule = state.rules.find(r => r.id === ruleId);
            if (rule) openRuleModal(state, rule, true);   // apre modale create pre-compilata
        });
    });

    // Delete buttons
    container.querySelectorAll('.btn-delete').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const row = e.target.closest('tr');
            const ruleId = row.dataset.id;

            const confirmed = await confirmDialog(
                t('firewall.deleteRule'),
                t('firewall.deleteRuleConfirm'),
                t('common.delete'),
                'btn-danger'
            );

            if (confirmed) {
                try {
                    await apiDelete(`/firewall/rules/${ruleId}`);
                    showToast(t('firewall.ruleDeleted'), 'success');
                    await state.reload();
                } catch (error) {
                    showToast(t('common.errorPrefix') + error.message, 'error');
                }
            }
        });
    });
}

/**
 * MADMIN - Firewall View
 *
 * Machine firewall management with multiple tables support.
 * Submodules: table.js (rules tables + drag-drop), rule-modal.js,
 * columns.js (visibility prefs), export-import.js, gateway.js (matrix).
 */

import { apiGet } from '../../api.js';
import { showToast } from '../../utils.js';
import { setPageActions, checkPermission } from '../../app.js';
import { t } from '../../i18n.js';
import { TABLES } from './constants.js';
import { loadUserPreferences, updateVisibleColumns } from './columns.js';
import { renderRules } from './table.js';
import { ruleModalHtml, bindRuleModal, openRuleModal } from './rule-modal.js';
import { handleExport, openImportModal } from './export-import.js';
import { openGatewayModal } from './gateway.js';

/**
 * Render the firewall view
 */
export async function render(container) {
    const state = {
        rules: [],
        editingRule: null,
        currentTable: 'filter',
        currentChain: 'INPUT',
        userPreferences: {},
        visibleColumns: [],
        reload: loadRules,
        rerender: () => renderRules(state),
    };

    if (checkPermission('firewall.manage')) {
        setPageActions(`
            <div class="btn-list">
                <button class="btn btn-outline-secondary" id="btn-export">
                    <i class="ti ti-download me-2"></i>${t('firewall.exportBtn')}
                </button>
                <button class="btn btn-outline-secondary" id="btn-import">
                    <i class="ti ti-upload me-2"></i>${t('firewall.importBtn')}
                </button>
                <button class="btn btn-outline-secondary" id="btn-gw-access">
                    <i class="ti ti-network me-2"></i>${t('firewall.gatewayAccess')}
                </button>
                <button class="btn btn-primary" id="btn-add-rule">
                    <i class="ti ti-plus me-2"></i>${t('firewall.newRule')}
                </button>
            </div>
        `);
    }

    // Pre-fetch column prefs + rules in parallel before any DOM write
    await Promise.all([
        loadUserPreferences(state),
        apiGet('/firewall/rules').then(r => { state.rules = r; }).catch(() => {}),
    ]);

    container.innerHTML = `
        <div class="row">
            <div class="col-12">
                <!-- Table Selection -->
                <div class="card mb-3">
                    <div class="card-body py-2">
                        <div class="d-flex gap-2">
                            <div class="btn-group flex-grow-1" role="group">
                                ${Object.entries(TABLES).map(([key, tbl]) => `
                                    <input type="radio" class="btn-check" name="fw-table" id="table-${key}"
                                           value="${key}" ${key === 'filter' ? 'checked' : ''}>
                                    <label class="btn btn-outline-primary" for="table-${key}">
                                        <i class="ti ti-${tbl.icon} me-1"></i>${tbl.label}
                                    </label>
                                `).join('')}
                            </div>
                            <div class="dropdown">
                                <button class="btn btn-outline-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" data-bs-auto-close="outside">
                                    <i class="ti ti-columns me-2"></i>${t('common.columns')}
                                </button>
                                <div class="dropdown-menu dropdown-menu-end" id="column-selector">
                                    <!-- Populated dynamically -->
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Chain Tabs -->
                <div class="card">
                    <div class="card-header">
                        <ul class="nav nav-tabs card-header-tabs" role="tablist" id="chain-tabs">
                            <!-- Tabs will be rendered dynamically -->
                        </ul>
                    </div>
                    <div class="card-body">
                        <div class="tab-content" id="chain-content">
                            <!-- Content will be rendered dynamically -->
                        </div>
                    </div>
                </div>
            </div>
        </div>

        ${ruleModalHtml()}
    `;

    // Page action buttons
    document.getElementById('btn-export')?.addEventListener('click', handleExport);
    document.getElementById('btn-import')?.addEventListener('click', () => openImportModal(state));
    document.getElementById('btn-gw-access')?.addEventListener('click', openGatewayModal);
    document.getElementById('btn-add-rule')?.addEventListener('click', () => openRuleModal(state));

    bindRuleModal(state);

    // Table selection
    document.querySelectorAll('input[name="fw-table"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            state.currentTable = e.target.value;
            updateVisibleColumns(state); // Update columns for new table
            renderChainTabs(state);
            renderRules(state);
        });
    });

    // Sync: chain tabs create the DOM containers, renderRules fills them — no intermediate paint
    renderChainTabs(state);
    renderRules(state);

    async function loadRules() {
        try {
            state.rules = await apiGet('/firewall/rules');
            renderRules(state);
        } catch (error) {
            showToast(t('firewall.loadRulesError', { error: error.message }), 'error');
        }
    }
}

/**
 * Render chain tabs for current table
 */
function renderChainTabs(state) {
    const tabsContainer = document.getElementById('chain-tabs');
    const contentContainer = document.getElementById('chain-content');
    if (!tabsContainer || !contentContainer) return;

    const chains = TABLES[state.currentTable].chains;
    state.currentChain = chains[0];

    tabsContainer.innerHTML = chains.map((chain, i) => `
        <li class="nav-item" role="presentation">
            <button class="nav-link ${i === 0 ? 'active' : ''}" data-bs-toggle="tab"
                    data-bs-target="#tab-${chain.toLowerCase()}" type="button"
                    data-chain="${chain}">
                ${chain}
                <span class="badge bg-azure-lt ms-2" id="count-${chain.toLowerCase()}">0</span>
            </button>
        </li>
    `).join('');

    contentContainer.innerHTML = chains.map((chain, i) => `
        <div class="tab-pane ${i === 0 ? 'active show' : ''}" id="tab-${chain.toLowerCase()}" role="tabpanel">
            <div id="rules-${chain.toLowerCase()}"></div>
        </div>
    `).join('');

    tabsContainer.querySelectorAll('button[data-bs-toggle="tab"]').forEach(btn => {
        btn.addEventListener('shown.bs.tab', () => {
            state.currentChain = btn.dataset.chain;
        });
    });
}

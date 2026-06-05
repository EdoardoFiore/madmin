/**
 * MADMIN - Firewall View
 * 
 * Machine firewall management with multiple tables support.
 * Displays rules with drag-and-drop ordering and iptables preview.
 */

import { apiGet, apiPost, apiPatch, apiDelete, apiPut, apiFetch } from '../api.js';
import { showToast, confirmDialog, actionBadge, emptyState, escapeHtml } from '../utils.js';
import { setPageActions, checkPermission } from '../app.js';
import { t } from '../i18n.js';

// Sentinel comment marking the protected managed-LAN MASQUERADE rule (mirrors backend)
const MANAGED_NAT_SENTINEL = 'MADMIN_MANAGED_LAN_NAT';

let rules = [];
let editingRule = null;
let currentTable = 'filter';
let currentChain = 'INPUT';
let userPreferences = {};
let visibleColumns = [];

// Column definitions
const ALL_COLUMNS = {
    protocol: { get label() { return t('firewall.columnLabels.protocol'); } },
    source: { get label() { return t('firewall.columnLabels.source'); } },
    destination: { get label() { return t('firewall.columnLabels.destination'); } },
    port: { get label() { return t('firewall.columnLabels.port'); } },
    state: { get label() { return t('firewall.columnLabels.state'); } },
    in_interface: { get label() { return t('firewall.columnLabels.in_interface'); } },
    out_interface: { get label() { return t('firewall.columnLabels.out_interface'); } },
    to_destination: { get label() { return t('firewall.columnLabels.to_destination'); }, tables: ['nat'] },
    to_source: { get label() { return t('firewall.columnLabels.to_source'); }, tables: ['nat'] },
    to_ports: { get label() { return t('firewall.columnLabels.to_ports'); }, tables: ['nat'] },
    log_prefix: { get label() { return t('firewall.columnLabels.log_prefix'); } },
    limit_rate: { get label() { return t('firewall.columnLabels.limit_rate'); } },
    comment: { get label() { return t('firewall.columnLabels.comment'); } }
};

const DEFAULT_COLUMNS = {
    filter: ['protocol', 'source', 'destination', 'port', 'state', 'comment'],
    nat: ['protocol', 'source', 'destination', 'port', 'to_destination', 'to_source', 'comment'],
    mangle: ['protocol', 'source', 'destination', 'port', 'state', 'comment'],
    raw: ['protocol', 'source', 'destination', 'port', 'state', 'comment']
};

// Table definitions with their chains
const TABLES = {
    filter: { label: 'Filter', chains: ['INPUT', 'OUTPUT', 'FORWARD'], icon: 'shield' },
    nat: { label: 'NAT', chains: ['PREROUTING', 'POSTROUTING', 'OUTPUT'], icon: 'arrows-exchange' },
    mangle: { label: 'Mangle', chains: ['PREROUTING', 'INPUT', 'FORWARD', 'OUTPUT', 'POSTROUTING'], icon: 'adjustments' },
    raw: { label: 'Raw', chains: ['PREROUTING', 'OUTPUT'], icon: 'bolt' }
};

// Actions available per table
const TABLE_ACTIONS = {
    filter: ['ACCEPT', 'DROP', 'REJECT', 'LOG'],
    nat: ['SNAT', 'DNAT', 'MASQUERADE', 'REDIRECT', 'ACCEPT'],
    mangle: ['MARK', 'TOS', 'TTL', 'ACCEPT'],
    raw: ['NOTRACK', 'ACCEPT']
};

/**
 * Render the firewall view
 */
export async function render(container) {
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

    container.innerHTML = `
        <div class="row">
            <div class="col-12">
                <!-- Table Selection -->
                <div class="card mb-3">
                    <div class="card-body py-2">
                        <div class="d-flex gap-2">
                            <div class="btn-group flex-grow-1" role="group">
                                ${Object.entries(TABLES).map(([key, t]) => `
                                    <input type="radio" class="btn-check" name="fw-table" id="table-${key}" 
                                           value="${key}" ${key === 'filter' ? 'checked' : ''}>
                                    <label class="btn btn-outline-primary" for="table-${key}">
                                        <i class="ti ti-${t.icon} me-1"></i>${t.label}
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
        
        <!-- Rule Modal -->
        <div class="modal modal-blur fade" id="rule-modal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="rule-modal-title">${t('firewall.newRule')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <form id="rule-form">
                        <div class="modal-body">
                            <div class="row g-3">
                                <div class="col-md-4">
                                    <label class="form-label required">${t('firewall.table')}</label>
                                    <select class="form-select" id="rule-table" required>
                                        ${Object.entries(TABLES).map(([k, tbl]) => `<option value="${k}">${tbl.label}</option>`).join('')}
                                    </select>
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label required">${t('firewall.chain')}</label>
                                    <select class="form-select" id="rule-chain" required>
                                        <!-- Populated dynamically -->
                                    </select>
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label required">${t('firewall.action')}</label>
                                    <select class="form-select" id="rule-action" required>
                                        <!-- Populated dynamically -->
                                    </select>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">${t('firewall.protocol')}</label>
                                    <select class="form-select" id="rule-protocol">
                                        <option value="">${t('firewall.allProtocols')}</option>
                                        <option value="tcp">TCP</option>
                                        <option value="udp">UDP</option>
                                        <option value="icmp">ICMP</option>
                                    </select>
                                </div>
                                <div class="col-md-6" id="port-group">
                                    <label class="form-label">${t('firewall.port')}</label>
                                    <input type="text" class="form-control" id="rule-port" placeholder="80, 443, 8000:8080">
                                    <small class="form-hint">${t('firewall.portHint')}</small>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">${t('firewall.source')}</label>
                                    <input type="text" class="form-control" id="rule-source"
                                           placeholder="es. 192.168.1.0/24">
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">${t('firewall.destination')}</label>
                                    <input type="text" class="form-control" id="rule-destination"
                                           placeholder="es. 10.0.0.0/8">
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">${t('firewall.inInterface')}</label>
                                    <input type="text" class="form-control" id="rule-in-interface"
                                           placeholder="es. eth0, wg0">
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">${t('firewall.outInterface')}</label>
                                    <input type="text" class="form-control" id="rule-out-interface"
                                           placeholder="es. eth0, wg0">
                                </div>

                                <!-- Action Specific Fields -->
                                <div class="col-md-6 field-dnat" style="display:none">
                                    <label class="form-label">
                                        To Destination 
                                        <i class="ti ti-help text-muted" data-bs-toggle="tooltip" title="Address to redirect to, e.g. 192.168.1.50:80"></i>
                                    </label>
                                    <input type="text" class="form-control" id="rule-to-destination" placeholder="192.168.1.50:80">
                                </div>
                                <div class="col-md-6 field-snat" style="display:none">
                                    <label class="form-label">
                                        To Source
                                        <i class="ti ti-help text-muted" data-bs-toggle="tooltip" title="Source address to map to, e.g. 1.2.3.4"></i>
                                    </label>
                                    <input type="text" class="form-control" id="rule-to-source" placeholder="1.2.3.4">
                                </div>
                                <div class="col-md-6 field-redirect" style="display:none">
                                    <label class="form-label">
                                        To Ports
                                        <i class="ti ti-help text-muted" data-bs-toggle="tooltip" title="Port range to map to, e.g. 8080"></i>
                                    </label>
                                    <input type="text" class="form-control" id="rule-to-ports" placeholder="8080">
                                </div>
                                <div class="col-md-6 field-log" style="display:none">
                                    <label class="form-label">
                                        Log Prefix
                                        <i class="ti ti-help text-muted" data-bs-toggle="tooltip" title="Prefix for log messages, max 29 chars"></i>
                                    </label>
                                    <input type="text" class="form-control" id="rule-log-prefix" placeholder="[DROP_SSH] ">
                                </div>
                                <div class="col-md-6 field-log" style="display:none">
                                    <label class="form-label">Log Level</label>
                                    <select class="form-select" id="rule-log-level">
                                        <option value="">Default</option>
                                        <option value="alert">Alert</option>
                                        <option value="crit">Crit</option>
                                        <option value="error">Error</option>
                                        <option value="warning">Warning</option>
                                        <option value="notice">Notice</option>
                                        <option value="info">Info</option>
                                        <option value="debug">Debug</option>
                                    </select>
                                </div>
                                <div class="col-md-6 field-reject" style="display:none">
                                    <label class="form-label">
                                        Reject With
                                        <i class="ti ti-help text-muted" data-bs-toggle="tooltip" title="ICMP Error message to send back"></i>
                                    </label>
                                    <select class="form-select" id="rule-reject-with">
                                        <option value="">Default (icmp-port-unreachable)</option>
                                        <option value="icmp-net-unreachable">icmp-net-unreachable</option>
                                        <option value="icmp-host-unreachable">icmp-host-unreachable</option>
                                        <option value="icmp-port-unreachable">icmp-port-unreachable</option>
                                        <option value="icmp-proto-unreachable">icmp-proto-unreachable</option>
                                        <option value="icmp-net-prohibited">icmp-net-prohibited</option>
                                        <option value="icmp-host-prohibited">icmp-host-prohibited</option>
                                        <option value="icmp-admin-prohibited">icmp-admin-prohibited</option>
                                    </select>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">${t('firewall.connectionState')}</label>
                                    <select class="form-select" id="rule-state">
                                        <option value="">${t('common.none')}</option>
                                        <option value="NEW">NEW</option>
                                        <option value="ESTABLISHED">ESTABLISHED</option>
                                        <option value="RELATED">RELATED</option>
                                        <option value="ESTABLISHED,RELATED">ESTABLISHED,RELATED</option>
                                        <option value="NEW,ESTABLISHED,RELATED">NEW,ESTABLISHED,RELATED</option>
                                    </select>
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label">${t('firewall.rateLimit')}</label>
                                    <input type="text" class="form-control" id="rule-limit-rate"
                                           placeholder="es. 10/second, 100/minute">
                                    <small class="form-hint">${t('firewall.rateLimitHint')}</small>
                                </div>
                                <div class="col-md-2">
                                    <label class="form-label">${t('firewall.burst')}</label>
                                    <input type="number" class="form-control" id="rule-limit-burst" 
                                           placeholder="es. 5" min="1">
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">${t('firewall.enabledLabel')}</label>
                                    <label class="form-check form-switch mt-2">
                                        <input class="form-check-input" type="checkbox" id="rule-enabled" checked>
                                        <span class="form-check-label">${t('firewall.ruleActive')}</span>
                                    </label>
                                </div>
                                <div class="col-12">
                                    <label class="form-label">${t('firewall.comment')}</label>
                                    <input type="text" class="form-control" id="rule-comment"
                                           placeholder="${t('firewall.commentPlaceholder')}">
                                </div>
                                <!-- iptables Preview -->
                                <div class="col-12">
                                    <label class="form-label">${t('firewall.iptablesPreview')}</label>
                                    <pre class="bg-dark text-success p-3 rounded" id="iptables-preview" 
                                         style="font-family: monospace; font-size: 0.85rem; overflow-x: auto;">
iptables -t filter -A INPUT -j ACCEPT
                                    </pre>
                                </div>
                            </div>
                            <div class="field-drop-info mt-3" style="display:none">
                                <div class="alert alert-info py-2 mb-0" style="font-size:0.82rem">
                                    <div class="d-flex">
                                        <i class="ti ti-info-circle me-2 mt-1 flex-shrink-0"></i>
                                        <div>${t('firewall.dropInfo')}</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.cancel')}</button>
                            <button type="submit" class="btn btn-primary" id="rule-submit-btn">${t('common.save')}</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
        <!-- Import Modal -->
        <div class="modal modal-blur fade" id="import-modal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${t('firewall.importRules')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <form id="import-form">
                        <div class="modal-body">
                            <div class="mb-3">
                                <label class="form-label required">${t('firewall.importFile')}</label>
                                <input type="file" class="form-control" id="import-file" accept=".json" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label required">${t('firewall.importMode')}</label>
                                <div class="form-selectgroup">
                                    <label class="form-selectgroup-item">
                                        <input type="radio" name="import-mode" value="append" class="form-selectgroup-input" checked>
                                        <span class="form-selectgroup-label d-flex align-items-center p-3">
                                            <span class="me-3">
                                                <span class="form-selectgroup-check"></span>
                                            </span>
                                            <span class="form-selectgroup-label-content">
                                                <span class="form-selectgroup-title strong mb-1">${t('firewall.importAppend')}</span>
                                                <span class="d-block text-muted">${t('firewall.importAppendDesc')}</span>
                                            </span>
                                        </span>
                                    </label>
                                    <label class="form-selectgroup-item">
                                        <input type="radio" name="import-mode" value="replace" class="form-selectgroup-input">
                                        <span class="form-selectgroup-label d-flex align-items-center p-3">
                                            <span class="me-3">
                                                <span class="form-selectgroup-check"></span>
                                            </span>
                                            <span class="form-selectgroup-label-content">
                                                <span class="form-selectgroup-title strong mb-1">${t('firewall.importReplace')}</span>
                                                <span class="d-block text-muted">${t('firewall.importReplaceDesc')}</span>
                                            </span>
                                        </span>
                                    </label>
                                </div>
                            </div>
                            <div class="alert alert-warning">
                                <i class="ti ti-alert-triangle me-2"></i>
                                ${t('firewall.importWarning')}
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.cancel')}</button>
                            <button type="submit" class="btn btn-primary">${t('firewall.importBtn')}</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>

        <!-- Gateway Access Modal -->
        <div class="modal modal-blur fade" id="gw-access-modal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="ti ti-network me-2"></i>${t('firewall.gatewayAccess')}
                        </h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="alert alert-info mb-3">
                            <div class="d-flex">
                                <i class="ti ti-info-circle me-2 mt-1 flex-shrink-0"></i>
                                <div>
                                    ${t('firewall.isolationInfo')}
                                    <br><small class="text-muted mt-1 d-block">
                                        ${t('firewall.isolationNote')}
                                    </small>
                                </div>
                            </div>
                        </div>
                        <div id="gw-matrix-content">
                            <div class="text-center py-4">
                                <div class="spinner-border text-primary"></div>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.close')}</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    setupEventListeners();
    renderChainTabs();
    await loadUserPreferences(); // Load preferences before rules
    await loadRules();
}

/**
 * Handle export rules
 */
async function handleExport() {
    try {
        const response = await apiFetch('/firewall/export');
        if (!response.ok) throw new Error('Export failed');

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'firewall_rules.json';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();
    } catch (error) {
        showToast(t('firewall.exportError', { error: error.message }), 'error');
    }
}

/**
 * Handle import rules
 */
async function handleImportSubmit(e) {
    e.preventDefault();

    const fileInput = document.getElementById('import-file');
    const file = fileInput.files[0];
    if (!file) return;

    const mode = document.querySelector('input[name="import-mode"]:checked').value;

    const formData = new FormData();
    formData.append('file', file);

    try {
        // Use apiFetch directly to handle FormData (apiPost forces JSON)
        const response = await apiFetch(`/firewall/import?mode=${mode}`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Import failed' }));
            throw new Error(error.detail || 'Import failed');
        }

        const result = await response.json();

        showToast(result.message || t('firewall.importSuccess'), 'success');

        if (result.errors && result.errors.length > 0) {
            console.warn('Import warnings:', result.errors);
            showToast(t('firewall.importWithErrors', { count: result.errors.length }), 'warning');
        }

        bootstrap.Modal.getInstance(document.getElementById('import-modal')).hide();
        await loadRules();
    } catch (error) {
        showToast(t('firewall.importError', { error: error.message }), 'error');
    }
}



/**
 * Load user preferences from API
 */
async function loadUserPreferences() {
    try {
        const user = await apiGet('/auth/me');
        if (user.preferences) {
            userPreferences = JSON.parse(user.preferences);
        }
    } catch (e) {
        console.error('Failed to load preferences:', e);
        userPreferences = {};
    }
    updateVisibleColumns();
}

/**
 * Save user preferences to API
 */
async function saveUserPreferences() {
    try {
        await apiPatch('/auth/me/preferences', {
            preferences: JSON.stringify(userPreferences)
        });
    } catch (e) {
        showToast(t('firewall.savePrefError'), 'error');
    }
}

/**
 * Get visible columns ordered by definition and filtered by current table
 */
function getOrderedVisibleColumns() {
    return Object.keys(ALL_COLUMNS).filter(key => {
        // Must be enabled by user
        if (!visibleColumns.includes(key)) return false;

        // Must be valid for current table
        const colDef = ALL_COLUMNS[key];
        if (colDef.tables && !colDef.tables.includes(currentTable)) return false;

        return true;
    });
}

/**
 * Render the column selector dropdown
 */
function renderColumnSelector() {
    const container = document.getElementById('column-selector');
    if (!container) return;

    // Filter columns valid for current table
    const validColumns = Object.entries(ALL_COLUMNS).filter(([key, col]) => {
        if (col.tables && !col.tables.includes(currentTable)) return false;
        return true;
    });

    container.innerHTML = validColumns.map(([key, col]) => `
        <label class="dropdown-item">
            <input class="form-check-input m-0 me-2 column-toggle" type="checkbox" 
                   value="${key}" ${visibleColumns.includes(key) ? 'checked' : ''}>
            ${col.label}
        </label>
    `).join('');

    // Re-attach listeners
    container.querySelectorAll('.column-toggle').forEach(chk => {
        chk.addEventListener('change', handleColumnToggle);
    });
}

/**
 * Handle column visibility toggle
 */
async function handleColumnToggle(e) {
    const column = e.target.value;
    const checked = e.target.checked;

    if (checked) {
        if (!visibleColumns.includes(column)) visibleColumns.push(column);
    } else {
        visibleColumns = visibleColumns.filter(c => c !== column);
    }

    // Save to user preferences
    if (!userPreferences.firewall_columns) userPreferences.firewall_columns = {};
    userPreferences.firewall_columns[currentTable] = visibleColumns;

    // Save to backend (fire and forget)
    saveUserPreferences();

    // Re-render
    renderRules();
}

/**
 * Update visible columns based on current table and preferences
 */
function updateVisibleColumns() {
    const tablePrefs = userPreferences.firewall_columns || {};
    // Ensure we start with a copy of defaults if nothing saved
    visibleColumns = [...(tablePrefs[currentTable] || DEFAULT_COLUMNS[currentTable])];
    renderColumnSelector();
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Export/Import buttons
    document.getElementById('btn-export')?.addEventListener('click', handleExport);
    document.getElementById('btn-import')?.addEventListener('click', () => {
        new bootstrap.Modal(document.getElementById('import-modal')).show();
    });

    // Gateway access button
    document.getElementById('btn-gw-access')?.addEventListener('click', openGatewayModal);

    // Import form submit
    document.getElementById('import-form')?.addEventListener('submit', handleImportSubmit);

    // Add rule button
    document.getElementById('btn-add-rule')?.addEventListener('click', () => openRuleModal());

    // Rule form submit
    document.getElementById('rule-form')?.addEventListener('submit', handleRuleSubmit);

    // Table selection
    document.querySelectorAll('input[name="fw-table"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            currentTable = e.target.value;
            updateVisibleColumns(); // Update columns for new table
            renderChainTabs();
            renderRules();
        });
    });

    // Modal table change - update chains and actions
    document.getElementById('rule-table')?.addEventListener('change', (e) => {
        updateModalChains(e.target.value);
        updateModalActions(e.target.value);
        toggleActionFields();
        updateIptablesPreview();
    });

    // Action change - show/hide specific fields
    document.getElementById('rule-action')?.addEventListener('change', () => {
        toggleActionFields();
        updateIptablesPreview();
    });

    // Protocol change - show/hide port field
    document.getElementById('rule-protocol')?.addEventListener('change', (e) => {
        const portGroup = document.getElementById('port-group');
        const proto = e.target.value;
        // Hide port for ICMP or no protocol
        portGroup.style.display = (proto === 'tcp' || proto === 'udp') ? 'block' : 'none';
        if (proto !== 'tcp' && proto !== 'udp') {
            document.getElementById('rule-port').value = '';
        }
        updateIptablesPreview();
    });

    // Update preview on any field change
    ['rule-chain', 'rule-action', 'rule-protocol', 'rule-port', 'rule-source',
        'rule-destination', 'rule-in-interface', 'rule-out-interface', 'rule-state',
        'rule-limit-rate', 'rule-limit-burst', 'rule-to-destination', 'rule-to-source',
        'rule-to-ports', 'rule-log-prefix', 'rule-log-level', 'rule-reject-with']
        .forEach(id => {
            document.getElementById(id)?.addEventListener('change', updateIptablesPreview);
            document.getElementById(id)?.addEventListener('input', updateIptablesPreview);
        });
}

/**
 * Render chain tabs for current table
 */
function renderChainTabs() {
    const tabsContainer = document.getElementById('chain-tabs');
    const contentContainer = document.getElementById('chain-content');
    if (!tabsContainer || !contentContainer) return;

    const chains = TABLES[currentTable].chains;
    currentChain = chains[0];

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
            currentChain = btn.dataset.chain;
        });
    });
}

/**
 * Update modal chain options based on selected table
 */
function updateModalChains(table) {
    const chainSelect = document.getElementById('rule-chain');
    const chains = TABLES[table].chains;
    chainSelect.innerHTML = chains.map(c => `<option value="${c}">${c}</option>`).join('');
}

/**
 * Update modal action options based on selected table
 */
function updateModalActions(table) {
    const actionSelect = document.getElementById('rule-action');
    const actions = TABLE_ACTIONS[table];
    actionSelect.innerHTML = actions.map(a => `<option value="${a}">${a}</option>`).join('');
}

/**
 * Show/Hide fields based on selected action
 */
function toggleActionFields() {
    const action = document.getElementById('rule-action').value;

    // Hide all first
    document.querySelectorAll('.field-dnat, .field-snat, .field-redirect, .field-log, .field-reject')
        .forEach(el => el.style.display = 'none');

    // Show specific
    if (action === 'DNAT') document.querySelectorAll('.field-dnat').forEach(el => el.style.display = 'block');
    if (action === 'SNAT') document.querySelectorAll('.field-snat').forEach(el => el.style.display = 'block');
    if (['REDIRECT', 'MASQUERADE'].includes(action)) document.querySelectorAll('.field-redirect').forEach(el => el.style.display = 'block');
    if (action === 'LOG') document.querySelectorAll('.field-log').forEach(el => el.style.display = 'block');
    if (action === 'REJECT') document.querySelectorAll('.field-reject').forEach(el => el.style.display = 'block');

    // Show informational banner for blocking actions
    const isBlocking = ['DROP', 'REJECT'].includes(action);
    document.querySelectorAll('.field-drop-info').forEach(el => {
        el.style.display = isBlocking ? 'block' : 'none';
    });
}

/**
 * Update iptables command preview
 */
function updateIptablesPreview() {
    const preview = document.getElementById('iptables-preview');
    if (!preview) return;

    const table = document.getElementById('rule-table')?.value || 'filter';
    const chain = document.getElementById('rule-chain')?.value || 'INPUT';
    const action = document.getElementById('rule-action')?.value || 'ACCEPT';
    const protocol = document.getElementById('rule-protocol')?.value;
    const port = document.getElementById('rule-port')?.value;
    const source = document.getElementById('rule-source')?.value;
    const destination = document.getElementById('rule-destination')?.value;
    const inIface = document.getElementById('rule-in-interface')?.value;
    const outIface = document.getElementById('rule-out-interface')?.value;
    const state = document.getElementById('rule-state')?.value;
    const limitRate = document.getElementById('rule-limit-rate')?.value;
    const limitBurst = document.getElementById('rule-limit-burst')?.value;

    // New fields
    const toDest = document.getElementById('rule-to-destination')?.value;
    const toSource = document.getElementById('rule-to-source')?.value;
    const toPorts = document.getElementById('rule-to-ports')?.value;
    const logPrefix = document.getElementById('rule-log-prefix')?.value;
    const logLevel = document.getElementById('rule-log-level')?.value;
    const rejectWith = document.getElementById('rule-reject-with')?.value;

    let cmd = `iptables -t ${table} -A ${chain}`;

    if (protocol) cmd += ` -p ${protocol}`;
    if (source) cmd += ` -s ${source}`;
    if (destination) cmd += ` -d ${destination}`;
    if (inIface) cmd += ` -i ${inIface}`;
    if (outIface) cmd += ` -o ${outIface}`;
    if (state) cmd += ` -m state --state ${state}`;
    if (port && (protocol === 'tcp' || protocol === 'udp')) {
        if (port.includes(',')) {
            cmd += ` -m multiport --dports ${port}`;
        } else {
            cmd += ` --dport ${port}`;
        }
    }
    if (limitRate) {
        cmd += ` -m limit --limit ${limitRate}`;
        if (limitBurst) cmd += ` --limit-burst ${limitBurst}`;
    }
    cmd += ` -j ${action}`;

    // Append action arguments
    if (action === 'DNAT' && toDest) cmd += ` --to-destination ${toDest}`;
    if (action === 'SNAT' && toSource) cmd += ` --to-source ${toSource}`;
    if (['REDIRECT', 'MASQUERADE'].includes(action) && toPorts) cmd += ` --to-ports ${toPorts}`;
    if (action === 'LOG') {
        if (logPrefix) cmd += ` --log-prefix "${logPrefix}"`;
        if (logLevel) cmd += ` --log-level ${logLevel}`;
    }
    if (action === 'REJECT' && rejectWith) cmd += ` --reject-with ${rejectWith}`;

    preview.textContent = cmd;
}

/**
 * Load rules from API
 */
async function loadRules() {
    try {
        rules = await apiGet('/firewall/rules');
        renderRules();
    } catch (error) {
        showToast(t('firewall.loadRulesError', { error: error.message }), 'error');
    }
}

/**
 * Render rules in tables
 */
function renderRules() {
    const chains = TABLES[currentTable].chains;

    for (const chain of chains) {
        const chainRules = rules
            .filter(r => r.table_name === currentTable && r.chain === chain)
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

        const orderedColumns = getOrderedVisibleColumns();

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
                        ${chainRules.map(rule => renderRuleRow(rule, orderedColumns)).join('')}
                    </tbody>
                </table>
            </div>
        `;

        // Setup row event listeners and drag-drop
        setupRowEvents(container);
        setupDragDrop(container.querySelector('.sortable-container'));
    }
}

/**
 * Render a single rule row
 */
function renderRuleRow(rule, orderedColumns) {
    const canManage = checkPermission('firewall.manage');
    const disabledClass = rule.enabled ? '' : 'disabled';

    // If orderedColumns not provided (legacy call?), fallback
    const columns = orderedColumns || getOrderedVisibleColumns();

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
function setupDragDrop(tbody) {
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
                const draggedRule = rules.find(r => r.id === draggedId);
                const targetRule = rules.find(r => r.id === targetId);

                if (draggedRule && targetRule) {
                    try {
                        await apiPatch(`/firewall/rules/${draggedId}/reorder`, {
                            new_order: targetRule.order
                        });
                        showToast(t('firewall.orderUpdated'), 'success');
                        await loadRules();
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
function setupRowEvents(container) {
    // Flush conntrack buttons
    container.querySelectorAll('.btn-flush-conntrack').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const row = e.target.closest('tr');
            const ruleId = row.dataset.id;
            const rule = rules.find(r => r.id === ruleId);

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
            const ruleId = row.dataset.id;
            const rule = rules.find(r => r.id === ruleId);
            if (rule) {
                openRuleModal(rule);
            }
        });
    });

    // Duplicate buttons
    container.querySelectorAll('.btn-duplicate').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const ruleId = e.target.closest('tr').dataset.id;
            const rule = rules.find(r => r.id === ruleId);
            if (rule) openRuleModal(rule, true);   // apre modale create pre-compilata
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
                await deleteRule(ruleId);
            }
        });
    });
}

/**
 * Open rule modal for create/edit
 */
function openRuleModal(rule = null, isDuplicate = false) {
    editingRule = isDuplicate ? null : rule;   // duplica => submit fa POST (nuova regola)

    const title = document.getElementById('rule-modal-title');
    title.textContent = (rule && !isDuplicate) ? t('firewall.editRule') : t('firewall.newRule');

    // Set table first, then update chains/actions
    const tableSelect = document.getElementById('rule-table');
    tableSelect.value = rule?.table_name || currentTable;
    updateModalChains(tableSelect.value);
    updateModalActions(tableSelect.value);

    // Reset form fields
    document.getElementById('rule-chain').value = rule?.chain || currentChain;
    document.getElementById('rule-action').value = rule?.action || TABLE_ACTIONS[tableSelect.value][0];
    document.getElementById('rule-protocol').value = rule?.protocol || '';
    document.getElementById('rule-port').value = rule?.port || '';
    document.getElementById('rule-source').value = rule?.source || '';
    document.getElementById('rule-destination').value = rule?.destination || '';
    document.getElementById('rule-in-interface').value = rule?.in_interface || '';
    document.getElementById('rule-out-interface').value = rule?.out_interface || '';
    document.getElementById('rule-state').value = rule?.state || '';
    document.getElementById('rule-limit-rate').value = rule?.limit_rate || '';
    document.getElementById('rule-limit-burst').value = rule?.limit_burst || '';
    document.getElementById('rule-enabled').checked = rule?.enabled !== false;
    document.getElementById('rule-comment').value = rule?.comment || '';

    // New fields
    document.getElementById('rule-to-destination').value = rule?.to_destination || '';
    document.getElementById('rule-to-source').value = rule?.to_source || '';
    document.getElementById('rule-to-ports').value = rule?.to_ports || '';
    document.getElementById('rule-log-prefix').value = rule?.log_prefix || '';
    document.getElementById('rule-log-level').value = rule?.log_level || '';
    document.getElementById('rule-reject-with').value = rule?.reject_with || '';

    // Trigger visibility update (handles action-specific fields and drop info banner)
    toggleActionFields();

    // Show/hide port field based on protocol
    const proto = rule?.protocol || '';
    document.getElementById('port-group').style.display = (proto === 'tcp' || proto === 'udp') ? 'block' : 'none';

    // Update preview
    updateIptablesPreview();

    new bootstrap.Modal(document.getElementById('rule-modal')).show();
}

/**
 * Handle rule form submit
 */
async function handleRuleSubmit(e) {
    e.preventDefault();

    const data = {
        table_name: document.getElementById('rule-table').value,
        chain: document.getElementById('rule-chain').value,
        action: document.getElementById('rule-action').value,
        protocol: document.getElementById('rule-protocol').value || null,
        port: document.getElementById('rule-port').value || null,
        source: document.getElementById('rule-source').value || null,
        destination: document.getElementById('rule-destination').value || null,
        in_interface: document.getElementById('rule-in-interface').value || null,
        out_interface: document.getElementById('rule-out-interface').value || null,
        state: document.getElementById('rule-state').value || null,
        limit_rate: document.getElementById('rule-limit-rate').value || null,
        limit_burst: parseInt(document.getElementById('rule-limit-burst').value) || null,
        enabled: document.getElementById('rule-enabled').checked,
        comment: document.getElementById('rule-comment').value || null,

        // New fields
        to_destination: document.getElementById('rule-to-destination').value || null,
        to_source: document.getElementById('rule-to-source').value || null,
        to_ports: document.getElementById('rule-to-ports').value || null,
        log_prefix: document.getElementById('rule-log-prefix').value || null,
        log_level: document.getElementById('rule-log-level').value || null,
        reject_with: document.getElementById('rule-reject-with').value || null,
    };

    const constraintError = validateRuleConstraints(data);
    if (constraintError) {
        showToast(constraintError, 'error');
        return;
    }

    try {
        if (editingRule) {
            await apiPatch(`/firewall/rules/${editingRule.id}`, data);
            showToast(t('firewall.ruleUpdated'), 'success');
        } else {
            await apiPost('/firewall/rules', data);
            showToast(t('firewall.ruleCreated'), 'success');
        }

        bootstrap.Modal.getInstance(document.getElementById('rule-modal')).hide();
        await loadRules();

    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
    }
}

// Hook (chain) in cui ciascun match/azione è valido per netfilter.
const IN_IFACE_VALID_CHAINS = ['PREROUTING', 'INPUT', 'FORWARD'];
const OUT_IFACE_VALID_CHAINS = ['POSTROUTING', 'OUTPUT', 'FORWARD'];
const NAT_ACTION_VALID_CHAINS = {
    DNAT: ['PREROUTING', 'OUTPUT'],
    REDIRECT: ['PREROUTING', 'OUTPUT'],
    SNAT: ['POSTROUTING'],
    MASQUERADE: ['POSTROUTING'],
};

/**
 * Validate rule field/chain (hook) compatibility client-side, mirroring the
 * backend denylist. Returns a translated error string, or null if valid.
 */
function validateRuleConstraints(data) {
    const chain = data.chain;
    if (data.in_interface && !IN_IFACE_VALID_CHAINS.includes(chain)) {
        return t('firewall.validation.inIfaceHook', { chain });
    }
    if (data.out_interface && !OUT_IFACE_VALID_CHAINS.includes(chain)) {
        return t('firewall.validation.outIfaceHook', { chain });
    }
    const validChains = NAT_ACTION_VALID_CHAINS[data.action];
    if (validChains && !validChains.includes(chain)) {
        return t('firewall.validation.natActionHook', { action: data.action, chain });
    }
    return null;
}

/**
 * Delete a rule
 */
async function deleteRule(ruleId) {
    try {
        await apiDelete(`/firewall/rules/${ruleId}`);
        showToast(t('firewall.ruleDeleted'), 'success');
        await loadRules();
    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
    }
}


// =============================================================================
// GATEWAY ACCESS MODAL
// =============================================================================

// Virtual interface prefixes to exclude from LAN list (mirrors backend filter)
const GW_VIRTUAL_PREFIXES = ['lo', 'wg', 'veth', 'docker', 'br-', 'virbr', 'tun', 'tap'];
const GW_WAN_IFACE = 'eth0';

/**
 * Open the Gateway Access modal and render the badge matrix.
 */
async function openGatewayModal() {
    const modal = new bootstrap.Modal(document.getElementById('gw-access-modal'));
    modal.show();
    await renderGatewayMatrix();
}

/**
 * Load interfaces and current GW_EXCEPTIONS rules, then render the badge matrix.
 */
async function renderGatewayMatrix() {
    const content = document.getElementById('gw-matrix-content');
    content.innerHTML = `<div class="text-center py-4"><div class="spinner-border text-primary"></div></div>`;

    try {
        const [ifaceData, exceptionsData] = await Promise.all([
            apiGet('/network/interfaces'),
            apiGet('/firewall/rules?chain=GW_EXCEPTIONS')
        ]);

        const lanIfaces = (ifaceData.interfaces || []).filter(i =>
            i.ipv4 &&
            !GW_VIRTUAL_PREFIXES.some(p => i.name.startsWith(p)) &&
            i.name !== GW_WAN_IFACE
        );

        const exceptions = exceptionsData || [];

        if (lanIfaces.length < 2) {
            content.innerHTML = `
                <div class="empty">
                    <p class="empty-title">${t('firewall.lessThan2Lans')}</p>
                    <p class="empty-subtitle text-muted">${t('firewall.add2LansHint')}</p>
                </div>`;
            return;
        }

        content.innerHTML = `
            <table class="table table-sm table-hover">
                <thead>
                    <tr>
                        <th style="width:200px">${t('firewall.sourceNetwork')}</th>
                        <th>${t('firewall.canReach')}</th>
                    </tr>
                </thead>
                <tbody>
                    ${lanIfaces.map(src => {
                        const targets = lanIfaces.filter(dst => dst.name !== src.name);
                        const badges = targets.map(dst => {
                            const existing = exceptions.find(r =>
                                r.in_interface === src.name &&
                                r.destination === dst.ipv4
                            );
                            const active = !!existing;
                            return `<span
                                class="badge ${active ? 'bg-success-lt' : 'bg-secondary-lt'} me-1 mb-1 gw-badge"
                                style="cursor:pointer;font-size:.8rem;padding:.4em .7em"
                                data-src="${escapeHtml(src.name)}"
                                data-dst="${escapeHtml(dst.ipv4)}"
                                data-dst-name="${escapeHtml(dst.name)}"
                                data-rule-id="${existing ? existing.id : ''}"
                                data-active="${active}"
                                title="${active ? t('firewall.clickToBlock') : t('firewall.clickToEnable')}"
                            >${escapeHtml(dst.name)} <small>${escapeHtml(dst.ipv4)}</small></span>`;
                        }).join('');

                        return `<tr>
                            <td class="align-middle">
                                <strong>${escapeHtml(src.name)}</strong>
                                <br><small class="text-muted">${escapeHtml(src.ipv4)}</small>
                            </td>
                            <td class="align-middle">${badges}</td>
                        </tr>`;
                    }).join('')}
                </tbody>
            </table>
            <small class="text-muted">
                ${t('firewall.legendEnabled')} &nbsp;&nbsp; ${t('firewall.legendBlocked')}
            </small>`;

        // Bind badge clicks
        content.querySelectorAll('.gw-badge').forEach(badge => {
            badge.addEventListener('click', handleGatewayBadgeToggle);
        });

    } catch (error) {
        content.innerHTML = `<div class="alert alert-danger">${t('firewall.gatewayLoadError', { error: escapeHtml(error.message) })}</div>`;
    }
}

/**
 * Toggle a gateway exception on badge click.
 */
async function handleGatewayBadgeToggle(e) {
    const badge = e.currentTarget;
    const src = badge.dataset.src;
    const dst = badge.dataset.dst;
    const dstName = badge.dataset.dstName;
    const ruleId = badge.dataset.ruleId;
    const active = badge.dataset.active === 'true';

    badge.style.opacity = '0.5';
    badge.style.pointerEvents = 'none';

    try {
        if (active) {
            await apiDelete(`/firewall/rules/${ruleId}`);
            badge.classList.remove('bg-success-lt');
            badge.classList.add('bg-secondary-lt');
            badge.dataset.active = 'false';
            badge.dataset.ruleId = '';
            badge.title = t('firewall.clickToEnable');
        } else {
            const result = await apiPost('/firewall/rules', {
                chain: 'GW_EXCEPTIONS',
                table_name: 'filter',
                action: 'ACCEPT',
                in_interface: src,
                destination: dst,
                comment: `${src} → ${dstName} gateway`
            });
            badge.classList.remove('bg-secondary-lt');
            badge.classList.add('bg-success-lt');
            badge.dataset.active = 'true';
            badge.dataset.ruleId = result.id;
            badge.title = t('firewall.clickToBlock');
        }
    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
    } finally {
        badge.style.opacity = '';
        badge.style.pointerEvents = '';
    }
}

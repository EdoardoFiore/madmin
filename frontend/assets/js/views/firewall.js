/**
 * MADMIN - Firewall View
 * 
 * Machine firewall management with multiple tables support.
 * Displays rules with drag-and-drop ordering and iptables preview.
 */

import { apiGet, apiPost, apiPatch, apiDelete, apiPut, apiFetch } from '../api.js';
import { showToast, confirmDialog, actionBadge, emptyState, escapeHtml } from '../utils.js';
import { setPageActions, checkPermission } from '../app.js';

let rules = [];
let editingRule = null;
let currentTable = 'filter';
let userPreferences = {};
let visibleColumns = [];

// Column definitions
const ALL_COLUMNS = {
    protocol: { label: 'Protocollo' },
    source: { label: 'Sorgente' },
    destination: { label: 'Destinazione' },
    port: { label: 'Porta' },
    state: { label: 'Stato' },
    in_interface: { label: 'In Iface' },
    out_interface: { label: 'Out Iface' },
    to_destination: { label: 'To Dest', tables: ['nat'] },
    to_source: { label: 'To Source', tables: ['nat'] },
    to_ports: { label: 'To Ports', tables: ['nat'] },
    log_prefix: { label: 'Log Prefix' },
    limit_rate: { label: 'Rate Limit' },
    comment: { label: 'Commento' }
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
                    <i class="ti ti-download me-2"></i>Esporta
                </button>
                <button class="btn btn-outline-secondary" id="btn-import">
                    <i class="ti ti-upload me-2"></i>Importa
                </button>
                <button class="btn btn-primary" id="btn-add-rule">
                    <i class="ti ti-plus me-2"></i>Nuova Regola
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
                                    <i class="ti ti-columns me-2"></i>Colonne
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
                        <h5 class="modal-title" id="rule-modal-title">Nuova Regola</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <form id="rule-form">
                        <div class="modal-body">
                            <div class="row g-3">
                                <div class="col-md-4">
                                    <label class="form-label required">Tabella</label>
                                    <select class="form-select" id="rule-table" required>
                                        ${Object.entries(TABLES).map(([k, t]) => `<option value="${k}">${t.label}</option>`).join('')}
                                    </select>
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label required">Catena</label>
                                    <select class="form-select" id="rule-chain" required>
                                        <!-- Populated dynamically -->
                                    </select>
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label required">Azione</label>
                                    <select class="form-select" id="rule-action" required>
                                        <!-- Populated dynamically -->
                                    </select>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Protocollo</label>
                                    <select class="form-select" id="rule-protocol">
                                        <option value="">Tutti</option>
                                        <option value="tcp">TCP</option>
                                        <option value="udp">UDP</option>
                                        <option value="icmp">ICMP</option>
                                    </select>
                                </div>
                                <div class="col-md-6" id="port-group">
                                    <label class="form-label">Porta</label>
                                    <input type="text" class="form-control" id="rule-port" placeholder="80, 443, 8000:8080">
                                    <small class="form-hint">Singola porta o range (80:443)</small>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Sorgente</label>
                                    <input type="text" class="form-control" id="rule-source" 
                                           placeholder="es. 192.168.1.0/24">
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Destinazione</label>
                                    <input type="text" class="form-control" id="rule-destination" 
                                           placeholder="es. 10.0.0.0/8">
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Interfaccia In</label>
                                    <input type="text" class="form-control" id="rule-in-interface" 
                                           placeholder="es. eth0, wg0">
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Interfaccia Out</label>
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
                                    <label class="form-label">Stato Connessione</label>
                                    <select class="form-select" id="rule-state">
                                        <option value="">Nessuno</option>
                                        <option value="NEW">NEW</option>
                                        <option value="ESTABLISHED">ESTABLISHED</option>
                                        <option value="RELATED">RELATED</option>
                                        <option value="ESTABLISHED,RELATED">ESTABLISHED,RELATED</option>
                                        <option value="NEW,ESTABLISHED,RELATED">NEW,ESTABLISHED,RELATED</option>
                                    </select>
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label">Rate Limit</label>
                                    <input type="text" class="form-control" id="rule-limit-rate" 
                                           placeholder="es. 10/second, 100/minute">
                                    <small class="form-hint">Limita le connessioni (iptables -m limit)</small>
                                </div>
                                <div class="col-md-2">
                                    <label class="form-label">Burst</label>
                                    <input type="number" class="form-control" id="rule-limit-burst" 
                                           placeholder="es. 5" min="1">
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Abilitata</label>
                                    <label class="form-check form-switch mt-2">
                                        <input class="form-check-input" type="checkbox" id="rule-enabled" checked>
                                        <span class="form-check-label">Regola attiva</span>
                                    </label>
                                </div>
                                <div class="col-12">
                                    <label class="form-label">Commento</label>
                                    <input type="text" class="form-control" id="rule-comment" 
                                           placeholder="Descrizione della regola">
                                </div>
                                <!-- iptables Preview -->
                                <div class="col-12">
                                    <label class="form-label">Anteprima Comando iptables</label>
                                    <pre class="bg-dark text-success p-3 rounded" id="iptables-preview" 
                                         style="font-family: monospace; font-size: 0.85rem; overflow-x: auto;">
iptables -t filter -A INPUT -j ACCEPT
                                    </pre>
                                </div>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-link" data-bs-dismiss="modal">Annulla</button>
                            <button type="submit" class="btn btn-primary" id="rule-submit-btn">Salva</button>
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
                        <h5 class="modal-title">Importa Regole Firewall</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <form id="import-form">
                        <div class="modal-body">
                            <div class="mb-3">
                                <label class="form-label required">File di configurazione (JSON)</label>
                                <input type="file" class="form-control" id="import-file" accept=".json" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label required">Modalità Importazione</label>
                                <div class="form-selectgroup">
                                    <label class="form-selectgroup-item">
                                        <input type="radio" name="import-mode" value="append" class="form-selectgroup-input" checked>
                                        <span class="form-selectgroup-label d-flex align-items-center p-3">
                                            <span class="me-3">
                                                <span class="form-selectgroup-check"></span>
                                            </span>
                                            <span class="form-selectgroup-label-content">
                                                <span class="form-selectgroup-title strong mb-1">Aggiungi</span>
                                                <span class="d-block text-muted">Aggiunge le regole a quelle esistenti</span>
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
                                                <span class="form-selectgroup-title strong mb-1">Sostituisci</span>
                                                <span class="d-block text-muted">Cancella tutto e ripristina dal backup</span>
                                            </span>
                                        </span>
                                    </label>
                                </div>
                            </div>
                            <div class="alert alert-warning">
                                <i class="ti ti-alert-triangle me-2"></i>
                                Attenzione: l'importazione applicherà immediatamente le regole al firewall.
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-link" data-bs-dismiss="modal">Annulla</button>
                            <button type="submit" class="btn btn-primary">Importa</button>
                        </div>
                    </form>
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
        showToast('Errore durante l\'esportazione: ' + error.message, 'error');
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

        showToast(result.message || 'Regole importate con successo', 'success');

        if (result.errors && result.errors.length > 0) {
            console.warn('Import warnings:', result.errors);
            showToast(`Importato con ${result.errors.length} errori/avvisi (vedi console)`, 'warning');
        }

        bootstrap.Modal.getInstance(document.getElementById('import-modal')).hide();
        await loadRules();
    } catch (error) {
        showToast('Errore importazione: ' + error.message, 'error');
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
        showToast('Errore salvataggio preferenze', 'error');
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

    tabsContainer.innerHTML = chains.map((chain, i) => `
        <li class="nav-item" role="presentation">
            <button class="nav-link ${i === 0 ? 'active' : ''}" data-bs-toggle="tab" 
                    data-bs-target="#tab-${chain.toLowerCase()}" type="button">
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
        showToast('Errore nel caricamento delle regole: ' + error.message, 'error');
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
            container.innerHTML = emptyState('ti-shield-off', 'Nessuna regola', `Non ci sono regole per la catena ${chain}`);
            continue;
        }

        const orderedColumns = getOrderedVisibleColumns();

        container.innerHTML = `
            <div class="table-responsive">
                <table class="table table-vcenter firewall-table" id="table-${chain.toLowerCase()}">
                    <thead>
                        <tr>
                            <th class="rule-order" style="width: 60px;">#</th>
                            <th>Azione</th>
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

    return `
        <tr class="${disabledClass} draggable-row" data-id="${rule.id}" draggable="${canManage}">
            <td class="rule-order">
                ${canManage ? '<i class="ti ti-grip-vertical drag-handle" style="cursor: grab;"></i>' : ''}
                <span class="ms-1">${rule.order + 1}</span>
            </td>
            <td>${actionBadge(rule.action)}</td>
            ${columns.map(col => `<td>${renderCell(rule, col)}</td>`).join('')}
            <td class="rule-actions">
                ${canManage ? `
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-ghost-primary btn-edit" title="Modifica">
                            <i class="ti ti-edit"></i>
                        </button>
                        <button class="btn btn-ghost-danger btn-delete" title="Elimina">
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
        case 'protocol': return rule.protocol ? `<code>${rule.protocol}</code>` : '<span class="text-muted">tutti</span>';
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
                        showToast('Ordine aggiornato', 'success');
                        await loadRules();
                    } catch (error) {
                        showToast('Errore: ' + error.message, 'error');
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

    // Delete buttons
    container.querySelectorAll('.btn-delete').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const row = e.target.closest('tr');
            const ruleId = row.dataset.id;

            const confirmed = await confirmDialog(
                'Elimina Regola',
                'Sei sicuro di voler eliminare questa regola? L\'azione è immediata.',
                'Elimina',
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
function openRuleModal(rule = null) {
    editingRule = rule;

    const title = document.getElementById('rule-modal-title');
    title.textContent = rule ? 'Modifica Regola' : 'Nuova Regola';

    // Set table first, then update chains/actions
    const tableSelect = document.getElementById('rule-table');
    tableSelect.value = rule?.table_name || currentTable;
    updateModalChains(tableSelect.value);
    updateModalActions(tableSelect.value);

    // Reset form fields
    document.getElementById('rule-chain').value = rule?.chain || TABLES[tableSelect.value].chains[0];
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

    // Trigger visibility update
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

    try {
        if (editingRule) {
            await apiPatch(`/firewall/rules/${editingRule.id}`, data);
            showToast('Regola aggiornata con successo', 'success');
        } else {
            await apiPost('/firewall/rules', data);
            showToast('Regola creata con successo', 'success');
        }

        bootstrap.Modal.getInstance(document.getElementById('rule-modal')).hide();
        await loadRules();

    } catch (error) {
        showToast('Errore: ' + error.message, 'error');
    }
}

/**
 * Delete a rule
 */
async function deleteRule(ruleId) {
    try {
        await apiDelete(`/firewall/rules/${ruleId}`);
        showToast('Regola eliminata', 'success');
        await loadRules();
    } catch (error) {
        showToast('Errore: ' + error.message, 'error');
    }
}

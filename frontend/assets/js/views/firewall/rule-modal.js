/**
 * MADMIN - Firewall View / rule create-edit modal
 *
 * Static modal markup (many conditional fields + live iptables preview);
 * exported as a template so index.js can compose it into the view.
 */

import { apiPost, apiPatch } from '../../api.js';
import { showToast } from '../../utils.js';
import { t } from '../../i18n.js';
import {
    TABLES, TABLE_ACTIONS,
    IN_IFACE_VALID_CHAINS, OUT_IFACE_VALID_CHAINS, NAT_ACTION_VALID_CHAINS,
} from './constants.js';

/**
 * Rule modal markup (inserted once per view render by index.js)
 */
export function ruleModalHtml() {
    return `
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
    `;
}

/**
 * Bind the rule modal listeners (once per view render)
 */
export function bindRuleModal(state) {
    document.getElementById('rule-form')?.addEventListener('submit', (e) => handleRuleSubmit(state, e));

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

    // Action-specific fields
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
 * Open rule modal for create/edit
 */
export function openRuleModal(state, rule = null, isDuplicate = false) {
    state.editingRule = isDuplicate ? null : rule;   // duplica => submit fa POST (nuova regola)

    const title = document.getElementById('rule-modal-title');
    title.textContent = (rule && !isDuplicate) ? t('firewall.editRule') : t('firewall.newRule');

    // Set table first, then update chains/actions
    const tableSelect = document.getElementById('rule-table');
    tableSelect.value = rule?.table_name || state.currentTable;
    updateModalChains(tableSelect.value);
    updateModalActions(tableSelect.value);

    // Reset form fields
    document.getElementById('rule-chain').value = rule?.chain || state.currentChain;
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

    // Action-specific fields
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
async function handleRuleSubmit(state, e) {
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

        // Action-specific fields
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
        if (state.editingRule) {
            await apiPatch(`/firewall/rules/${state.editingRule.id}`, data);
            showToast(t('firewall.ruleUpdated'), 'success');
        } else {
            await apiPost('/firewall/rules', data);
            showToast(t('firewall.ruleCreated'), 'success');
        }

        bootstrap.Modal.getInstance(document.getElementById('rule-modal')).hide();
        await state.reload();

    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
    }
}

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

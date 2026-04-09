/**
 * DNS Module - Settings Tab & Test DNS Tab
 */

import { t } from '/static/js/i18n.js';
import { apiGet, apiPost, apiPut } from '/static/js/api.js';
import { showToast, loadingSpinner } from '/static/js/utils.js';

// ============================================================
//  SETTINGS TAB
// ============================================================

export async function renderDnsSettingsTab(settings, perms) {
    const content = document.getElementById('dns-tab-content');
    if (!content) return;

    let listenIfaces = [];
    try { listenIfaces = JSON.parse(settings.listen_interfaces || '[]'); } catch (e) { }
    let sysForwarders = [];
    try { sysForwarders = JSON.parse(settings.system_forwarders || '[]'); } catch (e) { }

    let interfaces = [];
    try {
        const res = await apiGet('/network/interfaces');
        if (res && res.interfaces) {
            interfaces = res.interfaces.filter(i => i.ipv4).map(i => ({ name: i.name, ip: i.ipv4 }));
        }
    } catch (err) {
        showToast(t('dns.ifaceLoadError') + err.message, 'error');
    }

    content.innerHTML = `
        <div class="card-body">
            <h4 class="mb-3">${t('dns.globalSettings')}</h4>
            <div class="row">
                <div class="col-md-6 mb-3">
                    <label class="form-label">${t('dns.operationalMode')}</label>
                    <select class="form-select" id="setting-mode" ${!perms.manage ? 'disabled' : ''}>
                        <option value="recursive" ${settings.mode === 'recursive' ? 'selected' : ''}>${t('dns.modeRecursiveDesc')}</option>
                        <option value="forward_only" ${settings.mode === 'forward_only' ? 'selected' : ''}>${t('dns.modeForwardOnlyDesc')}</option>
                        <option value="non_recursive" ${settings.mode === 'non_recursive' ? 'selected' : ''}>${t('dns.modeNonRecursiveDesc')}</option>
                    </select>
                    <small class="form-hint">
                        <strong>${t('dns.modeRecursive')}:</strong> ${t('dns.modeRecursiveHint')}<br>
                        <strong>${t('dns.modeForwardOnly')}:</strong> ${t('dns.modeForwardOnlyHint')}<br>
                        <strong>${t('dns.modeNonRecursive')}:</strong> ${t('dns.modeNonRecursiveHint')}
                    </small>
                </div>
                <div class="col-md-6 mb-3">
                    <label class="form-label">${t('dns.systemForwarders')}</label>
                    <input type="text" class="form-control" id="setting-forwarders"
                           value="${sysForwarders.join(', ')}" placeholder="8.8.8.8, 1.1.1.1"
                           ${!perms.manage ? 'disabled' : ''}>
                    <small class="form-hint">${t('dns.forwardersHint')}</small>
                </div>
            </div>
            <div class="row">
                <div class="col-md-6 mb-3">
                    <label class="form-label">${t('dns.allowQuery')} <span class="text-muted">(Allow Query)</span></label>
                    <select class="form-select" id="setting-allow-query" ${!perms.manage ? 'disabled' : ''}>
                        <option value="localnets" ${settings.allow_query === 'localnets' ? 'selected' : ''}>${t('dns.allowLocalNets')}</option>
                        <option value="any" ${settings.allow_query === 'any' ? 'selected' : ''}>${t('dns.allowAny')}</option>
                    </select>
                    <small class="form-hint">
                        <strong>${t('dns.allowLocalNets').split(' ')[0]}:</strong> ${t('dns.allowLocalNetsHint')}<br>
                        <strong>${t('dns.allowAny').split(' ')[0]}:</strong> ${t('dns.allowAnyHint')}
                    </small>
                </div>
                <div class="col-md-6 mb-3" id="setting-listen-wrapper" style="${settings.allow_query === 'any' ? 'display: none;' : ''}">
                    <label class="form-label">${t('dns.listenOn')}</label>
                    <div class="card card-body p-2" style="max-height: 150px; overflow-y: auto;">
                        ${interfaces.map(i => {
                            const isChecked = listenIfaces.length === 0 || listenIfaces.includes(i.name);
                            return `
                            <div class="form-check mb-1">
                                <input class="form-check-input listen-iface-cb" type="checkbox" value="${i.name}" id="iface-${i.name}"
                                       ${isChecked ? 'checked' : ''} ${!perms.manage ? 'disabled' : ''}>
                                <label class="form-check-label" for="iface-${i.name}">
                                    ${i.name} <span class="text-muted">(${i.ip || 'no IP'})</span>
                                </label>
                            </div>`;
                        }).join('')}
                    </div>
                    <small class="form-hint mt-2">${t('dns.listenHint')}</small>
                </div>
            </div>
            <div class="row">
                <div class="col-md-6 mb-3">
                    <label class="form-label">${t('dns.dnssecValidation')}</label>
                    <div class="form-check form-switch mt-2">
                        <input class="form-check-input" type="checkbox" id="setting-dnssec"
                               ${settings.dnssec_validation ? 'checked' : ''} ${!perms.manage ? 'disabled' : ''}>
                        <label class="form-check-label" for="setting-dnssec">${t('dns.enableDnssec')}</label>
                    </div>
                </div>
            </div>
            ${perms.manage ? `
            <div class="mt-3">
                <button class="btn btn-primary" id="btn-save-settings">
                    <i class="ti ti-check me-1"></i>${t('dns.saveSettings')}
                </button>
            </div>` : ''}
        </div>
    `;

    document.getElementById('setting-allow-query')?.addEventListener('change', (e) => {
        const wrapper = document.getElementById('setting-listen-wrapper');
        if (wrapper) wrapper.style.display = e.target.value === 'any' ? 'none' : 'block';
    });

    document.getElementById('btn-save-settings')?.addEventListener('click', saveSettings);
}

async function saveSettings() {
    const mode = document.getElementById('setting-mode')?.value;
    const forwardersStr = document.getElementById('setting-forwarders')?.value.trim();
    const allowQuery = document.getElementById('setting-allow-query')?.value;
    const dnssec = document.getElementById('setting-dnssec')?.checked;

    let listenIfaces = [];
    if (allowQuery !== 'any') {
        const checkboxes = document.querySelectorAll('.listen-iface-cb:checked');
        listenIfaces = Array.from(checkboxes).map(cb => cb.value);
    }

    const forwarders = forwardersStr ? forwardersStr.split(',').map(s => s.trim()).filter(Boolean) : [];

    try {
        const result = await apiPut('/modules/dns/settings', {
            mode,
            system_forwarders: JSON.stringify(forwarders),
            allow_query: allowQuery,
            listen_interfaces: JSON.stringify(listenIfaces),
            dnssec_validation: dnssec,
        });
        showToast(
            result.applied ? t('dns.settingsSavedApplied') : `${t('dns.settingsSavedWarning')}: ${result.apply_message}`,
            result.applied ? 'success' : 'warning'
        );
    } catch (err) { showToast(err.message, 'error'); }
}

// ============================================================
//  TEST DNS TAB
// ============================================================

const RECORD_TYPES = ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'SRV', 'NS', 'PTR'];

export function renderDnsTestTab() {
    const content = document.getElementById('dns-tab-content');
    if (!content) return;

    content.innerHTML = `
        <div class="card-body">
            <h4 class="mb-3">${t('dns.testQueryTitle')}</h4>
            <p class="text-muted">${t('dns.testQueryDesc')}</p>
            <div class="row align-items-end">
                <div class="col-md-5 mb-3">
                    <label class="form-label">${t('dns.domain')}</label>
                    <input type="text" class="form-control" id="test-domain" placeholder="es. www.lab.local">
                </div>
                <div class="col-md-3 mb-3">
                    <label class="form-label">${t('dns.recordType')}</label>
                    <select class="form-select" id="test-type">
                        ${RECORD_TYPES.map(tp => `<option value="${tp}" ${tp === 'A' ? 'selected' : ''}>${tp}</option>`).join('')}
                    </select>
                </div>
                <div class="col-md-2 mb-3">
                    <button class="btn btn-primary w-100" id="btn-test-query">
                        <i class="ti ti-search me-1"></i>Test
                    </button>
                </div>
            </div>
            <div id="test-result" class="mt-2"></div>
        </div>
    `;

    document.getElementById('btn-test-query')?.addEventListener('click', testDnsQuery);
    document.getElementById('test-domain')?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') testDnsQuery();
    });
}

async function testDnsQuery() {
    const domain = document.getElementById('test-domain')?.value.trim();
    const recordType = document.getElementById('test-type')?.value;
    const resultDiv = document.getElementById('test-result');

    if (!domain) {
        showToast(t('dns.domainRequired'), 'error');
        return;
    }

    resultDiv.innerHTML = `<div class="text-center py-3">${loadingSpinner()}</div>`;

    try {
        const result = await apiPost('/modules/dns/test', { domain, record_type: recordType });
        const isSuccess = result.success;
        const { escapeHtml } = await import('/static/js/utils.js');

        resultDiv.innerHTML = `
            <div class="alert ${isSuccess ? 'alert-success' : 'alert-warning'}">
                <div class="d-flex align-items-center">
                    <i class="ti ti-${isSuccess ? 'check' : 'alert-triangle'} me-2"></i>
                    <div>
                        <strong>${t('dns.queryLabel')}:</strong> ${escapeHtml(result.query)}<br>
                        <strong>${t('dns.resultLabel')}:</strong> <code>${escapeHtml(result.result)}</code>
                        ${result.error ? `<br><strong>${t('dns.errorLabel')}:</strong> ${escapeHtml(result.error)}` : ''}
                    </div>
                </div>
            </div>
        `;
    } catch (err) {
        resultDiv.innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
    }
}

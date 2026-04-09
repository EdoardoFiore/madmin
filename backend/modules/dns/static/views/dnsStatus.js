/**
 * DNS Module - Status/Dashboard View
 *
 * Service status cards, tab shell, service start/stop.
 */

import { t } from '/static/js/i18n.js';
import { apiGet, apiPost } from '/static/js/api.js';
import { showToast, confirmDialog, loadingSpinner } from '/static/js/utils.js';
import { renderDnsZonesTab } from '/static/modules/dns/views/dnsZones.js';
import { renderDnsSettingsTab, renderDnsTestTab } from '/static/modules/dns/views/dnsSettings.js';

const MODE_LABELS = {
    get recursive() { return t('dns.modeRecursive'); },
    get forward_only() { return t('dns.modeForwardOnly'); },
    get non_recursive() { return t('dns.modeNonRecursive'); },
};

export async function renderDnsStatus(container, perms) {
    container.innerHTML = `<div class="text-center py-5">${loadingSpinner()}</div>`;

    try {
        const [status, zones, settings] = await Promise.all([
            apiGet('/modules/dns/status'),
            apiGet('/modules/dns/zones'),
            apiGet('/modules/dns/settings'),
        ]);

        container.innerHTML = `
            <!-- Status Cards -->
            <div class="row row-deck row-cards mb-3">
                <div class="col-sm-6 col-lg-3">
                    <div class="card">
                        <div class="card-body">
                            <div class="subheader">${t('dns.serviceStatus')}</div>
                            <div class="d-flex align-items-baseline mt-1">
                                <span class="status-dot ${status.running ? 'status-dot-animated bg-success' : 'bg-danger'} me-2"></span>
                                <span class="h1 mb-0">${status.running ? t('dns.statusActive') : t('dns.statusStopped')}</span>
                            </div>
                            ${perms.manage ? `
                            <div class="mt-2">
                                ${status.running
                                    ? `<button class="btn btn-sm btn-warning" id="btn-stop"><i class="ti ti-player-stop me-1"></i>${t('dns.stop')}</button>`
                                    : `<button class="btn btn-sm btn-success" id="btn-start"><i class="ti ti-player-play me-1"></i>${t('dns.start')}</button>`}
                            </div>` : ''}
                        </div>
                    </div>
                </div>
                <div class="col-sm-6 col-lg-3">
                    <div class="card">
                        <div class="card-body">
                            <div class="subheader">${t('dns.mode')}</div>
                            <div class="h1 mb-0 mt-1">${MODE_LABELS[status.mode] || status.mode}</div>
                        </div>
                    </div>
                </div>
                <div class="col-sm-6 col-lg-3">
                    <div class="card">
                        <div class="card-body">
                            <div class="subheader">${t('dns.dnsZones')}</div>
                            <div class="h1 mb-0 mt-1">${status.total_zones}</div>
                        </div>
                    </div>
                </div>
                <div class="col-sm-6 col-lg-3">
                    <div class="card">
                        <div class="card-body">
                            <div class="subheader">${t('dns.totalRecords')}</div>
                            <div class="h1 mb-0 mt-1">${status.total_records}</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Tabs -->
            <div class="card">
                <div class="card-header">
                    <ul class="nav nav-tabs card-header-tabs" id="dns-tabs">
                        <li class="nav-item">
                            <a class="nav-link active" href="#" data-tab="zones">
                                <i class="ti ti-world me-1"></i>${t('dns.tabZones')}
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#" data-tab="settings">
                                <i class="ti ti-settings me-1"></i>${t('dns.tabSettings')}
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#" data-tab="test">
                                <i class="ti ti-search me-1"></i>${t('dns.tabTestDns')}
                            </a>
                        </li>
                    </ul>
                </div>
                <div id="dns-tab-content"></div>
            </div>
        `;

        setupTabListeners(zones, settings, container, perms);
        setupServiceActions(container, perms);
        renderDnsZonesTab(zones, container, perms);

    } catch (err) {
        container.innerHTML = `<div class="alert alert-danger"><i class="ti ti-alert-triangle me-2"></i>${err.message}</div>`;
    }
}

function setupTabListeners(zones, settings, container, perms) {
    document.getElementById('dns-tabs')?.addEventListener('click', async (e) => {
        e.preventDefault();
        const tab = e.target.closest('[data-tab]');
        if (!tab) return;

        document.querySelectorAll('#dns-tabs .nav-link').forEach(l => l.classList.remove('active'));
        tab.classList.add('active');

        const tabName = tab.dataset.tab;
        if (tabName === 'zones') renderDnsZonesTab(zones, container, perms);
        else if (tabName === 'settings') await renderDnsSettingsTab(settings, perms);
        else if (tabName === 'test') renderDnsTestTab();
    });
}

function setupServiceActions(container, perms) {
    document.getElementById('btn-start')?.addEventListener('click', async () => {
        try {
            await apiPost('/modules/dns/start');
            showToast(t('dns.serviceStarted'), 'success');
            await renderDnsStatus(container, perms);
        } catch (err) { showToast(err.message, 'error'); }
    });

    document.getElementById('btn-stop')?.addEventListener('click', async () => {
        if (!await confirmDialog(t('dns.confirmStopTitle'), t('dns.confirmStopMsg'))) return;
        try {
            await apiPost('/modules/dns/stop');
            showToast(t('dns.serviceStopped'), 'success');
            await renderDnsStatus(container, perms);
        } catch (err) { showToast(err.message, 'error'); }
    });
}

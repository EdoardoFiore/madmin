/**
 * DNS Module - Dashboard Widget
 *
 * Shows DNS server status, zone count, record count on the dashboard.
 */

import { apiGet } from '/static/js/api.js';
import { t, loadModuleTranslations } from '/static/js/i18n.js';

// Load translations at module import time so render() can use t()
await loadModuleTranslations('dns');

export const widgets = {
    dns_dns_status: {
        render() {
            return `
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">
                            <img src="https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/isc-bind9-light.png"
                                 alt="" style="width: 20px; height: 20px; margin-right: 8px;">
                            DNS Server
                        </h3>
                        <div class="card-actions">
                            <a href="#dns" class="btn btn-sm btn-outline-primary">
                                <i class="ti ti-external-link me-1"></i>${t('dns.manage')}
                            </a>
                        </div>
                    </div>
                    <div class="card-body p-0" id="dns-widget-body"></div>
                </div>
            `;
        },

        async load() {
            const container = document.getElementById('dns-widget-body');
            if (!container) return;

            try {
                const status = await apiGet('/modules/dns/status');

                container.innerHTML = `
                    <div class="p-3">
                        <div class="row g-2">
                            <div class="col-6">
                                <div class="text-center">
                                    <div class="fw-bold fs-3">${status.total_zones}</div>
                                    <div class="text-muted small">${t('dns.zones')}</div>
                                </div>
                            </div>
                            <div class="col-6">
                                <div class="text-center">
                                    <div class="fw-bold fs-3">${status.total_records}</div>
                                    <div class="text-muted small">${t('dns.records')}</div>
                                </div>
                            </div>
                        </div>
                        <div class="mt-2 text-center">
                            <span class="badge ${status.running ? 'bg-green-lt' : 'bg-red-lt'}">
                                ${status.running ? t('dns.wServiceActive') : t('dns.wServiceStopped')}
                            </span>
                            <span class="badge bg-azure-lt ms-1">${status.mode || 'recursive'}</span>
                        </div>
                    </div>
                `;

            } catch (e) {
                container.innerHTML = `
                    <div class="text-muted text-center py-3 p-3">
                        <i class="ti ti-alert-circle"></i> ${t('dns.loadError')}
                    </div>
                `;
            }
        }
    }
};

/**
 * DHCP Module - Dashboard Widgets
 *
 * Uses existing APIs: GET /status + GET /leases
 */

import { apiGet } from '/static/js/api.js';
import { t, loadModuleTranslations } from '/static/js/i18n.js';

// Load translations at module import time so render() can use t()
await loadModuleTranslations('dhcp');

export const widgets = {
    dhcp_server_status: {
        render() {
            return `
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">
                            <img src="https://www.svgrepo.com/show/472739/network.svg"
                                 alt="" style="width: 20px; height: 20px; margin-right: 8px;">
                            DHCP Server
                        </h3>
                        <div class="card-actions">
                            <a href="#dhcp" class="btn btn-sm btn-outline-primary">
                                <i class="ti ti-external-link me-1"></i>${t('dhcp.manage')}
                            </a>
                        </div>
                    </div>
                    <div class="card-body p-0" id="dhcp-widget-body">
                        <div class="text-muted text-center py-4">
                            <span class="spinner-border spinner-border-sm"></span> ${t('dhcp.loading')}
                        </div>
                    </div>
                </div>
            `;
        },

        async load() {
            const container = document.getElementById('dhcp-widget-body');
            if (!container) return;

            try {
                const [status, leases] = await Promise.all([
                    apiGet('/modules/dhcp/status'),
                    apiGet('/modules/dhcp/leases'),
                ]);

                const activeLeases = leases.filter(l => l.state === 'active');

                container.innerHTML = `
                    <!-- Stats header -->
                    <div class="p-3 pb-2">
                        <div class="row g-2">
                            <div class="col-4">
                                <div class="text-center">
                                    <div class="fw-bold fs-3">${status.total_subnets}</div>
                                    <div class="text-muted small">${t('dhcp.subnet')}</div>
                                </div>
                            </div>
                            <div class="col-4">
                                <div class="text-center">
                                    <div class="fw-bold fs-3">${status.total_hosts}</div>
                                    <div class="text-muted small">${t('dhcp.wReserved')}</div>
                                </div>
                            </div>
                            <div class="col-4">
                                <div class="text-center">
                                    <div class="fw-bold fs-3">${activeLeases.length}</div>
                                    <div class="text-muted small">${t('dhcp.wActiveLeases')}</div>
                                </div>
                            </div>
                        </div>
                        <div class="mt-2 text-center">
                            <span class="badge ${status.running ? 'bg-green-lt' : 'bg-red-lt'}">
                                ${status.running ? t('dhcp.wServiceActive') : t('dhcp.wServiceStopped')}
                            </span>
                            ${status.config_valid === false ? `<span class="badge bg-yellow-lt ms-1">${t('dhcp.wConfigInvalid')}</span>` : ''}
                        </div>
                    </div>

                    <!-- Active leases list -->
                    <div class="border-top">
                        <div class="px-3 pt-2 pb-1 d-flex align-items-center justify-content-between">
                            <span class="text-muted small fw-bold">
                                <i class="ti ti-plug me-1"></i>${t('dhcp.wActiveLeases')}
                            </span>
                            ${activeLeases.length > 5 ? `
                                <input type="text" class="form-control form-control-sm"
                                       id="dhcp-lease-search" placeholder="${t('dhcp.wSearchIpMac')}"
                                       style="max-width: 150px; height: 26px; font-size: 0.75rem;">
                            ` : ''}
                        </div>
                        <div class="list-group list-group-flush" style="max-height: 200px; overflow-y: auto;">
                            ${activeLeases.length === 0 ? `
                                <div class="text-muted text-center py-3 small">
                                    <i class="ti ti-network-off"></i> ${t('dhcp.wNoActiveLeases')}
                                </div>
                            ` : activeLeases.map(l => `
                                <div class="list-group-item px-3 py-2 dhcp-lease-item"
                                     data-search="${(l.ip_address + ' ' + (l.mac_address || '') + ' ' + (l.hostname || '')).toLowerCase()}">
                                    <div class="d-flex align-items-center justify-content-between">
                                        <div>
                                            <div class="fw-bold small">${l.ip_address}</div>
                                            <div class="text-muted" style="font-size: 0.7rem;">
                                                ${l.hostname || l.mac_address || '—'}
                                                ${l.subnet_name ? ` · ${l.subnet_name}` : ''}
                                            </div>
                                        </div>
                                        <div class="text-end">
                                            <div class="text-muted" style="font-size: 0.7rem;">
                                                ${l.mac_address && l.hostname ? l.mac_address : ''}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                `;

                // Search filter
                const searchInput = document.getElementById('dhcp-lease-search');
                if (searchInput) {
                    searchInput.addEventListener('input', () => {
                        const q = searchInput.value.toLowerCase();
                        document.querySelectorAll('.dhcp-lease-item').forEach(item => {
                            item.style.display = (item.dataset.search || '').includes(q) ? '' : 'none';
                        });
                    });
                }

            } catch (e) {
                container.innerHTML = `
                    <div class="text-muted text-center py-3 p-3">
                        <i class="ti ti-alert-circle"></i> ${t('dhcp.loadError')}
                    </div>
                `;
            }
        }
    }
};

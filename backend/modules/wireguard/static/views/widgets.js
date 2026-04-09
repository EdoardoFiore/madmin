/**
 * WireGuard Module - Dashboard Widgets
 *
 * Exports widget implementations for the dashboard.
 * Uses existing API endpoints (no dedicated widget endpoints).
 */

import { apiGet } from '/assets/js/api.js';
import { t, loadModuleTranslations } from '/static/js/i18n.js';

// Load translations at module import time so render() can use t()
await loadModuleTranslations('wireguard');

function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

export const widgets = {
    wireguard_vpn_status: {
        render() {
            return `
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">
                            <img src="https://www.svgrepo.com/show/520310/wireguard.svg"
                                 alt="" style="width: 20px; height: 20px; margin-right: 8px;">
                            WireGuard VPN
                        </h3>
                        <div class="card-actions">
                            <a href="#wireguard" class="btn btn-sm btn-outline-primary">
                                <i class="ti ti-external-link me-1"></i>${t('wireguard.manage')}
                            </a>
                        </div>
                    </div>
                    <div class="card-body p-0" id="wg-widget-body">
                        <div class="text-muted text-center py-4">
                            <span class="spinner-border spinner-border-sm"></span> ${t('wireguard.loading')}
                        </div>
                    </div>
                </div>
            `;
        },

        async load() {
            const container = document.getElementById('wg-widget-body');
            if (!container) return;

            try {
                // Fetch instances (existing API)
                const instances = await apiGet('/modules/wireguard/instances');

                const total = instances.length;
                const running = instances.filter(i => i.status === 'running').length;
                const totalClients = instances.reduce((sum, i) => sum + (i.client_count || 0), 0);

                // Fetch clients for all running instances (existing API)
                const allClients = [];
                for (const inst of instances.filter(i => i.status === 'running')) {
                    try {
                        const clients = await apiGet(`/modules/wireguard/instances/${inst.id}/clients`);
                        for (const c of clients) {
                            allClients.push({ ...c, instance_name: inst.name });
                        }
                    } catch (e) { /* skip */ }
                }

                const connectedClients = allClients.filter(c => c.is_connected);

                container.innerHTML = `
                    <!-- Stats header -->
                    <div class="p-3 pb-2">
                        <div class="row g-2">
                            <div class="col-6">
                                <div class="d-flex align-items-center">
                                    <span class="avatar avatar-sm bg-green-lt me-2">
                                        <i class="ti ti-server"></i>
                                    </span>
                                    <div>
                                        <div class="fw-bold">${running}/${total}</div>
                                        <div class="text-muted small">${t('wireguard.wActiveInstances')}</div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-6">
                                <div class="d-flex align-items-center">
                                    <span class="avatar avatar-sm bg-azure-lt me-2">
                                        <i class="ti ti-users"></i>
                                    </span>
                                    <div>
                                        <div class="fw-bold">${totalClients}</div>
                                        <div class="text-muted small">${t('wireguard.wConfiguredClients')}</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Connected clients section -->
                    <div class="border-top">
                        <div class="px-3 pt-2 pb-1 d-flex align-items-center justify-content-between">
                            <span class="text-muted small fw-bold">
                                <i class="ti ti-wifi me-1"></i>${connectedClients.length} ${t('wireguard.wConnected')}
                            </span>
                            ${connectedClients.length > 3 ? `
                                <input type="text" class="form-control form-control-sm"
                                       id="wg-client-search" placeholder="${t('wireguard.wSearchClient')}"
                                       style="max-width: 150px; height: 26px; font-size: 0.75rem;">
                            ` : ''}
                        </div>
                        <div class="list-group list-group-flush" id="wg-client-list"
                             style="max-height: 200px; overflow-y: auto;">
                            ${connectedClients.length === 0 ? `
                                <div class="text-muted text-center py-3 small">
                                    <i class="ti ti-plug-connected-x"></i> ${t('wireguard.wNoConnectedClients')}
                                </div>
                            ` : connectedClients.map(c => `
                                <div class="list-group-item px-3 py-2 wg-client-item"
                                     data-name="${(c.name || '').toLowerCase()}">
                                    <div class="d-flex align-items-center justify-content-between">
                                        <div class="d-flex align-items-center">
                                            <span class="status-dot status-dot-active me-2"></span>
                                            <div>
                                                <div class="fw-bold small">${c.name}</div>
                                                <div class="text-muted" style="font-size: 0.7rem;">
                                                    ${c.instance_name} · ${c.allocated_ip}
                                                </div>
                                            </div>
                                        </div>
                                        <div class="text-end">
                                            <div class="text-muted" style="font-size: 0.7rem;">
                                                ↓${formatBytes(c.rx_bytes)} ↑${formatBytes(c.tx_bytes)}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                `;

                // Setup search filter
                const searchInput = document.getElementById('wg-client-search');
                if (searchInput) {
                    searchInput.addEventListener('input', () => {
                        const q = searchInput.value.toLowerCase();
                        document.querySelectorAll('.wg-client-item').forEach(item => {
                            const name = item.dataset.name || '';
                            item.style.display = name.includes(q) ? '' : 'none';
                        });
                    });
                }

            } catch (e) {
                container.innerHTML = `
                    <div class="text-muted text-center py-3 p-3">
                        <i class="ti ti-alert-circle"></i> ${t('wireguard.loadError')}
                    </div>
                `;
            }
        }
    }
};

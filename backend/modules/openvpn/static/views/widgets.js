/**
 * OpenVPN Module - Dashboard Widgets
 *
 * Uses existing API: GET /instances + GET /instances/{id}/clients
 */

import { apiGet } from '/static/js/api.js';
import { t, loadModuleTranslations } from '/static/js/i18n.js';

// Load translations at module import time so render() can use t()
await loadModuleTranslations('openvpn');

function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

export const widgets = {
    openvpn_vpn_status: {
        render() {
            return `
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">
                            <img src="https://www.svgrepo.com/show/504696/openvpn.svg"
                                 alt="" style="width: 20px; height: 20px; margin-right: 8px;">
                            OpenVPN
                        </h3>
                        <div class="card-actions">
                            <a href="#openvpn" class="btn btn-sm btn-outline-primary">
                                <i class="ti ti-external-link me-1"></i>${t('openvpn.manage')}
                            </a>
                        </div>
                    </div>
                    <div class="card-body p-0" id="ovpn-widget-body"></div>
                </div>
            `;
        },

        async load() {
            const container = document.getElementById('ovpn-widget-body');
            if (!container) return;

            try {
                const instances = await apiGet('/modules/openvpn/instances');

                const total = instances.length;
                const running = instances.filter(i => i.status === 'running').length;
                const totalClients = instances.reduce((sum, i) => sum + (i.client_count || 0), 0);

                // Fetch clients for running instances
                const allClients = [];
                for (const inst of instances.filter(i => i.status === 'running')) {
                    try {
                        const clients = await apiGet(`/modules/openvpn/instances/${inst.id}/clients`);
                        for (const c of clients) {
                            if (!c.revoked) allClients.push({ ...c, instance_name: inst.name });
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
                                        <div class="text-muted small">${t('openvpn.wActiveInstances')}</div>
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
                                        <div class="text-muted small">${t('openvpn.wConfiguredClients')}</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Connected clients -->
                    <div class="border-top">
                        <div class="px-3 pt-2 pb-1 d-flex align-items-center justify-content-between">
                            <span class="text-muted small fw-bold">
                                <i class="ti ti-wifi me-1"></i>${connectedClients.length} ${t('openvpn.wConnected')}
                            </span>
                            ${connectedClients.length > 3 ? `
                                <input type="text" class="form-control form-control-sm"
                                       id="ovpn-client-search" placeholder="${t('openvpn.wSearchClient')}"
                                       style="max-width: 150px; height: 26px; font-size: 0.75rem;">
                            ` : ''}
                        </div>
                        <div class="list-group list-group-flush" id="ovpn-client-list"
                             style="max-height: 200px; overflow-y: auto;">
                            ${connectedClients.length === 0 ? `
                                <div class="text-muted text-center py-3 small">
                                    <i class="ti ti-plug-connected-x"></i> ${t('openvpn.wNoConnectedClients')}
                                </div>
                            ` : connectedClients.map(c => `
                                <div class="list-group-item px-3 py-2 ovpn-client-item"
                                     data-name="${(c.name || '').toLowerCase()}">
                                    <div class="d-flex align-items-center justify-content-between">
                                        <div class="d-flex align-items-center">
                                            <span class="status-dot status-dot-active me-2"></span>
                                            <div>
                                                <div class="fw-bold small">${c.name}</div>
                                                <div class="text-muted" style="font-size: 0.7rem;">
                                                    ${c.instance_name} · ${c.allocated_ip || '—'}
                                                </div>
                                            </div>
                                        </div>
                                        <div class="text-end">
                                            <div class="text-muted" style="font-size: 0.7rem;">
                                                ↓${formatBytes(c.bytes_received)} ↑${formatBytes(c.bytes_sent)}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                `;

                // Search filter
                const searchInput = document.getElementById('ovpn-client-search');
                if (searchInput) {
                    searchInput.addEventListener('input', () => {
                        const q = searchInput.value.toLowerCase();
                        document.querySelectorAll('.ovpn-client-item').forEach(item => {
                            item.style.display = (item.dataset.name || '').includes(q) ? '' : 'none';
                        });
                    });
                }

            } catch (e) {
                container.innerHTML = `
                    <div class="text-muted text-center py-3 p-3">
                        <i class="ti ti-alert-circle"></i> ${t('openvpn.loadError')}
                    </div>
                `;
            }
        }
    }
};

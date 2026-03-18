/**
 * DHCP Module - Dashboard Widgets
 * 
 * Uses existing APIs: GET /status + GET /leases
 */

import { apiGet } from '/assets/js/api.js';

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
                                <i class="ti ti-external-link me-1"></i>Gestisci
                            </a>
                        </div>
                    </div>
                    <div class="card-body p-0" id="dhcp-widget-body">
                        <div class="text-muted text-center py-4">
                            <span class="spinner-border spinner-border-sm"></span> Caricamento...
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
                                    <div class="text-muted small">Subnet</div>
                                </div>
                            </div>
                            <div class="col-4">
                                <div class="text-center">
                                    <div class="fw-bold fs-3">${status.total_hosts}</div>
                                    <div class="text-muted small">Riservati</div>
                                </div>
                            </div>
                            <div class="col-4">
                                <div class="text-center">
                                    <div class="fw-bold fs-3">${activeLeases.length}</div>
                                    <div class="text-muted small">Lease attivi</div>
                                </div>
                            </div>
                        </div>
                        <div class="mt-2 text-center">
                            <span class="badge ${status.running ? 'bg-green-lt' : 'bg-red-lt'}">
                                ${status.running ? 'Servizio attivo' : 'Servizio fermo'}
                            </span>
                            ${status.config_valid === false ? '<span class="badge bg-yellow-lt ms-1">Config non valida</span>' : ''}
                        </div>
                    </div>

                    <!-- Active leases list -->
                    <div class="border-top">
                        <div class="px-3 pt-2 pb-1 d-flex align-items-center justify-content-between">
                            <span class="text-muted small fw-bold">
                                <i class="ti ti-plug me-1"></i>Lease attivi
                            </span>
                            ${activeLeases.length > 5 ? `
                                <input type="text" class="form-control form-control-sm" 
                                       id="dhcp-lease-search" placeholder="Cerca IP/MAC..." 
                                       style="max-width: 150px; height: 26px; font-size: 0.75rem;">
                            ` : ''}
                        </div>
                        <div class="list-group list-group-flush" style="max-height: 200px; overflow-y: auto;">
                            ${activeLeases.length === 0 ? `
                                <div class="text-muted text-center py-3 small">
                                    <i class="ti ti-network-off"></i> Nessun lease attivo
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
                        <i class="ti ti-alert-circle"></i> Impossibile caricare i dati
                    </div>
                `;
            }
        }
    }
};

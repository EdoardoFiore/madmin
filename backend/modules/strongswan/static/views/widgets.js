/**
 * StrongSwan Module - Dashboard Widgets
 * 
 * Uses existing API: GET /tunnels (includes child_sas with is_up)
 */

import { apiGet } from '/assets/js/api.js';

export const widgets = {
    strongswan_tunnel_status: {
        render() {
            return `
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">
                            <img src="https://www.svgrepo.com/show/306809/strongswan.svg" 
                                 alt="" style="width: 20px; height: 20px; margin-right: 8px;">
                            IPsec VPN
                        </h3>
                        <div class="card-actions">
                            <a href="#strongswan" class="btn btn-sm btn-outline-primary">
                                <i class="ti ti-external-link me-1"></i>Gestisci
                            </a>
                        </div>
                    </div>
                    <div class="card-body p-0" id="ipsec-widget-body">
                        <div class="text-muted text-center py-4">
                            <span class="spinner-border spinner-border-sm"></span> Caricamento...
                        </div>
                    </div>
                </div>
            `;
        },

        async load() {
            const container = document.getElementById('ipsec-widget-body');
            if (!container) return;

            try {
                const tunnels = await apiGet('/modules/strongswan/tunnels');

                const totalTunnels = tunnels.length;
                let totalChildSas = 0;
                let upChildSas = 0;

                // Flatten tunnel + child SA data
                const tunnelRows = [];
                for (const t of tunnels) {
                    const children = t.child_sas || [];
                    totalChildSas += children.length;
                    const childrenUp = children.filter(c => c.is_up);
                    upChildSas += childrenUp.length;

                    tunnelRows.push({
                        name: t.name,
                        remote: t.remote_addr,
                        childCount: children.length,
                        childrenUp: childrenUp.length,
                        children: children,
                    });
                }

                container.innerHTML = `
                    <!-- Stats header -->
                    <div class="p-3 pb-2">
                        <div class="row g-2">
                            <div class="col-6">
                                <div class="d-flex align-items-center">
                                    <span class="avatar avatar-sm bg-cyan-lt me-2">
                                        <i class="ti ti-lock"></i>
                                    </span>
                                    <div>
                                        <div class="fw-bold">${totalTunnels}</div>
                                        <div class="text-muted small">Tunnel</div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-6">
                                <div class="d-flex align-items-center">
                                    <span class="avatar avatar-sm ${upChildSas > 0 ? 'bg-green-lt' : 'bg-secondary-lt'} me-2">
                                        <i class="ti ti-arrows-exchange"></i>
                                    </span>
                                    <div>
                                        <div class="fw-bold">${upChildSas}/${totalChildSas}</div>
                                        <div class="text-muted small">Child SA attive</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Tunnel list -->
                    <div class="border-top">
                        <div class="list-group list-group-flush" style="max-height: 250px; overflow-y: auto;">
                            ${tunnelRows.length === 0 ? `
                                <div class="text-muted text-center py-3 small">
                                    <i class="ti ti-lock-off"></i> Nessun tunnel configurato
                                </div>
                            ` : tunnelRows.map(t => `
                                <div class="list-group-item px-3 py-2">
                                    <div class="d-flex align-items-center justify-content-between mb-1">
                                        <div class="d-flex align-items-center">
                                            <span class="status-dot ${t.childrenUp > 0 ? 'status-dot-active' : 'status-dot-inactive'} me-2"></span>
                                            <span class="fw-bold small">${t.name}</span>
                                        </div>
                                        <span class="text-muted" style="font-size: 0.7rem;">${t.remote || '—'}</span>
                                    </div>
                                    ${t.children.length > 0 ? `
                                        <div class="ms-3">
                                            ${t.children.map(c => `
                                                <div class="d-flex align-items-center py-1" style="font-size: 0.7rem;">
                                                    <span class="badge ${c.is_up ? 'bg-green-lt' : 'bg-secondary-lt'} me-2" 
                                                          style="width: 8px; height: 8px; padding: 0; border-radius: 50%;"></span>
                                                    <span class="text-muted">${c.name}</span>
                                                    <span class="ms-auto text-muted">
                                                        ${c.local_ts || '?'} ↔ ${c.remote_ts || '?'}
                                                    </span>
                                                </div>
                                            `).join('')}
                                        </div>
                                    ` : ''}
                                </div>
                            `).join('')}
                        </div>
                    </div>
                `;

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

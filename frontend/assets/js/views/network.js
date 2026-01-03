/**
 * MADMIN - Network Interfaces View
 * 
 * Displays network interface information with IP, MAC, status, and traffic stats.
 * Allows netplan configuration for static IP or DHCP.
 */

import { apiGet, apiPost, apiDelete } from '../api.js';
import { showToast, confirmDialog } from '../utils.js';
import { checkPermission } from '../app.js';

/**
 * Format bytes to human readable string
 */
function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

/**
 * Render the network interfaces view
 */
export async function render(container) {
    const canManage = checkPermission('settings.manage');

    container.innerHTML = `
        <div class="row row-deck row-cards">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">
                            <i class="ti ti-network me-2"></i>Interfacce di Rete
                        </h3>
                        <div class="card-actions">
                            ${canManage ? `
                            <button class="btn btn-outline-warning me-2" id="btn-apply-netplan" title="Applica Configurazione">
                                <i class="ti ti-check me-1"></i>Applica Netplan
                            </button>
                            ` : ''}
                            <button class="btn btn-ghost-primary" id="btn-refresh-interfaces" title="Aggiorna">
                                <i class="ti ti-refresh"></i>
                            </button>
                        </div>
                    </div>
                    <div class="card-body" id="interfaces-container">
                        <div class="text-center py-4 text-muted">
                            <i class="ti ti-loader ti-spin" style="font-size: 2rem;"></i>
                            <p class="mt-2">Caricamento interfacce...</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Netplan Config Modal -->
        <div class="modal" id="modal-netplan" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="ti ti-settings me-2"></i>Configura <span id="modal-iface-name"></span>
                        </h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <input type="hidden" id="netplan-interface">
                        
                        <div class="mb-3">
                            <label class="form-check form-switch">
                                <input class="form-check-input" type="checkbox" id="netplan-dhcp" checked>
                                <span class="form-check-label">Usa DHCP (automatico)</span>
                            </label>
                        </div>
                        
                        <div id="static-config" style="display: none;">
                            <div class="mb-3">
                                <label class="form-label">Indirizzo IP (CIDR)</label>
                                <input type="text" class="form-control" id="netplan-address" 
                                       placeholder="es. 192.168.1.100/24">
                                <small class="form-hint">Formato: IP/prefisso (es. 192.168.1.100/24)</small>
                            </div>
                            
                            <div class="mb-3">
                                <label class="form-label">Gateway predefinito</label>
                                <input type="text" class="form-control" id="netplan-gateway" 
                                       placeholder="es. 192.168.1.1">
                            </div>
                            
                            <div class="mb-3">
                                <label class="form-label">DNS Server</label>
                                <input type="text" class="form-control" id="netplan-dns" 
                                       placeholder="es. 8.8.8.8, 8.8.4.4">
                                <small class="form-hint">Separati da virgola</small>
                            </div>
                        </div>
                        
                        <div class="mb-3">
                            <label class="form-label">MTU (opzionale)</label>
                            <input type="number" class="form-control" id="netplan-mtu" 
                                   placeholder="1500" min="576" max="9000">
                        </div>
                        
                        <div class="alert alert-warning">
                            <i class="ti ti-alert-triangle me-2"></i>
                            <strong>Attenzione:</strong> Dopo il salvataggio, clicca "Applica Netplan" per attivare le modifiche.
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-link" data-bs-dismiss="modal">Annulla</button>
                        <button type="button" class="btn btn-primary" id="btn-save-netplan">
                            <i class="ti ti-device-floppy me-1"></i>Salva
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Setup event listeners
    document.getElementById('btn-refresh-interfaces')?.addEventListener('click', loadInterfaces);
    document.getElementById('btn-apply-netplan')?.addEventListener('click', applyNetplan);
    document.getElementById('btn-save-netplan')?.addEventListener('click', saveNetplanConfig);

    // DHCP toggle
    document.getElementById('netplan-dhcp')?.addEventListener('change', (e) => {
        document.getElementById('static-config').style.display = e.target.checked ? 'none' : 'block';
    });

    // Load interfaces
    await loadInterfaces();
}

/**
 * Load network interfaces from API
 */
async function loadInterfaces() {
    const container = document.getElementById('interfaces-container');
    if (!container) return;

    try {
        const response = await apiGet('/network/interfaces');
        const interfaces = response.interfaces || [];

        if (interfaces.length === 0) {
            container.innerHTML = `
                <div class="text-center py-4 text-muted">
                    <i class="ti ti-network-off" style="font-size: 2rem;"></i>
                    <p class="mt-2">Nessuna interfaccia di rete trovata</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="row g-3">
                ${interfaces.map(iface => renderInterfaceCard(iface)).join('')}
            </div>
        `;

        // Setup configure buttons
        document.querySelectorAll('[data-configure-iface]').forEach(btn => {
            btn.addEventListener('click', () => openNetplanModal(btn.dataset.configureIface));
        });

    } catch (error) {
        console.error('Error loading interfaces:', error);
        container.innerHTML = `
            <div class="text-center py-4 text-danger">
                <i class="ti ti-alert-circle" style="font-size: 2rem;"></i>
                <p class="mt-2">Errore caricamento interfacce: ${error.message}</p>
            </div>
        `;
    }
}

/**
 * Render a single interface card
 */
function renderInterfaceCard(iface) {
    const isUp = iface.is_up;
    const statusClass = isUp ? 'bg-success' : 'bg-secondary';
    const statusText = isUp ? 'Attiva' : 'Inattiva';
    const canManage = checkPermission('settings.manage');

    // Determine interface type icon
    let icon = 'ti-network';
    if (iface.name.startsWith('wg') || iface.name.startsWith('tun') || iface.name.startsWith('tap')) {
        icon = 'ti-lock';
    } else if (iface.name.startsWith('docker') || iface.name.startsWith('br-') || iface.name.startsWith('veth')) {
        icon = 'ti-container';
    } else if (iface.name === 'lo') {
        icon = 'ti-arrow-loop-right';
    } else if (iface.name.startsWith('wl') || iface.name.includes('wlan')) {
        icon = 'ti-wifi';
    }

    // Netplan config badge
    let netplanBadge = '';
    if (iface.netplan) {
        if (iface.netplan.dhcp4) {
            netplanBadge = '<span class="badge bg-info text-white ms-1">DHCP</span>';
        } else if (iface.netplan.addresses?.length > 0) {
            netplanBadge = '<span class="badge bg-purple text-white ms-1">Statico</span>';
        }
    }

    return `
        <div class="col-md-6 col-lg-4">
            <div class="card">
                <div class="card-body">
                    <div class="d-flex align-items-center mb-3">
                        <div class="avatar bg-primary-lt me-3">
                            <i class="ti ${icon}"></i>
                        </div>
                        <div class="flex-fill">
                            <h4 class="mb-0">${iface.name}</h4>
                            <span class="badge ${statusClass}">${statusText}</span>
                            ${iface.speed > 0 ? `<span class="badge bg-azure text-white ms-1">${iface.speed} Mbps</span>` : ''}
                            ${netplanBadge}
                        </div>
                        ${canManage && !iface.name.startsWith('docker') && !iface.name.startsWith('veth') ? `
                        <button class="btn btn-sm btn-ghost-primary" data-configure-iface="${iface.name}" title="Configura">
                            <i class="ti ti-settings"></i>
                        </button>
                        ` : ''}
                    </div>
                    
                    <dl class="row mb-0 small">
                        ${iface.ipv4 ? `
                            <dt class="col-4 text-muted">IPv4:</dt>
                            <dd class="col-8"><code>${iface.ipv4}</code></dd>
                        ` : ''}
                        ${iface.ipv6 ? `
                            <dt class="col-4 text-muted">IPv6:</dt>
                            <dd class="col-8"><code class="small">${iface.ipv6.substring(0, 20)}...</code></dd>
                        ` : ''}
                        ${iface.mac && iface.mac !== '00:00:00:00:00:00' ? `
                            <dt class="col-4 text-muted">MAC:</dt>
                            <dd class="col-8"><code>${iface.mac}</code></dd>
                        ` : ''}
                        ${iface.mtu > 0 ? `
                            <dt class="col-4 text-muted">MTU:</dt>
                            <dd class="col-8">${iface.mtu}</dd>
                        ` : ''}
                    </dl>
                    
                    <hr class="my-2">
                    
                    <div class="row text-center small">
                        <div class="col-6">
                            <div class="text-muted mb-1">
                                <i class="ti ti-arrow-down text-success"></i> Ricevuti
                            </div>
                            <strong>${formatBytes(iface.bytes_recv)}</strong>
                            <div class="text-muted">${iface.packets_recv.toLocaleString()} pkt</div>
                        </div>
                        <div class="col-6">
                            <div class="text-muted mb-1">
                                <i class="ti ti-arrow-up text-primary"></i> Inviati
                            </div>
                            <strong>${formatBytes(iface.bytes_sent)}</strong>
                            <div class="text-muted">${iface.packets_sent.toLocaleString()} pkt</div>
                        </div>
                    </div>
                    
                    ${(iface.errors_in > 0 || iface.errors_out > 0) ? `
                        <div class="mt-2 text-center small text-danger">
                            <i class="ti ti-alert-triangle"></i>
                            Errori: ${iface.errors_in} in / ${iface.errors_out} out
                        </div>
                    ` : ''}
                </div>
            </div>
        </div>
    `;
}

/**
 * Open netplan config modal
 */
async function openNetplanModal(interfaceName) {
    document.getElementById('netplan-interface').value = interfaceName;
    document.getElementById('modal-iface-name').textContent = interfaceName;

    // Reset form
    document.getElementById('netplan-dhcp').checked = true;
    document.getElementById('static-config').style.display = 'none';
    document.getElementById('netplan-address').value = '';
    document.getElementById('netplan-gateway').value = '';
    document.getElementById('netplan-dns').value = '';
    document.getElementById('netplan-mtu').value = '';

    // Try to load existing config
    try {
        const response = await apiGet(`/network/interfaces/${interfaceName}/config`);
        if (response.config) {
            const config = response.config;
            document.getElementById('netplan-dhcp').checked = config.dhcp4;
            document.getElementById('static-config').style.display = config.dhcp4 ? 'none' : 'block';

            if (config.addresses?.length > 0) {
                document.getElementById('netplan-address').value = config.addresses[0];
            }
            if (config.gateway4) {
                document.getElementById('netplan-gateway').value = config.gateway4;
            }
            if (config.dns_servers?.length > 0) {
                document.getElementById('netplan-dns').value = config.dns_servers.join(', ');
            }
            if (config.mtu) {
                document.getElementById('netplan-mtu').value = config.mtu;
            }
        }
    } catch (error) {
        // No existing config, start fresh
    }

    new bootstrap.Modal(document.getElementById('modal-netplan')).show();
}

/**
 * Save netplan configuration
 */
async function saveNetplanConfig() {
    const interfaceName = document.getElementById('netplan-interface').value;
    const dhcp4 = document.getElementById('netplan-dhcp').checked;

    const data = {
        interface: interfaceName,
        dhcp4: dhcp4
    };

    if (!dhcp4) {
        const address = document.getElementById('netplan-address').value.trim();
        const gateway = document.getElementById('netplan-gateway').value.trim();
        const dns = document.getElementById('netplan-dns').value.trim();

        if (!address) {
            showToast('Inserisci un indirizzo IP', 'error');
            return;
        }

        data.addresses = [address];
        if (gateway) data.gateway = gateway;
        if (dns) {
            data.dns_servers = dns.split(',').map(s => s.trim()).filter(s => s);
        }
    }

    const mtu = document.getElementById('netplan-mtu').value;
    if (mtu) {
        data.mtu = parseInt(mtu);
    }

    try {
        await apiPost(`/network/interfaces/${interfaceName}/config`, data);
        showToast('Configurazione salvata. Clicca "Applica Netplan" per attivare.', 'success');
        bootstrap.Modal.getInstance(document.getElementById('modal-netplan'))?.hide();
        await loadInterfaces();
    } catch (error) {
        showToast('Errore: ' + error.message, 'error');
    }
}

/**
 * Apply netplan configuration
 */
async function applyNetplan() {
    const confirmed = await confirmDialog(
        'Applica Configurazione Rete',
        'Stai per applicare le modifiche alla configurazione di rete. Questo potrebbe interrompere temporaneamente la connettività. Continuare?',
        'Applica',
        'btn-warning'
    );

    if (!confirmed) return;

    try {
        await apiPost('/network/netplan/apply', {});
        showToast('Configurazione applicata con successo', 'success');
        await loadInterfaces();
    } catch (error) {
        showToast('Errore applicazione: ' + error.message, 'error');
    }
}


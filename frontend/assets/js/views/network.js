/**
 * MADMIN - Network Interfaces View
 *
 * Displays network interface information with IP, MAC, status, and traffic stats.
 * Allows netplan configuration for static IP or DHCP.
 */

import { apiGet, apiPost, apiDelete } from '../api.js';
import { showToast, confirmDialog, isValidCIDR, isValidIP, escapeHtml, emptyState } from '../utils.js';
import { checkPermission } from '../app.js';
import { t } from '../i18n.js';

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function ifaceId(name) {
    return 'iface-' + name.replace(/[^a-zA-Z0-9]/g, '_');
}

// Name of the managed LAN interface (DHCP/NAT), or null. Loaded with interfaces.
let managedIface = null;
// All interfaces locked read-only by provisioning (incl. the managed one). Set of names.
let lockedIfaces = new Set();
// WAN edit-protection state (installer flag --protect-wan). Loaded with interfaces.
let wanProtectionEnabled = false;

export async function render(container) {
    const canManage = checkPermission('settings.manage');

    container.innerHTML = `
        <div class="row row-deck row-cards">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">
                            <i class="ti ti-network me-2"></i>${t('network.title')}
                        </h3>
                        <div class="card-actions">
                            ${canManage ? `
                            <button class="btn btn-outline-warning me-2" id="btn-apply-netplan" title="${t('network.applyNetplan')}">
                                <i class="ti ti-check me-1"></i>${t('network.applyNetplan')}
                            </button>
                            ` : ''}
                            <button class="btn btn-ghost-primary" id="btn-refresh-interfaces" title="${t('common.refresh')}">
                                <i class="ti ti-refresh"></i>
                            </button>
                        </div>
                    </div>
                    <div class="card-body p-2" id="interfaces-container" style="background: var(--tblr-bg-surface-secondary, #e9ecef)">
                        <div class="text-center py-4 text-muted">
                            <i class="ti ti-loader ti-spin" style="font-size: 2rem;"></i>
                            <p class="mt-2">${t('network.loadingInterfaces')}</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Netplan Config Modal -->
        <div class="modal" id="modal-netplan" tabindex="-1">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title d-flex align-items-center gap-2">
                            <span class="avatar avatar-sm bg-primary-lt">
                                <i class="ti ti-settings"></i>
                            </span>
                            ${t('network.configureInterface')} <code id="modal-iface-name" class="ms-1"></code>
                        </h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <input type="hidden" id="netplan-interface">

                        <div class="mb-4">
                            <label class="form-label fw-semibold">${t('network.ipMode')}</label>
                            <div class="form-selectgroup form-selectgroup-boxes d-flex">
                                <label class="form-selectgroup-item flex-fill">
                                    <input type="radio" name="netplan-mode" value="dhcp" class="form-selectgroup-input" checked>
                                    <div class="form-selectgroup-label d-flex align-items-center p-3">
                                        <i class="ti ti-refresh me-2 text-cyan"></i>
                                        <div>
                                            <div class="fw-semibold">DHCP</div>
                                            <small class="text-muted">${t('network.automatic')}</small>
                                        </div>
                                    </div>
                                </label>
                                <label class="form-selectgroup-item flex-fill">
                                    <input type="radio" name="netplan-mode" value="static" class="form-selectgroup-input">
                                    <div class="form-selectgroup-label d-flex align-items-center p-3">
                                        <i class="ti ti-pin me-2 text-purple"></i>
                                        <div>
                                            <div class="fw-semibold">${t('network.staticIp')}</div>
                                            <small class="text-muted">${t('network.staticIp')}</small>
                                        </div>
                                    </div>
                                </label>
                            </div>
                        </div>

                        <div id="static-config" style="display: none;">
                            <div class="row g-3 mb-3">
                                <div class="col-12">
                                    <label class="form-label">${t('network.ipCidr')}</label>
                                    <input type="text" class="form-control" id="netplan-address"
                                           placeholder="192.168.1.100/24">
                                    <small class="form-hint">${t('network.ipCidrHint')}</small>
                                </div>
                                <div class="col-sm-6">
                                    <label class="form-label">${t('network.gateway')}</label>
                                    <input type="text" class="form-control" id="netplan-gateway"
                                           placeholder="192.168.1.1">
                                </div>
                                <div class="col-sm-6">
                                    <label class="form-label">${t('network.dnsServer')}</label>
                                    <input type="text" class="form-control" id="netplan-dns"
                                           placeholder="8.8.8.8, 8.8.4.4">
                                    <small class="form-hint">${t('network.dnsHint')}</small>
                                </div>
                            </div>
                        </div>

                        <div class="mb-3">
                            <label class="form-label">${t('network.mtuLabel')} <span class="text-muted">(${t('network.mtuOptional')})</span></label>
                            <input type="number" class="form-control" id="netplan-mtu"
                                   placeholder="1500" min="576" max="9000">
                        </div>

                        <div class="alert alert-warning py-2 mb-0">
                            <div class="d-flex align-items-center">
                                <i class="ti ti-alert-triangle me-2 flex-shrink-0"></i>
                                <small>${t('network.afterSaveNote')}</small>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.cancel')}</button>
                        <button type="button" class="btn btn-primary" id="btn-save-netplan">
                            <i class="ti ti-device-floppy me-1"></i>${t('common.save')}
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <style>
            .iface-row {
                display: grid;
                grid-template-columns: 44px minmax(160px, 220px) 1fr 160px 60px;
                align-items: center;
                gap: 1rem;
                padding: 0.6rem 1rem;
                cursor: pointer;
                transition: background-color 0.15s;
                border-radius: var(--tblr-border-radius, 4px);
            }
            .iface-row:hover { background-color: var(--tblr-hover-bg, rgba(0,0,0,.04)); }
            .iface-chevron { transition: transform 0.2s ease; }
            .iface-chevron.rotated { transform: rotate(180deg); }
            @media (max-width: 768px) {
                .iface-row { grid-template-columns: 44px 1fr auto 48px; }
                .iface-col-traffic { display: none; }
            }
        </style>
    `;

    document.getElementById('btn-refresh-interfaces')?.addEventListener('click', loadInterfaces);
    document.getElementById('btn-apply-netplan')?.addEventListener('click', applyNetplan);
    document.getElementById('btn-save-netplan')?.addEventListener('click', saveNetplanConfig);

    document.querySelectorAll('input[name="netplan-mode"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            document.getElementById('static-config').style.display =
                e.target.value === 'static' ? 'block' : 'none';
        });
    });

    await loadInterfaces();
}

async function loadInterfaces() {
    const container = document.getElementById('interfaces-container');
    if (!container) return;

    try {
        const response = await apiGet('/network/interfaces');
        const interfaces = response.interfaces || [];

        // Resolve the managed LAN interface + the full locked set (if provisioning is enabled)
        try {
            const prov = await apiGet('/provisioning/managed-lan');
            managedIface = prov?.enabled ? prov.interface : null;
            lockedIfaces = new Set(prov?.enabled ? (prov.locked_interfaces || []) : []);
        } catch (e) {
            managedIface = null;
            lockedIfaces = new Set();
        }

        // Resolve WAN edit-protection state (mirror of managed-LAN resolution)
        try {
            const sys = await apiGet('/settings/system');
            wanProtectionEnabled = !!sys?.wan_protection_enabled;
        } catch (e) {
            wanProtectionEnabled = false;
        }

        if (interfaces.length === 0) {
            container.innerHTML = emptyState('ti-network-off', t('network.noInterfaces'));
            return;
        }

        // Natural numeric sort: eth1 < eth2 < eth10 (not lexicographic)
        interfaces.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
        container.innerHTML = interfaces.map(iface => renderInterfaceRow(iface)).join('');

        // Row click: toggle collapse manually so stopPropagation on child buttons works reliably
        container.querySelectorAll('.iface-row').forEach(row => {
            const collapseEl = document.getElementById(row.dataset.collapseTarget);
            if (!collapseEl) return;
            row.addEventListener('click', () => {
                bootstrap.Collapse.getOrCreateInstance(collapseEl, { toggle: false }).toggle();
            });
            collapseEl.addEventListener('show.bs.collapse', () => {
                container.querySelector(`.iface-chevron[data-iface-chevron="${collapseEl.id}"]`)?.classList.add('rotated');
            });
            collapseEl.addEventListener('hide.bs.collapse', () => {
                container.querySelector(`.iface-chevron[data-iface-chevron="${collapseEl.id}"]`)?.classList.remove('rotated');
            });
        });

        container.querySelectorAll('[data-configure-iface]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                openNetplanModal(btn.dataset.configureIface);
            });
        });

    } catch (error) {
        console.error('Error loading interfaces:', error);
        container.innerHTML = `
            <div class="text-center py-4 text-danger">
                <i class="ti ti-alert-circle" style="font-size: 2rem;"></i>
                <p class="mt-2">${t('network.loadError', { error: escapeHtml(error.message) })}</p>
            </div>
        `;
    }
}

function renderInterfaceRow(iface) {
    const isUp = iface.is_up;
    const canManage = checkPermission('settings.manage');
    const isWAN = iface.name === 'eth0';
    // WAN is read-only only when edit-protection is enabled (installer flag --protect-wan)
    const isProtected = isWAN && wanProtectionEnabled;
    const collapseId = ifaceId(iface.name);
    const secondaryCount = iface.secondary_ips?.length || 0;

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

    const statusBadge = isUp
        ? `<span class="badge bg-success-lt">${t('network.up')}</span>`
        : `<span class="badge bg-secondary-lt">${t('network.down')}</span>`;

    let netplanBadge = '';
    if (iface.netplan?.dhcp4) {
        netplanBadge = '<span class="badge bg-cyan-lt">DHCP</span>';
    } else if (iface.netplan?.addresses?.length > 0) {
        netplanBadge = `<span class="badge bg-purple-lt">${t('network.staticIp')}</span>`;
    }

    const isManaged = managedIface && iface.name === managedIface;
    // Locked by provisioning but not the managed (DHCP/NAT) one: read-only only.
    const isLockedLan = lockedIfaces.has(iface.name);
    const isLockedSecondary = isLockedLan && !isManaged;
    const wanBadge = isWAN ? '<span class="badge bg-orange-lt">WAN</span>' : '';
    // Uniform "read-only" badge for every locked interface (managed or not, WAN).
    // The managed vs locked distinction is kept only in the expanded detail note.
    const managedBadge = '';
    const speedBadge = iface.speed > 0 ? `<span class="badge bg-azure-lt">${iface.speed} Mbps</span>` : '';
    const lockBadge = (isProtected || isLockedLan) ? `<span class="badge bg-secondary-lt" title="${isManaged ? t('network.managedHint') : ''}"><i class="ti ti-lock me-1"></i>${t('common.readOnly')}</span>` : '';

    const secondaryBadge = secondaryCount > 0
        ? `<span class="badge bg-secondary-lt ms-1" title="${t('network.secondaryIps', { count: secondaryCount })}">+${secondaryCount}</span>`
        : '';

    const ipDisplay = iface.ipv4
        ? `<code>${iface.ipv4}</code>${secondaryBadge}`
        : `<span class="text-muted">—</span>`;

    // Managed/locked LAN interfaces are read-only too: their IP is assigned externally.
    const canConfigure = canManage && !iface.name.startsWith('docker') && !iface.name.startsWith('veth') && !isProtected && !isLockedLan;
    const configureBtn = canConfigure
        ? `<button class="btn btn-sm btn-ghost-primary" data-configure-iface="${iface.name}" title="${t('network.configureInterface')}">
               <i class="ti ti-settings"></i>
           </button>`
        : '';

    // ── Expanded section ────────────────────────────────────────────────────

    const allIps = [
        iface.ipv4 ? { label: t('network.primaryIpv4'), value: iface.ipv4 } : null,
        ...(iface.secondary_ips || []).map((ip, i) => ({ label: t('network.secondaryIpv4', { index: i + 1 }), value: ip })),
        iface.ipv6 ? { label: 'IPv6', value: iface.ipv6 } : null,
    ].filter(Boolean);

    const ipRows = allIps.map(ip => `
        <tr>
            <td class="text-muted small" style="width:160px">${ip.label}</td>
            <td><code class="small">${ip.value}</code></td>
        </tr>`).join('');

    const macRow = (iface.mac && iface.mac !== '00:00:00:00:00:00') ? `
        <tr>
            <td class="text-muted small">MAC</td>
            <td><code class="small">${iface.mac}</code></td>
        </tr>` : '';

    const mtuRow = iface.mtu > 0 ? `
        <tr>
            <td class="text-muted small">MTU</td>
            <td class="small">${iface.mtu}</td>
        </tr>` : '';

    const errorsRow = (iface.errors_in > 0 || iface.errors_out > 0) ? `
        <tr>
            <td class="text-muted small">${t('network.errors')}</td>
            <td>
                <span class="badge bg-danger-lt">
                    <i class="ti ti-alert-triangle me-1"></i>${iface.errors_in} in / ${iface.errors_out} out
                </span>
            </td>
        </tr>` : '';

    const wanNote = isProtected ? `
        <div class="mt-3 text-muted small">
            <i class="ti ti-lock me-1"></i>${t('network.wanReadOnly')}
        </div>` : isManaged ? `
        <div class="mt-3 text-muted small">
            <i class="ti ti-lock me-1"></i>${t('network.managedNote')}
        </div>` : isLockedSecondary ? `
        <div class="mt-3 text-muted small">
            <i class="ti ti-lock me-1"></i>${t('network.lockedNote')}
        </div>` : '';

    return `
        <div class="card mb-2">
            <div class="iface-row" data-collapse-target="${collapseId}">

                <div class="avatar avatar-sm bg-primary-lt flex-shrink-0">
                    <i class="ti ${icon}"></i>
                </div>

                <div class="d-flex flex-wrap align-items-center gap-1">
                    <span class="fw-semibold me-1">${iface.name}</span>
                    ${statusBadge}
                    ${netplanBadge}
                    ${speedBadge}
                    ${wanBadge}
                    ${managedBadge}
                    ${lockBadge}
                </div>

                <div class="d-flex align-items-center">
                    ${ipDisplay}
                </div>

                <div class="iface-col-traffic d-flex flex-column gap-1 small text-muted">
                    <span>
                        <i class="ti ti-arrow-down text-success me-1"></i>
                        <strong class="text-body">${formatBytes(iface.bytes_recv)}</strong>
                    </span>
                    <span>
                        <i class="ti ti-arrow-up text-primary me-1"></i>
                        <strong class="text-body">${formatBytes(iface.bytes_sent)}</strong>
                    </span>
                </div>

                <div class="d-flex align-items-center justify-content-end gap-1">
                    ${configureBtn}
                    <i class="ti ti-chevron-down iface-chevron text-muted" data-iface-chevron="${collapseId}"></i>
                </div>
            </div>

            <div class="collapse" id="${collapseId}">
                <div class="border-top px-3 py-3">
                    <div class="row g-4">
                        <div class="col-md-6">
                            <div class="small text-muted fw-semibold text-uppercase mb-2">${t('network.addresses')}</div>
                            <table class="table table-sm table-borderless mb-0">
                                <tbody>
                                    ${ipRows}
                                    ${macRow}
                                    ${mtuRow}
                                    ${errorsRow}
                                </tbody>
                            </table>
                        </div>
                        <div class="col-md-6">
                            <div class="small text-muted fw-semibold text-uppercase mb-2">${t('network.traffic')}</div>
                            <table class="table table-sm table-borderless mb-0">
                                <tbody>
                                    <tr>
                                        <td style="width:140px">
                                            <i class="ti ti-arrow-down text-success me-1"></i>
                                            <span class="text-muted small">${t('network.received')}</span>
                                        </td>
                                        <td>
                                            <strong>${formatBytes(iface.bytes_recv)}</strong>
                                            <span class="text-muted small ms-2">${iface.packets_recv.toLocaleString()} pkt</span>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td>
                                            <i class="ti ti-arrow-up text-primary me-1"></i>
                                            <span class="text-muted small">${t('network.sent')}</span>
                                        </td>
                                        <td>
                                            <strong>${formatBytes(iface.bytes_sent)}</strong>
                                            <span class="text-muted small ms-2">${iface.packets_sent.toLocaleString()} pkt</span>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                            ${wanNote}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

async function openNetplanModal(interfaceName) {
    document.getElementById('netplan-interface').value = interfaceName;
    document.getElementById('modal-iface-name').textContent = interfaceName;

    document.querySelector('input[name="netplan-mode"][value="dhcp"]').checked = true;
    document.querySelector('input[name="netplan-mode"][value="static"]').checked = false;
    document.getElementById('static-config').style.display = 'none';
    document.getElementById('netplan-address').value = '';
    document.getElementById('netplan-gateway').value = '';
    document.getElementById('netplan-dns').value = '';
    document.getElementById('netplan-mtu').value = '';

    try {
        const response = await apiGet(`/network/interfaces/${interfaceName}/config`);
        if (response.config) {
            const config = response.config;
            const isDhcp = config.dhcp4;
            document.querySelector(`input[name="netplan-mode"][value="${isDhcp ? 'dhcp' : 'static'}"]`).checked = true;
            document.getElementById('static-config').style.display = isDhcp ? 'none' : 'block';
            if (config.addresses?.length > 0) document.getElementById('netplan-address').value = config.addresses[0];
            if (config.gateway4) document.getElementById('netplan-gateway').value = config.gateway4;
            if (config.dns_servers?.length > 0) document.getElementById('netplan-dns').value = config.dns_servers.join(', ');
            if (config.mtu) document.getElementById('netplan-mtu').value = config.mtu;
        }
    } catch (error) {
        // No existing config, start fresh
    }

    new bootstrap.Modal(document.getElementById('modal-netplan')).show();
}

async function saveNetplanConfig() {
    const interfaceName = document.getElementById('netplan-interface').value;
    const dhcp4 = document.querySelector('input[name="netplan-mode"]:checked')?.value === 'dhcp';

    const data = { interface: interfaceName, dhcp4 };

    if (!dhcp4) {
        const address = document.getElementById('netplan-address').value.trim();
        const gateway = document.getElementById('netplan-gateway').value.trim();
        const dns = document.getElementById('netplan-dns').value.trim();

        if (!address) { showToast(t('network.enterIp'), 'error'); return; }
        if (!isValidCIDR(address)) { showToast(t('network.invalidIp'), 'error'); return; }
        if (gateway && !isValidIP(gateway)) { showToast(t('network.invalidGateway'), 'error'); return; }

        const dnsArr = dns ? dns.split(',').map(s => s.trim()).filter(Boolean) : [];
        for (const d of dnsArr) {
            if (!isValidIP(d)) { showToast(t('network.invalidDns', { dns: d }), 'error'); return; }
        }

        data.addresses = [address];
        if (gateway) data.gateway = gateway;
        if (dnsArr.length > 0) data.dns_servers = dnsArr;
    }

    const mtu = document.getElementById('netplan-mtu').value;
    if (mtu) data.mtu = parseInt(mtu);

    try {
        await apiPost(`/network/interfaces/${interfaceName}/config`, data);
        showToast(t('network.configSaved'), 'success');
        bootstrap.Modal.getInstance(document.getElementById('modal-netplan'))?.hide();
        await loadInterfaces();
    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
    }
}

async function applyNetplan() {
    const confirmed = await confirmDialog(
        t('network.applyNetworkConfig'),
        t('network.applyNetworkConfirm'),
        t('common.apply'),
        'btn-warning'
    );
    if (!confirmed) return;

    try {
        await apiPost('/network/netplan/apply', {});
        showToast(t('network.configApplied'), 'success');
        await loadInterfaces();
    } catch (error) {
        showToast(t('network.applyError', { error: error.message }), 'error');
    }
}

/**
 * MADMIN - Firewall View / gateway access matrix
 *
 * LAN-to-LAN reachability matrix built on GW_EXCEPTIONS ACCEPT rules.
 */

import { apiGet, apiPost, apiDelete } from '../../api.js';
import { showToast, escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';
import { openModal } from '../../components/modal.js';
import { GW_VIRTUAL_PREFIXES, GW_WAN_IFACE } from './constants.js';

/**
 * Open the Gateway Access modal and render the badge matrix.
 */
export function openGatewayModal() {
    openModal({
        title: t('firewall.gatewayAccess'),
        size: 'lg',
        body: `
            <div class="alert alert-info mb-3">
                <div class="d-flex">
                    <i class="ti ti-info-circle me-2 mt-1 flex-shrink-0"></i>
                    <div>
                        ${t('firewall.isolationInfo')}
                        <br><small class="text-muted mt-1 d-block">
                            ${t('firewall.isolationNote')}
                        </small>
                    </div>
                </div>
            </div>
            <div id="gw-matrix-content">
                <div class="text-center py-4">
                    <div class="spinner-border text-primary"></div>
                </div>
            </div>
        `,
        footer: `<button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.close')}</button>`,
    });

    renderGatewayMatrix();
}

/**
 * Load interfaces and current GW_EXCEPTIONS rules, then render the badge matrix.
 */
async function renderGatewayMatrix() {
    const content = document.getElementById('gw-matrix-content');
    if (!content) return;

    try {
        const [ifaceData, exceptionsData] = await Promise.all([
            apiGet('/network/interfaces'),
            apiGet('/firewall/rules?chain=GW_EXCEPTIONS')
        ]);

        const lanIfaces = (ifaceData.interfaces || []).filter(i =>
            i.ipv4 &&
            !GW_VIRTUAL_PREFIXES.some(p => i.name.startsWith(p)) &&
            i.name !== GW_WAN_IFACE
        );

        const exceptions = exceptionsData || [];

        if (lanIfaces.length < 2) {
            content.innerHTML = `
                <div class="empty">
                    <p class="empty-title">${t('firewall.lessThan2Lans')}</p>
                    <p class="empty-subtitle text-muted">${t('firewall.add2LansHint')}</p>
                </div>`;
            return;
        }

        content.innerHTML = `
            <table class="table table-sm table-hover">
                <thead>
                    <tr>
                        <th style="width:200px">${t('firewall.sourceNetwork')}</th>
                        <th>${t('firewall.canReach')}</th>
                    </tr>
                </thead>
                <tbody>
                    ${lanIfaces.map(src => {
                        const targets = lanIfaces.filter(dst => dst.name !== src.name);
                        const badges = targets.map(dst => {
                            const existing = exceptions.find(r =>
                                r.in_interface === src.name &&
                                r.destination === dst.ipv4
                            );
                            const active = !!existing;
                            return `<span
                                class="badge ${active ? 'bg-success-lt' : 'bg-secondary-lt'} me-1 mb-1 gw-badge"
                                style="cursor:pointer;font-size:.8rem;padding:.4em .7em"
                                data-src="${escapeHtml(src.name)}"
                                data-dst="${escapeHtml(dst.ipv4)}"
                                data-dst-name="${escapeHtml(dst.name)}"
                                data-rule-id="${existing ? existing.id : ''}"
                                data-active="${active}"
                                title="${active ? t('firewall.clickToBlock') : t('firewall.clickToEnable')}"
                            >${escapeHtml(dst.name)} <small>${escapeHtml(dst.ipv4)}</small></span>`;
                        }).join('');

                        return `<tr>
                            <td class="align-middle">
                                <strong>${escapeHtml(src.name)}</strong>
                                <br><small class="text-muted">${escapeHtml(src.ipv4)}</small>
                            </td>
                            <td class="align-middle">${badges}</td>
                        </tr>`;
                    }).join('')}
                </tbody>
            </table>
            <small class="text-muted">
                ${t('firewall.legendEnabled')} &nbsp;&nbsp; ${t('firewall.legendBlocked')}
            </small>`;

        // Bind badge clicks
        content.querySelectorAll('.gw-badge').forEach(badge => {
            badge.addEventListener('click', handleGatewayBadgeToggle);
        });

    } catch (error) {
        content.innerHTML = `<div class="alert alert-danger">${t('firewall.gatewayLoadError', { error: escapeHtml(error.message) })}</div>`;
    }
}

/**
 * Toggle a gateway exception on badge click.
 */
async function handleGatewayBadgeToggle(e) {
    const badge = e.currentTarget;
    const src = badge.dataset.src;
    const dst = badge.dataset.dst;
    const dstName = badge.dataset.dstName;
    const ruleId = badge.dataset.ruleId;
    const active = badge.dataset.active === 'true';

    badge.style.opacity = '0.5';
    badge.style.pointerEvents = 'none';

    try {
        if (active) {
            await apiDelete(`/firewall/rules/${ruleId}`);
            badge.classList.remove('bg-success-lt');
            badge.classList.add('bg-secondary-lt');
            badge.dataset.active = 'false';
            badge.dataset.ruleId = '';
            badge.title = t('firewall.clickToEnable');
        } else {
            const result = await apiPost('/firewall/rules', {
                chain: 'GW_EXCEPTIONS',
                table_name: 'filter',
                action: 'ACCEPT',
                in_interface: src,
                destination: dst,
                comment: `${src} → ${dstName} gateway`
            });
            badge.classList.remove('bg-secondary-lt');
            badge.classList.add('bg-success-lt');
            badge.dataset.active = 'true';
            badge.dataset.ruleId = result.id;
            badge.title = t('firewall.clickToBlock');
        }
    } catch (error) {
        showToast(t('common.errorPrefix') + error.message, 'error');
    } finally {
        badge.style.opacity = '';
        badge.style.pointerEvents = '';
    }
}

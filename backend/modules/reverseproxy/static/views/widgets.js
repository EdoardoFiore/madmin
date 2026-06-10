/**
 * Reverse Proxy - Dashboard widget
 *
 * Shows nginx service status and active host count.
 * Contract: export { widgets: { [widget_id]: { render(), load? } } }
 */
import { apiGet } from '/static/js/api.js';
import { t, loadModuleTranslations } from '/static/js/i18n.js';

// Load translations at module import time so render() can use t()
await loadModuleTranslations('reverseproxy');

const MODULE_API = '/modules/reverseproxy';

export const widgets = {
    reverseproxy_revproxy_status: {
        render() {
            return `
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">
                            <i class="ti ti-network me-2"></i>Reverse Proxy
                        </h3>
                        <div class="card-actions">
                            <a href="#reverseproxy" class="btn btn-sm btn-outline-primary">
                                <i class="ti ti-external-link me-1"></i>${t('reverseproxy.manage')}
                            </a>
                        </div>
                    </div>
                    <div class="card-body p-0" id="revproxy-widget-body"></div>
                </div>
            `;
        },

        async load() {
            const container = document.getElementById('revproxy-widget-body');
            if (!container) return;

            try {
                const [status, hosts] = await Promise.all([
                    apiGet(`${MODULE_API}/service/status`).catch(() => null),
                    apiGet(`${MODULE_API}/hosts`).catch(() => []),
                ]);

                const activeCount = (hosts || []).filter(h => h.enabled).length;
                const totalCount = (hosts || []).length;

                let statusBadge;
                if (!status) {
                    statusBadge = `<span class="badge bg-secondary-lt">–</span>`;
                } else if (status.blocked) {
                    statusBadge = `<span class="badge bg-danger-lt">${t('reverseproxy.blockedTitle')}</span>`;
                } else if (status.active) {
                    statusBadge = `<span class="badge bg-green-lt">${t('reverseproxy.serviceActive')}</span>`;
                } else {
                    statusBadge = `<span class="badge bg-warning-lt">${t('reverseproxy.serviceInactive')}</span>`;
                }

                container.innerHTML = `
                    <div class="p-3">
                        <div class="row g-2">
                            <div class="col-6">
                                <div class="text-center">
                                    <div class="fw-bold fs-3">${activeCount}</div>
                                    <div class="text-muted small">${t('reverseproxy.online')}</div>
                                </div>
                            </div>
                            <div class="col-6">
                                <div class="text-center">
                                    <div class="fw-bold fs-3">${totalCount}</div>
                                    <div class="text-muted small">${t('reverseproxy.tabHosts')}</div>
                                </div>
                            </div>
                        </div>
                        <div class="mt-2 text-center">
                            ${statusBadge}
                        </div>
                    </div>
                `;
            } catch (e) {
                console.error('revproxy widget load error:', e);
                container.innerHTML = `
                    <div class="text-muted text-center py-3 p-3">
                        <i class="ti ti-alert-circle"></i> ${t('common.errorPrefix')}${e.message}
                    </div>
                `;
            }
        },
    },
};

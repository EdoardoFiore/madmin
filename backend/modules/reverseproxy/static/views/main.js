/**
 * Reverse Proxy Module - Entry view
 *
 * Two tabs: Proxy Hosts and Access Lists. Loads module translations,
 * shows a banner if the module is blocked by a port conflict.
 */
import { apiGet } from '/static/js/api.js';
import { showToast } from '/static/js/utils.js';
import { checkPermission } from '/static/js/app.js';
import { t, loadModuleTranslations } from '/static/js/i18n.js';

import { renderHostsTab } from './hostsList.js';
import { renderAccessListsTab } from './accessLists.js';
import { renderCertsTab } from './certsList.js';

const MODULE_API = '/modules/reverseproxy';

export async function render(container, params) {
    await loadModuleTranslations('reverseproxy');

    const perms = {
        view: checkPermission('reverseproxy.view'),
        manage: checkPermission('reverseproxy.manage'),
        accessLists: checkPermission('reverseproxy.access_lists'),
        certs: checkPermission('reverseproxy.certs'),
    };

    const activeTab = params && params[0] === 'access-lists' ? 'access-lists'
        : params && params[0] === 'certs' ? 'certs'
        : 'hosts';

    container.innerHTML = `
        <div id="revproxy-block-banner" class="mb-3" style="display:none;"></div>

        <div class="card">
            <div class="card-header">
                <ul class="nav nav-tabs card-header-tabs" role="tablist">
                    <li class="nav-item">
                        <button type="button" class="nav-link ${activeTab === 'hosts' ? 'active' : ''}"
                                data-bs-toggle="tab" data-bs-target="#revproxy-pane-hosts">
                            <i class="ti ti-server me-2"></i>${t('reverseproxy.tabHosts')}
                        </button>
                    </li>
                    <li class="nav-item">
                        <button type="button" class="nav-link ${activeTab === 'access-lists' ? 'active' : ''}"
                                data-bs-toggle="tab" data-bs-target="#revproxy-pane-acls">
                            <i class="ti ti-lock me-2"></i>${t('reverseproxy.tabAccessLists')}
                        </button>
                    </li>
                    <li class="nav-item">
                        <button type="button" class="nav-link ${activeTab === 'certs' ? 'active' : ''}"
                                data-bs-toggle="tab" data-bs-target="#revproxy-pane-certs">
                            <i class="ti ti-shield me-2"></i>${t('reverseproxy.tabCerts')}
                        </button>
                    </li>
                </ul>
                <div class="card-options">
                    <span id="revproxy-service-badge" class="badge bg-secondary-lt">…</span>
                </div>
            </div>
            <div class="tab-content">
                <div class="tab-pane fade ${activeTab === 'hosts' ? 'show active' : ''}" id="revproxy-pane-hosts">
                    <div id="revproxy-hosts-body"></div>
                </div>
                <div class="tab-pane fade ${activeTab === 'access-lists' ? 'show active' : ''}" id="revproxy-pane-acls">
                    <div id="revproxy-acls-body"></div>
                </div>
                <div class="tab-pane fade ${activeTab === 'certs' ? 'show active' : ''}" id="revproxy-pane-certs">
                    <div id="revproxy-certs-body"></div>
                </div>
            </div>
        </div>
    `;

    await refreshServiceStatus();
    await renderHostsTab(document.getElementById('revproxy-hosts-body'), perms);
    await renderAccessListsTab(document.getElementById('revproxy-acls-body'), perms);
    await renderCertsTab(document.getElementById('revproxy-certs-body'), perms);

    // Sync route hash when user switches tab manually
    container.querySelectorAll('button[data-bs-toggle="tab"]').forEach(btn => {
        btn.addEventListener('shown.bs.tab', (e) => {
            const target = e.target.getAttribute('data-bs-target');
            if (target === '#revproxy-pane-acls') {
                history.replaceState(null, '', '#reverseproxy/access-lists');
            } else if (target === '#revproxy-pane-certs') {
                history.replaceState(null, '', '#reverseproxy/certs');
            } else {
                history.replaceState(null, '', '#reverseproxy');
            }
        });
    });
}

async function refreshServiceStatus() {
    const badge = document.getElementById('revproxy-service-badge');
    const banner = document.getElementById('revproxy-block-banner');
    try {
        const s = await apiGet(`${MODULE_API}/service/status`);
        if (s.blocked) {
            badge.className = 'badge bg-danger-lt';
            badge.textContent = t('reverseproxy.blockedTitle');
            banner.style.display = '';
            banner.innerHTML = `
                <div class="alert alert-danger mb-0">
                    <h4 class="mb-1"><i class="ti ti-alert-triangle me-2"></i>${t('reverseproxy.blockedTitle')}</h4>
                    <div class="small">${escapeText(s.block_reason || '')}</div>
                    <div class="small text-muted mt-1">${t('reverseproxy.blockedHint')}</div>
                </div>`;
        } else if (s.active) {
            badge.className = 'badge bg-success-lt';
            badge.textContent = t('reverseproxy.serviceActive');
            banner.style.display = 'none';
        } else {
            badge.className = 'badge bg-warning-lt';
            badge.textContent = t('reverseproxy.serviceInactive');
            banner.style.display = 'none';
        }
    } catch {
        badge.className = 'badge bg-secondary-lt';
        badge.textContent = '–';
    }
}

function escapeText(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

/**
 * Reverse Proxy - SSL/TLS Certificates tab
 */
import { apiGet, apiPost, apiDelete } from '/static/js/api.js';
import { showToast, confirmDialog, escapeHtml, emptyState, formatDate } from '/static/js/utils.js';
import { t } from '/static/js/i18n.js';

const MODULE_API = '/modules/reverseproxy';
let _perms = null;
let _hosts = [];

export async function renderCertsTab(container, perms) {
    _perms = perms;
    container.innerHTML = `<div id="revproxy-certs-table"></div>`;
    await reloadCerts();
}

async function reloadCerts() {
    try {
        _hosts = await apiGet(`${MODULE_API}/hosts`);
        renderTable();
    } catch (err) {
        const root = document.getElementById('revproxy-certs-table');
        if (root) root.innerHTML = `<div class="alert alert-danger m-3">${escapeHtml(err.message)}</div>`;
    }
}

function renderTable() {
    const root = document.getElementById('revproxy-certs-table');
    if (!root) return;

    const certsHosts = _hosts.filter(h => h.certificate);

    if (!certsHosts.length) {
        root.innerHTML = `<div class="p-3">${emptyState('ti-shield-off', t('reverseproxy.noCertificates'), t('reverseproxy.noCertificatesHint'))}</div>`;
        return;
    }

    root.innerHTML = `<table class="table table-vcenter card-table table-hover">
        <thead><tr>
            <th>${t('reverseproxy.domainNames')}</th>
            <th>${t('reverseproxy.tls')}</th>
            <th>${t('reverseproxy.certIssuedAt')}</th>
            <th>${t('reverseproxy.certExpiresAt')}</th>
            <th>${t('reverseproxy.status')}</th>
            <th class="w-1"></th>
        </tr></thead>
        <tbody>${certsHosts.map(renderCertRow).join('')}</tbody>
    </table>`;

    root.querySelectorAll('[data-cert-action]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const host = _hosts.find(h => h.id === btn.dataset.id);
            if (!host) return;
            if (btn.dataset.certAction === 'renew') renewCert(host);
            else if (btn.dataset.certAction === 'revoke') revokeCert(host);
        });
    });
}

function renderCertRow(h) {
    const cert = h.certificate;
    const domains = (h.domains || []).map(d => escapeHtml(d.domain)).join(', ') || '–';

    const providerBadge = cert.provider === 'letsencrypt'
        ? `<span class="badge bg-blue-lt">Let's Encrypt</span>`
        : `<span class="badge bg-secondary-lt">Custom</span>`;

    const issued = cert.issued_at ? formatDate(cert.issued_at) : '–';

    const expiryDate = cert.expires_at ? new Date(cert.expires_at) : null;
    const expiry = expiryDate ? expiryDate.toLocaleDateString() : '–';
    const now = Date.now();
    const expiryMs = expiryDate ? expiryDate.getTime() : null;
    const isExpired = expiryMs && expiryMs < now;
    const isExpiring = expiryMs && !isExpired && expiryMs < now + 30 * 86400000;

    const statusBadge = !expiryMs
        ? `<span class="badge bg-secondary-lt">–</span>`
        : isExpired
            ? `<span class="badge bg-danger-lt">${t('reverseproxy.certExpired')}</span>`
            : isExpiring
                ? `<span class="badge bg-warning-lt">${t('reverseproxy.certExpiringSoon')}</span>`
                : `<span class="badge bg-success-lt">${t('reverseproxy.certValid')}</span>`;

    const actions = _perms.certs ? `
        <div class="dropdown">
            <button type="button" class="btn btn-ghost-secondary btn-icon" data-bs-toggle="dropdown" data-bs-strategy="fixed" aria-expanded="false">
                <i class="ti ti-dots-vertical"></i>
            </button>
            <ul class="dropdown-menu dropdown-menu-end">
                <li><a href="#" class="dropdown-item" data-cert-action="renew" data-id="${h.id}">
                    <i class="ti ti-refresh me-2"></i>${t('reverseproxy.certRenew')}</a></li>
                <li><a href="#" class="dropdown-item text-danger" data-cert-action="revoke" data-id="${h.id}">
                    <i class="ti ti-shield-off me-2"></i>${t('reverseproxy.certRevoke')}</a></li>
            </ul>
        </div>` : '';

    return `<tr>
        <td>${domains}</td>
        <td>${providerBadge}</td>
        <td>${issued}</td>
        <td>${expiry}</td>
        <td>${statusBadge}</td>
        <td>${actions}</td>
    </tr>`;
}

async function renewCert(host) {
    try {
        showToast(t('reverseproxy.loading'), 'info');
        await apiPost(`${MODULE_API}/hosts/${host.id}/certificate`, {});
        showToast(t('reverseproxy.certRequested'), 'success');
        await reloadCerts();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function revokeCert(host) {
    const ok = await confirmDialog(t('reverseproxy.certRevoke'), '', t('reverseproxy.delete'), 'btn-danger');
    if (!ok) return;
    try {
        await apiDelete(`${MODULE_API}/hosts/${host.id}/certificate`);
        showToast(t('reverseproxy.certRevoked'), 'success');
        await reloadCerts();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

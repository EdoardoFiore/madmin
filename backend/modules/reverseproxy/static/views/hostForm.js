/**
 * Reverse Proxy - Proxy Host create/edit modal
 */
import { apiGet, apiPost, apiPatch, apiDelete } from '/static/js/api.js';
import { showToast, confirmDialog, escapeHtml } from '/static/js/utils.js';
import { t } from '/static/js/i18n.js';

const MODULE_API = '/modules/reverseproxy';
let _domains = [];
let _forceHttps = false;

export async function openHostForm({ host = null, onSaved, perms = {} }) {
    const isEdit = !!host;
    _domains = isEdit ? (host.domains || []).map(d => d.domain) : [];
    _forceHttps = !!host?.force_https;

    // Local cert state — updated after in-modal cert operations
    let _cert = host?.certificate || null;

    // Always fetch fresh access lists so newly-created ones are immediately available
    let acls = [];
    try { acls = await apiGet(`${MODULE_API}/access_lists`); } catch (_) {}

    const modalId = 'revproxy-host-modal';
    document.getElementById(modalId)?.remove();

    const modalEl = document.createElement('div');
    modalEl.id = modalId;
    modalEl.className = 'modal fade';
    modalEl.tabIndex = -1;
    modalEl.innerHTML = `
        <div class="modal-dialog modal-lg">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">${isEdit ? t('reverseproxy.editProxyHostTitle') : t('reverseproxy.newProxyHostTitle')}</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <ul class="nav nav-tabs mb-3" role="tablist">
                        <li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#rphf-details">${t('reverseproxy.tabDetails')}</button></li>
                        <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#rphf-ssl">${t('reverseproxy.tabSsl')}</button></li>
                        <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#rphf-advanced">${t('reverseproxy.tabAdvanced')}</button></li>
                    </ul>
                    <div class="tab-content">
                        <div class="tab-pane fade show active" id="rphf-details">
                            <div class="mb-3">
                                <label class="form-label">${t('reverseproxy.domainNames')}</label>
                                <div id="rphf-domains-tags" class="form-control" style="min-height:42px; cursor:text; display:flex; flex-wrap:wrap; gap:4px; align-items:center;"></div>
                                <small class="form-hint">${t('reverseproxy.domainNamesHint')}</small>
                            </div>
                            <div class="row">
                                <div class="col-3 mb-3">
                                    <label class="form-label">${t('reverseproxy.forwardScheme')}</label>
                                    <select class="form-select" id="rphf-scheme">
                                        <option value="http" ${host?.forward_scheme === 'http' ? 'selected' : ''}>http</option>
                                        <option value="https" ${host?.forward_scheme === 'https' ? 'selected' : ''}>https</option>
                                    </select>
                                </div>
                                <div class="col-6 mb-3">
                                    <label class="form-label">${t('reverseproxy.forwardHost')}</label>
                                    <input type="text" class="form-control" id="rphf-host" placeholder="192.168.1.10" value="${escapeHtml(host?.forward_host || '')}">
                                </div>
                                <div class="col-3 mb-3">
                                    <label class="form-label">${t('reverseproxy.forwardPort')}</label>
                                    <input type="number" min="1" max="65535" class="form-control" id="rphf-port" value="${host?.forward_port || 8080}">
                                </div>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">${t('reverseproxy.accessList')}</label>
                                <select class="form-select" id="rphf-acl">
                                    <option value="">${t('reverseproxy.publiclyAccessible')}</option>
                                    ${acls.map(a => `<option value="${a.id}" ${host?.access_list_id === a.id ? 'selected' : ''}>${escapeHtml(a.name)}</option>`).join('')}
                                </select>
                            </div>
                            <div class="row">
                                <div class="col-md-6">
                                    <label class="form-check form-switch">
                                        <input class="form-check-input" type="checkbox" id="rphf-http2" ${host?.http2_support !== false ? 'checked' : ''}>
                                        <span class="form-check-label">${t('reverseproxy.http2Support')}</span>
                                    </label>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-check form-switch">
                                        <input class="form-check-input" type="checkbox" id="rphf-block-exploits" ${host?.block_exploits !== false ? 'checked' : ''}>
                                        <span class="form-check-label">${t('reverseproxy.blockExploits')}</span>
                                    </label>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-check form-switch">
                                        <input class="form-check-input" type="checkbox" id="rphf-websockets" ${host?.websockets_support ? 'checked' : ''}>
                                        <span class="form-check-label">${t('reverseproxy.websocketsSupport')}</span>
                                    </label>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-check form-switch">
                                        <input class="form-check-input" type="checkbox" id="rphf-caching" ${host?.caching_enabled ? 'checked' : ''}>
                                        <span class="form-check-label">${t('reverseproxy.cachingEnabled')}</span>
                                    </label>
                                </div>
                            </div>
                        </div>
                        <div class="tab-pane fade" id="rphf-ssl"></div>
                        <div class="tab-pane fade" id="rphf-advanced">
                            <div class="mb-3">
                                <label class="form-label">${t('reverseproxy.customNginxConfig')}</label>
                                <textarea class="form-control font-monospace" id="rphf-custom" rows="10"
                                    placeholder="${t('reverseproxy.customNginxPlaceholder')}">${escapeHtml(host?.custom_nginx_config || '')}</textarea>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-outline-secondary" data-bs-dismiss="modal">${t('reverseproxy.cancel')}</button>
                    <button class="btn btn-primary" id="rphf-save">${isEdit ? t('reverseproxy.saveChanges') : t('reverseproxy.create')}</button>
                </div>
            </div>
        </div>`;
    document.body.appendChild(modalEl);

    renderDomainTags();
    renderSslPane();

    const modal = new bootstrap.Modal(modalEl);
    modal.show();
    modalEl.addEventListener('hidden.bs.modal', () => modalEl.remove());

    modalEl.querySelector('#rphf-save').addEventListener('click', async () => {
        const ok = await saveHost(host, onSaved);
        if (ok) modal.hide();
    });

    // -----------------------------------------------------------------------
    // SSL tab
    // -----------------------------------------------------------------------

    function renderSslPane() {
        const pane = modalEl.querySelector('#rphf-ssl');
        const hasCerts = perms.certs;

        if (!isEdit) {
            pane.innerHTML = `
                <div class="alert alert-info d-flex gap-2 align-items-start mb-3">
                    <i class="ti ti-info-circle mt-1"></i>
                    <div>${t('reverseproxy.sslSaveFirst')}</div>
                </div>
                <label class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" id="rphf-force-https" disabled>
                    <span class="form-check-label text-muted">${t('reverseproxy.forceHttps')}
                        <span class="badge bg-secondary-lt ms-1">${t('reverseproxy.requiresCert')}</span>
                    </span>
                </label>`;
            return;
        }

        if (_cert) {
            const expiryDate = _cert.expires_at ? new Date(_cert.expires_at) : null;
            const expiry = expiryDate ? expiryDate.toLocaleDateString() : '–';
            const now = Date.now();
            const expiryMs = expiryDate ? expiryDate.getTime() : null;
            const isExpired = expiryMs && expiryMs < now;
            const isExpiring = expiryMs && expiryMs < now + 30 * 86400000;

            const statusBadge = !expiryMs ? ''
                : isExpired ? `<span class="badge bg-danger-lt ms-1">${t('reverseproxy.certExpired')}</span>`
                : isExpiring ? `<span class="badge bg-warning-lt ms-1">${t('reverseproxy.certExpiringSoon')}</span>`
                : `<span class="badge bg-success-lt ms-1">${t('reverseproxy.certValid')}</span>`;

            const providerLabel = _cert.provider === 'letsencrypt' ? "Let's Encrypt" : 'Custom';
            const providerBadge = `<span class="badge bg-blue-lt">${providerLabel}</span>`;

            pane.innerHTML = `
                <div class="mb-3 p-3 rounded border border-success-subtle bg-success-lt d-flex align-items-start gap-3">
                    <i class="ti ti-shield-check text-success mt-1" style="font-size:1.5rem;"></i>
                    <div>
                        <div class="d-flex align-items-center gap-2 mb-1">
                            ${providerBadge}${statusBadge}
                        </div>
                        <div class="text-muted small">${t('reverseproxy.certExpiresAt')}: <strong>${expiry}</strong></div>
                    </div>
                </div>
                <label class="form-check form-switch mb-3">
                    <input class="form-check-input" type="checkbox" id="rphf-force-https" ${_forceHttps ? 'checked' : ''}>
                    <span class="form-check-label">${t('reverseproxy.forceHttps')}</span>
                </label>
                ${hasCerts ? `
                <div class="d-flex gap-2">
                    <button class="btn btn-outline-primary btn-sm" id="rphf-cert-renew">
                        <i class="ti ti-refresh me-1"></i>${t('reverseproxy.certRenew')}
                    </button>
                    <button class="btn btn-outline-danger btn-sm" id="rphf-cert-revoke">
                        <i class="ti ti-shield-off me-1"></i>${t('reverseproxy.certRevoke')}
                    </button>
                </div>` : ''}`;

            pane.querySelector('#rphf-force-https')?.addEventListener('change', e => { _forceHttps = e.target.checked; });
            pane.querySelector('#rphf-cert-renew')?.addEventListener('click', () => doIssueCert(true));
            pane.querySelector('#rphf-cert-revoke')?.addEventListener('click', doRevokeCert);
        } else {
            pane.innerHTML = `
                <div class="mb-3 p-3 rounded border bg-secondary-lt d-flex align-items-start gap-3">
                    <i class="ti ti-shield-off text-muted mt-1" style="font-size:1.5rem;"></i>
                    <div>
                        <div class="fw-medium text-muted">${t('reverseproxy.tlsNone')}</div>
                        <div class="text-muted small">${t('reverseproxy.sslNocert')}</div>
                    </div>
                </div>
                <label class="form-check form-switch mb-3">
                    <input class="form-check-input" type="checkbox" id="rphf-force-https" disabled>
                    <span class="form-check-label text-muted">${t('reverseproxy.forceHttps')}
                        <span class="badge bg-secondary-lt ms-1">${t('reverseproxy.requiresCert')}</span>
                    </span>
                </label>
                ${hasCerts ? `
                <button class="btn btn-outline-primary btn-sm" id="rphf-cert-request">
                    <i class="ti ti-shield-check me-1"></i>${t('reverseproxy.certIssue')}
                </button>` : ''}`;

            pane.querySelector('#rphf-cert-request')?.addEventListener('click', () => doIssueCert(false));
        }
    }

    async function doIssueCert(isRenew) {
        const btnId = isRenew ? '#rphf-cert-renew' : '#rphf-cert-request';
        const btn = modalEl.querySelector(btnId);
        if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('reverseproxy.loading')}`; }
        try {
            await apiPost(`${MODULE_API}/hosts/${host.id}/certificate`, {});
            const updated = await apiGet(`${MODULE_API}/hosts/${host.id}`);
            _cert = updated.certificate || null;
            _forceHttps = false;
            renderSslPane();
            showToast(t('reverseproxy.certRequested'), 'success');
            if (typeof onSaved === 'function') onSaved();
        } catch (err) {
            showToast(err.message, 'error');
            if (btn) { btn.disabled = false; btn.innerHTML = isRenew
                ? `<i class="ti ti-refresh me-1"></i>${t('reverseproxy.certRenew')}`
                : `<i class="ti ti-shield-check me-1"></i>${t('reverseproxy.certIssue')}`; }
        }
    }

    async function doRevokeCert() {
        const ok = await confirmDialog(t('reverseproxy.certRevoke'), '', t('reverseproxy.delete'), 'btn-danger');
        if (!ok) return;
        try {
            await apiDelete(`${MODULE_API}/hosts/${host.id}/certificate`);
            _cert = null;
            _forceHttps = false;
            renderSslPane();
            showToast(t('reverseproxy.certRevoked'), 'success');
            if (typeof onSaved === 'function') onSaved();
        } catch (err) {
            showToast(err.message, 'error');
        }
    }
}

function renderDomainTags() {
    const tags = document.getElementById('rphf-domains-tags');
    tags.innerHTML = _domains.map((d, i) => `
        <span class="badge bg-dark-lt d-inline-flex align-items-center">
            ${escapeHtml(d)}
            <button type="button" class="btn-close btn-close-white ms-2" style="font-size:8px;"
                    data-remove="${i}" aria-label="remove"></button>
        </span>`).join('') + `
        <input type="text" id="rphf-domains-input" class="border-0 flex-grow-1"
               style="outline:none; min-width:120px;" placeholder="example.com">`;
    tags.querySelectorAll('[data-remove]').forEach(b => {
        b.addEventListener('click', () => {
            _domains.splice(parseInt(b.dataset.remove, 10), 1);
            renderDomainTags();
            document.getElementById('rphf-domains-input').focus();
        });
    });
    const input = tags.querySelector('#rphf-domains-input');
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            commitDomainInput(input);
        } else if (e.key === 'Backspace' && !input.value && _domains.length) {
            _domains.pop();
            renderDomainTags();
            document.getElementById('rphf-domains-input').focus();
        }
    });
    input.addEventListener('blur', () => commitDomainInput(input));
    tags.addEventListener('click', () => input.focus());
}

function commitDomainInput(input) {
    const raw = (input.value || '').trim().toLowerCase().replace(/[,;\s]+$/, '');
    if (!raw) return;
    if (!_domains.includes(raw)) _domains.push(raw);
    input.value = '';
    renderDomainTags();
    document.getElementById('rphf-domains-input').focus();
}

async function saveHost(existing, onSaved) {
    const inputEl = document.getElementById('rphf-domains-input');
    if (inputEl && inputEl.value.trim()) commitDomainInput(inputEl);

    if (!_domains.length) { showToast(t('reverseproxy.domainNames'), 'error'); return false; }
    const name = _domains[0];

    const forceEl = document.getElementById('rphf-force-https');
    const forceHttps = forceEl && !forceEl.disabled ? forceEl.checked : _forceHttps;

    const aclId = document.getElementById('rphf-acl').value || null;
    const payload = {
        name,
        domains: _domains,
        forward_scheme: document.getElementById('rphf-scheme').value,
        forward_host: document.getElementById('rphf-host').value.trim(),
        forward_port: parseInt(document.getElementById('rphf-port').value, 10) || 0,
        force_https: forceHttps,
        http2_support: document.getElementById('rphf-http2').checked,
        block_exploits: document.getElementById('rphf-block-exploits').checked,
        websockets_support: document.getElementById('rphf-websockets').checked,
        caching_enabled: document.getElementById('rphf-caching').checked,
        custom_nginx_config: document.getElementById('rphf-custom').value,
    };
    if (aclId) payload.access_list_id = aclId;

    try {
        if (existing) {
            await apiPatch(`${MODULE_API}/hosts/${existing.id}`, payload);
            if (existing.access_list_id && !aclId) {
                await apiDelete(`${MODULE_API}/hosts/${existing.id}/access-list`);
            }
        } else {
            await apiPost(`${MODULE_API}/hosts`, payload);
        }
        showToast(t('reverseproxy.hostSaved'), 'success');
        if (typeof onSaved === 'function') await onSaved();
        return true;
    } catch (err) {
        showToast(err.message, 'error');
        return false;
    }
}

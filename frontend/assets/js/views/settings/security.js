/**
 * MADMIN - Settings View / network security (management port, password policy, SSL)
 */

import { apiPatch, apiPost } from '../../api.js';
import { showToast, confirmDialog } from '../../utils.js';
import { t } from '../../i18n.js';

export function securityHtml(canManage) {
    return `
        <div class="col-12">
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title"><i class="ti ti-lock me-2"></i>${t('settings.networkSecurity')}</h3>
                </div>
                <div class="card-body">
                    <div class="row g-3">
                        <!-- Management Port -->
                        <div class="col-md-4">
                            <label class="form-label">${t('settings.managementPort')}</label>
                            <div class="input-group">
                                <input type="number" class="form-control" id="network-port" placeholder="7443" ${canManage ? '' : 'disabled'}>
                                ${canManage ? `<button class="btn btn-warning" id="save-port">${t('settings.changePort')}</button>` : ''}
                            </div>
                            <small class="form-hint text-warning">
                                <i class="ti ti-alert-triangle me-1"></i>
                                ${t('settings.portWarning')}
                            </small>
                        </div>
                        <!-- Password Policy -->
                        <div class="col-md-4">
                            <label class="form-label">${t('settings.passwordMaxAge')}</label>
                            <div class="input-group">
                                <input type="number" min="0" class="form-control" id="password-max-age" placeholder="0" ${canManage ? '' : 'disabled'}>
                                <span class="input-group-text text-muted">${t('settings.days')}</span>
                            </div>
                            <small class="form-hint">${t('settings.passwordMaxAgeHint')}</small>
                            ${canManage ? `<button class="btn btn-primary btn-sm mt-2" id="save-password-policy">${t('common.save')}</button>` : ''}
                        </div>
                        <!-- SSL Certificate -->
                        <div class="col-md-4">
                            <label class="form-label">${t('settings.sslCert')}</label>
                            <div class="card card-sm mb-0">
                                <div class="card-body">
                                    <div class="d-flex align-items-center mb-2">
                                        <span class="badge bg-green-lt me-2" id="ssl-status-badge">-</span>
                                        <div class="text-muted small" id="ssl-issuer">Issuer: -</div>
                                    </div>
                                    <div class="text-muted small mb-2" id="ssl-validity">-</div>
                                    ${canManage ? `
                                    <div class="btn-group w-100">
                                        <button class="btn btn-outline-primary btn-sm" id="renew-ssl">
                                            <i class="ti ti-refresh me-1"></i>${t('settings.renewSelfSigned')}
                                        </button>
                                        <button class="btn btn-outline-secondary btn-sm" id="btn-upload-ssl-modal">
                                            <i class="ti ti-upload me-1"></i>${t('settings.uploadCustomCert')}
                                        </button>
                                    </div>
                                    ` : ''}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

export function sslModalHtml() {
    return `
        <div class="modal modal-blur fade" id="modal-upload-ssl" tabindex="-1" role="dialog" aria-hidden="true">
          <div class="modal-dialog modal-dialog-centered" role="document">
            <div class="modal-content">
              <div class="modal-header">
                <h5 class="modal-title">${t('settings.uploadCustomCertTitle')}</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
              </div>
              <div class="modal-body">
                <div class="mb-3">
                  <label class="form-label">${t('settings.certFile')}</label>
                  <input type="file" class="form-control" id="upload-ssl-crt" accept=".crt,.pem,.cer">
                  <small class="form-hint">${t('settings.certFileHint')}</small>
                </div>
                <div class="mb-3">
                  <label class="form-label">${t('settings.keyFile')}</label>
                  <input type="file" class="form-control" id="upload-ssl-key" accept=".key,.pem">
                  <small class="form-hint">${t('settings.keyFileHint')}</small>
                </div>
                <div class="mb-3">
                  <label class="form-label">${t('settings.caFile')}</label>
                  <input type="file" class="form-control" id="upload-ssl-ca" accept=".crt,.pem,.ca-bundle">
                  <small class="form-hint">${t('settings.caFileHint')}</small>
                </div>
                <div class="alert alert-warning">
                    <i class="ti ti-alert-triangle me-1"></i>
                    ${t('settings.sslUploadWarning')}
                </div>
              </div>
              <div class="modal-footer">
                <button type="button" class="btn btn-link link-secondary" data-bs-dismiss="modal">${t('common.cancel')}</button>
                <button type="button" class="btn btn-primary ms-auto" id="confirm-upload-ssl">
                  <i class="ti ti-upload me-1"></i>${t('settings.uploadAndRestart')}
                </button>
              </div>
            </div>
          </div>
        </div>
    `;
}

export function fillSecurity(system, network) {
    document.getElementById('network-port').value = network.management_port;

    const pwdMaxAgeEl = document.getElementById('password-max-age');
    if (pwdMaxAgeEl) pwdMaxAgeEl.value = system.password_max_age_days ?? 0;

    // SSL Info
    if (network.certificate) {
        document.getElementById('ssl-issuer').textContent = `Issuer: ${network.certificate.issuer}`;
        const validTo = new Date(network.certificate.valid_to).toLocaleDateString(undefined);
        document.getElementById('ssl-validity').textContent = t('settings.sslExpiry', { date: validTo, days: network.certificate.days_remaining });

        const badge = document.getElementById('ssl-status-badge');
        if (network.certificate.is_self_signed) {
            badge.className = 'badge bg-yellow-lt me-2';
            badge.textContent = 'Self-Signed';
        } else {
            badge.className = 'badge bg-green-lt me-2';
            badge.textContent = 'Valid';
        }
    } else {
        document.getElementById('ssl-status-badge').className = 'badge bg-secondary-lt me-2';
        document.getElementById('ssl-status-badge').textContent = t('common.none');
    }
}

export function bindSecurity() {
    // Save password policy
    document.getElementById('save-password-policy')?.addEventListener('click', async () => {
        try {
            const passwordMaxAge = parseInt(document.getElementById('password-max-age')?.value, 10) || 0;
            await apiPatch('/settings/system', { password_max_age_days: passwordMaxAge });
            showToast(t('settings.settingsSaved'), 'success');
        } catch (err) {
            showToast(t('common.errorPrefix') + err.message, 'error');
        }
    });

    // Save management port
    document.getElementById('save-port')?.addEventListener('click', async () => {
        const port = parseInt(document.getElementById('network-port').value);
        if (!port || port < 1 || port > 65535) {
            showToast(t('settings.portInvalid'), 'error');
            return;
        }

        const confirmed = await confirmDialog(
            t('settings.changePortConfirmTitle'),
            `<p>${t('settings.portChangeMsg', { port })}</p>
            <div class="alert alert-warning mb-2">
                <div class="fw-bold mb-1"><i class="ti ti-shield-lock me-1"></i>Firewall</div>
                <p class="mb-1">${t('settings.portFirewallWarning')}</p>
                <code class="d-block p-1 bg-dark text-white rounded small">iptables -A INPUT -p tcp --dport ${port} -j ACCEPT</code>
                <p class="mt-1 mb-0 small text-muted">${t('settings.portFirewallNoAccess')}</p>
            </div>
            <div class="alert alert-danger mb-0">
                <i class="ti ti-plug-connected-x me-1"></i>
                ${t('settings.portDisconnectWarning')}<br>
                <strong>https://${location.hostname}:${port}</strong>
            </div>`,
            t('settings.portChangeAndRestart'),
            'btn-warning',
            true,
            ''
        );
        if (!confirmed) return;

        const btn = document.getElementById('save-port');
        const originalText = btn.innerHTML;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('settings.portChanging')}`;
        btn.disabled = true;

        try {
            await apiPost('/settings/network/port', { port });
            showToast(t('settings.portChanged2', { port }), 'success');
            // Do not reload, connection will be lost
        } catch (e) {
            showToast(t('settings.portChangeError', { error: e.message }), 'error');
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });

    // Renew self-signed SSL
    document.getElementById('renew-ssl')?.addEventListener('click', async () => {
        const confirmed = await confirmDialog(
            t('settings.regenerateCert'),
            t('settings.regenerateCertConfirm'),
            t('settings.renewSelfSigned'),
            'btn-primary'
        );
        if (!confirmed) return;

        const btn = document.getElementById('renew-ssl');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>...';
        btn.disabled = true;

        try {
            await apiPost('/settings/network/ssl/renew', {});
            showToast(t('settings.certRegenerated'), 'success');
            setTimeout(() => location.reload(), 5000);
        } catch (e) {
            showToast(t('settings.certRenewError', { error: e.message }), 'error');
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });

    // Open SSL upload modal
    document.getElementById('btn-upload-ssl-modal')?.addEventListener('click', () => {
        new bootstrap.Modal(document.getElementById('modal-upload-ssl')).show();
    });

    // Confirm SSL upload
    document.getElementById('confirm-upload-ssl')?.addEventListener('click', async () => {
        const crtFile = document.getElementById('upload-ssl-crt').files[0];
        const keyFile = document.getElementById('upload-ssl-key').files[0];
        const caFile = document.getElementById('upload-ssl-ca').files[0];

        if (!crtFile || !keyFile) {
            showToast(t('settings.sslSelectBoth'), 'warning');
            return;
        }

        const btn = document.getElementById('confirm-upload-ssl');
        const originalText = btn.innerHTML;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('settings.certUploading')}`;
        btn.disabled = true;

        try {
            const formData = new FormData();
            formData.append('cert_file', crtFile);
            formData.append('key_file', keyFile);
            if (caFile) {
                formData.append('ca_file', caFile);
            }

            const response = await fetch('/api/settings/network/ssl/upload', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` },
                body: formData
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Upload failed');
            }

            showToast(t('settings.certUploadSuccess'), 'success');
            bootstrap.Modal.getInstance(document.getElementById('modal-upload-ssl'))?.hide();
            setTimeout(() => location.reload(), 5000);

        } catch (e) {
            showToast(t('settings.certUploadError', { error: e.message }), 'error');
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });
}

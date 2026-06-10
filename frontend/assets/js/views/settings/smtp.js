/**
 * MADMIN - Settings View / SMTP configuration
 */

import { apiPatch, apiPost } from '../../api.js';
import { showToast, inputDialog } from '../../utils.js';
import { t } from '../../i18n.js';

export function smtpHtml(canManage) {
    return `
        <div class="col-12">
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title"><i class="ti ti-mail me-2"></i>${t('settings.smtpConfig')}</h3>
                </div>
                <div class="card-body">
                    <div class="row g-3">
                        <div class="col-md-4">
                            <label class="form-label">${t('settings.smtpServer')}</label>
                            <input type="text" class="form-control" id="smtp-host" placeholder="smtp.gmail.com" ${canManage ? '' : 'disabled'}>
                        </div>
                        <div class="col-md-2">
                            <label class="form-label">${t('settings.smtpPort')}</label>
                            <input type="number" class="form-control" id="smtp-port" value="587" ${canManage ? '' : 'disabled'}>
                        </div>
                        <div class="col-md-3">
                            <label class="form-label">${t('settings.smtpEncryption')}</label>
                            <select class="form-select" id="smtp-encryption" ${canManage ? '' : 'disabled'}>
                                <option value="none">${t('settings.encryptionNone')}</option>
                                <option value="tls" selected>TLS (STARTTLS)</option>
                                <option value="ssl">SSL/TLS</option>
                            </select>
                        </div>
                        <div class="col-md-5">
                            <label class="form-label">${t('settings.publicDownloadUrl')}</label>
                            <div class="input-group">
                                <span class="input-group-text text-muted">https://</span>
                                <input type="text" class="form-control" id="public-download-host" placeholder="192.168.1.1 o dominio.it" ${canManage ? '' : 'disabled'}>
                                <span class="input-group-text text-muted">:</span>
                                <input type="number" class="form-control" id="public-download-port" placeholder="6443" min="1" max="65535" style="max-width:90px" ${canManage ? '' : 'disabled'}>
                            </div>
                            <small class="form-hint">
                                ${t('settings.publicDownloadHint')}
                                <span class="text-warning ms-1" title="${t('settings.publicDownloadFirewallTitle')}">
                                    <i class="ti ti-info-circle"></i> ${t('settings.publicDownloadFirewall')}
                                </span>
                            </small>
                        </div>
                        <div class="col-md-3">
                            <label class="form-label">${t('settings.smtpUsername')}</label>
                            <input type="text" class="form-control" id="smtp-username" ${canManage ? '' : 'disabled'}>
                        </div>
                        <div class="col-md-3">
                            <label class="form-label">${t('settings.smtpPassword')}</label>
                            <input type="password" class="form-control" id="smtp-password" placeholder="••••••••" ${canManage ? '' : 'disabled'}>
                        </div>
                        <div class="col-md-3">
                            <label class="form-label">${t('settings.senderEmail')}</label>
                            <input type="email" class="form-control" id="sender-email" placeholder="noreply@example.com" ${canManage ? '' : 'disabled'}>
                        </div>
                        <div class="col-md-3">
                            <label class="form-label">${t('settings.senderName')}</label>
                            <input type="text" class="form-control" id="sender-name" placeholder="MADMIN" ${canManage ? '' : 'disabled'}>
                        </div>
                        <div class="col-12">
                            ${canManage ? `
                            <button class="btn btn-primary" id="save-smtp">${t('common.save')}</button>
                            <button class="btn btn-outline-secondary ms-2" id="test-smtp">
                                <i class="ti ti-send me-1"></i>${t('settings.sendTestEmail')}
                            </button>
                            ` : ''}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

export function fillSmtp(smtp) {
    document.getElementById('smtp-host').value = smtp.smtp_host || '';
    document.getElementById('smtp-port').value = smtp.smtp_port || 587;
    document.getElementById('smtp-encryption').value = smtp.smtp_encryption || 'tls';

    const existingDownloadUrl = smtp.public_download_url || '';
    if (existingDownloadUrl) {
        try {
            const parsed = new URL(existingDownloadUrl);
            document.getElementById('public-download-host').value = parsed.hostname;
            document.getElementById('public-download-port').value = parsed.port && parsed.port !== '443' ? parsed.port : '';
        } catch {
            document.getElementById('public-download-host').value = existingDownloadUrl;
            document.getElementById('public-download-port').value = '';
        }
    } else {
        document.getElementById('public-download-host').value = '';
        document.getElementById('public-download-port').value = '';
    }
    document.getElementById('smtp-username').value = smtp.smtp_username || '';
    document.getElementById('sender-email').value = smtp.sender_email || '';
    document.getElementById('sender-name').value = smtp.sender_name || '';
}

export function bindSmtp() {
    // Save SMTP settings
    document.getElementById('save-smtp')?.addEventListener('click', async () => {
        try {
            const data = {
                smtp_host: document.getElementById('smtp-host').value,
                smtp_port: parseInt(document.getElementById('smtp-port').value),
                smtp_encryption: document.getElementById('smtp-encryption').value,
                public_download_url: (() => {
                    const host = document.getElementById('public-download-host').value.trim();
                    const port = document.getElementById('public-download-port').value.trim();
                    return host ? `https://${host}:${port || 443}` : null;
                })(),
                smtp_username: document.getElementById('smtp-username').value || null,
                sender_email: document.getElementById('sender-email').value,
                sender_name: document.getElementById('sender-name').value
            };
            const pwd = document.getElementById('smtp-password').value;
            if (pwd) data.smtp_password = pwd;

            await apiPatch('/settings/smtp', data);
            showToast(t('settings.smtpSaved'), 'success');
        } catch (e) { showToast(e.message, 'error'); }
    });

    // Test SMTP - use modal for recipient email
    document.getElementById('test-smtp')?.addEventListener('click', async () => {
        const recipient = await inputDialog(
            t('settings.smtpTestTitle'),
            t('settings.smtpTestRecipient'),
            'user@example.com',
            'email'
        );
        if (!recipient) return;

        // Validate email format
        if (!recipient.match(/^[^\s@]+@[^\s@]+\.[^\s@]+$/)) {
            showToast(t('settings.smtpInvalidEmail'), 'error');
            return;
        }

        const btn = document.getElementById('test-smtp');
        const originalText = btn.innerHTML;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${t('settings.smtpTestSending')}`;
        btn.disabled = true;

        try {
            await apiPost('/settings/smtp/test', { recipient_email: recipient });
            showToast(t('settings.smtpTestSent', { recipient }), 'success');
        } catch (e) {
            showToast(t('settings.smtpSendError', { error: e.message }), 'error');
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });
}

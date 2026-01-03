/**
 * MADMIN - Settings View
 */

import { apiGet, apiPatch, apiPost } from '../api.js';
import { showToast, escapeHtml, inputDialog, confirmDialog } from '../utils.js';
import { checkPermission } from '../app.js';

/**
 * Render the settings view
 */
export async function render(container) {
    const canManage = checkPermission('settings.manage');

    container.innerHTML = `
        <div class="row row-deck row-cards">
            <!-- Personalization Settings -->
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title"><i class="ti ti-palette me-2"></i>Personalizzazione</h3>
                    </div>
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-4">
                                <label class="form-label">Nome Azienda</label>
                                <div class="input-group">
                                    <input type="text" class="form-control" id="company-name" placeholder="MADMIN" ${canManage ? '' : 'disabled'}>
                                    ${canManage ? '<button type="button" class="btn btn-outline-secondary" id="reset-company" title="Ripristina predefinito"><i class="ti ti-refresh"></i></button>' : ''}
                                </div>
                                <small class="form-hint">Predefinito: MADMIN</small>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Colore Primario</label>
                                <div class="input-group">
                                    <input type="color" class="form-control form-control-color" id="primary-color" ${canManage ? '' : 'disabled'}>
                                    <input type="text" class="form-control" id="primary-color-hex" placeholder="#206bc4" ${canManage ? '' : 'disabled'}>
                                    ${canManage ? '<button type="button" class="btn btn-outline-secondary" id="reset-color" title="Ripristina predefinito"><i class="ti ti-refresh"></i></button>' : ''}
                                </div>
                                <small class="form-hint">Predefinito: #206bc4</small>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">URL Supporto</label>
                                <div class="input-group">
                                    <input type="url" class="form-control" id="support-url" placeholder="https://..." ${canManage ? '' : 'disabled'}>
                                    ${canManage ? '<button type="button" class="btn btn-outline-secondary" id="reset-support" title="Rimuovi link supporto"><i class="ti ti-x"></i></button>' : ''}
                                </div>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Logo</label>
                                <div class="d-flex align-items-center gap-3">
                                    <div id="logo-preview-container" class="border rounded p-2 d-flex align-items-center justify-content-center bg-dark"
                                         style="min-height: 50px; min-width: 120px;">
                                        <img id="logo-preview-img" src="" class="d-none" style="max-height: 50px; max-width: 100%; object-fit: contain;">
                                        <div id="logo-preview-default" class="text-primary d-flex align-items-center">
                                            <i class="ti ti-server-cog" style="font-size: 1.5rem;"></i>
                                            <span class="ms-2 text-white fw-bold">MADMIN</span>
                                        </div>
                                    </div>
                                    ${canManage ? `
                                    <div class="btn-group">
                                        <label class="btn btn-outline-primary btn-sm">
                                            <i class="ti ti-upload me-1"></i>Carica
                                            <input type="file" id="logo-upload" accept="image/*" class="d-none">
                                        </label>
                                        <button type="button" class="btn btn-outline-secondary btn-sm" id="reset-logo" title="Rimuovi logo">
                                            <i class="ti ti-x"></i>
                                        </button>
                                    </div>
                                    ` : ''}
                                </div>
                                <small class="form-hint">PNG o SVG, max 200x50px</small>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Favicon</label>
                                <div class="d-flex align-items-center gap-3">
                                    <div id="favicon-preview-container" class="border rounded d-flex align-items-center justify-content-center bg-dark"
                                         style="width: 40px; height: 40px;">
                                        <img id="favicon-preview-img" src="" class="d-none" style="height: 32px; width: 32px; object-fit: contain;">
                                        <i id="favicon-preview-default" class="ti ti-server-cog text-primary"></i>
                                    </div>
                                    ${canManage ? `
                                    <div class="btn-group">
                                        <label class="btn btn-outline-primary btn-sm">
                                            <i class="ti ti-upload me-1"></i>Carica
                                            <input type="file" id="favicon-upload" accept="image/*,.ico" class="d-none">
                                        </label>
                                        <button type="button" class="btn btn-outline-secondary btn-sm" id="reset-favicon" title="Ripristina predefinito">
                                            <i class="ti ti-refresh"></i>
                                        </button>
                                    </div>
                                    ` : ''}
                                </div>
                                <small class="form-hint">ICO o PNG 32x32px</small>
                            </div>
                            <div class="col-12">
                                ${canManage ? '<button class="btn btn-primary" id="save-system">Salva Impostazioni</button>' : ''}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- SMTP Settings -->
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title"><i class="ti ti-mail me-2"></i>Configurazione Email (SMTP)</h3>
                    </div>
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-4">
                                <label class="form-label">Server SMTP</label>
                                <input type="text" class="form-control" id="smtp-host" placeholder="smtp.gmail.com" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-md-2">
                                <label class="form-label">Porta</label>
                                <input type="number" class="form-control" id="smtp-port" value="587" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">Crittografia</label>
                                <select class="form-select" id="smtp-encryption" ${canManage ? '' : 'disabled'}>
                                    <option value="none">Nessuna</option>
                                    <option value="tls" selected>TLS (STARTTLS)</option>
                                    <option value="ssl">SSL/TLS</option>
                                </select>
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">URL Pubblico App</label>
                                <input type="url" class="form-control" id="public-url" placeholder="https://app.example.com" ${canManage ? '' : 'disabled'}>
                                <small class="form-hint">Per link nelle email</small>
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">Username SMTP</label>
                                <input type="text" class="form-control" id="smtp-username" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">Password SMTP</label>
                                <input type="password" class="form-control" id="smtp-password" placeholder="••••••••" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">Email Mittente</label>
                                <input type="email" class="form-control" id="sender-email" placeholder="noreply@example.com" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">Nome Mittente</label>
                                <input type="text" class="form-control" id="sender-name" placeholder="MADMIN" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-12">
                                ${canManage ? `
                                <button class="btn btn-primary" id="save-smtp">Salva</button>
                                <button class="btn btn-outline-secondary ms-2" id="test-smtp">
                                    <i class="ti ti-send me-1"></i>Test Invio
                                </button>
                                ` : ''}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Backup Settings -->
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title"><i class="ti ti-database-export me-2"></i>Backup Automatico</h3>
                    </div>
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-3">
                                <label class="form-check form-switch">
                                    <input class="form-check-input" type="checkbox" id="backup-enabled" ${canManage ? '' : 'disabled'}>
                                    <span class="form-check-label">Backup Automatico</span>
                                </label>
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">Frequenza</label>
                                <select class="form-select" id="backup-frequency" ${canManage ? '' : 'disabled'}>
                                    <option value="daily">Giornaliero</option>
                                    <option value="weekly">Settimanale</option>
                                </select>
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">Ora</label>
                                <input type="time" class="form-control" id="backup-time" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">Protocollo</label>
                                <select class="form-select" id="backup-protocol" ${canManage ? '' : 'disabled'}>
                                    <option value="sftp">SFTP</option>
                                    <option value="ftp">FTP</option>
                                </select>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Host Remoto</label>
                                <input type="text" class="form-control" id="backup-host" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-md-2">
                                <label class="form-label">Porta</label>
                                <input type="number" class="form-control" id="backup-port" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Percorso</label>
                                <input type="text" class="form-control" id="backup-path" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Utente</label>
                                <input type="text" class="form-control" id="backup-user" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Password</label>
                                <input type="password" class="form-control" id="backup-password" placeholder="••••••••" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-12">
                                ${canManage ? '<button class="btn btn-primary" id="save-backup">Salva</button>' : ''}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- System Management -->
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title"><i class="ti ti-server me-2"></i>Gestione Sistema</h3>
                    </div>
                    <div class="card-body">
                        <div class="row g-3 align-items-center">
                            <div class="col-md-8">
                                <h4 class="mb-1">Riavvia MADMIN</h4>
                                <p class="text-muted mb-0">Riavvia il servizio MADMIN per applicare eventuali modifiche di configurazione.</p>
                            </div>
                            <div class="col-md-4 text-end">
                                ${canManage ? `
                                <button class="btn btn-warning" id="btn-restart-madmin">
                                    <i class="ti ti-refresh me-1"></i>Riavvia MADMIN
                                </button>
                                ` : '<span class="text-muted">Permessi insufficienti</span>'}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

    await loadSettings();
    setupEventListeners();
}

async function loadSettings() {
    try {
        const [system, smtp, backup] = await Promise.all([
            apiGet('/settings/system'),
            apiGet('/settings/smtp'),
            apiGet('/settings/backup')
        ]);
        // System
        document.getElementById('company-name').value = system.company_name || '';
        document.getElementById('primary-color').value = system.primary_color || '#206bc4';
        document.getElementById('primary-color-hex').value = system.primary_color || '#206bc4';
        document.getElementById('support-url').value = system.support_url || '';

        // Logo preview - show uploaded image if URL exists (toggle img/default visibility)
        if (system.logo_url) {
            const logoImg = document.getElementById('logo-preview-img');
            const logoDefault = document.getElementById('logo-preview-default');
            if (logoImg && logoDefault) {
                logoImg.src = system.logo_url;
                logoImg.classList.remove('d-none');
                logoDefault.classList.add('d-none');
            }
        }

        // Favicon preview - show uploaded image if URL exists
        if (system.favicon_url) {
            const faviconImg = document.getElementById('favicon-preview-img');
            const faviconDefault = document.getElementById('favicon-preview-default');
            if (faviconImg && faviconDefault) {
                faviconImg.src = system.favicon_url;
                faviconImg.classList.remove('d-none');
                faviconDefault.classList.add('d-none');
            }
        }

        // SMTP
        document.getElementById('smtp-host').value = smtp.smtp_host || '';
        document.getElementById('smtp-port').value = smtp.smtp_port || 587;
        document.getElementById('smtp-encryption').value = smtp.smtp_encryption || 'tls';
        document.getElementById('public-url').value = smtp.public_url || '';
        document.getElementById('smtp-username').value = smtp.smtp_username || '';
        document.getElementById('sender-email').value = smtp.sender_email || '';
        document.getElementById('sender-name').value = smtp.sender_name || '';

        // Backup
        document.getElementById('backup-enabled').checked = backup.enabled;
        document.getElementById('backup-frequency').value = backup.frequency || 'daily';
        document.getElementById('backup-time').value = backup.time || '03:00';
        document.getElementById('backup-protocol').value = backup.remote_protocol || 'sftp';
        document.getElementById('backup-host').value = backup.remote_host || '';
        document.getElementById('backup-port').value = backup.remote_port || 22;
        document.getElementById('backup-path').value = backup.remote_path || '/';
        document.getElementById('backup-user').value = backup.remote_user || '';

    } catch (error) {
        showToast('Errore caricamento impostazioni', 'error');
    }
}

function setupEventListeners() {
    // Color picker sync
    const colorPicker = document.getElementById('primary-color');
    const colorHex = document.getElementById('primary-color-hex');

    colorPicker?.addEventListener('input', () => {
        colorHex.value = colorPicker.value;
    });

    colorHex?.addEventListener('input', () => {
        if (/^#[0-9A-Fa-f]{6}$/.test(colorHex.value)) {
            colorPicker.value = colorHex.value;
        }
    });

    // Reset color to default
    document.getElementById('reset-color')?.addEventListener('click', () => {
        const defaultColor = '#206bc4';
        colorPicker.value = defaultColor;
        colorHex.value = defaultColor;
        showToast('Colore ripristinato al predefinito', 'info');
    });

    // Reset company name to default
    document.getElementById('reset-company')?.addEventListener('click', async () => {
        const companyInput = document.getElementById('company-name');
        companyInput.value = 'MADMIN';
        try {
            await apiPatch('/settings/system', { company_name: 'MADMIN' });
            showToast('Nome azienda ripristinato', 'success');
        } catch (e) { showToast(e.message, 'error'); }
    });

    // Reset support URL (clear)
    document.getElementById('reset-support')?.addEventListener('click', async () => {
        const supportInput = document.getElementById('support-url');
        supportInput.value = '';
        try {
            await apiPatch('/settings/system', { support_url: '' });
            showToast('URL supporto rimosso', 'success');
        } catch (e) { showToast(e.message, 'error'); }
    });

    // Reset logo (remove custom)
    document.getElementById('reset-logo')?.addEventListener('click', async () => {
        try {
            await apiPatch('/settings/system', { logo_url: null });
            // Restore default preview
            const logoImg = document.getElementById('logo-preview-img');
            const logoDefault = document.getElementById('logo-preview-default');
            if (logoImg && logoDefault) {
                logoImg.classList.add('d-none');
                logoDefault.classList.remove('d-none');
            }
            showToast('Logo rimosso', 'success');
        } catch (e) { showToast(e.message, 'error'); }
    });

    // Reset favicon (restore default)
    document.getElementById('reset-favicon')?.addEventListener('click', async () => {
        try {
            await apiPatch('/settings/system', { favicon_url: null });
            // Restore default preview
            const faviconImg = document.getElementById('favicon-preview-img');
            const faviconDefault = document.getElementById('favicon-preview-default');
            if (faviconImg && faviconDefault) {
                faviconImg.classList.add('d-none');
                faviconDefault.classList.remove('d-none');
            }
            showToast('Favicon ripristinata al predefinito', 'success');
        } catch (e) { showToast(e.message, 'error'); }
    });

    // Logo upload
    document.getElementById('logo-upload')?.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (file) {
            // Show preview immediately (toggle img/default visibility)
            const reader = new FileReader();
            reader.onload = (ev) => {
                const img = document.getElementById('logo-preview-img');
                const defaultEl = document.getElementById('logo-preview-default');
                if (img && defaultEl) {
                    img.src = ev.target.result;
                    img.classList.remove('d-none');
                    defaultEl.classList.add('d-none');
                }
            };
            reader.readAsDataURL(file);

            // Upload to server
            try {
                const formData = new FormData();
                formData.append('file', file);

                const response = await fetch('/api/files/upload', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` },
                    body: formData
                });

                if (!response.ok) throw new Error('Upload fallito');
                const data = await response.json();

                // Save URL to settings
                await apiPatch('/settings/system', { logo_url: data.url });
                showToast('Logo caricato e salvato', 'success');
            } catch (err) {
                showToast('Errore caricamento: ' + err.message, 'error');
            }
        }
    });

    // Favicon upload
    document.getElementById('favicon-upload')?.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (file) {
            // Show preview immediately (toggle img/default visibility)
            const reader = new FileReader();
            reader.onload = (ev) => {
                const img = document.getElementById('favicon-preview-img');
                const defaultEl = document.getElementById('favicon-preview-default');
                if (img && defaultEl) {
                    img.src = ev.target.result;
                    img.classList.remove('d-none');
                    defaultEl.classList.add('d-none');
                }
            };
            reader.readAsDataURL(file);

            // Upload to server
            try {
                const formData = new FormData();
                formData.append('file', file);

                const response = await fetch('/api/files/upload', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` },
                    body: formData
                });

                if (!response.ok) throw new Error('Upload fallito');
                const data = await response.json();

                // Save URL to settings
                await apiPatch('/settings/system', { favicon_url: data.url });
                showToast('Favicon caricata e salvata', 'success');
            } catch (err) {
                showToast('Errore caricamento: ' + err.message, 'error');
            }
        }
    });

    // Save system settings
    document.getElementById('save-system')?.addEventListener('click', async () => {
        try {
            const companyName = document.getElementById('company-name').value || 'MADMIN';
            const primaryColor = document.getElementById('primary-color').value;
            const supportUrl = document.getElementById('support-url').value || '';

            await apiPatch('/settings/system', {
                company_name: companyName,
                primary_color: primaryColor,
                support_url: supportUrl
            });

            // Apply changes immediately to UI
            // Update browser title
            document.title = `${companyName} - Dashboard`;

            // Update sidebar brand
            const brandText = document.getElementById('navbar-brand-text');
            if (brandText) brandText.textContent = companyName;

            // Update mobile header brand
            const mobileBrand = document.getElementById('mobile-brand-name');
            if (mobileBrand) mobileBrand.textContent = companyName;

            // Update footer brand
            const footerBrand = document.getElementById('footer-brand');
            if (footerBrand) footerBrand.textContent = companyName;

            // Update support link visibility
            const supportItem = document.getElementById('support-link-item');
            const supportLink = document.getElementById('support-link');
            if (supportItem && supportLink) {
                if (supportUrl) {
                    supportLink.href = supportUrl;
                    supportItem.style.display = 'list-item';
                } else {
                    supportItem.style.display = 'none';
                }
            }

            showToast('Impostazioni salvate', 'success');
        } catch (e) { showToast(e.message, 'error'); }
    });

    // Save SMTP settings
    document.getElementById('save-smtp')?.addEventListener('click', async () => {
        try {
            const data = {
                smtp_host: document.getElementById('smtp-host').value,
                smtp_port: parseInt(document.getElementById('smtp-port').value),
                smtp_encryption: document.getElementById('smtp-encryption').value,
                public_url: document.getElementById('public-url').value || null,
                smtp_username: document.getElementById('smtp-username').value || null,
                sender_email: document.getElementById('sender-email').value,
                sender_name: document.getElementById('sender-name').value
            };
            const pwd = document.getElementById('smtp-password').value;
            if (pwd) data.smtp_password = pwd;

            await apiPatch('/settings/smtp', data);
            showToast('Impostazioni SMTP salvate', 'success');
        } catch (e) { showToast(e.message, 'error'); }
    });

    // Test SMTP - use modal for recipient email
    document.getElementById('test-smtp')?.addEventListener('click', async () => {
        const recipient = await inputDialog(
            'Test Email SMTP',
            'Email destinatario',
            'esempio@dominio.it',
            'email'
        );
        if (!recipient) return;

        // Validate email format
        if (!recipient.match(/^[^\s@]+@[^\s@]+\.[^\s@]+$/)) {
            showToast('Inserisci un indirizzo email valido', 'error');
            return;
        }

        const btn = document.getElementById('test-smtp');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Invio...';
        btn.disabled = true;

        try {
            await apiPost('/settings/smtp/test', { recipient_email: recipient });
            showToast(`Email di test inviata a ${recipient}`, 'success');
        } catch (e) {
            showToast('Errore invio: ' + e.message, 'error');
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });

    // Save backup settings
    document.getElementById('save-backup')?.addEventListener('click', async () => {
        try {
            const data = {
                enabled: document.getElementById('backup-enabled').checked,
                frequency: document.getElementById('backup-frequency').value,
                time: document.getElementById('backup-time').value,
                remote_protocol: document.getElementById('backup-protocol').value,
                remote_host: document.getElementById('backup-host').value,
                remote_port: parseInt(document.getElementById('backup-port').value),
                remote_path: document.getElementById('backup-path').value,
                remote_user: document.getElementById('backup-user').value
            };
            const pwd = document.getElementById('backup-password').value;
            if (pwd) data.remote_password = pwd;

            await apiPatch('/settings/backup', data);
            showToast('Impostazioni backup salvate', 'success');
        } catch (e) { showToast(e.message, 'error'); }
    });

    // Restart MADMIN service
    document.getElementById('btn-restart-madmin')?.addEventListener('click', async () => {
        const confirmed = await confirmDialog(
            'Riavvia MADMIN',
            'Sei sicuro di voler riavviare MADMIN? La connessione sarà temporaneamente interrotta.',
            'Riavvia',
            'btn-warning'
        );
        if (!confirmed) return;

        const btn = document.getElementById('btn-restart-madmin');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Riavvio...';
        btn.disabled = true;

        try {
            await apiPost('/services/madmin.service/restart', {});
            showToast('Servizio MADMIN riavviato. La pagina si ricaricherà tra 5 secondi...', 'success');
            setTimeout(() => {
                location.reload();
            }, 5000);
        } catch (e) {
            showToast('Errore riavvio: ' + e.message, 'error');
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });
}

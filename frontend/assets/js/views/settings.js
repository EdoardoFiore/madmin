/**
 * MADMIN - Settings View
 */

import { apiGet, apiPatch, apiPost, apiDelete } from '../api.js';
import { showToast, escapeHtml, inputDialog, confirmDialog } from '../utils.js';
import { checkPermission, applyTheme, getCurrentTheme } from '../app.js';

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
                            <div class="col-md-4 d-flex align-items-end">
                                <div class="mb-0">
                                    <label class="form-check form-switch">
                                        <input type="checkbox" class="form-check-input" id="dark-mode-toggle">
                                        <span class="form-check-label">Tema scuro</span>
                                    </label>
                                    <small class="form-hint">Preferenza personale per utente</small>
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
            
            <!-- Network Security Settings -->
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title"><i class="ti ti-lock me-2"></i>Sicurezza e Rete</h3>
                    </div>
                    <div class="card-body">
                        <div class="row g-3">
                             <!-- Port Configuration -->
                            <div class="col-md-6">
                                <label class="form-label">Porta di Gestione (HTTPS)</label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="network-port" placeholder="7443" ${canManage ? '' : 'disabled'}>
                                    ${canManage ? '<button class="btn btn-warning" id="save-port">Cambia Porta</button>' : ''}
                                </div>
                                <small class="form-hint text-warning">
                                    <i class="ti ti-alert-triangle me-1"></i>
                                    Il cambio porta interromperà la connessione. Dovrai ricollegarti manualmente.
                                </small>
                            </div>

                            <!-- SSL Certificate Info -->
                            <div class="col-md-6">
                                 <label class="form-label">Certificato SSL</label>
                                 <div class="card card-sm">
                                    <div class="card-body">
                                        <div class="d-flex align-items-center mb-2">
                                            <span class="badge bg-green-lt me-2" id="ssl-status-badge">Attivo</span>
                                            <div class="text-muted small" id="ssl-issuer">Issuer: -</div>
                                        </div>
                                        <div class="text-muted small mb-2" id="ssl-validity">Scadenza: -</div>
                                        
                                        ${canManage ? `
                                        <div class="btn-group w-100">
                                            <button class="btn btn-outline-primary btn-sm" id="renew-ssl">
                                                <i class="ti ti-refresh me-1"></i>Rinnova Self-Signed
                                            </button>
                                            <button class="btn btn-outline-secondary btn-sm" id="btn-upload-ssl-modal">
                                                <i class="ti ti-upload me-1"></i>Carica Custom
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
                            <div class="col-md-5">
                                <label class="form-label">URL Pubblico Download VPN</label>
                                <div class="input-group">
                                    <span class="input-group-text text-muted">https://</span>
                                    <input type="text" class="form-control" id="public-download-host" placeholder="192.168.1.1 o dominio.it" ${canManage ? '' : 'disabled'}>
                                    <span class="input-group-text text-muted">:</span>
                                    <input type="number" class="form-control" id="public-download-port" placeholder="6443" min="1" max="65535" style="max-width:90px" ${canManage ? '' : 'disabled'}>
                                </div>
                                <small class="form-hint">
                                    Lasciare vuoto per disabilitare. Porta vuota = 443 (HTTPS standard).
                                    <span class="text-warning ms-1" title="Ricorda di creare una regola ACCEPT nel firewall per la porta specificata (es. iptables -A INPUT -p tcp --dport PORTA -j ACCEPT)">
                                        <i class="ti ti-info-circle"></i> Apri la porta nel firewall.
                                    </span>
                                </small>
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
            
            <!-- Backup & Migrazione -->
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title"><i class="ti ti-database-export me-2"></i>Backup & Migrazione</h3>
                        <div class="card-actions">
                            ${canManage ? `
                            <div class="btn-group">
                                <button class="btn btn-primary btn-sm" id="backup-local-btn">
                                    <i class="ti ti-device-floppy me-1"></i>Backup Locale
                                </button>
                                <button class="btn btn-cyan btn-sm" id="backup-remote-btn" style="display:none">
                                    <i class="ti ti-cloud-upload me-1"></i>Backup Remoto
                                </button>
                            </div>
                            <button class="btn btn-warning btn-sm ms-2" id="open-import-modal-btn">
                                <i class="ti ti-file-import me-1"></i>Ripristina...
                            </button>
                            ` : ''}
                        </div>
                    </div>
                    <div class="card-body">
                        <!-- Last backup status -->
                        <div class="alert alert-info mb-3" id="backup-status-alert">
                            <div class="d-flex align-items-center">
                                <i class="ti ti-info-circle me-2"></i>
                                <span id="backup-last-status">Caricamento...</span>
                            </div>
                        </div>

                        <!-- Scheduled Backup Settings -->
                        <h4 class="mb-3"><i class="ti ti-clock me-2"></i>Backup Programmato</h4>
                        <div class="row g-3">
                            <div class="col-md-2">
                                <label class="form-check form-switch">
                                    <input class="form-check-input" type="checkbox" id="backup-enabled" ${canManage ? '' : 'disabled'}>
                                    <span class="form-check-label">Automatico</span>
                                </label>
                            </div>
                            <div class="col-md-2">
                                <label class="form-label">Frequenza</label>
                                <select class="form-select" id="backup-frequency" ${canManage ? '' : 'disabled'}>
                                    <option value="daily">Giornaliero</option>
                                    <option value="weekly">Settimanale</option>
                                </select>
                            </div>
                            <div class="col-md-2">
                                <label class="form-label">Ora</label>
                                <input type="time" class="form-control" id="backup-time" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-md-2">
                                <label class="form-label">Retention (giorni)</label>
                                <input type="number" class="form-control" id="backup-retention" min="0" placeholder="30" ${canManage ? '' : 'disabled'}>
                                <small class="form-hint">0 = illimitato</small>
                            </div>
                            <div class="col-md-2">
                                <label class="form-label">Protocollo</label>
                                <select class="form-select" id="backup-protocol" ${canManage ? '' : 'disabled'}>
                                    <option value="sftp">SFTP</option>
                                    <option value="ftp">FTP</option>
                                </select>
                            </div>
                            <div class="col-md-2">
                                <label class="form-label">Porta</label>
                                <input type="number" class="form-control" id="backup-port" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Host Remoto</label>
                                <input type="text" class="form-control" id="backup-host" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Percorso</label>
                                <input type="text" class="form-control" id="backup-path" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-md-2">
                                <label class="form-label">Utente</label>
                                <input type="text" class="form-control" id="backup-user" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-md-2">
                                <label class="form-label">Password</label>
                                <input type="password" class="form-control" id="backup-password" placeholder="••••••••" ${canManage ? '' : 'disabled'}>
                            </div>
                            <div class="col-12">
                                ${canManage ? '<button class="btn btn-primary" id="save-backup">Salva Configurazione</button>' : ''}
                            </div>
                        </div>
                        
                        <!-- Local Backup History -->
                        <hr class="my-4">
                        <h4 class="mb-3"><i class="ti ti-history me-2"></i>Backup Locali</h4>
                        <div class="table-responsive">
                            <table class="table table-vcenter">
                                <thead>
                                    <tr>
                                        <th>File</th>
                                        <th>Dimensione</th>
                                        <th>Data</th>
                                        <th class="text-end">Azioni</th>
                                    </tr>
                                </thead>
                                <tbody id="backup-history-body">
                                    <tr><td colspan="4" class="text-center text-muted">Caricamento...</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                    
                    <!-- Remote Backup History -->
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h4 class="card-title m-0"><i class="ti ti-cloud me-2"></i>Backup Remoti</h4>
                        ${canManage ? `
                        <button class="btn btn-sm btn-outline-warning" onclick="cleanupRemoteBackups()" title="Applica retention">
                            <i class="ti ti-trash me-1"></i>Pulizia
                        </button>` : ''}
                    </div>
                    <div class="card-body pt-2">
                        <div class="table-responsive">
                            <table class="table table-vcenter card-table">
                                <thead>
                                    <tr>
                                        <th>File</th>
                                        <th>Dimensione</th>
                                        <th>Data</th>
                                        <th class="text-end">Azioni</th>
                                    </tr>
                                </thead>
                                <tbody id="remote-backup-history-body">
                                    <tr><td colspan="4" class="text-center text-muted">Caricamento...</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Import/Restore Modal -->
            <div class="modal modal-blur fade" id="modal-import-config" tabindex="-1" role="dialog" aria-hidden="true">
                <div class="modal-dialog modal-dialog-centered" role="document">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title"><i class="ti ti-file-import me-2"></i>Ripristina Configurazione</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <!-- Upload -->
                            <h4 class="mb-2">Carica file</h4>
                            <div class="border border-2 border-dashed rounded-3 p-3 text-center mb-3" id="import-dropzone"
                                 style="cursor: pointer; transition: all 0.2s;">
                                <i class="ti ti-file-upload" style="font-size: 1.5rem; color: var(--tblr-primary);"></i>
                                <p class="mt-1 mb-0 text-muted small">Trascina un file .tar.gz o clicca per selezionare</p>
                                <input type="file" id="import-file-input" accept=".tar.gz" class="d-none">
                            </div>

                            <!-- SCP Files -->
                            <h4 class="mb-2"><i class="ti ti-server me-1"></i>File da SCP</h4>
                            <p class="text-muted small mb-2">
                                Carica via SCP in <code>/opt/madmin/data/imports/</code>
                            </p>
                            <div id="scp-files-list">
                                <div class="text-muted small">Caricamento...</div>
                            </div>

                            <div id="import-progress" class="d-none mt-3">
                                <div class="progress">
                                    <div class="progress-bar progress-bar-indeterminate"></div>
                                </div>
                                <small class="text-muted">Importazione in corso...</small>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-link link-secondary" data-bs-dismiss="modal">Chiudi</button>
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
        </div>
        
        <!-- Upload SSL Modal -->
        <div class="modal modal-blur fade" id="modal-upload-ssl" tabindex="-1" role="dialog" aria-hidden="true">
          <div class="modal-dialog modal-dialog-centered" role="document">
            <div class="modal-content">
              <div class="modal-header">
                <h5 class="modal-title">Carica Certificato SSL Custom</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
              </div>
              <div class="modal-body">
                <div class="mb-3">
                  <label class="form-label">Certificato (server.crt)</label>
                  <input type="file" class="form-control" id="upload-ssl-crt" accept=".crt,.pem,.cer">
                  <small class="form-hint">Certificato pubblico X.509 (PEM)</small>
                </div>
                <div class="mb-3">
                  <label class="form-label">Chiave Privata (server.key)</label>
                  <input type="file" class="form-control" id="upload-ssl-key" accept=".key,.pem">
                  <small class="form-hint">Chiave privata RSA (senza password)</small>
                </div>
                <div class="mb-3">
                  <label class="form-label">CA Bundle/Chain (Opzionale)</label>
                  <input type="file" class="form-control" id="upload-ssl-ca" accept=".crt,.pem,.ca-bundle">
                  <small class="form-hint">Certificati intermedi per la catena di fiducia</small>
                </div>
                <div class="alert alert-warning">
                    <i class="ti ti-alert-triangle me-1"></i>
                    <strong>Attenzione:</strong> Il caricamento riavvierà il servizio web. La connessione verrà interrotta temporaneamente.
                </div>
              </div>
              <div class="modal-footer">
                <button type="button" class="btn btn-link link-secondary" data-bs-dismiss="modal">Annulla</button>
                <button type="button" class="btn btn-primary ms-auto" id="confirm-upload-ssl">
                  <i class="ti ti-upload me-1"></i>Carica e Riavvia
                </button>
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
        const [system, smtp, backup, network] = await Promise.all([
            apiGet('/settings/system'),
            apiGet('/settings/smtp'),
            apiGet('/settings/backup'),
            apiGet('/settings/network')
        ]);

        // Network
        document.getElementById('network-port').value = network.management_port;

        // SSL Info
        if (network.certificate) {
            document.getElementById('ssl-issuer').textContent = `Issuer: ${network.certificate.issuer}`;
            const validTo = new Date(network.certificate.valid_to).toLocaleDateString('it-IT');
            document.getElementById('ssl-validity').textContent = `Scadenza: ${validTo} (${network.certificate.days_remaining} giorni rimanenti)`;

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
            document.getElementById('ssl-status-badge').textContent = 'Nessuno';
        }

        // System
        document.getElementById('company-name').value = system.company_name || '';
        document.getElementById('primary-color').value = system.primary_color || '#206bc4';
        document.getElementById('primary-color-hex').value = system.primary_color || '#206bc4';
        document.getElementById('support-url').value = system.support_url || '';

        // Dark mode toggle (per-user preference)
        const darkToggle = document.getElementById('dark-mode-toggle');
        if (darkToggle) {
            darkToggle.checked = getCurrentTheme() === 'dark';
        }

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

        // Backup
        document.getElementById('backup-enabled').checked = backup.enabled;
        document.getElementById('backup-frequency').value = backup.frequency || 'daily';
        document.getElementById('backup-time').value = backup.time || '03:00';
        document.getElementById('backup-retention').value = backup.retention_days || 30;
        document.getElementById('backup-protocol').value = backup.remote_protocol || 'sftp';
        document.getElementById('backup-host').value = backup.remote_host || '';
        document.getElementById('backup-port').value = backup.remote_port || 22;
        document.getElementById('backup-path').value = backup.remote_path || '/';
        document.getElementById('backup-user').value = backup.remote_user || '';

        // Last backup status
        const statusEl = document.getElementById('backup-last-status');
        const alertEl = document.getElementById('backup-status-alert');
        if (backup.last_run_time) {
            const date = new Date(backup.last_run_time).toLocaleString('it-IT');
            const status = backup.last_run_status === 'success' ? 'completato' : backup.last_run_status;
            statusEl.textContent = `Ultimo backup: ${date} - ${status}`;
            alertEl.className = backup.last_run_status === 'success' ? 'alert alert-success mb-3' : 'alert alert-warning mb-3';
        } else {
            statusEl.textContent = 'Nessun backup eseguito';
        }

        // Show remote backup button only if remote is configured
        const remoteBtn = document.getElementById('backup-remote-btn');
        if (remoteBtn) {
            remoteBtn.style.display = (backup.remote_host && backup.remote_user) ? '' : 'none';
        }

        // Load backup history
        await loadBackupHistory();
        await loadRemoteBackupHistory();

        // Setup export/import listeners
        setupExportImportListeners();

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

    // Dark mode toggle
    document.getElementById('dark-mode-toggle')?.addEventListener('change', async (e) => {
        const newTheme = e.target.checked ? 'dark' : 'light';
        applyTheme(newTheme);
        try {
            const user = await apiGet('/auth/me');
            const allPrefs = JSON.parse(user.preferences || '{}');
            allPrefs.theme = newTheme;
            await apiPatch('/auth/me/preferences', { preferences: JSON.stringify(allPrefs) });
        } catch (err) {
            showToast('Errore salvataggio tema', 'error');
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
                retention_days: parseInt(document.getElementById('backup-retention').value) || 30,
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

    // Backup Locale - exports and saves on server
    document.getElementById('backup-local-btn')?.addEventListener('click', async () => {
        const btn = document.getElementById('backup-local-btn');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Backup...';
        btn.disabled = true;

        try {
            const result = await apiPost('/backup/export', {});
            showToast('Backup locale completato!', 'success');
            await loadBackupHistory();
        } catch (e) {
            showToast('Errore backup: ' + e.message, 'error');
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });

    // Backup Remoto - exports + uploads to configured remote
    document.getElementById('backup-remote-btn')?.addEventListener('click', async () => {
        const btn = document.getElementById('backup-remote-btn');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Backup...';
        btn.disabled = true;

        try {
            const result = await apiPost('/backup/run', {});
            if (result.success) {
                showToast('Backup remoto completato!', 'success');
                await loadBackupHistory();
                await loadRemoteBackupHistory();
            } else {
                showToast('Backup con errori: ' + (result.errors || []).join(', '), 'warning');
            }
        } catch (e) {
            showToast('Errore backup remoto: ' + e.message, 'error');
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });

    // Open Import/Restore Modal
    document.getElementById('open-import-modal-btn')?.addEventListener('click', () => {
        const modal = new bootstrap.Modal(document.getElementById('modal-import-config'));
        modal.show();
    });

    // Network - Save Port
    document.getElementById('save-port')?.addEventListener('click', async () => {
        const port = parseInt(document.getElementById('network-port').value);
        if (!port || port < 1 || port > 65535) {
            showToast('Porta non valida (1-65535)', 'error');
            return;
        }

        const confirmed = await confirmDialog(
            'Cambia Porta di Gestione',
            `<p>Stai per spostare il pannello alla porta <strong>${port}</strong>.</p>
            <div class="alert alert-warning mb-2">
                <div class="fw-bold mb-1"><i class="ti ti-shield-lock me-1"></i>Firewall — azione richiesta</div>
                <p class="mb-1">Prima di continuare, assicurati di aver aperto la porta nel firewall:</p>
                <code class="d-block p-1 bg-dark text-white rounded small">iptables -A INPUT -p tcp --dport ${port} -j ACCEPT</code>
                <p class="mt-1 mb-0 small text-muted">Senza questa regola il pannello non sarà più raggiungibile.</p>
            </div>
            <div class="alert alert-danger mb-0">
                <i class="ti ti-plug-connected-x me-1"></i>
                La connessione attuale verrà interrotta. Ricollegati a:<br>
                <strong>https://${location.hostname}:${port}</strong>
            </div>`,
            'Cambia e Riavvia',
            'btn-warning',
            true,
            ''
        );
        if (!confirmed) return;

        const btn = document.getElementById('save-port');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Riavvio...';
        btn.disabled = true;

        try {
            await apiPost('/settings/network/port', { port });
            showToast(`Porta cambiata a ${port}. Il servizio si sta riavviando...`, 'success');
            // Do not reload, connection will be lost
        } catch (e) {
            showToast('Errore cambio porta: ' + e.message, 'error');
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });

    // Network - Renew SSL
    document.getElementById('renew-ssl')?.addEventListener('click', async () => {
        const confirmed = await confirmDialog(
            'Rinnova Certificato',
            'Vuoi rigenerare il certificato Self-Signed per altri 10 anni? Il servizio web verrà riavviato.',
            'Rinnova',
            'btn-primary'
        );
        if (!confirmed) return;

        const btn = document.getElementById('renew-ssl');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>...';
        btn.disabled = true;

        try {
            await apiPost('/settings/network/ssl/renew', {});
            showToast('Certificato rinnovato. Ricarica la pagina se necessario.', 'success');
            setTimeout(() => location.reload(), 5000);
        } catch (e) {
            showToast('Errore rinnovo: ' + e.message, 'error');
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });

    // Network - Open Upload Modal
    document.getElementById('btn-upload-ssl-modal')?.addEventListener('click', () => {
        const modal = new bootstrap.Modal(document.getElementById('modal-upload-ssl'));
        modal.show();
    });

    // Network - Confirm Upload SSL
    document.getElementById('confirm-upload-ssl')?.addEventListener('click', async () => {
        const crtFile = document.getElementById('upload-ssl-crt').files[0];
        const keyFile = document.getElementById('upload-ssl-key').files[0];
        const caFile = document.getElementById('upload-ssl-ca').files[0];

        if (!crtFile || !keyFile) {
            showToast('Seleziona sia il certificato (.crt) che la chiave privata (.key)', 'warning');
            return;
        }

        const btn = document.getElementById('confirm-upload-ssl');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Caricamento...';
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
                throw new Error(err.detail || 'Upload fallito');
            }

            showToast('Certificato caricato con successo. Riavvio in corso...', 'success');
            const modal = bootstrap.Modal.getInstance(document.getElementById('modal-upload-ssl'));
            modal.hide();
            setTimeout(() => location.reload(), 5000);

        } catch (e) {
            showToast('Errore: ' + e.message, 'error');
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });
}


function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

async function loadBackupHistory() {
    const tbody = document.getElementById('backup-history-body');
    if (!tbody) return;

    try {
        const history = await apiGet('/backup/history');

        if (history.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Nessun backup disponibile</td></tr>';
            return;
        }

        tbody.innerHTML = history.map(backup => `
            <tr>
                <td><i class="ti ti-file-zip me-2"></i>${backup.filename}</td>
                <td>${formatFileSize(backup.size_bytes)}</td>
                <td>${new Date(backup.created_at).toLocaleString('it-IT')}</td>
                <td class="text-end">
                    <button class="btn btn-sm btn-ghost-warning" onclick="restoreFromLocalBackup('${backup.filename}')" title="Ripristina">
                        <i class="ti ti-refresh"></i>
                    </button>
                    <button class="btn btn-sm btn-ghost-primary" onclick="downloadLocalBackup('${backup.filename}')" title="Scarica">
                        <i class="ti ti-download"></i>
                    </button>
                    <button class="btn btn-sm btn-ghost-danger" onclick="deleteBackup('${backup.filename}')" title="Elimina">
                        <i class="ti ti-trash"></i>
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-danger">Errore caricamento storico</td></tr>';
    }
}

// ============== EXPORT & IMPORT SETUP ==============

function setupExportImportListeners() {
    // Import - Drag & Drop
    const dropzone = document.getElementById('import-dropzone');
    const fileInput = document.getElementById('import-file-input');

    if (dropzone && fileInput) {
        dropzone.addEventListener('click', () => fileInput.click());

        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.style.borderColor = 'var(--tblr-primary)';
            dropzone.style.background = 'var(--tblr-bg-surface-secondary)';
        });

        dropzone.addEventListener('dragleave', () => {
            dropzone.style.borderColor = '';
            dropzone.style.background = '';
        });

        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.style.borderColor = '';
            dropzone.style.background = '';
            const file = e.dataTransfer.files[0];
            if (file && file.name.endsWith('.tar.gz')) {
                handleImportFile(file);
            } else {
                showToast('Il file deve essere un archivio .tar.gz', 'warning');
            }
        });

        fileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) handleImportFile(file);
        });
    }

    // Load SCP files
    loadScpFiles();
}

// ============== IMPORT ==============

async function handleImportFile(file) {
    // First, preview
    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/api/backup/import/preview', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` },
            body: formData
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Preview fallito');
        }

        const preview = await response.json();
        showImportPreviewModal(preview, file);
    } catch (e) {
        showToast('Errore preview: ' + e.message, 'error');
    }
}

function showImportPreviewModal(preview, file, scpFilename = null) {
    const versionWarning = preview.source_version !== preview.current_version
        ? `<div class="alert alert-warning mb-3">
            <i class="ti ti-alert-triangle me-2"></i>
            <strong>Versione diversa!</strong> Sorgente: ${preview.source_version} → Corrente: ${preview.current_version}
           </div>`
        : '';

    // Build core section
    const coreUsers = (preview.core?.users || []).map(u =>
        `<tr>
            <td><i class="ti ti-user me-1"></i>${u.username}</td>
            <td>${u.is_superuser ? '<span class="badge bg-red-lt">Super Admin</span>' : '<span class="badge bg-blue-lt">Utente</span>'}</td>
            <td>${u.is_active ? '<span class="badge bg-green-lt">Attivo</span>' : '<span class="badge bg-secondary-lt">Disattivo</span>'}</td>
        </tr>`
    ).join('');

    // Build modules section
    const modulesHtml = Object.entries(preview.modules || {}).map(([modId, modData]) => {
        const tablesHtml = Object.entries(modData.tables || {}).map(([table, count]) =>
            `<div class="d-flex justify-content-between"><span class="text-muted">${table}</span><span class="badge bg-blue-lt">${count}</span></div>`
        ).join('');

        return `
            <div class="col-md-6">
                <div class="card card-sm">
                    <div class="card-body">
                        <div class="d-flex align-items-center mb-2">
                            <span class="avatar avatar-sm bg-purple-lt me-2"><i class="ti ti-puzzle"></i></span>
                            <strong>${modId}</strong>
                            ${modData.has_files ? '<span class="badge bg-cyan-lt ms-2">+ file</span>' : ''}
                        </div>
                        ${tablesHtml}
                    </div>
                </div>
            </div>`;
    }).join('');

    const modalHtml = `
        <div class="modal fade" id="import-preview-modal" tabindex="-1">
            <div class="modal-dialog modal-lg modal-dialog-centered modal-dialog-scrollable">
                <div class="modal-content">
                    <div class="modal-header bg-primary-lt">
                        <h5 class="modal-title"><i class="ti ti-file-import me-2"></i>Anteprima Importazione</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        ${versionWarning}
                        
                        <div class="d-flex gap-3 mb-3">
                            <span class="badge bg-blue-lt">Versione: ${preview.source_version}</span>
                            <span class="badge bg-secondary-lt">${new Date(preview.timestamp).toLocaleString('it-IT')}</span>
                        </div>

                        <!-- Core Section -->
                        <h4 class="mb-2"><i class="ti ti-settings me-2"></i>Core</h4>
                        
                        <div class="row g-3 mb-3">
                            <div class="col-12">
                                <div class="card card-sm">
                                    <div class="card-body">
                                        <div class="d-flex align-items-center mb-2">
                                            <span class="avatar avatar-sm bg-green-lt me-2"><i class="ti ti-users"></i></span>
                                            <strong>Utenti (${preview.core?.users?.length || 0})</strong>
                                        </div>
                                        ${coreUsers ? `
                                        <table class="table table-sm table-vcenter mb-0">
                                            <thead><tr><th>Username</th><th>Ruolo</th><th>Stato</th></tr></thead>
                                            <tbody>${coreUsers}</tbody>
                                        </table>` : '<span class="text-muted">Nessun utente</span>'}
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="card card-sm">
                                    <div class="card-body">
                                        <div class="d-flex align-items-center">
                                            <span class="avatar avatar-sm bg-orange-lt me-2"><i class="ti ti-shield"></i></span>
                                            <strong>Regole Firewall</strong>
                                            <span class="badge bg-orange-lt ms-auto">${preview.core?.firewall_rules || 0}</span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="card card-sm">
                                    <div class="card-body">
                                        <div class="d-flex align-items-center">
                                            <span class="avatar avatar-sm bg-cyan-lt me-2"><i class="ti ti-adjustments"></i></span>
                                            <strong>Impostazioni</strong>
                                            <span class="badge bg-cyan-lt ms-auto">${preview.core?.settings?.company_name || '-'}</span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Modules Section -->
                        ${modulesHtml ? `
                        <h4 class="mb-2"><i class="ti ti-puzzle me-2"></i>Moduli</h4>
                        <div class="row g-3">${modulesHtml}</div>
                        ` : ''}

                        <div class="alert alert-warning mt-3 mb-0">
                            <i class="ti ti-alert-circle me-2"></i>
                            <strong>Attenzione!</strong> L'importazione sovrascriverà le regole firewall e i dati dei moduli esistenti.
                            I moduli non attivi verranno attivati automaticamente.
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Annulla</button>
                        <button type="button" class="btn btn-primary" id="confirm-import-btn">
                            <i class="ti ti-file-import me-1"></i>Importa
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Remove existing modal if any
    document.getElementById('import-preview-modal')?.remove();
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    const modal = new bootstrap.Modal(document.getElementById('import-preview-modal'));
    modal.show();

    // Handle confirm
    document.getElementById('confirm-import-btn').addEventListener('click', async () => {
        modal.hide();

        const progressEl = document.getElementById('import-progress');
        if (progressEl) progressEl.classList.remove('d-none');

        try {
            let response;

            if (scpFilename) {
                // Import from SCP file
                response = await fetch(`/api/backup/import/from-file?filename=${encodeURIComponent(scpFilename)}`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` }
                });
            } else {
                // Import from uploaded file
                const formData = new FormData();
                formData.append('file', file);

                response = await fetch('/api/backup/import', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` },
                    body: formData
                });
            }

            const result = await response.json();

            if (progressEl) progressEl.classList.add('d-none');

            if (result.success || response.ok) {
                let summary = 'Importazione completata: ';
                summary += `${result.users_imported || 0} utenti, `;
                summary += `${result.firewall_rules_imported || 0} regole firewall, `;
                summary += `${result.modules_imported?.length || 0} moduli`;

                if (result.warnings?.length > 0) {
                    summary += '. Avvisi: ' + result.warnings.join(', ');
                }

                showToast(summary + '. MADMIN si riavvierà automaticamente...', 'success');
                setTimeout(() => location.reload(), 5000);
            } else {
                const errors = result.result?.errors || result.errors || ['Errore sconosciuto'];
                showToast('Importazione fallita: ' + errors.join(', '), 'error');
            }
        } catch (err) {
            if (progressEl) progressEl.classList.add('d-none');
            showToast('Errore importazione: ' + err.message, 'error');
        }
    });
}

// ============== SCP FILES ==============

async function loadScpFiles() {
    const container = document.getElementById('scp-files-list');
    if (!container) return;

    try {
        const files = await apiGet('/backup/import/files');

        if (files.length === 0) {
            container.innerHTML = '<div class="text-muted small">Nessun file disponibile</div>';
            return;
        }

        container.innerHTML = files.map(f => `
            <div class="d-flex align-items-center justify-content-between mb-2 p-2 bg-surface-secondary rounded">
                <div>
                    <i class="ti ti-file-zip me-1"></i>
                    <span class="small">${f.filename}</span>
                    <span class="badge bg-secondary-lt ms-1">${formatFileSize(f.size_bytes)}</span>
                </div>
                <button class="btn btn-sm btn-outline-primary" onclick="importScpFile('${f.filename}')">
                    <i class="ti ti-file-import me-1"></i>Importa
                </button>
            </div>
        `).join('');
    } catch (e) {
        container.innerHTML = '<div class="text-muted small">Errore caricamento</div>';
    }
}

window.importScpFile = async function (filename) {
    try {
        const response = await fetch(`/api/backup/import/preview/from-file?filename=${encodeURIComponent(filename)}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` }
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Preview fallito');
        }

        const preview = await response.json();
        showImportPreviewModal(preview, null, filename);
    } catch (e) {
        showToast('Errore preview: ' + e.message, 'error');
    }
};
// ============== RESTORE FROM LOCAL BACKUP ==============

window.restoreFromLocalBackup = async function (filename) {
    try {
        const response = await fetch(`/api/backup/restore/preview/${encodeURIComponent(filename)}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` }
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Preview fallito');
        }

        const preview = await response.json();
        showRestorePreviewModal(preview, filename);
    } catch (e) {
        showToast('Errore preview: ' + e.message, 'error');
    }
};

function showRestorePreviewModal(preview, filename) {
    const versionWarning = preview.source_version !== preview.current_version
        ? `<div class="alert alert-warning mb-3">
            <i class="ti ti-alert-triangle me-2"></i>
            <strong>Versione diversa!</strong> Sorgente: ${preview.source_version} → Corrente: ${preview.current_version}
           </div>`
        : '';

    const coreUsers = (preview.core?.users || []).map(u =>
        `<tr>
            <td><i class="ti ti-user me-1"></i>${u.username}</td>
            <td>${u.is_superuser ? '<span class="badge bg-red-lt">Super Admin</span>' : '<span class="badge bg-blue-lt">Utente</span>'}</td>
        </tr>`
    ).join('');

    const modulesHtml = Object.entries(preview.modules || {}).map(([modId, modData]) => {
        const tablesHtml = Object.entries(modData.tables || {}).map(([table, count]) =>
            `<div class="d-flex justify-content-between"><span class="text-muted small">${table}</span><span class="badge bg-blue-lt">${count}</span></div>`
        ).join('');

        return `
            <div class="col-md-6">
                <div class="card card-sm">
                    <div class="card-body py-2">
                        <div class="d-flex align-items-center mb-1">
                            <span class="avatar avatar-xs bg-purple-lt me-2"><i class="ti ti-puzzle"></i></span>
                            <strong class="small">${modId}</strong>
                            ${modData.has_files ? '<span class="badge bg-cyan-lt ms-auto">+ file</span>' : ''}
                        </div>
                        ${tablesHtml}
                    </div>
                </div>
            </div>`;
    }).join('');

    const modalHtml = `
        <div class="modal fade" id="restore-preview-modal" tabindex="-1">
            <div class="modal-dialog modal-lg modal-dialog-centered modal-dialog-scrollable">
                <div class="modal-content">
                    <div class="modal-header bg-warning-lt">
                        <h5 class="modal-title"><i class="ti ti-refresh me-2"></i>Conferma Ripristino</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        ${versionWarning}

                        <div class="d-flex gap-2 mb-3">
                            <span class="badge bg-blue-lt">v${preview.source_version}</span>
                            <span class="badge bg-secondary-lt">${new Date(preview.timestamp).toLocaleString('it-IT')}</span>
                            <span class="badge bg-secondary-lt">${filename}</span>
                        </div>

                        <div class="row g-2 mb-3">
                            <div class="col-12">
                                <div class="card card-sm">
                                    <div class="card-body py-2">
                                        <div class="d-flex align-items-center">
                                            <span class="avatar avatar-xs bg-green-lt me-2"><i class="ti ti-users"></i></span>
                                            <strong class="small">Utenti (${preview.core?.users?.length || 0})</strong>
                                        </div>
                                        ${coreUsers ? `<table class="table table-sm mb-0 mt-1"><tbody>${coreUsers}</tbody></table>` : ''}
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="card card-sm">
                                    <div class="card-body py-2 d-flex align-items-center">
                                        <span class="avatar avatar-xs bg-orange-lt me-2"><i class="ti ti-shield"></i></span>
                                        <strong class="small">Firewall</strong>
                                        <span class="badge bg-orange-lt ms-auto">${preview.core?.firewall_rules || 0}</span>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="card card-sm">
                                    <div class="card-body py-2 d-flex align-items-center">
                                        <span class="avatar avatar-xs bg-cyan-lt me-2"><i class="ti ti-adjustments"></i></span>
                                        <strong class="small">Impostazioni</strong>
                                        <span class="badge bg-cyan-lt ms-auto">${preview.core?.settings?.company_name || '-'}</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        ${modulesHtml ? `
                        <h4 class="mb-2"><i class="ti ti-puzzle me-1"></i>Moduli</h4>
                        <div class="row g-2">${modulesHtml}</div>
                        ` : ''}

                        <div class="alert alert-danger mt-3 mb-0">
                            <i class="ti ti-alert-circle me-2"></i>
                            <strong>Attenzione!</strong> Il ripristino sovrascriverà i dati correnti.
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Annulla</button>
                        <button type="button" class="btn btn-warning" id="confirm-restore-btn">
                            <i class="ti ti-refresh me-1"></i>Ripristina
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    document.getElementById('restore-preview-modal')?.remove();
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    const modal = new bootstrap.Modal(document.getElementById('restore-preview-modal'));
    modal.show();

    document.getElementById('confirm-restore-btn').addEventListener('click', async () => {
        modal.hide();
        showToast('Ripristino in corso...', 'info');

        try {
            const result = await apiPost(`/backup/restore/${encodeURIComponent(filename)}`, {});

            if (result.success !== false) {
                let summary = 'Ripristino completato: ';
                summary += `${result.users_imported || 0} utenti, `;
                summary += `${result.firewall_rules_imported || 0} regole firewall, `;
                summary += `${result.modules_imported?.length || 0} moduli`;

                showToast(summary + '. MADMIN si riavvierà automaticamente...', 'success');
                setTimeout(() => location.reload(), 5000);
            } else {
                showToast('Ripristino fallito: ' + (result.errors || []).join(', '), 'error');
            }
        } catch (err) {
            showToast('Errore ripristino: ' + err.message, 'error');
        }
    });
}


window.deleteBackup = async function (filename) {
    const confirmed = await confirmDialog(
        'Elimina File',
        `Eliminare definitivamente ${filename}?`,
        'Elimina',
        'btn-danger'
    );
    if (!confirmed) return;

    try {
        await fetch(`/api/backup/delete/${filename}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` }
        });
        showToast('File eliminato', 'success');
        await loadBackupHistory();
    } catch (e) {
        showToast('Errore eliminazione: ' + e.message, 'error');
    }
};

async function downloadLocalBackup(filename) {
    try {
        const response = await fetch(`/api/backup/download/${filename}`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` }
        });

        if (!response.ok) throw new Error('Download fallito');

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// ============== REMOTE BACKUP FUNCTIONS ==============

async function loadRemoteBackupHistory() {
    const tbody = document.getElementById('remote-backup-history-body');
    if (!tbody) return;

    // Pre-flight check: avoid 400 Bad Request if remote is obviously not configured
    const protocol = document.getElementById('backup-protocol')?.value;
    const host = document.getElementById('backup-host')?.value;
    if (!protocol || protocol === 'none' || !host) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Remote non configurato</td></tr>';
        return;
    }

    try {
        const history = await apiGet('/backup/remote/list');

        if (history.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Nessun backup remoto</td></tr>';
            return;
        }

        tbody.innerHTML = history.map(backup => `
            <tr>
                <td><i class="ti ti-cloud me-2"></i>${backup.filename}</td>
                <td>${formatFileSize(backup.size_bytes)}</td>
                <td>${backup.mtime ? new Date(backup.mtime).toLocaleString('it-IT') : '-'}</td>
                <td class="text-end">
                    <button class="btn btn-sm btn-ghost-primary" onclick="downloadRemoteBackup('${backup.filename}')" title="Scarica in locale">
                        <i class="ti ti-download"></i>
                    </button>
                    <button class="btn btn-sm btn-ghost-danger" onclick="deleteRemoteBackup('${backup.filename}')" title="Elimina">
                        <i class="ti ti-trash"></i>
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Remote non configurato</td></tr>';
    }
}

window.downloadRemoteBackup = async function (filename) {
    try {
        showToast('Download in corso...', 'info');
        const result = await apiPost(`/backup/remote/download/${filename}`, {});
        showToast('File scaricato in locale', 'success');
        await loadBackupHistory();
    } catch (e) {
        showToast('Errore download: ' + e.message, 'error');
    }
};

window.deleteRemoteBackup = async function (filename) {
    const confirmed = await confirmDialog(
        'Elimina Backup Remoto',
        `Eliminare definitivamente ${filename} dal server remoto?`,
        'Elimina',
        'btn-danger'
    );
    if (!confirmed) return;

    try {
        await apiDelete(`/backup/remote/delete/${filename}`);
        showToast('Backup remoto eliminato', 'success');
        await loadRemoteBackupHistory();
    } catch (e) {
        showToast('Errore eliminazione: ' + e.message, 'error');
    }
};

window.cleanupRemoteBackups = async function () {
    const confirmed = await confirmDialog(
        'Pulizia Backup Remoti',
        'Applicare la policy di retention ed eliminare i backup più vecchi?',
        'Applica',
        'btn-warning'
    );
    if (!confirmed) return;

    try {
        const result = await apiPost('/backup/remote/cleanup', {});
        showToast(`Pulizia completata: ${result.deleted_count} file eliminati`, 'success');
        await loadRemoteBackupHistory();
    } catch (e) {
        showToast('Errore pulizia: ' + e.message, 'error');
    }
};

// Make globally available
window.downloadLocalBackup = downloadLocalBackup;


/**
 * MADMIN - Settings View / appearance (company, color, logo, favicon, system language)
 */

import { apiPatch } from '../../api.js';
import { showToast } from '../../utils.js';
import { t } from '../../i18n.js';

export function appearanceHtml(canManage) {
    return `
        <div class="col-12">
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title"><i class="ti ti-palette me-2"></i>${t('settings.personalization')}</h3>
                </div>
                <div class="card-body">
                    <div class="row g-3">
                        <div class="col-md-4">
                            <label class="form-label">${t('settings.companyName')}</label>
                            <div class="input-group">
                                <input type="text" class="form-control" id="company-name" placeholder="MADMIN" ${canManage ? '' : 'disabled'}>
                                ${canManage ? `<button type="button" class="btn btn-outline-secondary" id="reset-company" title="${t('settings.resetDefault')}"><i class="ti ti-refresh"></i></button>` : ''}
                            </div>
                            <small class="form-hint">${t('settings.companyNameDefault')}</small>
                        </div>
                        <div class="col-md-4">
                            <label class="form-label">${t('settings.primaryColor')}</label>
                            <div class="input-group">
                                <input type="color" class="form-control form-control-color" id="primary-color" ${canManage ? '' : 'disabled'}>
                                <input type="text" class="form-control" id="primary-color-hex" placeholder="#206bc4" ${canManage ? '' : 'disabled'}>
                                ${canManage ? `<button type="button" class="btn btn-outline-secondary" id="reset-color" title="${t('settings.resetDefault')}"><i class="ti ti-refresh"></i></button>` : ''}
                            </div>
                            <small class="form-hint">${t('settings.primaryColorDefault')}</small>
                        </div>
                        <div class="col-md-4">
                            <label class="form-label">${t('settings.supportUrl')}</label>
                            <div class="input-group">
                                <input type="url" class="form-control" id="support-url" placeholder="https://..." ${canManage ? '' : 'disabled'}>
                                ${canManage ? `<button type="button" class="btn btn-outline-secondary" id="reset-support" title="${t('settings.remove')}"><i class="ti ti-x"></i></button>` : ''}
                            </div>
                        </div>
                        <div class="col-md-4">
                            <label class="form-label">${t('settings.language')}</label>
                            <select class="form-select" id="system-language" ${canManage ? '' : 'disabled'}>
                                <option value="en">English</option>
                                <option value="it">Italiano</option>
                            </select>
                            <small class="form-hint">${t('settings.languageHint')}</small>
                        </div>
                        <div class="col-md-4">
                            <label class="form-label">${t('settings.logo')}</label>
                            <div class="d-flex align-items-center gap-3">
                                <div id="logo-preview-container" class="border rounded p-2 d-flex align-items-center justify-content-center bg-dark"
                                     style="min-height: 50px; min-width: 120px;">
                                    <img id="logo-preview-img" src="/static/img/logo.png" style="max-height: 50px; max-width: 100%; object-fit: contain;">
                                </div>
                                ${canManage ? `
                                <div class="btn-group">
                                    <label class="btn btn-outline-primary btn-sm">
                                        <i class="ti ti-upload me-1"></i>${t('common.upload')}
                                        <input type="file" id="logo-upload" accept="image/*" class="d-none">
                                    </label>
                                    <button type="button" class="btn btn-outline-secondary btn-sm" id="reset-logo" title="${t('settings.remove')}">
                                        <i class="ti ti-x"></i>
                                    </button>
                                </div>
                                ` : ''}
                            </div>
                            <small class="form-hint">${t('settings.logoHint')}</small>
                        </div>
                        <div class="col-md-4">
                            <label class="form-label">${t('settings.favicon')}</label>
                            <div class="d-flex align-items-center gap-3">
                                <div id="favicon-preview-container" class="border rounded d-flex align-items-center justify-content-center bg-dark"
                                     style="width: 40px; height: 40px;">
                                    <img id="favicon-preview-img" src="/static/img/favicon.ico" style="height: 32px; width: 32px; object-fit: contain;">
                                </div>
                                ${canManage ? `
                                <div class="btn-group">
                                    <label class="btn btn-outline-primary btn-sm">
                                        <i class="ti ti-upload me-1"></i>${t('common.upload')}
                                        <input type="file" id="favicon-upload" accept="image/*,.ico" class="d-none">
                                    </label>
                                    <button type="button" class="btn btn-outline-secondary btn-sm" id="reset-favicon" title="${t('settings.resetDefault')}">
                                        <i class="ti ti-refresh"></i>
                                    </button>
                                </div>
                                ` : ''}
                            </div>
                            <small class="form-hint">${t('settings.faviconHint')}</small>
                        </div>
                        <div class="col-12">
                            ${canManage ? `<button class="btn btn-primary" id="save-system">${t('settings.saveSettings')}</button>` : ''}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

export function fillAppearance(system) {
    document.getElementById('company-name').value = system.company_name || '';
    document.getElementById('primary-color').value = system.primary_color || '#206bc4';
    document.getElementById('primary-color-hex').value = system.primary_color || '#206bc4';
    document.getElementById('support-url').value = system.support_url || '';

    const systemLangEl = document.getElementById('system-language');
    if (systemLangEl) systemLangEl.value = system.default_language || 'en';

    // Logo / favicon preview - use custom URL if set, otherwise default
    const logoPreviewImg = document.getElementById('logo-preview-img');
    if (logoPreviewImg) {
        logoPreviewImg.src = system.logo_url || '/static/img/logo.png';
    }
    const faviconPreviewImg = document.getElementById('favicon-preview-img');
    if (faviconPreviewImg) {
        faviconPreviewImg.src = system.favicon_url || '/static/img/favicon.ico';
    }
}

/**
 * Upload an image to /api/files/upload and persist its URL into the given
 * settings field (shared by logo and favicon).
 */
function bindImageUpload(inputId, previewId, settingsField, successKey) {
    document.getElementById(inputId)?.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        // Show preview immediately
        const reader = new FileReader();
        reader.onload = (ev) => {
            const img = document.getElementById(previewId);
            if (img) img.src = ev.target.result;
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

            if (!response.ok) throw new Error('Upload failed');
            const data = await response.json();

            // Save URL to settings
            await apiPatch('/settings/system', { [settingsField]: data.url });
            showToast(t(successKey), 'success');
        } catch (err) {
            showToast(t('settings.uploadError', { error: err.message }), 'error');
        }
    });
}

export function bindAppearance() {
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
        showToast(t('settings.colorReset'), 'info');
    });

    // Reset company name to default
    document.getElementById('reset-company')?.addEventListener('click', async () => {
        document.getElementById('company-name').value = 'MADMIN';
        try {
            await apiPatch('/settings/system', { company_name: 'MADMIN' });
            showToast(t('settings.companyNameReset'), 'success');
        } catch (e) { showToast(e.message, 'error'); }
    });

    // Reset support URL (clear)
    document.getElementById('reset-support')?.addEventListener('click', async () => {
        document.getElementById('support-url').value = '';
        try {
            await apiPatch('/settings/system', { support_url: '' });
            showToast(t('settings.supportUrlRemoved'), 'success');
        } catch (e) { showToast(e.message, 'error'); }
    });

    // Reset logo (restore default)
    document.getElementById('reset-logo')?.addEventListener('click', async () => {
        try {
            await apiPatch('/settings/system', { logo_url: null });
            const logoImg = document.getElementById('logo-preview-img');
            if (logoImg) logoImg.src = '/static/img/logo.png';
            showToast(t('settings.logoRemoved'), 'success');
        } catch (e) { showToast(e.message, 'error'); }
    });

    // Reset favicon (restore default)
    document.getElementById('reset-favicon')?.addEventListener('click', async () => {
        try {
            await apiPatch('/settings/system', { favicon_url: null });
            const faviconImg = document.getElementById('favicon-preview-img');
            if (faviconImg) faviconImg.src = '/static/img/favicon.ico';
            showToast(t('settings.faviconReset'), 'success');
        } catch (e) { showToast(e.message, 'error'); }
    });

    bindImageUpload('logo-upload', 'logo-preview-img', 'logo_url', 'settings.logoUploaded');
    bindImageUpload('favicon-upload', 'favicon-preview-img', 'favicon_url', 'settings.faviconUploaded');

    // Save appearance settings
    document.getElementById('save-system')?.addEventListener('click', async () => {
        try {
            const companyName = document.getElementById('company-name').value || 'MADMIN';
            const primaryColor = document.getElementById('primary-color').value;
            const supportUrl = document.getElementById('support-url').value || '';
            const systemLang = document.getElementById('system-language')?.value || 'en';

            await apiPatch('/settings/system', {
                company_name: companyName,
                primary_color: primaryColor,
                support_url: supportUrl,
                default_language: systemLang
            });

            // Apply changes immediately to UI
            document.title = `${companyName} - Dashboard`;

            const brandText = document.getElementById('navbar-brand-text');
            if (brandText) brandText.textContent = companyName;

            const mobileBrand = document.getElementById('mobile-brand-name');
            if (mobileBrand) mobileBrand.textContent = companyName;

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

            showToast(t('settings.settingsSaved'), 'success');
        } catch (e) { showToast(e.message, 'error'); }
    });
}

/**
 * MADMIN - Settings View / personal preferences (theme, language)
 */

import { apiGet, apiPatch } from '../../api.js';
import { showToast } from '../../utils.js';
import { applyTheme, getCurrentTheme } from '../../app.js';
import { t, init as i18nInit, getLang } from '../../i18n.js';

export function preferencesHtml() {
    return `
        <div class="col-12">
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title"><i class="ti ti-user-cog me-2"></i>${t('settings.personalPreferences')}</h3>
                    <div class="card-options">
                        <span class="text-muted small">${t('settings.personalPreferencesHint')}</span>
                    </div>
                </div>
                <div class="card-body">
                    <div class="row g-3 align-items-center">
                        <div class="col-md-4">
                            <label class="form-label">${t('settings.myLanguage')}</label>
                            <select class="form-select" id="my-language">
                                <option value="en">English</option>
                                <option value="it">Italiano</option>
                            </select>
                            <small class="form-hint">${t('settings.myLanguageHint')}</small>
                        </div>
                        <div class="col-md-4 d-flex align-items-end">
                            <div>
                                <label class="form-check form-switch">
                                    <input type="checkbox" class="form-check-input" id="dark-mode-toggle">
                                    <span class="form-check-label">${t('settings.darkMode')}</span>
                                </label>
                                <small class="form-hint">${t('settings.darkModeHint')}</small>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

export function fillPreferences() {
    const darkToggle = document.getElementById('dark-mode-toggle');
    if (darkToggle) {
        darkToggle.checked = getCurrentTheme() === 'dark';
    }
    const myLangEl = document.getElementById('my-language');
    if (myLangEl) myLangEl.value = getLang();
}

export function bindPreferences() {
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
            showToast(t('settings.themeError'), 'error');
        }
    });

    // Personal language change
    document.getElementById('my-language')?.addEventListener('change', async (e) => {
        const newLang = e.target.value;
        try {
            const user = await apiGet('/auth/me');
            const allPrefs = JSON.parse(user.preferences || '{}');
            allPrefs.lang = newLang;
            await apiPatch('/auth/me/preferences', { preferences: JSON.stringify(allPrefs) });
            localStorage.setItem('madmin_lang', newLang);
            await i18nInit(newLang);
            showToast(t('settings.settingsSaved'), 'success');
            setTimeout(() => location.reload(), 800);
        } catch (err) {
            showToast(t('settings.themeError'), 'error');
        }
    });
}

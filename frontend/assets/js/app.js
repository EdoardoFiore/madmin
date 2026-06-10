/**
 * MADMIN - Main Application Module
 *
 * Bootstraps the SPA: auth check, i18n, shell (menu/theme), session watch,
 * 2FA enforcement and the hash router. The implementation lives in core/*;
 * this file stays the stable entry point and contract facade.
 *
 * FROZEN MODULE CONTRACT — installable modules import this file by URL
 * (/static/js/app.js). Do NOT rename, remove, or change the signature of:
 *   checkPermission
 * The router must keep importing /static/modules/{id}/views/main.js and
 * calling its exported render(container, params).
 * Additive changes only.
 */

import { isAuthenticated, redirectToLogin, getCurrentUser } from './api.js';
import { init as i18nInit, detectLang, translateDOM } from './i18n.js';
import { installErrorBoundary } from './core/errors.js';
import { initShell, loadMenu, loadSystemSettings, updateUserDisplay, applyUserTheme } from './core/shell.js';
import { startRouter } from './core/router.js';
import { startSessionWatch } from './core/session.js';
import { check2FAEnforcement } from './core/twofa.js';

// Re-exported shell helpers (used by core views; applyTheme also by settings)
export { setPageActions, applyTheme, getCurrentTheme } from './core/shell.js';

// Current user data
let currentUser = null;

/**
 * Initialize the application
 */
async function init() {
    console.log('MADMIN initializing...');

    installErrorBoundary();

    // Check authentication
    if (!isAuthenticated()) {
        redirectToLogin();
        return;
    }

    // Load user info
    try {
        currentUser = await getCurrentUser();
    } catch (error) {
        console.error('Failed to get user info:', error);
        redirectToLogin();
        return;
    }

    // Warn before the JWT expires; redirect to login when it does
    startSessionWatch();

    // Load system settings to get default language before i18n init
    let systemDefault = 'en';
    try {
        const sysSettings = await fetch('/api/settings/system', {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` }
        });
        if (sysSettings.ok) {
            const s = await sysSettings.json();
            systemDefault = s.default_language || 'en';
        }
    } catch { /* ignore */ }

    // Initialize i18n
    const lang = detectLang(currentUser, systemDefault);
    localStorage.setItem('madmin_lang', lang);
    await i18nInit(lang);

    // Translate static HTML elements
    translateDOM();

    // Check if 2FA is enforced but not enabled - force user to set it up
    await check2FAEnforcement();

    // Shell: brand/colors, user display, theme, menu, mobile/dropdown handlers
    initShell({ getUser: () => currentUser, hasPermission });
    updateUserDisplay();
    await loadSystemSettings();
    applyUserTheme();
    await loadMenu();

    // Routing
    startRouter();

    console.log('MADMIN ready');
}

/**
 * Check if current user has a permission
 */
function hasPermission(permission) {
    if (!currentUser) return false;
    if (currentUser.is_superuser) return true;
    if (currentUser.permissions.includes('*')) return true;
    return currentUser.permissions.includes(permission);
}

/**
 * Get current user
 */
export function getUser() {
    return currentUser;
}

/**
 * Check user permission
 */
export function checkPermission(permission) {
    return hasPermission(permission);
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', init);

/**
 * MADMIN - Application Shell (internal, not part of the module contract)
 *
 * Everything around the routed content: sidebar menu, mobile menu, theme,
 * dropdowns, page title/actions, system customizations (brand, colors, logo).
 *
 * Dependencies on user state are injected via initShell() to keep this module
 * free of circular imports with app.js.
 */

import { apiPatch, clearToken, redirectToLogin } from '../api.js';
import { t } from '../i18n.js';

let _getUser = () => null;
let _hasPermission = () => false;

/**
 * Inject user-state accessors and bind all shell event listeners.
 */
export function initShell({ getUser, hasPermission }) {
    _getUser = getUser;
    _hasPermission = hasPermission;

    setupLogout();
    setupNavigation();
    setupMobileMenu();
    setupThemeToggle();
    setupDropdowns();
}

function isSafeUrl(url) {
    if (url.startsWith('//')) return false;  // block protocol-relative URLs
    try {
        const u = new URL(url, window.location.origin);
        return ['http:', 'https:'].includes(u.protocol);
    } catch { return false; }
}

/**
 * Load and apply system settings (company name, primary color, etc.)
 */
export async function loadSystemSettings() {
    try {
        const response = await fetch('/api/settings/system', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('madmin_token')}`
            }
        });

        if (!response.ok) return;

        const settings = await response.json();

        // Apply company name to browser title, sidebar, and mobile header
        if (settings.company_name) {
            document.title = `${settings.company_name} - Dashboard`;
            // Desktop sidebar brand
            const brandText = document.getElementById('navbar-brand-text');
            if (brandText) {
                brandText.textContent = settings.company_name;
            }
            // Mobile header brand
            const mobileBrand = document.getElementById('mobile-brand-name');
            if (mobileBrand) {
                mobileBrand.textContent = settings.company_name;
            }
        }

        // Apply primary color as CSS variable
        if (settings.primary_color && /^#(?:[0-9a-fA-F]{3}){1,2}$/.test(settings.primary_color)) {
            const safeColor = settings.primary_color;
            document.documentElement.style.setProperty('--madmin-primary', safeColor);
            document.documentElement.style.setProperty('--tblr-primary', safeColor);
            const style = document.createElement('style');
            style.textContent = `
                .btn-primary { background-color: ${safeColor} !important; border-color: ${safeColor} !important; }
                .nav-link.active { background-color: ${safeColor} !important; }
                .text-primary { color: ${safeColor} !important; }
            `;
            document.head.appendChild(style);
        }

        // Apply logo - use custom URL if set, otherwise default logo.png is already in src
        const logoImg = document.getElementById('navbar-logo-img');
        const mobileLogoImg = document.getElementById('mobile-logo-img');
        if (settings.logo_url && isSafeUrl(settings.logo_url)) {
            if (logoImg) logoImg.src = settings.logo_url;
            if (mobileLogoImg) mobileLogoImg.src = settings.logo_url;
        }

        // Apply favicon if set (override default favicon.ico)
        if (settings.favicon_url && isSafeUrl(settings.favicon_url)) {
            const faviconLink = document.getElementById('favicon-link');
            if (faviconLink) {
                faviconLink.href = settings.favicon_url;
            }
        }

        // Show support URL in footer if configured (inline with version)
        if (settings.support_url && isSafeUrl(settings.support_url)) {
            const supportLink = document.getElementById('support-link');
            const supportItem = document.getElementById('support-link-item');
            if (supportLink && supportItem) {
                supportLink.href = settings.support_url;
                supportItem.style.display = 'list-item';
            }
        }

        // Update footer brand with company name
        if (settings.company_name) {
            const footerBrand = document.getElementById('footer-brand');
            if (footerBrand) {
                footerBrand.textContent = settings.company_name;
            }
        }

    } catch (error) {
        console.error('Failed to load system settings:', error);
    }
}

/**
 * Update user display in sidebar
 */
export function updateUserDisplay() {
    const userNameEl = document.getElementById('user-name');
    const user = _getUser();
    if (userNameEl && user) {
        userNameEl.textContent = user.username;
    }
}

/**
 * Setup logout button
 */
function setupLogout() {
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', (e) => {
            e.preventDefault();
            clearToken();
            redirectToLogin();
        });
    }
}

/**
 * Apply user theme from preferences
 */
export function applyUserTheme() {
    const user = _getUser();
    if (!user) return;
    try {
        const prefs = JSON.parse(user.preferences || '{}');
        const theme = prefs.theme || 'light';
        applyTheme(theme);
    } catch (e) {
        applyTheme('light');
    }
}

/**
 * Apply a theme and update toggle UI
 */
export function applyTheme(theme) {
    document.documentElement.setAttribute('data-bs-theme', theme);
    // Update toggle button UI
    const icon = document.getElementById('theme-toggle-icon');
    const label = document.getElementById('theme-toggle-label');
    if (icon) {
        icon.className = theme === 'dark' ? 'ti ti-sun me-2' : 'ti ti-moon me-2';
    }
    if (label) {
        label.textContent = theme === 'dark' ? t('auth.lightTheme') : t('auth.darkTheme');
    }
}

/**
 * Get current theme
 */
export function getCurrentTheme() {
    return document.documentElement.getAttribute('data-bs-theme') || 'light';
}

/**
 * Setup theme toggle in user dropdown
 */
function setupThemeToggle() {
    const toggleBtn = document.getElementById('theme-toggle-btn');
    if (!toggleBtn) return;

    toggleBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        const newTheme = getCurrentTheme() === 'dark' ? 'light' : 'dark';
        applyTheme(newTheme);

        // Save to user preferences
        const user = _getUser();
        if (!user) return;
        try {
            const allPrefs = JSON.parse(user.preferences || '{}');
            allPrefs.theme = newTheme;
            const prefsStr = JSON.stringify(allPrefs);
            await apiPatch('/auth/me/preferences', { preferences: prefsStr });
            user.preferences = prefsStr;
        } catch (err) {
            console.error('Failed to save theme preference:', err);
        }
    });
}

/**
 * Setup navigation click handlers
 */
function setupNavigation() {
    const navMenu = document.getElementById('nav-menu');
    if (navMenu) {
        navMenu.addEventListener('click', (e) => {
            const link = e.target.closest('a.nav-link');
            if (link) {
                // Update active state
                navMenu.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
                link.classList.add('active');
                // Close mobile menu on navigation
                closeMobileMenu();
            }
        });
    }
}

/**
 * Setup mobile menu toggle
 */
function setupMobileMenu() {
    const toggleBtn = document.getElementById('mobile-menu-toggle');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('mobile-overlay');

    if (!toggleBtn || !sidebar) return;

    // Toggle menu on hamburger click
    toggleBtn.addEventListener('click', () => {
        sidebar.classList.toggle('mobile-open');
        overlay?.classList.toggle('show');
    });

    // Close on overlay click
    overlay?.addEventListener('click', closeMobileMenu);
}

/**
 * Close mobile menu
 */
export function closeMobileMenu() {
    document.getElementById('sidebar')?.classList.remove('mobile-open');
    document.getElementById('mobile-overlay')?.classList.remove('show');
}

/**
 * Global Dropdown Manager
 */
function setupDropdowns() {
    // Toggle on trigger click
    document.addEventListener('click', (e) => {
        const trigger = e.target.closest('[data-bs-toggle="dropdown"]');

        if (trigger) {
            e.preventDefault();
            e.stopPropagation();

            const parent = trigger.closest('.dropdown, .dropup, .dropend, .dropstart, [id$="-dropdown"]');
            const menu = parent ? parent.querySelector('.dropdown-menu') : null;

            if (!menu) return;

            const isOpen = menu.classList.contains('show');

            // Close all other open dropdowns first
            closeAllDropdowns();

            if (!isOpen) {
                trigger.classList.add('show');
                trigger.setAttribute('aria-expanded', 'true');
                menu.classList.add('show');
            }
        } else {
            // Clicked outside - close all dropdowns
            closeAllDropdowns();
        }
    }, true);

    document.addEventListener('click', (e) => {
        const menuEl = e.target.closest('.dropdown-menu.show');
        if (menuEl) {
            const parent = menuEl.closest('.dropdown, .dropup, .dropend, .dropstart, [id$="-dropdown"]');
            const trigger = parent?.querySelector('[data-bs-toggle="dropdown"]');
            const autoClose = trigger?.getAttribute('data-bs-auto-close');

            if (autoClose !== 'outside') {
                closeAllDropdowns();
            }
        }
    });
}

/**
 * Close all currently open dropdowns
 */
function closeAllDropdowns() {
    document.querySelectorAll('.dropdown-menu.show').forEach(menu => {
        menu.classList.remove('show');
    });
    document.querySelectorAll('[data-bs-toggle="dropdown"].show').forEach(trigger => {
        trigger.classList.remove('show');
        trigger.setAttribute('aria-expanded', 'false');
    });
}

/**
 * Load menu from API
 */
export async function loadMenu() {
    const navMenu = document.getElementById('nav-menu');
    if (!navMenu) return;

    try {
        const response = await fetch('/api/ui/menu', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('madmin_token')}`
            }
        });

        if (!response.ok) throw new Error('Failed to load menu');

        const menuData = await response.json();

        // Build menu HTML
        let menuHtml = '';

        // Core menu items
        for (const item of menuData.core) {
            if (item.permission && !_hasPermission(item.permission)) {
                continue;
            }
            menuHtml += createMenuItem(item);
        }

        // Module menu items
        if (menuData.modules && menuData.modules.length > 0) {
            const visibleModules = menuData.modules.filter(item =>
                !item.permission || _hasPermission(item.permission)
            );

            if (visibleModules.length > 0) {
                menuHtml += `
                    <li class="nav-item pt-3">
                        <span class="nav-link disabled text-uppercase text-muted" style="font-size: 0.7rem;">
                            ${t('menu.modulesSection')}
                        </span>
                    </li>
                `;

                for (const item of visibleModules) {
                    menuHtml += createMenuItem(item);
                }
            }
        }

        navMenu.innerHTML = menuHtml;

    } catch (error) {
        console.error('Failed to load menu:', error);
    }
}

/**
 * Create a menu item HTML - supports both Tabler icons and custom URLs
 */
function createMenuItem(item) {
    let iconHtml;
    if (item.icon && (item.icon.startsWith('http://') || item.icon.startsWith('https://'))) {
        iconHtml = `<img src="${item.icon}" alt="" class="module-icon-menu" style="width: 20px; height: 20px;">`;
    } else {
        const iconClass = item.icon ? `ti-${item.icon}` : 'ti-circle';
        iconHtml = `<i class="ti ${iconClass}"></i>`;
    }
    // item.label is either a translation key (e.g. "menu.users") or a display name (module names)
    const label = item.label.includes('.') ? t(item.label) : item.label;
    return `
        <li class="nav-item">
            <a class="nav-link" href="${item.route}">
                <span class="nav-link-icon d-md-none d-lg-inline-block">
                    ${iconHtml}
                </span>
                <span class="nav-link-title">${label}</span>
            </a>
        </li>
    `;
}

/**
 * Update active menu item for the current route
 */
export function updateActiveMenuItem(viewName) {
    const navMenu = document.getElementById('nav-menu');
    if (!navMenu) return;

    navMenu.querySelectorAll('.nav-link').forEach(link => {
        const href = link.getAttribute('href');
        const linkView = href ? href.replace('#', '').split('/')[0] : '';

        if (linkView === viewName) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });
}

/**
 * Set the page title in the header
 */
export function setPageTitle(title) {
    const pageTitle = document.getElementById('page-title');
    if (pageTitle) {
        pageTitle.textContent = title;
    }
}

/**
 * Set page actions (buttons in header)
 */
export function setPageActions(html) {
    const pageActions = document.getElementById('page-actions');
    if (pageActions) {
        pageActions.innerHTML = html;
    }
}

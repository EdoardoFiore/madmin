/**
 * MADMIN - Main Application Module
 * 
 * Handles routing, menu loading, and view rendering.
 * Uses ES modules for dynamic view loading.
 */

import { isAuthenticated, redirectToLogin, getCurrentUser, clearToken } from './api.js';
import { showToast, loadingSpinner } from './utils.js';

// View registry - maps routes to view modules
const views = {
    'dashboard': () => import('./views/dashboard.js'),
    'users': () => import('./views/users.js'),
    'firewall': () => import('./views/firewall.js'),
    'network': () => import('./views/network.js'),
    'crontab': () => import('./views/crontab.js'),
    'settings': () => import('./views/settings.js'),
    'modules': () => import('./views/modules.js'),
};

// Current user data
let currentUser = null;

/**
 * Initialize the application
 */
async function init() {
    console.log('MADMIN initializing...');

    // Check authentication
    if (!isAuthenticated()) {
        redirectToLogin();
        return;
    }

    // Load user info
    try {
        currentUser = await getCurrentUser();
        updateUserDisplay();
    } catch (error) {
        console.error('Failed to get user info:', error);
        redirectToLogin();
        return;
    }

    // Load and apply system settings (customizations)
    await loadSystemSettings();

    // Setup event listeners
    setupLogout();
    setupNavigation();
    setupMobileMenu();

    // Load menu
    await loadMenu();

    // Handle initial route
    handleRoute();

    // Listen for hash changes
    window.addEventListener('hashchange', handleRoute);

    console.log('MADMIN ready');
}

/**
 * Load and apply system settings (company name, primary color, etc.)
 */
async function loadSystemSettings() {
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
        if (settings.primary_color) {
            document.documentElement.style.setProperty('--madmin-primary', settings.primary_color);
            document.documentElement.style.setProperty('--tblr-primary', settings.primary_color);
            const style = document.createElement('style');
            style.textContent = `
                .btn-primary { background-color: ${settings.primary_color} !important; border-color: ${settings.primary_color} !important; }
                .nav-link.active { background-color: ${settings.primary_color} !important; }
                .text-primary { color: ${settings.primary_color} !important; }
            `;
            document.head.appendChild(style);
        }

        // Apply logo if set - show img and hide default icon
        if (settings.logo_url) {
            const logoImg = document.getElementById('navbar-logo-img');
            const logoDefault = document.getElementById('navbar-logo-default');
            if (logoImg && logoDefault) {
                logoImg.src = settings.logo_url;
                logoImg.classList.remove('d-none');
                logoDefault.classList.add('d-none');
            }
        }

        // Apply favicon if set (override default)
        if (settings.favicon_url) {
            const faviconLink = document.getElementById('favicon-link');
            if (faviconLink) {
                faviconLink.href = settings.favicon_url;
            }
        }

        // Show support URL in footer if configured (inline with version)
        if (settings.support_url) {
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
function updateUserDisplay() {
    const userNameEl = document.getElementById('user-name');
    if (userNameEl && currentUser) {
        userNameEl.textContent = currentUser.username;
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
function closeMobileMenu() {
    document.getElementById('sidebar')?.classList.remove('mobile-open');
    document.getElementById('mobile-overlay')?.classList.remove('show');
}

/**
 * Load menu from API
 */
async function loadMenu() {
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
            // Check permission (null = always visible)
            if (item.permission && !hasPermission(item.permission)) {
                continue;
            }

            menuHtml += createMenuItem(item);
        }

        // Module menu items (if any)
        if (menuData.modules && menuData.modules.length > 0) {
            menuHtml += `
                <li class="nav-item pt-3">
                    <span class="nav-link disabled text-uppercase text-muted" style="font-size: 0.7rem;">
                        Moduli
                    </span>
                </li>
            `;

            for (const item of menuData.modules) {
                menuHtml += createMenuItem(item);
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
    return `
        <li class="nav-item">
            <a class="nav-link" href="${item.route}">
                <span class="nav-link-icon d-md-none d-lg-inline-block">
                    ${iconHtml}
                </span>
                <span class="nav-link-title">${item.label}</span>
            </a>
        </li>
    `;
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
 * Handle route changes
 */
async function handleRoute() {
    const hash = window.location.hash.slice(1) || 'dashboard';
    const [viewName, ...params] = hash.split('/');

    // Update page title
    const pageTitle = document.getElementById('page-title');
    if (pageTitle) {
        pageTitle.textContent = getViewTitle(viewName);
    }

    // Update active menu item
    updateActiveMenuItem(viewName);

    // Clear page actions
    const pageActions = document.getElementById('page-actions');
    if (pageActions) {
        pageActions.innerHTML = '';
    }

    // Load view
    const contentEl = document.getElementById('app-content');
    if (!contentEl) return;

    contentEl.innerHTML = loadingSpinner();

    try {
        let viewModule;

        // Check if this is a module view (route starts with module ID like "wireguard", "openvpn", etc.)
        // Module views are loaded dynamically from /static/modules/{moduleId}/views/main.js
        if (!views[viewName]) {
            // Try to load as module view
            try {
                viewModule = await import(`/static/modules/${viewName}/views/main.js`);
            } catch (moduleError) {
                // Not a core view and not a module - show 404
                contentEl.innerHTML = `
                    <div class="card">
                        <div class="card-body text-center py-5">
                            <i class="ti ti-error-404 text-muted" style="font-size: 4rem;"></i>
                            <h3 class="mt-3">Pagina non trovata</h3>
                            <p class="text-muted">La pagina richiesta non esiste.</p>
                            <a href="#dashboard" class="btn btn-primary">Torna alla Dashboard</a>
                        </div>
                    </div>
                `;
                return;
            }
        } else {
            // Core view
            const viewLoader = views[viewName];
            viewModule = await viewLoader();
        }

        await viewModule.render(contentEl, params);

    } catch (error) {
        console.error('Failed to load view:', error);
        contentEl.innerHTML = `
            <div class="card">
                <div class="card-body text-center py-5">
                    <i class="ti ti-alert-circle text-danger" style="font-size: 4rem;"></i>
                    <h3 class="mt-3">Errore di caricamento</h3>
                    <p class="text-muted">${error.message}</p>
                    <button class="btn btn-primary" onclick="location.reload()">Ricarica</button>
                </div>
            </div>
        `;
    }
}

/**
 * Get human-readable title for a view
 */
function getViewTitle(viewName) {
    const titles = {
        'dashboard': 'Dashboard',
        'users': 'Gestione Utenti',
        'firewall': 'Firewall Macchina',
        'network': 'Interfacce di Rete',
        'crontab': 'Gestione Crontab',
        'settings': 'Impostazioni',
        'modules': 'Gestione Moduli',
    };
    return titles[viewName] || viewName.charAt(0).toUpperCase() + viewName.slice(1);
}

/**
 * Update active menu item
 */
function updateActiveMenuItem(viewName) {
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
 * Set page actions (buttons in header)
 */
export function setPageActions(html) {
    const pageActions = document.getElementById('page-actions');
    if (pageActions) {
        pageActions.innerHTML = html;
    }
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

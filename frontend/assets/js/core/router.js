/**
 * MADMIN - Hash Router (internal, not part of the module contract)
 *
 * Routes #viewName/param1/param2 to core views (lazy-imported from views/)
 * or module views (imported from /static/modules/{id}/views/main.js — this
 * import path and the render(container, params) signature are FROZEN).
 *
 * View lifecycle: before a new view renders, the previous view module's
 * optional exported destroy() is called (cleanup of intervals, charts, …).
 */

import { loadingSpinner } from '../utils.js';
import { t, loadModuleTranslations } from '../i18n.js';
import { updateActiveMenuItem, setPageTitle, setPageActions } from './shell.js';

// View registry - maps routes to view modules
const views = {
    'dashboard': () => import('../views/dashboard/index.js'),
    'users': () => import('../views/users/index.js'),
    'firewall': () => import('../views/firewall/index.js'),
    'network': () => import('../views/network.js'),
    'crontab': () => import('../views/crontab.js'),
    'settings': () => import('../views/settings.js'),
    'modules': () => import('../views/modules.js'),
    'logs': () => import('../views/logs/index.js'),
};

let _currentModule = null;

/**
 * Start the router: handle the current hash and listen for changes.
 */
export function startRouter() {
    handleRoute();
    window.addEventListener('hashchange', handleRoute);
}

/**
 * Handle route changes
 */
export async function handleRoute() {
    let hash = window.location.hash.slice(1);

    // Remove leading slash if present
    if (hash.startsWith('/')) {
        hash = hash.substring(1);
    }

    // Default route
    if (!hash) hash = 'dashboard';

    const [viewName, ...params] = hash.split('/');

    setPageTitle(getViewTitle(viewName));
    updateActiveMenuItem(viewName);
    setPageActions('');

    // Load view
    const contentEl = document.getElementById('app-content');
    if (!contentEl) return;

    // Let the outgoing view clean up (intervals, chart instances, …)
    try {
        _currentModule?.destroy?.();
    } catch (e) {
        console.error('View destroy() failed:', e);
    }
    _currentModule = null;

    contentEl.innerHTML = loadingSpinner();

    try {
        let viewModule;

        if (!views[viewName]) {
            // Try to load as module view
            try {
                await loadModuleTranslations(viewName);
                viewModule = await import(`/static/modules/${viewName}/views/main.js`);
            } catch (moduleError) {
                // Not a core view and not a module - show 404
                contentEl.innerHTML = `
                    <div class="card">
                        <div class="card-body text-center py-5">
                            <i class="ti ti-error-404 text-muted" style="font-size: 4rem;"></i>
                            <h3 class="mt-3">${t('app.pageNotFound')}</h3>
                            <p class="text-muted">${t('app.pageNotFoundDesc')}</p>
                            <a href="#dashboard" class="btn btn-primary">${t('app.backToDashboard')}</a>
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

        _currentModule = viewModule;
        await viewModule.render(contentEl, params);

        // Subtle enter transition (CSS-only, respects prefers-reduced-motion)
        contentEl.classList.remove('view-enter');
        void contentEl.offsetWidth; // restart the animation
        contentEl.classList.add('view-enter');

    } catch (error) {
        console.error('Failed to load view:', error);
        contentEl.innerHTML = `
            <div class="card">
                <div class="card-body text-center py-5">
                    <i class="ti ti-alert-circle text-danger" style="font-size: 4rem;"></i>
                    <h3 class="mt-3">${t('app.loadingError')}</h3>
                    <p class="text-muted">${error.message}</p>
                    <button class="btn btn-primary" data-route-retry>${t('app.retry')}</button>
                </div>
            </div>
        `;
        // Retry re-runs the route instead of reloading the whole app
        contentEl.querySelector('[data-route-retry]')?.addEventListener('click', handleRoute);
    }
}

/**
 * Get human-readable title for a view
 */
function getViewTitle(viewName) {
    const titles = {
        'dashboard': t('menu.dashboard'),
        'users': t('menu.users'),
        'firewall': t('menu.firewall'),
        'network': t('menu.network'),
        'crontab': t('menu.crontab'),
        'settings': t('menu.settings'),
        'modules': t('menu.modules'),
        'logs': t('menu.logs'),
    };
    return titles[viewName] || viewName.charAt(0).toUpperCase() + viewName.slice(1);
}

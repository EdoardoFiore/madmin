/**
 * MADMIN - Dashboard View
 *
 * Widget-based dashboard with configurable visibility and ordering.
 * Core widgets live in core-widgets.js / charts.js; module widgets are
 * registered via module-widgets.js (frozen contract surface).
 *
 * Exports destroy() so the router stops the auto-refresh interval and
 * frees chart instances when navigating away.
 */

import { apiGet, apiPatch } from '../../api.js';
import { t } from '../../i18n.js';
import { openModal } from '../../components/modal.js';
import {
    renderWelcome, loadWelcome,
    renderSystemStats, loadSystemStats,
    renderServices, loadServicesStatus,
    renderAlerts, loadAlerts,
    renderBackupStatus, loadBackupStatus,
    renderStatCards, loadStatCards,
    renderQuickActions,
} from './core-widgets.js';
import {
    renderResourceGraphs, loadResourceGraphs,
    renderNetTraffic, loadNetTrafficGraph, loadNetTraffic,
    destroyCharts,
} from './charts.js';
import { loadModuleWidgets } from './module-widgets.js';

let autoRefreshInterval = null;

// ============== WIDGET REGISTRY ==============

const CORE_WIDGETS = [
    { id: 'welcome', get title() { return t('dashboard.welcome'); }, col: 12, fixed: true, render: renderWelcome, load: loadWelcome },
    { id: 'system_stats', get title() { return t('dashboard.systemStats'); }, col: 12, fixed: false, render: renderSystemStats, load: loadSystemStats },
    { id: 'services', get title() { return t('dashboard.serviceStatus'); }, col: 12, fixed: false, render: renderServices, load: loadServicesStatus },
    { id: 'resource_graphs', get title() { return t('dashboard.resourceTrend'); }, col: 12, fixed: false, render: renderResourceGraphs, load: loadResourceGraphs },
    { id: 'net_traffic', get title() { return t('dashboard.networkTraffic'); }, col: 6, fixed: false, render: renderNetTraffic, load: loadNetTraffic },
    { id: 'alerts', get title() { return t('dashboard.systemAlerts'); }, col: 6, fixed: false, render: renderAlerts, load: loadAlerts },
    { id: 'backup_status', get title() { return t('dashboard.backupStatus'); }, col: 6, fixed: false, render: renderBackupStatus, load: loadBackupStatus },
    { id: 'quick_actions', get title() { return t('dashboard.quickActions'); }, col: 6, fixed: false, render: renderQuickActions, load: null },
    { id: 'stat_cards', get title() { return t('dashboard.counters'); }, col: 12, fixed: false, render: renderStatCards, load: loadStatCards },
];

// Lookup map; module widgets are added here at render time
const WIDGET_MAP = Object.fromEntries(CORE_WIDGETS.map(w => [w.id, w]));

// Track loaded module widget IDs so we can include them in preferences
let _moduleWidgetIds = [];

// ============== WIDGET PREFERENCES ==============

// In-memory cache of prefs (loaded from DB on first dashboard render)
let _widgetPrefsCache = null;

async function loadWidgetPrefsFromServer() {
    const allWidgetIds = () => [...CORE_WIDGETS.map(w => w.id), ..._moduleWidgetIds];
    try {
        const user = await apiGet('/auth/me');
        const allPrefs = JSON.parse(user.preferences || '{}');
        const raw = allPrefs.dashboard_widgets || null;
        if (Array.isArray(raw)) {
            // Deduplicate and validate
            const seen = new Set();
            const prefs = [];
            for (const p of raw) {
                if (p.id && !seen.has(p.id) && WIDGET_MAP[p.id]) {
                    seen.add(p.id);
                    prefs.push(p);
                }
            }
            // Add any new widgets not yet in saved prefs (core + module)
            for (const wid of allWidgetIds()) {
                if (!seen.has(wid)) {
                    seen.add(wid);
                    prefs.push({ id: wid, enabled: true });
                }
            }
            _widgetPrefsCache = prefs;
        } else {
            _widgetPrefsCache = allWidgetIds().map(id => ({ id, enabled: true }));
        }
    } catch (e) {
        console.error('Failed to load widget prefs from server:', e);
        _widgetPrefsCache = allWidgetIds().map(id => ({ id, enabled: true }));
    }
}

function getWidgetPrefs() {
    if (!_widgetPrefsCache) {
        const allWidgetIds = [...CORE_WIDGETS.map(w => w.id), ..._moduleWidgetIds];
        return allWidgetIds.map(id => ({ id, enabled: true }));
    }
    return _widgetPrefsCache;
}

/**
 * Save widget prefs to cache and to the server (async, fire-and-forget).
 */
function saveWidgetPrefs(prefs) {
    _widgetPrefsCache = prefs;
    // Save to server in background
    (async () => {
        try {
            const user = await apiGet('/auth/me');
            const allPrefs = JSON.parse(user.preferences || '{}');
            allPrefs.dashboard_widgets = prefs;
            await apiPatch('/auth/me/preferences', { preferences: JSON.stringify(allPrefs) });
        } catch (e) {
            console.error('Failed to save widget prefs:', e);
        }
    })();
}

/**
 * Get ordered list of widgets to render, respecting user prefs.
 * Fixed widgets (welcome) always come first regardless of order.
 */
function getOrderedWidgets() {
    const prefs = getWidgetPrefs();
    const ordered = [];

    // Fixed widgets first
    for (const w of CORE_WIDGETS) {
        if (w.fixed) ordered.push({ widget: w, enabled: true });
    }

    // Then user-ordered widgets
    for (const pref of prefs) {
        const w = WIDGET_MAP[pref.id];
        if (w && !w.fixed) {
            ordered.push({ widget: w, enabled: pref.enabled });
        }
    }

    return ordered;
}

// ============== MAIN RENDER ==============

export async function render(container) {
    // Load module widgets first (registers them in WIDGET_MAP)
    const newIds = await loadModuleWidgets(WIDGET_MAP);
    _moduleWidgetIds.push(...newIds);

    // Load prefs from server only on first render (when cache is empty)
    if (!_widgetPrefsCache) {
        await loadWidgetPrefsFromServer();
    }

    const ordered = getOrderedWidgets();

    // Build widget HTML (only enabled)
    let widgetsHtml = '';
    for (const { widget, enabled } of ordered) {
        if (!enabled) continue;
        widgetsHtml += `
            <div class="col-lg-${widget.col}" data-widget-id="${widget.id}">
                ${widget.render()}
            </div>
        `;
    }

    container.innerHTML = `
        <div class="row row-deck row-cards" id="dashboard-widgets">
            ${widgetsHtml}
        </div>
    `;

    setupEventListeners();

    // Load data for all visible widgets
    const loadPromises = [];
    for (const { widget, enabled } of ordered) {
        if (!enabled || !widget.load) continue;
        loadPromises.push(widget.load().catch(e => console.error(`Widget ${widget.id} error:`, e)));
    }
    await Promise.all(loadPromises);
}

/**
 * Router lifecycle hook: stop polling and free chart instances.
 */
export function destroy() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
    }
    destroyCharts();
}

// ============== WIDGET CONFIG MODAL ==============

function openWidgetConfigModal() {
    const prefs = getWidgetPrefs();
    const nonFixed = prefs.filter(p => WIDGET_MAP[p.id] && !WIDGET_MAP[p.id].fixed);

    openModal({
        title: t('app.widgetManagement'),
        size: 'sm',
        body: `
            <div class="list-group list-group-flush" id="widget-sortable-list">
                ${nonFixed.map(p => {
                    const w = WIDGET_MAP[p.id];
                    return `
                        <div class="list-group-item d-flex align-items-center" data-widget-id="${p.id}">
                            <i class="ti ti-grip-vertical text-muted me-2 drag-handle" style="cursor: grab;"></i>
                            <label class="form-check form-switch mb-0 flex-fill">
                                <input type="checkbox" class="form-check-input widget-modal-toggle"
                                       data-widget-id="${p.id}" ${p.enabled ? 'checked' : ''}>
                                <span class="form-check-label">${w.title}</span>
                            </label>
                        </div>
                    `;
                }).join('')}
            </div>
        `,
        footer: '',
        onShown(ctx) {
            ctx.bodyEl.classList.add('p-0');
            // Initialize SortableJS on the list
            const listEl = ctx.bodyEl.querySelector('#widget-sortable-list');
            if (listEl && typeof Sortable !== 'undefined') {
                Sortable.create(listEl, {
                    handle: '.drag-handle',
                    animation: 150,
                    ghostClass: 'bg-blue-lt',
                    onEnd: () => saveOrderFromModal(ctx),
                });
            }
            // Toggle listeners — save immediately but don't re-render yet
            ctx.bodyEl.querySelectorAll('.widget-modal-toggle').forEach(cb => {
                cb.addEventListener('change', () => saveOrderFromModal(ctx));
            });
        },
        onHidden() {
            // Re-render the dashboard with the new prefs (replaces the old
            // full-page reload)
            const contentEl = document.getElementById('app-content');
            if (contentEl) {
                destroy();
                render(contentEl);
            }
        },
    });
}

/**
 * Read current order and enabled state from the modal DOM and save to preferences.
 */
function saveOrderFromModal(ctx) {
    const listEl = ctx.bodyEl.querySelector('#widget-sortable-list');
    if (!listEl) return;

    const fixedPrefs = CORE_WIDGETS.filter(w => w.fixed).map(w => ({ id: w.id, enabled: true }));
    const items = listEl.querySelectorAll('[data-widget-id]');
    const nonFixedPrefs = [];

    items.forEach(item => {
        const id = item.dataset.widgetId;
        const enabled = item.querySelector('.widget-modal-toggle')?.checked ?? true;
        nonFixedPrefs.push({ id, enabled });
    });

    saveWidgetPrefs([...fixedPrefs, ...nonFixedPrefs]);
}

// ============== EVENT LISTENERS ==============

function setupEventListeners() {
    // Refresh stats
    document.getElementById('btn-refresh-stats')?.addEventListener('click', async () => {
        const btn = document.getElementById('btn-refresh-stats');
        btn.innerHTML = '<i class="ti ti-loader ti-spin"></i>';
        await loadSystemStats();
        btn.innerHTML = '<i class="ti ti-refresh"></i>';
    });

    // Auto-refresh toggle
    document.getElementById('auto-refresh-toggle')?.addEventListener('change', (e) => {
        if (e.target.checked) {
            autoRefreshInterval = setInterval(loadSystemStats, 30000);
        } else {
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
                autoRefreshInterval = null;
            }
        }
    });

    // Resource graph range
    document.querySelectorAll('input[name="graph-range"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            loadResourceGraphs(parseInt(e.target.value));
        });
    });

    // Network traffic interface selector
    document.getElementById('net-interface-select')?.addEventListener('change', (e) => {
        const hours = parseInt(document.querySelector('input[name="net-range"]:checked')?.value || '1');
        loadNetTrafficGraph(e.target.value, hours);
    });

    // Network traffic range
    document.querySelectorAll('input[name="net-range"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            const iface = document.getElementById('net-interface-select')?.value;
            if (iface) loadNetTrafficGraph(iface, parseInt(e.target.value));
        });
    });

    // Widget config button -> open modal
    document.getElementById('btn-widget-config')?.addEventListener('click', () => {
        openWidgetConfigModal();
    });
}

/**
 * MADMIN - Dashboard View
 * 
 * Widget-based dashboard with configurable visibility.
 * Each widget is a self-contained card with render + load functions.
 */

import { apiGet, apiPatch } from '../api.js';
import { formatRelativeTime } from '../utils.js';

let autoRefreshInterval = null;
let netTrafficChart = null;
let cpuChart = null;
let ramChart = null;
let diskChart = null;

// ============== WIDGET REGISTRY ==============

/**
 * Core widget definitions.
 * Future: module widgets will be appended here by the module loader.
 * 
 * Each widget has:
 *  - id: unique identifier
 *  - title: display name
 *  - col: Bootstrap column width (12=full, 6=half)
 *  - fixed: if true, cannot be hidden
 *  - render: function returning HTML string
 *  - load: async function to populate data (null if static)
 */
const CORE_WIDGETS = [
    { id: 'welcome', title: 'Benvenuto', col: 12, fixed: true, render: renderWelcome, load: loadWelcome },
    { id: 'system_stats', title: 'Statistiche', col: 12, fixed: false, render: renderSystemStats, load: loadSystemStats },
    { id: 'services', title: 'Stato Servizi', col: 12, fixed: false, render: renderServices, load: loadServicesStatus },
    { id: 'resource_graphs', title: 'Grafici Risorse', col: 12, fixed: false, render: renderResourceGraphs, load: loadResourceGraphs },
    { id: 'net_traffic', title: 'Traffico Rete', col: 6, fixed: false, render: renderNetTraffic, load: loadNetTraffic },
    { id: 'alerts', title: 'Alert Sistema', col: 6, fixed: false, render: renderAlerts, load: loadAlerts },
    { id: 'backup_status', title: 'Stato Backup', col: 6, fixed: false, render: renderBackupStatus, load: loadBackupStatus },
    { id: 'quick_actions', title: 'Azioni Rapide', col: 6, fixed: false, render: renderQuickActions, load: null },
    { id: 'stat_cards', title: 'Contatori', col: 12, fixed: false, render: renderStatCards, load: loadStatCards },
];

// Build a lookup map for quick access
const WIDGET_MAP = Object.fromEntries(CORE_WIDGETS.map(w => [w.id, w]));


// ============== WIDGET PREFERENCES ==============

// In-memory cache of prefs (loaded from DB on dashboard render)
let _widgetPrefsCache = null;

/**
 * Load widget preferences from the server (user.preferences JSON field).
 * Called once on dashboard render.
 */
async function loadWidgetPrefsFromServer() {
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
            // Add any new widgets not yet in saved prefs
            for (const w of CORE_WIDGETS) {
                if (!seen.has(w.id)) {
                    seen.add(w.id);
                    prefs.push({ id: w.id, enabled: true });
                }
            }
            _widgetPrefsCache = prefs;
        } else {
            _widgetPrefsCache = CORE_WIDGETS.map(w => ({ id: w.id, enabled: true }));
        }
    } catch (e) {
        console.error('Failed to load widget prefs from server:', e);
        _widgetPrefsCache = CORE_WIDGETS.map(w => ({ id: w.id, enabled: true }));
    }
}

/**
 * Get widget prefs from in-memory cache.
 */
function getWidgetPrefs() {
    if (!_widgetPrefsCache) {
        return CORE_WIDGETS.map(w => ({ id: w.id, enabled: true }));
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

    // Setup event listeners
    setupEventListeners();

    // Load company name
    await loadCompanyName();

    // Load data for all visible widgets
    const loadPromises = [];
    for (const { widget, enabled } of ordered) {
        if (!enabled || !widget.load) continue;
        loadPromises.push(widget.load().catch(e => console.error(`Widget ${widget.id} error:`, e)));
    }
    await Promise.all(loadPromises);
}


function renderWidgetConfigButton() {
    return `
        <button class="btn btn-sm px-2 py-1" style="background: rgba(255,255,255,0.2); color: white; border: 1px solid rgba(255,255,255,0.3);" 
                id="btn-widget-config" title="Configura widget">
            <i class="ti ti-layout-dashboard fs-3"></i>
        </button>
    `;
}

/**
 * Open or refresh the widget config modal.
 * Modal is appended to document.body so it persists across dashboard re-renders.
 */
function openWidgetConfigModal() {
    // Remove existing modal if any
    document.getElementById('widget-config-modal')?.remove();

    const prefs = getWidgetPrefs();
    const nonFixed = prefs.filter(p => WIDGET_MAP[p.id] && !WIDGET_MAP[p.id].fixed);

    const modalHtml = `
        <div class="modal modal-blur" id="widget-config-modal" tabindex="-1">
            <div class="modal-dialog modal-sm modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title"><i class="ti ti-layout-dashboard me-2"></i>Gestione Widget</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body p-0">
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
                    </div>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);
    const modalEl = document.getElementById('widget-config-modal');
    const modal = new bootstrap.Modal(modalEl);

    // Initialize SortableJS on the list
    const listEl = document.getElementById('widget-sortable-list');
    if (listEl && typeof Sortable !== 'undefined') {
        Sortable.create(listEl, {
            handle: '.drag-handle',
            animation: 150,
            ghostClass: 'bg-blue-lt',
            onEnd: () => {
                saveOrderFromModal();
            }
        });
    }

    // Toggle listeners — save immediately but don't re-render yet
    modalEl.querySelectorAll('.widget-modal-toggle').forEach(cb => {
        cb.addEventListener('change', () => {
            saveOrderFromModal();
        });
    });

    // Refresh dashboard on modal close
    modalEl.addEventListener('hidden.bs.modal', () => {
        saveOrderFromModal();
        modalEl.remove();
        window.location.reload();
    });

    modal.show();
}

/**
 * Read current order and enabled state from the modal DOM and save to preferences.
 */
function saveOrderFromModal() {
    const listEl = document.getElementById('widget-sortable-list');
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

/**
 * Re-render the dashboard widgets.
 * Uses cached prefs (no server refetch).
 */
async function refreshDashboard() {
    const container = document.querySelector('[data-page="dashboard"]') || document.getElementById('page-content');
    if (container) await render(container);
}


// ============== WIDGET RENDERERS ==============

function renderWelcome() {
    return `
        <div class="card bg-primary text-white">
            <div class="card-body">
                <div class="d-flex align-items-center">
                    <div class="me-3">
                        <i class="ti ti-server-cog" style="font-size: 3rem;"></i>
                    </div>
                    <div class="flex-fill">
                        <h2 class="mb-1" id="dashboard-welcome">Benvenuto in MADMIN</h2>
                        <p class="mb-0 opacity-75">Sistema di amministrazione modulare per il tuo server</p>
                    </div>
                    <div class="d-flex align-items-center gap-3">
                        <div class="text-end" id="uptime-display">
                            <span class="spinner-border spinner-border-sm"></span>
                        </div>
                        ${renderWidgetConfigButton()}
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderSystemStats() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-cpu me-2"></i>Statistiche Sistema
                </h3>
                <div class="card-actions">
                    <div class="form-check form-switch me-3">
                        <input class="form-check-input" type="checkbox" id="auto-refresh-toggle">
                        <label class="form-check-label" for="auto-refresh-toggle">Auto (30s)</label>
                    </div>
                    <button class="btn btn-ghost-primary" id="btn-refresh-stats" title="Aggiorna">
                        <i class="ti ti-refresh"></i>
                    </button>
                </div>
            </div>
            <div class="card-body">
                <div class="row" id="system-stats-container">
                    <div class="col-md-4 mb-3">
                        <div class="d-flex align-items-center mb-2">
                            <i class="ti ti-cpu me-2 text-blue"></i>
                            <span class="fw-bold">CPU</span>
                            <span class="ms-auto text-muted" id="cpu-percent">--</span>
                        </div>
                        <div class="progress progress-sm">
                            <div class="progress-bar bg-blue" id="cpu-bar" style="width: 0%"></div>
                        </div>
                    </div>
                    <div class="col-md-4 mb-3">
                        <div class="d-flex align-items-center mb-2">
                            <i class="ti ti-device-desktop me-2 text-green"></i>
                            <span class="fw-bold">RAM</span>
                            <span class="ms-auto text-muted" id="ram-info">--</span>
                        </div>
                        <div class="progress progress-sm">
                            <div class="progress-bar bg-green" id="ram-bar" style="width: 0%"></div>
                        </div>
                    </div>
                    <div class="col-md-4 mb-3">
                        <div class="d-flex align-items-center mb-2">
                            <i class="ti ti-database me-2 text-orange"></i>
                            <span class="fw-bold">Disco</span>
                            <span class="ms-auto text-muted" id="disk-info">--</span>
                        </div>
                        <div class="progress progress-sm">
                            <div class="progress-bar bg-orange" id="disk-bar" style="width: 0%"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderServices() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-activity me-2"></i>Stato Servizi
                </h3>
            </div>
            <div class="card-body">
                <div class="row g-3" id="services-status-container">
                    ${['madmin|ti ti-server|bg-primary-lt|MADMIN', 'postgresql|ti ti-database|bg-blue-lt|PostgreSQL',
            'nginx|ti ti-world|bg-green-lt|Nginx', 'iptables|ti ti-shield-lock|bg-orange-lt|iptables']
            .map(s => {
                const [id, icon, bg, name] = s.split('|');
                return `
                            <div class="col-6 col-md-3">
                                <div class="card card-sm">
                                    <div class="card-body">
                                        <div class="d-flex align-items-center">
                                            <span class="avatar ${bg} me-3"><i class="${icon}"></i></span>
                                            <div>
                                                <div class="font-weight-medium">${name}</div>
                                                <div id="svc-${id}" class="text-muted">
                                                    <span class="spinner-border spinner-border-sm"></span>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                          `;
            }).join('')}
                </div>
            </div>
        </div>
    `;
}

function renderResourceGraphs() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-chart-line me-2"></i>Andamento Risorse
                </h3>
                <div class="card-actions">
                    <div class="btn-group" role="group">
                        <input type="radio" class="btn-check" name="graph-range" id="graph-1h" value="1" checked>
                        <label class="btn btn-sm" for="graph-1h">1h</label>
                        <input type="radio" class="btn-check" name="graph-range" id="graph-6h" value="6">
                        <label class="btn btn-sm" for="graph-6h">6h</label>
                        <input type="radio" class="btn-check" name="graph-range" id="graph-24h" value="24">
                        <label class="btn btn-sm" for="graph-24h">24h</label>
                    </div>
                </div>
            </div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-4">
                        <h4 class="subheader">CPU</h4>
                        <div id="chart-cpu" style="height: 150px;"></div>
                    </div>
                    <div class="col-md-4">
                        <h4 class="subheader">RAM</h4>
                        <div id="chart-ram" style="height: 150px;"></div>
                    </div>
                    <div class="col-md-4">
                        <h4 class="subheader">Disco</h4>
                        <div id="chart-disk" style="height: 150px;"></div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderNetTraffic() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-arrows-transfer-down me-2"></i>Traffico di Rete
                </h3>
                <div class="card-actions d-flex align-items-center gap-2">
                    <select class="form-select form-select-sm" id="net-interface-select" style="width: auto; min-width: 120px;">
                        <option value="">Caricamento...</option>
                    </select>
                    <div class="btn-group" role="group">
                        <input type="radio" class="btn-check" name="net-range" id="net-1h" value="1" checked>
                        <label class="btn btn-sm" for="net-1h">1h</label>
                        <input type="radio" class="btn-check" name="net-range" id="net-6h" value="6">
                        <label class="btn btn-sm" for="net-6h">6h</label>
                        <input type="radio" class="btn-check" name="net-range" id="net-24h" value="24">
                        <label class="btn btn-sm" for="net-24h">24h</label>
                    </div>
                </div>
            </div>
            <div class="card-body">
                <div id="chart-net-traffic" style="height: 200px;">
                    <div class="text-muted text-center py-5">
                        <span class="spinner-border spinner-border-sm"></span> Caricamento...
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderAlerts() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-bell me-2"></i>Alert Sistema
                </h3>
            </div>
            <div class="card-body" id="alerts-container">
                <div class="text-muted text-center py-3">
                    <span class="spinner-border spinner-border-sm"></span> Caricamento...
                </div>
            </div>
        </div>
    `;
}

function renderBackupStatus() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-archive me-2"></i>Stato Backup
                </h3>
                <div class="card-actions" id="backup-icons">
                </div>
            </div>
            <div class="card-body" id="backup-status-container">
                <div class="text-muted text-center py-3">
                    <span class="spinner-border spinner-border-sm"></span> Caricamento...
                </div>
            </div>
        </div>
    `;
}



function renderStatCards() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-chart-bar me-2"></i>Contatori
                </h3>
            </div>
            <div class="card-body">
                <div class="row g-3">
                    ${[
            { id: 'system-status', title: 'Stato Sistema', sub: 'Database', subId: 'db-status' },
            { id: 'firewall-count', title: 'Regole Firewall', sub: 'Regole attive', subId: null },
            { id: 'modules-count', title: 'Moduli Installati', sub: 'Moduli attivi', subId: null },
            { id: 'users-count', title: 'Utenti', sub: 'Utenti registrati', subId: null },
        ].map(c => `
                        <div class="col-sm-6 col-lg-3">
                            <div class="card card-sm">
                                <div class="card-body">
                                    <div class="d-flex align-items-center">
                                        <div class="subheader">${c.title}</div>
                                    </div>
                                    <div class="h1 mb-3" id="${c.id}">
                                        <span class="spinner-border spinner-border-sm"></span>
                                    </div>
                                    <div class="d-flex mb-2">
                                        <div class="text-muted">${c.sub}</div>
                                        ${c.subId ? `<div class="ms-auto" id="${c.subId}"><span class="spinner-border spinner-border-sm"></span></div>` : ''}
                                    </div>
                                </div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        </div>
    `;
}

function renderQuickActions() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-bolt me-2"></i>Azioni Rapide
                </h3>
            </div>
            <div class="card-body">
                <div class="row g-3">
                    <div class="col-6">
                        <a href="#users" class="btn btn-outline-primary w-100">
                            <i class="ti ti-user-plus me-2"></i>Nuovo Utente
                        </a>
                    </div>
                    <div class="col-6">
                        <a href="#firewall" class="btn btn-outline-primary w-100">
                            <i class="ti ti-shield-plus me-2"></i>Nuova Regola
                        </a>
                    </div>
                    <div class="col-6">
                        <a href="#settings" class="btn btn-outline-primary w-100">
                            <i class="ti ti-settings me-2"></i>Impostazioni
                        </a>
                    </div>
                    <div class="col-6">
                        <a href="#modules" class="btn btn-outline-primary w-100">
                            <i class="ti ti-puzzle me-2"></i>Moduli
                        </a>
                    </div>
                </div>
            </div>
        </div>
    `;
}


// ============== WIDGET LOADERS ==============

async function loadWelcome() {
    // Uptime
    try {
        const uptime = await apiGet('/system/uptime');
        const el = document.getElementById('uptime-display');
        if (el && uptime.available) {
            el.innerHTML = `
                <div class="text-white opacity-75" style="font-size: 0.85rem;">
                    <i class="ti ti-clock me-1"></i>Online da <strong>${uptime.uptime_formatted}</strong>
                </div>
            `;
        }
    } catch (e) {
        console.error('Failed to load uptime:', e);
    }
}

async function loadSystemStats() {
    try {
        const stats = await apiGet('/system/stats');

        if (!stats.available) {
            document.getElementById('system-stats-container').innerHTML = `
                <div class="col-12 text-center text-muted">
                    <i class="ti ti-alert-circle me-2"></i>
                    Statistiche non disponibili: ${stats.error || 'psutil non installato'}
                </div>
            `;
            return;
        }

        // CPU
        const cpuPercent = stats.cpu.percent;
        document.getElementById('cpu-percent').textContent = `${cpuPercent.toFixed(1)}%`;
        document.getElementById('cpu-bar').style.width = `${cpuPercent}%`;
        document.getElementById('cpu-bar').className = `progress-bar ${getProgressColor(cpuPercent)}`;

        // RAM
        const ramPercent = stats.memory.percent;
        const ramUsed = formatBytes(stats.memory.used);
        const ramTotal = formatBytes(stats.memory.total);
        document.getElementById('ram-info').textContent = `${ramPercent.toFixed(1)}% (${ramUsed} / ${ramTotal})`;
        document.getElementById('ram-bar').style.width = `${ramPercent}%`;
        document.getElementById('ram-bar').className = `progress-bar ${getProgressColor(ramPercent)}`;

        // Disk
        const diskPercent = stats.disk.percent;
        const diskUsed = formatBytes(stats.disk.used);
        const diskTotal = formatBytes(stats.disk.total);
        document.getElementById('disk-info').textContent = `${diskPercent.toFixed(1)}% (${diskUsed} / ${diskTotal})`;
        document.getElementById('disk-bar').style.width = `${diskPercent}%`;
        document.getElementById('disk-bar').className = `progress-bar ${getProgressColor(diskPercent)}`;

    } catch (error) {
        console.error('Error loading system stats:', error);
        const el = document.getElementById('system-stats-container');
        if (el) el.innerHTML = `
            <div class="col-12 text-center text-danger">
                <i class="ti ti-alert-circle me-2"></i>Errore caricamento statistiche
            </div>
        `;
    }
}

async function loadServicesStatus() {
    try {
        const services = await apiGet('/system/services');
        for (const [svc, data] of Object.entries(services)) {
            const el = document.getElementById(`svc-${svc}`);
            if (el) {
                const isActive = data.active;
                el.innerHTML = `
                    <span class="badge bg-${isActive ? 'success' : 'danger'}-lt">
                        ${isActive ? 'Attivo' : data.status || 'Inattivo'}
                    </span>
                `;
            }
        }
    } catch (error) {
        console.error('Error loading services status:', error);
        ['madmin', 'postgresql', 'nginx', 'iptables'].forEach(svc => {
            const el = document.getElementById(`svc-${svc}`);
            if (el) el.innerHTML = '<span class="badge bg-secondary-lt">Sconosciuto</span>';
        });
    }
}

async function loadResourceGraphs(hours) {
    if (typeof hours !== 'number') hours = 1;
    try {
        const [history, currentStats] = await Promise.all([
            apiGet(`/system/stats/history?hours=${hours}`),
            apiGet('/system/stats')
        ]);

        if (history.length === 0) {
            ['chart-cpu', 'chart-ram', 'chart-disk'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.innerHTML = '<div class="text-muted text-center py-4">Dati non ancora disponibili</div>';
            });
            return;
        }

        const timestamps = history.map(h => new Date(h.timestamp).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' }));
        const cpuData = history.map(h => parseFloat(h.cpu.toFixed(1)));

        const ramTotalGB = currentStats.available ? (currentStats.memory.total / (1024 ** 3)) : 2;
        const diskTotalGB = currentStats.available ? (currentStats.disk.total / (1024 ** 3)) : 50;
        const ramDataGB = history.map(h => parseFloat(((h.ram_used || 0) / (1024 ** 3)).toFixed(2)));
        const diskDataGB = history.map(h => parseFloat(((h.disk_used || 0) / (1024 ** 3)).toFixed(2)));

        const cpuMinMax = { min: Math.min(...cpuData).toFixed(1), max: Math.max(...cpuData).toFixed(1) };
        const ramMinMax = { min: Math.min(...ramDataGB).toFixed(1), max: Math.max(...ramDataGB).toFixed(1) };
        const diskMinMax = { min: Math.min(...diskDataGB).toFixed(1), max: Math.max(...diskDataGB).toFixed(1) };

        const baseOptions = (data, color, categories) => ({
            series: [{ data }],
            chart: { type: 'area', height: 120, sparkline: { enabled: false }, animations: { enabled: false }, toolbar: { show: false }, zoom: { enabled: false } },
            dataLabels: { enabled: false },
            stroke: { curve: 'smooth', width: 2 },
            fill: { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.4, opacityTo: 0.1 } },
            colors: [color],
            xaxis: { categories, labels: { show: false }, axisBorder: { show: false }, axisTicks: { show: false } },
            grid: { show: true, borderColor: '#e0e0e0', strokeDashArray: 3, padding: { left: 5, right: 5 } }
        });

        const cpuOptions = { ...baseOptions(cpuData, '#206bc4', timestamps), yaxis: { min: 0, max: 100, labels: { show: true, formatter: v => v.toFixed(0) + '%' } }, tooltip: { y: { formatter: v => v.toFixed(1) + '%' } } };
        const ramOptions = { ...baseOptions(ramDataGB, '#2fb344', timestamps), yaxis: { min: 0, max: Math.ceil(ramTotalGB), labels: { show: true, formatter: v => v.toFixed(0) + ' GB' } }, tooltip: { y: { formatter: v => v.toFixed(1) + ' GB' } } };
        const diskOptions = { ...baseOptions(diskDataGB, '#f76707', timestamps), yaxis: { min: 0, max: Math.ceil(diskTotalGB), labels: { show: true, formatter: v => v.toFixed(0) + ' GB' } }, tooltip: { y: { formatter: v => v.toFixed(1) + ' GB' } } };

        if (cpuChart) cpuChart.destroy();
        if (ramChart) ramChart.destroy();
        if (diskChart) diskChart.destroy();

        cpuChart = new ApexCharts(document.getElementById('chart-cpu'), cpuOptions);
        ramChart = new ApexCharts(document.getElementById('chart-ram'), ramOptions);
        diskChart = new ApexCharts(document.getElementById('chart-disk'), diskOptions);

        cpuChart.render();
        ramChart.render();
        diskChart.render();

        // Min/max labels
        document.getElementById('cpu-minmax')?.remove();
        document.getElementById('ram-minmax')?.remove();
        document.getElementById('disk-minmax')?.remove();

        document.getElementById('chart-cpu')?.insertAdjacentHTML('afterend',
            `<div id="cpu-minmax" class="text-muted small mt-1">Min: ${cpuMinMax.min}% | Max: ${cpuMinMax.max}%</div>`);
        document.getElementById('chart-ram')?.insertAdjacentHTML('afterend',
            `<div id="ram-minmax" class="text-muted small mt-1">Min: ${ramMinMax.min} GB | Max: ${ramMinMax.max} GB (${ramTotalGB.toFixed(0)} GB tot)</div>`);
        document.getElementById('chart-disk')?.insertAdjacentHTML('afterend',
            `<div id="disk-minmax" class="text-muted small mt-1">Min: ${diskMinMax.min} GB | Max: ${diskMinMax.max} GB (${diskTotalGB.toFixed(0)} GB tot)</div>`);

    } catch (error) {
        console.error('Error loading resource graphs:', error);
        ['chart-cpu', 'chart-ram', 'chart-disk'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = '<div class="text-muted text-center py-4">Errore caricamento dati</div>';
        });
    }
}

async function loadNetTraffic() {
    const select = document.getElementById('net-interface-select');
    if (!select) return;

    try {
        // Populate interface dropdown
        const netData = await apiGet('/system/network');
        if (!netData.available) {
            document.getElementById('chart-net-traffic').innerHTML = '<div class="text-muted text-center py-4">Dati non disponibili</div>';
            return;
        }

        const interfaces = Object.keys(netData.interfaces);
        select.innerHTML = interfaces.map((iface, i) =>
            `<option value="${iface}" ${i === 0 ? 'selected' : ''}>${iface}</option>`
        ).join('');

        // Load graph for first interface
        if (interfaces.length > 0) {
            await loadNetTrafficGraph(interfaces[0], 1);
        }
    } catch (error) {
        console.error('Error loading net traffic:', error);
        document.getElementById('chart-net-traffic').innerHTML = '<div class="text-muted text-center py-4">Errore caricamento</div>';
    }
}

async function loadNetTrafficGraph(iface, hours) {
    const container = document.getElementById('chart-net-traffic');
    if (!container) return;

    try {
        const history = await apiGet(`/system/network/history?hours=${hours}&interface=${iface}`);

        if (history.length === 0) {
            container.innerHTML = '<div class="text-muted text-center py-4"><i class="ti ti-clock me-2"></i>In attesa dei primi dati di traffico (circa 2 minuti)</div>';
            return;
        }

        const timestamps = history.map(h => new Date(h.timestamp).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' }));
        const txData = history.map(h => parseFloat((h.tx_rate / 1024).toFixed(2))); // KB/s
        const rxData = history.map(h => parseFloat((h.rx_rate / 1024).toFixed(2))); // KB/s

        // Auto-scale: if > 1024 KB/s, show MB/s
        const maxVal = Math.max(...txData, ...rxData);
        let unit = 'KB/s';
        let txDisplay = txData;
        let rxDisplay = rxData;
        if (maxVal > 1024) {
            unit = 'MB/s';
            txDisplay = txData.map(v => parseFloat((v / 1024).toFixed(2)));
            rxDisplay = rxData.map(v => parseFloat((v / 1024).toFixed(2)));
        }

        if (netTrafficChart) netTrafficChart.destroy();
        container.innerHTML = '';

        const options = {
            series: [
                { name: `TX (${unit})`, data: txDisplay },
                { name: `RX (${unit})`, data: rxDisplay }
            ],
            chart: { type: 'area', height: 180, toolbar: { show: false }, zoom: { enabled: false }, animations: { enabled: false } },
            dataLabels: { enabled: false },
            stroke: { curve: 'smooth', width: 2 },
            fill: { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.3, opacityTo: 0.05 } },
            colors: ['#f76707', '#206bc4'],
            xaxis: { categories: timestamps, labels: { show: false }, axisBorder: { show: false }, axisTicks: { show: false } },
            yaxis: { min: 0, labels: { show: true, formatter: v => v.toFixed(0) + ' ' + unit } },
            tooltip: { y: { formatter: v => v.toFixed(2) + ' ' + unit } },
            grid: { show: true, borderColor: '#e0e0e0', strokeDashArray: 3 },
            legend: { position: 'top', horizontalAlign: 'right' }
        };

        netTrafficChart = new ApexCharts(container, options);
        netTrafficChart.render();

    } catch (error) {
        console.error('Error loading net traffic graph:', error);
        container.innerHTML = '<div class="text-muted text-center py-4">Errore caricamento dati</div>';
    }
}

async function loadAlerts() {
    const container = document.getElementById('alerts-container');
    if (!container) return;

    try {
        const alerts = await apiGet('/system/alerts');

        if (alerts.length === 0) {
            container.innerHTML = `
                <div class="d-flex align-items-center text-success py-2">
                    <i class="ti ti-circle-check me-2 fs-2"></i>
                    <div>
                        <div class="fw-bold">Tutto OK</div>
                        <div class="text-muted small">Nessun avviso attivo</div>
                    </div>
                </div>
            `;
            return;
        }

        container.innerHTML = alerts.map(alert => `
            <div class="d-flex align-items-center py-2 ${alerts.indexOf(alert) > 0 ? 'border-top' : ''}">
                <span class="avatar avatar-sm bg-${alert.severity === 'danger' ? 'danger' : 'warning'}-lt me-3">
                    <i class="ti ${alert.icon}"></i>
                </span>
                <div>
                    <div class="fw-bold text-${alert.severity === 'danger' ? 'danger' : 'warning'}">${alert.message}</div>
                </div>
            </div>
        `).join('');

    } catch (error) {
        console.error('Error loading alerts:', error);
        container.innerHTML = '<div class="text-muted">Errore caricamento alert</div>';
    }
}

async function loadBackupStatus() {
    const container = document.getElementById('backup-status-container');
    const iconsEl = document.getElementById('backup-icons');
    if (!container) return;

    try {
        const [history, settings] = await Promise.all([
            apiGet('/backup/history').catch(() => []),
            apiGet('/settings/backup').catch(() => null)
        ]);

        let icons = '';
        let content = '';

        if (history && history.length > 0) {
            const latest = history[0];
            const backupDate = new Date(latest.created_at);
            const now = new Date();
            const daysOld = Math.floor((now - backupDate) / (1000 * 60 * 60 * 24));

            let timeStr;
            if (daysOld === 0) {
                timeStr = `Oggi alle ${backupDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
            } else if (daysOld === 1) {
                timeStr = `Ieri alle ${backupDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
            } else {
                timeStr = `${daysOld} giorni fa (${backupDate.toLocaleDateString()})`;
            }

            // Check for failures
            let status = 'success';
            if (settings && settings.last_run_status) {
                const runTime = new Date(settings.last_run_time);
                if (runTime >= backupDate) {
                    status = settings.last_run_status; // success, upload_failed, or failed
                }
            }

            let badge, avatarColor, avatarIcon;
            if (status === 'failed') {
                badge = '<span class="badge bg-danger">Fallito</span>';
                avatarColor = 'danger'; avatarIcon = 'x';
            } else if (status === 'upload_failed') {
                badge = '<span class="badge bg-warning">Upload remoto fallito</span>';
                avatarColor = 'warning'; avatarIcon = 'cloud-off';
            } else {
                badge = '<span class="badge bg-success">Successo</span>';
                avatarColor = 'blue'; avatarIcon = 'check';
            }

            content = `
                <div class="d-flex align-items-center">
                    <span class="avatar bg-${avatarColor} text-white me-3">
                        <i class="ti ti-${avatarIcon}"></i>
                    </span>
                    <div>
                        <div class="fw-bold">${timeStr}</div>
                        <div class="mt-1">${badge}</div>
                    </div>
                </div>
            `;

            // Warning icons
            if (daysOld > 7) {
                icons += `<i class="ti ti-clock text-warning fs-3 ms-2" title="Backup più vecchio di 7 giorni"></i>`;
            }
        } else {
            content = `
                <div class="d-flex align-items-center text-muted">
                    <span class="avatar bg-secondary-lt me-3"><i class="ti ti-archive-off"></i></span>
                    <div>Nessun backup trovato</div>
                </div>
            `;
            icons += `<i class="ti ti-clock text-warning fs-3 ms-2" title="Nessun backup mai eseguito"></i>`;
        }

        // Periodic backup not enabled
        if (!settings || !settings.enabled) {
            icons += `<i class="ti ti-settings text-warning fs-3 ms-2" title="Backup periodico non abilitato"></i>`;
        }

        if (iconsEl) iconsEl.innerHTML = icons;
        container.innerHTML = content;

    } catch (error) {
        console.error('Error loading backup status:', error);
        container.innerHTML = '<div class="text-muted">Errore caricamento stato backup</div>';
    }
}



async function loadStatCards() {
    // Health check → system status
    try {
        const health = await apiGet('/health');
        document.getElementById('system-status').innerHTML = `
            <span class="status-dot status-dot-${health.status === 'healthy' ? 'active' : 'warning'} me-2"></span>
            ${health.status === 'healthy' ? 'Operativo' : 'Degradato'}
        `;
        document.getElementById('db-status').innerHTML = `
            <span class="badge bg-${health.database === 'connected' ? 'success' : 'danger'}">
                ${health.database === 'connected' ? 'Connesso' : 'Disconnesso'}
            </span>
        `;
    } catch (e) {
        const el = document.getElementById('system-status');
        if (el) el.innerHTML = '<span class="status-dot status-dot-warning me-2"></span>Errore';
    }

    // Firewall
    try {
        const rules = await apiGet('/firewall/rules');
        document.getElementById('firewall-count').textContent = rules.filter(r => r.enabled).length;
    } catch (e) {
        const el = document.getElementById('firewall-count');
        if (el) el.textContent = '-';
    }

    // Modules
    try {
        const modules = await apiGet('/modules/available');
        document.getElementById('modules-count').textContent = modules.filter(m => m.enabled).length;
    } catch (e) {
        const el = document.getElementById('modules-count');
        if (el) el.textContent = '-';
    }

    // Users
    try {
        const users = await apiGet('/auth/users');
        document.getElementById('users-count').textContent = users.length;
    } catch (e) {
        const el = document.getElementById('users-count');
        if (el) el.textContent = '-';
    }
}


// ============== UTILITY FUNCTIONS ==============

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function getProgressColor(percent) {
    if (percent < 60) return 'bg-green';
    if (percent < 80) return 'bg-yellow';
    return 'bg-red';
}

async function loadCompanyName() {
    try {
        const response = await fetch('/api/settings/system', {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` }
        });
        if (response.ok) {
            const settings = await response.json();
            if (settings.company_name) {
                const welcomeEl = document.getElementById('dashboard-welcome');
                if (welcomeEl) welcomeEl.textContent = `Benvenuto in ${settings.company_name}`;
            }
        }
    } catch (e) {
        console.error('Failed to load company name:', e);
    }
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

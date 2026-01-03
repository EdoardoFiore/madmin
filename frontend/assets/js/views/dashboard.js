/**
 * MADMIN - Dashboard View
 */

import { apiGet } from '../api.js';
import { formatRelativeTime } from '../utils.js';

let autoRefreshInterval = null;

/**
 * Render the dashboard view
 */
export async function render(container) {
    container.innerHTML = `
        <div class="row row-deck row-cards">
            <!-- Welcome Card -->
            <div class="col-12">
                <div class="card bg-primary text-white">
                    <div class="card-body">
                        <div class="d-flex align-items-center">
                            <div class="me-3">
                                <i class="ti ti-server-cog" style="font-size: 3rem;"></i>
                            </div>
                            <div>
                                <h2 class="mb-1">Benvenuto in MADMIN</h2>
                                <p class="mb-0 opacity-75">Sistema di amministrazione modulare per il tuo server</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- System Stats Card -->
            <div class="col-12">
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
            </div>
            
            <!-- Stats Cards -->
            <div class="col-sm-6 col-lg-3">
                <div class="card">
                    <div class="card-body">
                        <div class="d-flex align-items-center">
                            <div class="subheader">Stato Sistema</div>
                        </div>
                        <div class="h1 mb-3" id="system-status">
                            <span class="spinner-border spinner-border-sm"></span>
                        </div>
                        <div class="d-flex mb-2">
                            <div class="text-muted">Database</div>
                            <div class="ms-auto" id="db-status">
                                <span class="spinner-border spinner-border-sm"></span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="col-sm-6 col-lg-3">
                <div class="card">
                    <div class="card-body">
                        <div class="d-flex align-items-center">
                            <div class="subheader">Regole Firewall</div>
                        </div>
                        <div class="h1 mb-3" id="firewall-count">
                            <span class="spinner-border spinner-border-sm"></span>
                        </div>
                        <div class="d-flex mb-2">
                            <div class="text-muted">Regole attive</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="col-sm-6 col-lg-3">
                <div class="card">
                    <div class="card-body">
                        <div class="d-flex align-items-center">
                            <div class="subheader">Moduli Installati</div>
                        </div>
                        <div class="h1 mb-3" id="modules-count">
                            <span class="spinner-border spinner-border-sm"></span>
                        </div>
                        <div class="d-flex mb-2">
                            <div class="text-muted">Moduli attivi</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="col-sm-6 col-lg-3">
                <div class="card">
                    <div class="card-body">
                        <div class="d-flex align-items-center">
                            <div class="subheader">Utenti</div>
                        </div>
                        <div class="h1 mb-3" id="users-count">
                            <span class="spinner-border spinner-border-sm"></span>
                        </div>
                        <div class="d-flex mb-2">
                            <div class="text-muted">Utenti registrati</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Quick Actions -->
            <div class="col-lg-6">
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
            </div>
            
            <!-- System Info -->
            <div class="col-lg-6">
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">
                            <i class="ti ti-info-circle me-2"></i>Informazioni Sistema
                        </h3>
                    </div>
                    <div class="card-body">
                        <dl class="row mb-0">
                            <dt class="col-5">Versione:</dt>
                            <dd class="col-7" id="system-version">-</dd>
                            
                            <dt class="col-5">Backend:</dt>
                            <dd class="col-7">FastAPI + SQLite</dd>
                            
                            <dt class="col-5">Frontend:</dt>
                            <dd class="col-7">Tabler UI + ES Modules</dd>
                            
                            <dt class="col-5">Ultimo Aggiornamento:</dt>
                            <dd class="col-7" id="last-update">-</dd>
                        </dl>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Setup event listeners
    setupEventListeners();

    // Load data
    await loadDashboardData();
    await loadSystemStats();
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Refresh stats button
    document.getElementById('btn-refresh-stats')?.addEventListener('click', async () => {
        const btn = document.getElementById('btn-refresh-stats');
        btn.innerHTML = '<i class="ti ti-loader ti-spin"></i>';
        await loadSystemStats();
        btn.innerHTML = '<i class="ti ti-refresh"></i>';
    });

    // Auto-refresh toggle
    document.getElementById('auto-refresh-toggle')?.addEventListener('change', (e) => {
        if (e.target.checked) {
            // Start auto-refresh every 30 seconds
            autoRefreshInterval = setInterval(loadSystemStats, 30000);
        } else {
            // Stop auto-refresh
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
                autoRefreshInterval = null;
            }
        }
    });
}

/**
 * Format bytes to human readable string
 */
function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

/**
 * Load system statistics
 */
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
        document.getElementById('system-stats-container').innerHTML = `
            <div class="col-12 text-center text-danger">
                <i class="ti ti-alert-circle me-2"></i>
                Errore caricamento statistiche
            </div>
        `;
    }
}

/**
 * Get progress bar color based on percentage
 */
function getProgressColor(percent) {
    if (percent < 60) return 'bg-green';
    if (percent < 80) return 'bg-yellow';
    return 'bg-red';
}

/**
 * Load dashboard data from API
 */
async function loadDashboardData() {
    // Health check
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

        document.getElementById('system-version').textContent = `v${health.version}`;

    } catch (error) {
        document.getElementById('system-status').innerHTML = `
            <span class="status-dot status-dot-warning me-2"></span>
            Errore
        `;
    }

    // Firewall rules count
    try {
        const rules = await apiGet('/firewall/rules');
        const activeRules = rules.filter(r => r.enabled).length;
        document.getElementById('firewall-count').textContent = activeRules;
    } catch (error) {
        document.getElementById('firewall-count').textContent = '-';
    }

    // Modules count
    try {
        const modules = await apiGet('/modules/');
        const activeModules = modules.filter(m => m.enabled).length;
        document.getElementById('modules-count').textContent = activeModules;
    } catch (error) {
        document.getElementById('modules-count').textContent = '-';
    }

    // Users count
    try {
        const users = await apiGet('/auth/users');
        document.getElementById('users-count').textContent = users.length;
    } catch (error) {
        document.getElementById('users-count').textContent = '-';
    }

    // Last update
    document.getElementById('last-update').textContent = formatRelativeTime(new Date());
}

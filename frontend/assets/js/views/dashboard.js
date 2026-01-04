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
                                <h2 class="mb-1" id="dashboard-welcome">Benvenuto in MADMIN</h2>
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
            
            <!-- Services Status -->
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">
                            <i class="ti ti-activity me-2"></i>Stato Servizi
                        </h3>
                    </div>
                    <div class="card-body">
                        <div class="row g-3" id="services-status-container">
                            <div class="col-6 col-md-3">
                                <div class="card card-sm">
                                    <div class="card-body">
                                        <div class="d-flex align-items-center">
                                            <span class="avatar bg-primary-lt me-3">
                                                <i class="ti ti-server"></i>
                                            </span>
                                            <div>
                                                <div class="font-weight-medium">MADMIN</div>
                                                <div id="svc-madmin" class="text-muted">
                                                    <span class="spinner-border spinner-border-sm"></span>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-6 col-md-3">
                                <div class="card card-sm">
                                    <div class="card-body">
                                        <div class="d-flex align-items-center">
                                            <span class="avatar bg-blue-lt me-3">
                                                <i class="ti ti-database"></i>
                                            </span>
                                            <div>
                                                <div class="font-weight-medium">PostgreSQL</div>
                                                <div id="svc-postgresql" class="text-muted">
                                                    <span class="spinner-border spinner-border-sm"></span>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-6 col-md-3">
                                <div class="card card-sm">
                                    <div class="card-body">
                                        <div class="d-flex align-items-center">
                                            <span class="avatar bg-green-lt me-3">
                                                <i class="ti ti-world"></i>
                                            </span>
                                            <div>
                                                <div class="font-weight-medium">Nginx</div>
                                                <div id="svc-nginx" class="text-muted">
                                                    <span class="spinner-border spinner-border-sm"></span>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-6 col-md-3">
                                <div class="card card-sm">
                                    <div class="card-body">
                                        <div class="d-flex align-items-center">
                                            <span class="avatar bg-orange-lt me-3">
                                                <i class="ti ti-shield"></i>
                                            </span>
                                            <div>
                                                <div class="font-weight-medium">iptables</div>
                                                <div id="svc-iptables" class="text-muted">
                                                    <span class="spinner-border spinner-border-sm"></span>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Resource Graphs -->
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">
                            <i class="ti ti-chart-line me-2"></i>Andamento Risorse
                        </h3>
                        <div class="card-actions">
                            <div class="btn-group" role="group">
                                <input type="radio" class="btn-check" name="graph-range" id="graph-1h" value="1" checked>
                                <label class="btn btn-sm" for="graph-1h">1h</label>
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
                            <dd class="col-7">FastAPI + PostgreSQL</dd>
                            
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

    // Load company name for welcome message
    await loadCompanyName();

    // Load data
    await loadDashboardData();
    await loadSystemStats();
    await loadServicesStatus();
    await loadResourceGraphs(1);
}

/**
 * Load company name for welcome message
 */
async function loadCompanyName() {
    try {
        const response = await fetch('/api/settings/system', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('madmin_token')}`
            }
        });
        if (response.ok) {
            const settings = await response.json();
            if (settings.company_name) {
                const welcomeEl = document.getElementById('dashboard-welcome');
                if (welcomeEl) {
                    welcomeEl.textContent = `Benvenuto in ${settings.company_name}`;
                }
            }
        }
    } catch (e) {
        console.error('Failed to load company name:', e);
    }
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


// ============== SERVICES STATUS ==============

/**
 * Load services status from API
 */
async function loadServicesStatus() {
    try {
        const services = await apiGet('/system/services');

        // Update each service status
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
        // Set all to unknown
        ['madmin', 'postgresql', 'nginx', 'iptables'].forEach(svc => {
            const el = document.getElementById(`svc-${svc}`);
            if (el) {
                el.innerHTML = '<span class="badge bg-secondary-lt">Sconosciuto</span>';
            }
        });
    }
}


// ============== RESOURCE GRAPHS ==============

let cpuChart = null;
let ramChart = null;
let diskChart = null;
/**
 * Load resource graphs with historical data
 */
async function loadResourceGraphs(hours = 1) {
    try {
        // Fetch both history and current stats (for totals)
        const [history, currentStats] = await Promise.all([
            apiGet(`/system/stats/history?hours=${hours}`),
            apiGet('/system/stats')
        ]);

        if (history.length === 0) {
            // Show placeholder message
            ['chart-cpu', 'chart-ram', 'chart-disk'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.innerHTML = '<div class="text-muted text-center py-4">Dati non ancora disponibili</div>';
            });
            return;
        }

        const timestamps = history.map(h => new Date(h.timestamp).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' }));

        // CPU data (percentage)
        const cpuData = history.map(h => parseFloat(h.cpu.toFixed(1)));

        // Get totals from current real-time stats
        const ramTotalGB = currentStats.available
            ? (currentStats.memory.total / (1024 * 1024 * 1024))
            : 2; // fallback
        const diskTotalGB = currentStats.available
            ? (currentStats.disk.total / (1024 * 1024 * 1024))
            : 50; // fallback

        // RAM data (convert to GB)
        const ramDataGB = history.map(h => parseFloat(((h.ram_used || 0) / (1024 * 1024 * 1024)).toFixed(2)));

        // Disk data (convert to GB)
        const diskDataGB = history.map(h => parseFloat(((h.disk_used || 0) / (1024 * 1024 * 1024)).toFixed(2)));

        // Calculate min/max for each
        const cpuMinMax = { min: Math.min(...cpuData).toFixed(1), max: Math.max(...cpuData).toFixed(1) };
        const ramMinMax = { min: Math.min(...ramDataGB).toFixed(1), max: Math.max(...ramDataGB).toFixed(1) };
        const diskMinMax = { min: Math.min(...diskDataGB).toFixed(1), max: Math.max(...diskDataGB).toFixed(1) };

        // Base chart options
        const baseOptions = (data, color, categories) => ({
            series: [{ data }],
            chart: {
                type: 'area',
                height: 120,
                sparkline: { enabled: false },
                animations: { enabled: false },
                toolbar: { show: false },
                zoom: { enabled: false }
            },
            dataLabels: { enabled: false },
            stroke: { curve: 'smooth', width: 2 },
            fill: {
                type: 'gradient',
                gradient: { shadeIntensity: 1, opacityFrom: 0.4, opacityTo: 0.1 }
            },
            colors: [color],
            xaxis: {
                categories,
                labels: { show: false },
                axisBorder: { show: false },
                axisTicks: { show: false }
            },
            grid: { show: true, borderColor: '#e0e0e0', strokeDashArray: 3, padding: { left: 5, right: 5 } }
        });

        // CPU chart (percentage 0-100%)
        const cpuOptions = {
            ...baseOptions(cpuData, '#206bc4', timestamps),
            yaxis: {
                min: 0,
                max: 100,
                labels: { show: true, formatter: (val) => val.toFixed(0) + '%' }
            },
            tooltip: { y: { formatter: (val) => val.toFixed(1) + '%' } }
        };

        // RAM chart (GB, 0 to total)
        const ramOptions = {
            ...baseOptions(ramDataGB, '#2fb344', timestamps),
            yaxis: {
                min: 0,
                max: Math.ceil(ramTotalGB),
                labels: { show: true, formatter: (val) => val.toFixed(0) + ' GB' }
            },
            tooltip: { y: { formatter: (val) => val.toFixed(1) + ' GB' } }
        };

        // Disk chart (GB, 0 to total)
        const diskOptions = {
            ...baseOptions(diskDataGB, '#f76707', timestamps),
            yaxis: {
                min: 0,
                max: Math.ceil(diskTotalGB),
                labels: { show: true, formatter: (val) => val.toFixed(0) + ' GB' }
            },
            tooltip: { y: { formatter: (val) => val.toFixed(1) + ' GB' } }
        };

        // Destroy existing charts
        if (cpuChart) cpuChart.destroy();
        if (ramChart) ramChart.destroy();
        if (diskChart) diskChart.destroy();

        // Create new charts
        cpuChart = new ApexCharts(document.getElementById('chart-cpu'), cpuOptions);
        ramChart = new ApexCharts(document.getElementById('chart-ram'), ramOptions);
        diskChart = new ApexCharts(document.getElementById('chart-disk'), diskOptions);

        cpuChart.render();
        ramChart.render();
        diskChart.render();

        // Update min/max labels
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

// Add event listener for graph range toggle after setupEventListeners
const originalSetupEventListeners = setupEventListeners;
setupEventListeners = function () {
    originalSetupEventListeners();

    // Graph range toggle
    document.querySelectorAll('input[name="graph-range"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            const hours = parseInt(e.target.value);
            loadResourceGraphs(hours);
        });
    });
};

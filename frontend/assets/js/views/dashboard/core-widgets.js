/**
 * MADMIN - Dashboard / core widgets
 *
 * Render + load pairs for the non-chart core widgets: welcome, system stats,
 * services, alerts, backup status, stat cards, quick actions.
 */

import { apiGet } from '../../api.js';
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';

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

// ============== WELCOME ==============

export function renderWelcome() {
    return `
        <div class="card bg-primary text-white">
            <div class="card-body">
                <div class="d-flex align-items-center">
                    <div class="me-3">
                        <i class="ti ti-server-cog" style="font-size: 3rem;"></i>
                    </div>
                    <div class="flex-fill">
                        <h2 class="mb-1" id="dashboard-welcome">${t('dashboard.welcomeTitle')}</h2>
                        <p class="mb-0 opacity-75">${t('dashboard.welcomeSubtitle')}</p>
                    </div>
                    <div class="d-flex align-items-center gap-3">
                        <div class="text-end" id="uptime-display">
                            <span class="spinner-border spinner-border-sm"></span>
                        </div>
                        <button class="btn btn-sm px-2 py-1" style="background: rgba(255,255,255,0.2); color: white; border: 1px solid rgba(255,255,255,0.3);"
                                id="btn-widget-config" title="${t('app.widgetManagement')}">
                            <i class="ti ti-layout-dashboard fs-3"></i>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

export async function loadWelcome() {
    // Uptime
    try {
        const uptime = await apiGet('/system/uptime');
        const el = document.getElementById('uptime-display');
        if (el && uptime.available) {
            el.innerHTML = `
                <div class="text-white opacity-75" style="font-size: 0.85rem;">
                    <i class="ti ti-clock me-1"></i>${t('dashboard.onlineSince')} <strong>${uptime.uptime_formatted}</strong>
                </div>
            `;
        }
    } catch (e) {
        console.error('Failed to load uptime:', e);
    }

    // Company name in the welcome title
    try {
        const response = await fetch('/api/settings/system', {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('madmin_token')}` }
        });
        if (response.ok) {
            const settings = await response.json();
            if (settings.company_name) {
                const welcomeEl = document.getElementById('dashboard-welcome');
                if (welcomeEl) welcomeEl.textContent = t('dashboard.welcomeTo', { name: settings.company_name });
            }
        }
    } catch (e) {
        console.error('Failed to load company name:', e);
    }
}

// ============== SYSTEM STATS ==============

export function renderSystemStats() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-cpu me-2"></i>${t('dashboard.systemStats')}
                </h3>
                <div class="card-actions">
                    <div class="form-check form-switch me-3">
                        <input class="form-check-input" type="checkbox" id="auto-refresh-toggle">
                        <label class="form-check-label" for="auto-refresh-toggle">${t('dashboard.auto30s')}</label>
                    </div>
                    <button class="btn btn-ghost-primary" id="btn-refresh-stats" title="${t('common.refresh')}">
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
                            <span class="fw-bold">${t('dashboard.disk')}</span>
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

export async function loadSystemStats() {
    try {
        const stats = await apiGet('/system/stats');

        if (!stats.available) {
            document.getElementById('system-stats-container').innerHTML = `
                <div class="col-12 text-center text-muted">
                    <i class="ti ti-alert-circle me-2"></i>
                    ${t('dashboard.statsNotAvailable', { error: stats.error || 'psutil' })}
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
                <i class="ti ti-alert-circle me-2"></i>${t('dashboard.statsLoadError')}
            </div>
        `;
    }
}

// ============== SERVICES ==============

export function renderServices() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-activity me-2"></i>${t('dashboard.serviceStatus')}
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

export async function loadServicesStatus() {
    try {
        const services = await apiGet('/system/services');
        for (const [svc, data] of Object.entries(services)) {
            const el = document.getElementById(`svc-${svc}`);
            if (el) {
                const isActive = data.active;
                el.innerHTML = `
                    <span class="badge bg-${isActive ? 'success' : 'danger'}-lt">
                        ${isActive ? t('dashboard.operational') : data.status || t('dashboard.degraded')}
                    </span>
                `;
            }
        }
    } catch (error) {
        console.error('Error loading services status:', error);
        ['madmin', 'postgresql', 'nginx', 'iptables'].forEach(svc => {
            const el = document.getElementById(`svc-${svc}`);
            if (el) el.innerHTML = `<span class="badge bg-secondary-lt">${t('dashboard.unknown')}</span>`;
        });
    }
}

// ============== ALERTS ==============

export function renderAlerts() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-bell me-2"></i>${t('dashboard.systemAlerts')}
                </h3>
            </div>
            <div class="card-body" id="alerts-container">
                <div class="text-muted text-center py-3">
                    <span class="spinner-border spinner-border-sm"></span> ${t('common.loading')}
                </div>
            </div>
        </div>
    `;
}

export async function loadAlerts() {
    const container = document.getElementById('alerts-container');
    if (!container) return;

    try {
        const alerts = await apiGet('/system/alerts');

        if (alerts.length === 0) {
            container.innerHTML = `
                <div class="d-flex align-items-center text-success py-2">
                    <i class="ti ti-circle-check me-2 fs-2"></i>
                    <div>
                        <div class="fw-bold">${t('dashboard.allOk')}</div>
                        <div class="text-muted small">${t('dashboard.noActiveAlerts')}</div>
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
                    <div class="fw-bold text-${alert.severity === 'danger' ? 'danger' : 'warning'}">${escapeHtml(alert.message)}</div>
                </div>
            </div>
        `).join('');

    } catch (error) {
        console.error('Error loading alerts:', error);
        container.innerHTML = `<div class="text-muted">${t('dashboard.alertLoadError')}</div>`;
    }
}

// ============== BACKUP STATUS ==============

export function renderBackupStatus() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-archive me-2"></i>${t('dashboard.backupStatus')}
                </h3>
                <div class="card-actions" id="backup-icons">
                </div>
            </div>
            <div class="card-body" id="backup-status-container">
                <div class="text-muted text-center py-3">
                    <span class="spinner-border spinner-border-sm"></span> ${t('common.loading')}
                </div>
            </div>
        </div>
    `;
}

export async function loadBackupStatus() {
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
            const timeFormatted = backupDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            if (daysOld === 0) {
                timeStr = t('dashboard.todayAt', { time: timeFormatted });
            } else if (daysOld === 1) {
                timeStr = t('dashboard.yesterdayAt', { time: timeFormatted });
            } else {
                timeStr = t('dashboard.daysAgo', { days: daysOld, date: backupDate.toLocaleDateString() });
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
                badge = `<span class="badge bg-danger-lt">${t('dashboard.failed')}</span>`;
                avatarColor = 'danger'; avatarIcon = 'x';
            } else if (status === 'upload_failed') {
                badge = `<span class="badge bg-warning-lt">${t('dashboard.uploadFailed')}</span>`;
                avatarColor = 'warning'; avatarIcon = 'cloud-off';
            } else {
                badge = `<span class="badge bg-success-lt">${t('common.success')}</span>`;
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
                icons += `<i class="ti ti-clock text-warning fs-3 ms-2" title="${t('dashboard.backupOlderThan7d')}"></i>`;
            }
        } else {
            content = `
                <div class="d-flex align-items-center text-muted">
                    <span class="avatar bg-secondary-lt me-3"><i class="ti ti-archive-off"></i></span>
                    <div>${t('dashboard.noBackupFound')}</div>
                </div>
            `;
            icons += `<i class="ti ti-clock text-warning fs-3 ms-2" title="${t('dashboard.noBackupEverRun')}"></i>`;
        }

        // Periodic backup not enabled
        if (!settings || !settings.enabled) {
            icons += `<i class="ti ti-settings text-warning fs-3 ms-2" title="${t('dashboard.periodicBackupNotEnabled')}"></i>`;
        }

        if (iconsEl) iconsEl.innerHTML = icons;
        container.innerHTML = content;

    } catch (error) {
        console.error('Error loading backup status:', error);
        container.innerHTML = `<div class="text-muted">${t('dashboard.backupStatusLoadError')}</div>`;
    }
}

// ============== STAT CARDS ==============

export function renderStatCards() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-chart-bar me-2"></i>${t('dashboard.counters')}
                </h3>
            </div>
            <div class="card-body">
                <div class="row g-3">
                    ${[
            { id: 'system-status', get title() { return t('dashboard.systemStatus'); }, sub: t('dashboard.database'), subId: 'db-status' },
            { id: 'firewall-count', get title() { return t('dashboard.firewallRules'); }, get sub() { return t('dashboard.activeRules'); }, subId: null },
            { id: 'modules-count', get title() { return t('dashboard.installedModules'); }, get sub() { return t('dashboard.activeModules'); }, subId: null },
            { id: 'users-count', get title() { return t('dashboard.usersCount'); }, get sub() { return t('dashboard.registeredUsers'); }, subId: null },
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

export async function loadStatCards() {
    // Health check → system status
    try {
        const health = await apiGet('/health');
        document.getElementById('system-status').innerHTML = `
            <span class="status-dot status-dot-${health.status === 'healthy' ? 'active' : 'warning'} me-2"></span>
            ${health.status === 'healthy' ? t('dashboard.operational') : t('dashboard.degraded')}
        `;
        document.getElementById('db-status').innerHTML = `
            <span class="badge bg-${health.database === 'connected' ? 'success' : 'danger'}">
                ${health.database === 'connected' ? t('dashboard.connected') : t('dashboard.disconnected')}
            </span>
        `;
    } catch (e) {
        const el = document.getElementById('system-status');
        if (el) el.innerHTML = `<span class="status-dot status-dot-warning me-2"></span>${t('dashboard.loadingError')}`;
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

// ============== QUICK ACTIONS ==============

export function renderQuickActions() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-bolt me-2"></i>${t('dashboard.quickActions')}
                </h3>
            </div>
            <div class="card-body">
                <div class="row g-3">
                    <div class="col-6">
                        <a href="#users" class="btn btn-outline-primary w-100">
                            <i class="ti ti-user-plus me-2"></i>${t('dashboard.newUser')}
                        </a>
                    </div>
                    <div class="col-6">
                        <a href="#firewall" class="btn btn-outline-primary w-100">
                            <i class="ti ti-shield-plus me-2"></i>${t('dashboard.newRule')}
                        </a>
                    </div>
                    <div class="col-6">
                        <a href="#settings" class="btn btn-outline-primary w-100">
                            <i class="ti ti-settings me-2"></i>${t('dashboard.settings')}
                        </a>
                    </div>
                    <div class="col-6">
                        <a href="#modules" class="btn btn-outline-primary w-100">
                            <i class="ti ti-puzzle me-2"></i>${t('dashboard.modules')}
                        </a>
                    </div>
                </div>
            </div>
        </div>
    `;
}

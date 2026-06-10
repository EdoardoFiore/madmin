/**
 * MADMIN - Dashboard / ApexCharts widgets
 *
 * Resource trend (CPU/RAM/disk) and network traffic charts. Chart instances
 * are tracked here so destroyCharts() can free them on route change.
 */

import { apiGet } from '../../api.js';
import { t } from '../../i18n.js';

let netTrafficChart = null;
let cpuChart = null;
let ramChart = null;
let diskChart = null;

/**
 * Destroy all chart instances (called from the view's destroy()).
 */
export function destroyCharts() {
    for (const chart of [cpuChart, ramChart, diskChart, netTrafficChart]) {
        try { chart?.destroy(); } catch (e) { /* already gone */ }
    }
    cpuChart = ramChart = diskChart = netTrafficChart = null;
}

export function renderResourceGraphs() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-chart-line me-2"></i>${t('dashboard.resourceTrend')}
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
                        <h4 class="subheader">${t('dashboard.disk')}</h4>
                        <div id="chart-disk" style="height: 150px;"></div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

export function renderNetTraffic() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i class="ti ti-arrows-transfer-down me-2"></i>${t('dashboard.networkTraffic')}
                </h3>
                <div class="card-actions d-flex align-items-center gap-2">
                    <select class="form-select form-select-sm" id="net-interface-select" style="width: auto; min-width: 120px;">
                        <option value="">${t('common.loading')}</option>
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
                        <span class="spinner-border spinner-border-sm"></span> ${t('common.loading')}
                    </div>
                </div>
            </div>
        </div>
    `;
}

export async function loadResourceGraphs(hours) {
    if (typeof hours !== 'number') hours = 1;
    try {
        const [history, currentStats] = await Promise.all([
            apiGet(`/system/stats/history?hours=${hours}`),
            apiGet('/system/stats')
        ]);

        if (history.length === 0) {
            ['chart-cpu', 'chart-ram', 'chart-disk'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.innerHTML = `<div class="text-muted text-center py-4">${t('dashboard.dataNotYetAvailable')}</div>`;
            });
            return;
        }

        const timestamps = history.map(h => new Date(h.timestamp).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }));
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
            if (el) el.innerHTML = `<div class="text-muted text-center py-4">${t('dashboard.errorLoadingData')}</div>`;
        });
    }
}

export async function loadNetTraffic() {
    const select = document.getElementById('net-interface-select');
    if (!select) return;

    try {
        // Populate interface dropdown
        const netData = await apiGet('/system/network');
        if (!netData.available) {
            document.getElementById('chart-net-traffic').innerHTML = `<div class="text-muted text-center py-4">${t('dashboard.dataNotAvailable')}</div>`;
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
        document.getElementById('chart-net-traffic').innerHTML = `<div class="text-muted text-center py-4">${t('dashboard.loadingError')}</div>`;
    }
}

export async function loadNetTrafficGraph(iface, hours) {
    const container = document.getElementById('chart-net-traffic');
    if (!container) return;

    try {
        const history = await apiGet(`/system/network/history?hours=${hours}&interface=${iface}`);

        if (history.length === 0) {
            container.innerHTML = `<div class="text-muted text-center py-4"><i class="ti ti-clock me-2"></i>${t('dashboard.waitingForTrafficData')}</div>`;
            return;
        }

        const timestamps = history.map(h => new Date(h.timestamp).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }));

        // Convert bytes/s → Mbit/s  (bytes × 8 ÷ 1,000,000)
        const toBits = v => parseFloat(((v * 8) / 1_000_000).toFixed(3));
        let txData = history.map(h => toBits(h.tx_rate));
        let rxData = history.map(h => toBits(h.rx_rate));

        // Auto-scale: if values are very small, fall back to Kb/s
        const maxVal = Math.max(...txData, ...rxData);
        let unit = 'Mb/s';
        let txDisplay = txData;
        let rxDisplay = rxData;
        if (maxVal < 0.01) {
            // Show in Kb/s instead
            unit = 'Kb/s';
            txDisplay = txData.map(v => parseFloat((v * 1000).toFixed(2)));
            rxDisplay = rxData.map(v => parseFloat((v * 1000).toFixed(2)));
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
        container.innerHTML = `<div class="text-muted text-center py-4">${t('dashboard.errorLoadingData')}</div>`;
    }
}

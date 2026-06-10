/**
 * MADMIN - Skeleton Loaders
 *
 * Tabler placeholder-glow skeletons shown while a view loads its data.
 * Core views use these instead of the generic spinner; utils.loadingSpinner()
 * stays untouched for the frozen module contract.
 *
 * Semi-public: stable path /static/js/components/skeleton.js — modules may
 * adopt it. Exports are additive-only once shipped.
 */

/**
 * Table-shaped skeleton.
 * @param {number} rows
 * @param {number} cols
 * @returns {string}
 */
export function skeletonTable(rows = 5, cols = 4) {
    const row = `
        <tr>${Array.from({ length: cols }, () =>
            `<td><div class="placeholder placeholder-glow"><span class="placeholder col-8"></span></div></td>`
        ).join('')}</tr>`;
    return `
        <div class="table-responsive">
            <table class="table table-vcenter card-table">
                <thead><tr>${Array.from({ length: cols }, () =>
                    `<th><div class="placeholder placeholder-glow"><span class="placeholder col-6"></span></div></th>`
                ).join('')}</tr></thead>
                <tbody>${row.repeat(rows)}</tbody>
            </table>
        </div>`;
}

/**
 * Card grid skeleton.
 * @param {number} count
 * @param {Object} [opts]
 * @param {number} [opts.lines] - Text lines per card
 * @param {string} [opts.col] - Bootstrap column class per card
 * @returns {string}
 */
export function skeletonCards(count = 3, { lines = 3, col = 'col-md-4' } = {}) {
    const card = `
        <div class="${col}">
            <div class="card placeholder-glow">
                <div class="card-body">
                    <div class="placeholder col-5 mb-3"></div>
                    ${Array.from({ length: lines }, (_, i) =>
                        `<div class="placeholder col-${9 - (i % 3) * 2} placeholder-sm d-block mb-2"></div>`
                    ).join('')}
                </div>
            </div>
        </div>`;
    return `<div class="row g-3">${card.repeat(count)}</div>`;
}

/**
 * Chart-area skeleton.
 * @param {number} height - px
 * @returns {string}
 */
export function skeletonChart(height = 240) {
    return `
        <div class="placeholder-glow">
            <div class="placeholder col-12" style="height:${height}px"></div>
        </div>`;
}

/**
 * Single stat-card skeleton.
 * @returns {string}
 */
export function skeletonStat() {
    return `
        <div class="card placeholder-glow">
            <div class="card-body">
                <div class="placeholder col-6 placeholder-sm mb-2"></div>
                <div class="placeholder col-4" style="height:1.75rem"></div>
            </div>
        </div>`;
}

/**
 * List rows skeleton: avatar + title + optional subtext.
 * Used for alerts, backup status, any avatar+text list.
 * @param {number} count
 * @param {boolean} subtext - Show a second shorter line per row
 * @returns {string}
 */
export function skeletonListRows(count = 3, subtext = true) {
    const widths = [7, 5, 8, 6, 9, 7];
    return Array.from({ length: count }, (_, i) => `
        <div class="d-flex align-items-center py-2 placeholder-glow${i > 0 ? ' border-top' : ''}">
            <span class="placeholder avatar avatar-sm me-3 rounded"></span>
            <div class="flex-fill">
                <div class="placeholder col-${widths[i % widths.length]} d-block mb-1 placeholder-sm"></div>
                ${subtext ? `<div class="placeholder col-${widths[(i + 2) % widths.length] - 2} placeholder-xs"></div>` : ''}
            </div>
        </div>`
    ).join('');
}

/**
 * Terminal/log output skeleton: varying-width monospace lines.
 * @param {number} count
 * @returns {string}
 */
export function skeletonLines(count = 10) {
    const widths = [10, 8, 11, 7, 10, 9, 6, 11, 8, 10, 7, 9];
    return `
        <div class="placeholder-glow p-3 font-monospace">
            ${Array.from({ length: count }, (_, i) =>
                `<div class="placeholder col-${widths[i % widths.length]} d-block mb-2 placeholder-sm"></div>`
            ).join('')}
        </div>`;
}

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

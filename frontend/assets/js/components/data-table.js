/**
 * MADMIN - Data Table Component
 *
 * Declarative table in the Tabler table-vcenter style with delegated row
 * actions. Replaces the per-view hand-rolled table builders.
 *
 * Semi-public: stable path /static/js/components/data-table.js — modules may
 * adopt it. Exports are additive-only once shipped.
 *
 * Escaping contract: `label`, `value()` output and row action labels/titles
 * are escaped; `render()` is the explicit raw-HTML opt-in (badges, <code>, …)
 * and the caller is responsible for escaping interpolated data inside it.
 */

import { escapeHtml, emptyState } from '../utils.js';
import { t } from '../i18n.js';

/**
 * @param {Object} opts
 * @param {Array} opts.columns - [{ key, label, value?: (row)=>string (escaped),
 *   render?: (row)=>html (raw), className?, width?, hidden? }]
 * @param {Array} opts.rows - Plain data objects
 * @param {string} [opts.rowKey] - Property used to map DOM rows back to data (default 'id')
 * @param {Function} [opts.rowClass] - (row) => extra <tr> class
 * @param {Array} [opts.rowActions] - [{ action, icon, label?, className?,
 *   title?, visible?: (row)=>bool }] rendered as a btn-list in the last column
 * @param {Object} [opts.empty] - { icon, title, subtitle? } shown when rows is empty
 * @param {boolean} [opts.responsive] - Wrap in .table-responsive (default true)
 * @returns {{html: string, mount: Function}} mount(rootEl, { onAction }) binds
 *   ONE delegated click listener; onAction(action, row, event).
 */
export function createTable({
    columns,
    rows,
    rowKey = 'id',
    rowClass = null,
    rowActions = null,
    empty = null,
    responsive = true,
} = {}) {
    const visibleCols = columns.filter(c => !c.hidden);

    let html;
    if (!rows.length && empty) {
        html = emptyState(empty.icon, empty.title, empty.subtitle || '');
    } else {
        const head = visibleCols.map(c =>
            `<th ${c.width ? `style="width:${c.width}"` : ''} class="${c.className || ''}">${escapeHtml(c.label ?? '')}</th>`
        ).join('') + (rowActions ? `<th class="w-1 text-end">${escapeHtml(t('common.actions'))}</th>` : '');

        const body = rows.map((row, idx) => {
            const cells = visibleCols.map(c => {
                const content = c.render
                    ? c.render(row)
                    : escapeHtml(String(c.value ? c.value(row) : (row[c.key] ?? '')));
                return `<td class="${c.className || ''}">${content}</td>`;
            }).join('');

            const actions = rowActions ? `
                <td class="text-end">
                    <div class="btn-list flex-nowrap justify-content-end">
                        ${rowActions.filter(a => !a.visible || a.visible(row)).map(a => `
                            <button class="btn btn-sm ${a.className || 'btn-outline-secondary'}"
                                    data-action="${escapeHtml(a.action)}" data-row="${idx}"
                                    ${a.title ? `title="${escapeHtml(a.title)}"` : ''}>
                                ${a.icon ? `<i class="ti ${escapeHtml(a.icon)}${a.label ? ' me-1' : ''}"></i>` : ''}${a.label ? escapeHtml(a.label) : ''}
                            </button>
                        `).join('')}
                    </div>
                </td>` : '';

            return `<tr data-row="${idx}" data-key="${escapeHtml(String(row[rowKey] ?? idx))}"
                        class="${rowClass ? rowClass(row) : ''}">${cells}${actions}</tr>`;
        }).join('');

        const table = `
            <table class="table table-vcenter card-table">
                <thead><tr>${head}</tr></thead>
                <tbody>${body}</tbody>
            </table>`;
        html = responsive ? `<div class="table-responsive">${table}</div>` : table;
    }

    return {
        html,
        /**
         * Bind one delegated listener on the mounted region.
         * @param {HTMLElement} rootEl - Element that contains the table HTML
         * @param {Object} [handlers]
         * @param {Function} [handlers.onAction] - (action, row, event) => {}
         */
        mount(rootEl, { onAction } = {}) {
            if (!onAction) return;
            rootEl.addEventListener('click', (e) => {
                const btn = e.target.closest('[data-action]');
                if (!btn || !rootEl.contains(btn)) return;
                const row = rows[Number(btn.dataset.row)];
                if (row === undefined) return;
                onAction(btn.dataset.action, row, e);
            });
        },
    };
}

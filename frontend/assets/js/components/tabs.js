/**
 * MADMIN - Tabs Component
 *
 * Card-header nav-tabs with delegated switching (logs/settings pattern).
 * The caller owns the pane content; this only renders the tab bar and
 * manages the .active class.
 *
 * Semi-public: stable path /static/js/components/tabs.js — modules may adopt
 * it. Exports are additive-only once shipped.
 */

import { escapeHtml } from '../utils.js';

/**
 * Render a nav-tabs bar.
 * @param {Object} opts
 * @param {string} opts.id - Container id for the <ul>
 * @param {Array} opts.items - [{ id, label, icon? }] (label escaped)
 * @param {string} opts.active - id of the active tab
 * @returns {string}
 */
export function tabs({ id, items, active } = {}) {
    return `
        <ul class="nav nav-tabs card-header-tabs" id="${escapeHtml(id)}" role="tablist">
            ${items.map(item => `
                <li class="nav-item" role="presentation">
                    <a href="#" class="nav-link ${item.id === active ? 'active' : ''}" data-tab="${escapeHtml(item.id)}" role="tab">
                        ${item.icon ? `<i class="ti ${escapeHtml(item.icon)} me-1"></i>` : ''}${escapeHtml(item.label)}
                    </a>
                </li>
            `).join('')}
        </ul>`;
}

/**
 * Bind one delegated click listener for [data-tab] links. Idempotent: a
 * previous tabs listener on the same element is replaced.
 * Toggles .active and calls onChange(tabId) only when the tab changes.
 * @param {HTMLElement} rootEl
 * @param {Function} onChange - (tabId) => {}
 */
export function bindTabs(rootEl, onChange) {
    if (rootEl._madminTabsHandler) {
        rootEl.removeEventListener('click', rootEl._madminTabsHandler);
    }
    const handler = (e) => {
        const link = e.target.closest('[data-tab]');
        if (!link || !rootEl.contains(link)) return;
        e.preventDefault();
        if (link.classList.contains('active')) return;
        rootEl.querySelectorAll('[data-tab].active').forEach(el => el.classList.remove('active'));
        link.classList.add('active');
        onChange(link.dataset.tab);
    };
    rootEl._madminTabsHandler = handler;
    rootEl.addEventListener('click', handler);
}

/**
 * MADMIN - Pagination Component
 *
 * Tabler card-footer pagination with windowed page numbers, extracted from
 * the logs view implementation.
 *
 * Semi-public: stable path /static/js/components/pagination.js — modules may
 * adopt it. Exports are additive-only once shipped.
 */

import { t } from '../i18n.js';

/**
 * Render a card-footer pagination bar.
 * @param {Object} opts
 * @param {number} opts.page - Current page (1-based)
 * @param {number} opts.pages - Total pages
 * @param {number} opts.total - Total items
 * @param {number} [opts.windowSize] - Pages shown around the current one
 * @param {string} [opts.summaryKey] - i18n key with {current}/{total}/{items}
 * @returns {string} HTML ('' summary-only footer when there is one page)
 */
export function pagination({ page, pages, total, windowSize = 2, summaryKey = 'common.pageOf' } = {}) {
    if (pages <= 1) {
        return `<div class="card-footer"><small class="text-muted">${total} ${t('common.results')}</small></div>`;
    }

    const maxVisible = windowSize * 2 + 1;
    let start = Math.max(1, page - windowSize);
    const end = Math.min(pages, start + maxVisible - 1);
    if (end - start < maxVisible - 1) start = Math.max(1, end - maxVisible + 1);

    let items = '';
    if (start > 1) {
        items += `<li class="page-item"><a class="page-link" href="#" data-page="1">1</a></li>`;
        if (start > 2) items += `<li class="page-item disabled"><span class="page-link">…</span></li>`;
    }
    for (let i = start; i <= end; i++) {
        items += `<li class="page-item ${i === page ? 'active' : ''}">
            <a class="page-link" href="#" data-page="${i}">${i}</a></li>`;
    }
    if (end < pages) {
        if (end < pages - 1) items += `<li class="page-item disabled"><span class="page-link">…</span></li>`;
        items += `<li class="page-item"><a class="page-link" href="#" data-page="${pages}">${pages}</a></li>`;
    }

    return `
        <div class="card-footer d-flex align-items-center justify-content-between">
            <small class="text-muted">${t(summaryKey, { current: page, total: pages, items: total })}</small>
            <ul class="pagination m-0 ms-auto">
                <li class="page-item ${page <= 1 ? 'disabled' : ''}">
                    <a class="page-link" href="#" data-page="${page - 1}"><i class="ti ti-chevron-left"></i></a>
                </li>
                ${items}
                <li class="page-item ${page >= pages ? 'disabled' : ''}">
                    <a class="page-link" href="#" data-page="${page + 1}"><i class="ti ti-chevron-right"></i></a>
                </li>
            </ul>
        </div>
    `;
}

/**
 * Bind one delegated click listener for [data-page] links. Idempotent: a
 * previous pagination listener on the same element is replaced.
 * @param {HTMLElement} rootEl
 * @param {Function} onPage - (pageNumber) => {}
 */
export function bindPagination(rootEl, onPage) {
    if (rootEl._madminPaginationHandler) {
        rootEl.removeEventListener('click', rootEl._madminPaginationHandler);
    }
    const handler = (e) => {
        const link = e.target.closest('[data-page]');
        if (!link || !rootEl.contains(link)) return;
        e.preventDefault();
        if (link.closest('.page-item')?.classList.contains('disabled')) return;
        onPage(Number(link.dataset.page));
    };
    rootEl._madminPaginationHandler = handler;
    rootEl.addEventListener('click', handler);
}

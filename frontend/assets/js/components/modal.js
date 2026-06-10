/**
 * MADMIN - Modal Component
 *
 * Declarative Bootstrap modals: create, show, auto-destroy on close.
 * Replaces the hand-rolled `insertAdjacentHTML + new bootstrap.Modal` blocks.
 *
 * Semi-public: stable path /static/js/components/modal.js — modules may adopt
 * it. Exports are additive-only once shipped.
 *
 * Escaping contract: `title` and other plain-text options are escaped here;
 * `body` and `footer` are raw HTML by design — the caller composes them and is
 * responsible for escaping any interpolated data (use escapeHtml).
 */

import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';

let _seq = 0;

/**
 * Create and show a modal. The element is removed from the DOM as soon as it
 * is hidden, so every call gets a fresh modal — no stale state, no ID clashes.
 *
 * @param {Object} opts
 * @param {string} opts.title - Modal title (escaped)
 * @param {string} [opts.body] - Body HTML (raw — caller escapes data)
 * @param {string|null} [opts.footer] - Footer HTML (raw). null → default Cancel
 *   button. '' → no footer at all.
 * @param {string} [opts.size] - '' | 'sm' | 'lg' | 'xl'
 * @param {boolean} [opts.blur] - Add modal-blur backdrop (default true)
 * @param {boolean} [opts.backdropStatic] - Undismissable backdrop
 * @param {Function} [opts.onShown] - (ctx) => {} after shown.bs.modal
 * @param {Function} [opts.onAction] - (action, ctx, event) => {} delegated
 *   click handler for any [data-action] element inside the modal
 * @param {Function} [opts.onHidden] - () => {} before DOM removal
 * @returns {{el: HTMLElement, bodyEl: HTMLElement, modal: Object, hide: Function, setBusy: Function}}
 */
export function openModal({
    title,
    body = '',
    footer = null,
    size = '',
    blur = true,
    backdropStatic = false,
    onShown = null,
    onAction = null,
    onHidden = null,
} = {}) {
    const modalId = `madmin-modal-${Date.now()}-${_seq++}`;
    const sizeClass = size ? ` modal-${size}` : '';
    const footerHtml = footer === null
        ? `<button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.cancel')}</button>`
        : footer;

    document.body.insertAdjacentHTML('beforeend', `
        <div class="modal${blur ? ' modal-blur' : ''} fade" id="${modalId}" tabindex="-1"
             ${backdropStatic ? 'data-bs-backdrop="static" data-bs-keyboard="false"' : ''}>
            <div class="modal-dialog${sizeClass}">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${escapeHtml(title)}</h5>
                        ${backdropStatic ? '' : '<button type="button" class="btn-close" data-bs-dismiss="modal"></button>'}
                    </div>
                    <div class="modal-body">${body}</div>
                    ${footerHtml ? `<div class="modal-footer">${footerHtml}</div>` : ''}
                </div>
            </div>
        </div>
    `);

    const el = document.getElementById(modalId);
    const bodyEl = el.querySelector('.modal-body');
    const modal = new bootstrap.Modal(el);

    const ctx = {
        el,
        bodyEl,
        modal,
        hide() { modal.hide(); },
        /**
         * Toggle the busy state of a button inside the modal: disables it and
         * swaps its content for a spinner (+ optional label).
         */
        setBusy(selector, busy, busyLabel = '') {
            const btn = el.querySelector(selector);
            if (!btn) return;
            if (busy) {
                btn.dataset.idleHtml = btn.innerHTML;
                btn.disabled = true;
                btn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status"></span>${escapeHtml(busyLabel)}`;
            } else {
                btn.disabled = false;
                if (btn.dataset.idleHtml !== undefined) {
                    btn.innerHTML = btn.dataset.idleHtml;
                    delete btn.dataset.idleHtml;
                }
            }
        },
    };

    if (onAction) {
        el.addEventListener('click', (e) => {
            const target = e.target.closest('[data-action]');
            if (!target || !el.contains(target)) return;
            onAction(target.dataset.action, ctx, e);
        });
    }

    el.addEventListener('shown.bs.modal', () => {
        // Autofocus the first usable field (generalizes the old setTimeout hack)
        const field = el.querySelector('input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea:not([disabled])');
        if (field) field.focus();
        if (onShown) onShown(ctx);
    });

    el.addEventListener('hidden.bs.modal', () => {
        if (onHidden) onHidden();
        el.remove();
    });

    modal.show();
    return ctx;
}

/**
 * Promise-based confirmation modal.
 * utils.confirmDialog() delegates here — behavior must stay identical.
 *
 * @returns {Promise<boolean>}
 */
export function confirm({
    title,
    message,
    html = false,
    confirmText = null,
    confirmClass = 'btn-danger',
    size = 'sm',
} = {}) {
    return new Promise((resolve) => {
        openModal({
            title,
            body: html ? message : escapeHtml(message),
            size,
            footer: `
                <button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.cancel')}</button>
                <button type="button" class="btn ${confirmClass}" data-action="confirm">${escapeHtml(confirmText ?? t('common.confirm'))}</button>
            `,
            onAction(action, ctx) {
                if (action === 'confirm') {
                    // Resolve at click time (not on hidden) so callers can start
                    // their work while the close animation runs.
                    resolve(true);
                    ctx.hide();
                }
            },
            onHidden() { resolve(false); }, // no-op if already resolved
        });
    });
}

/**
 * Promise-based form modal built on components/form.js.
 * Validates on submit; resolves the typed values object, or null on cancel.
 * If `onSubmit` is provided it runs before resolving — throw inside it to keep
 * the modal open (the error message is shown on the form / as a toast).
 *
 * @param {Object} opts
 * @param {string} opts.title
 * @param {Array} opts.fields - Field specs (see components/form.js)
 * @param {string} [opts.size]
 * @param {string} [opts.submitText]
 * @param {string} [opts.submitClass]
 * @param {Function|null} [opts.onSubmit] - async (values, ctx) => {}
 * @returns {Promise<Object|null>}
 */
export async function formModal({
    title,
    fields,
    size = '',
    submitText = null,
    submitClass = 'btn-primary',
    onSubmit = null,
} = {}) {
    const { renderFields, validateForm } = await import('./form.js');
    const { showToast } = await import('../utils.js');

    return new Promise((resolve) => {
        let result = null;
        openModal({
            title,
            size,
            body: `<form data-madmin-form>${renderFields(fields)}</form>`,
            footer: `
                <button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.cancel')}</button>
                <button type="button" class="btn ${submitClass}" data-action="submit">${escapeHtml(submitText ?? t('common.save'))}</button>
            `,
            async onAction(action, ctx) {
                if (action !== 'submit') return;
                const formEl = ctx.bodyEl.querySelector('[data-madmin-form]');
                const { valid, values } = validateForm(formEl, fields);
                if (!valid) return;
                if (onSubmit) {
                    ctx.setBusy('[data-action="submit"]', true);
                    try {
                        await onSubmit(values, ctx);
                    } catch (err) {
                        ctx.setBusy('[data-action="submit"]', false);
                        showToast(err.message, 'error');
                        return;
                    }
                }
                result = values;
                ctx.hide();
            },
            onHidden() { resolve(result); },
        });
    });
}

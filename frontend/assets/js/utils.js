/**
 * MADMIN - Utilities Module
 *
 * Common utility functions used across the application.
 *
 * FROZEN MODULE CONTRACT — installable modules import this file by URL
 * (/static/js/utils.js). Do NOT rename, remove, or change the signature of:
 *   showToast, confirmDialog, loadingSpinner, escapeHtml, emptyState,
 *   statusBadge, formatDate, isValidCIDR, isValidIP
 * Additive changes only.
 */

import { t, getLang } from './i18n.js';
import { openModal, confirm as modalConfirm } from './components/modal.js';

/**
 * Show a toast notification
 * @param {string} message - Message to display
 * @param {string} type - 'success', 'error', 'warning', 'info'
 * @param {number} duration - Duration in ms (default 3000)
 */
export function showToast(message, type = 'info', duration = 3000) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const icons = {
        success: 'ti-check',
        error: 'ti-x',
        warning: 'ti-alert-triangle',
        info: 'ti-info-circle'
    };

    const titles = {
        success: t('common.success'),
        error: t('common.error'),
        warning: t('common.warning'),
        info: t('common.info')
    };

    const toastId = `toast-${Date.now()}`;
    const toastHtml = `
        <div id="${toastId}" class="toast toast-${type}" role="alert">
            <div class="toast-header">
                <i class="ti ${icons[type]} me-2"></i>
                <strong class="me-auto">${titles[type]}</strong>
                <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
            </div>
            <div class="toast-body">${escapeHtml(message)}</div>
        </div>
    `;

    container.insertAdjacentHTML('beforeend', toastHtml);

    const toastEl = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastEl, { delay: duration });
    toast.show();

    // Clean up after hide
    toastEl.addEventListener('hidden.bs.toast', () => {
        toastEl.remove();
    });
}

/**
 * Escape HTML to prevent XSS
 * @param {string} text 
 * @returns {string}
 */
export function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Format a date for display
 * @param {string|Date} date 
 * @returns {string}
 */
export function formatDate(date) {
    if (!date) return '-';
    const d = new Date(date);
    const locale = getLang() === 'it' ? 'it-IT' : 'en-US';
    return d.toLocaleDateString(locale, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

/**
 * Format relative time (e.g., "2 hours ago")
 * @param {string|Date} date 
 * @returns {string}
 */
export function formatRelativeTime(date) {
    if (!date) return '-';
    const d = new Date(date);
    const now = new Date();
    const diff = now - d;

    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (minutes < 1) return t('time.now');
    if (minutes < 60) return t('time.minutesAgo', { n: minutes });
    if (hours < 24) return t('time.hoursAgo', { n: hours });
    if (days < 7) return t('time.daysAgo', { n: days });

    return formatDate(date);
}

/**
 * Create a loading spinner HTML
 * @returns {string}
 */
export function loadingSpinner() {
    return `
        <div class="d-flex align-items-center justify-content-center py-5">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">${t('common.loading')}</span>
            </div>
        </div>
    `;
}

/**
 * Create an empty state HTML
 * @param {string} icon - Tabler icon class
 * @param {string} title 
 * @param {string} subtitle 
 * @returns {string}
 */
export function emptyState(icon, title, subtitle = '') {
    return `
        <div class="empty-state">
            <div class="empty-state-icon">
                <i class="ti ${icon}"></i>
            </div>
            <div class="empty-state-title">${escapeHtml(title)}</div>
            ${subtitle ? `<div class="empty-state-subtitle">${escapeHtml(subtitle)}</div>` : ''}
        </div>
    `;
}

/**
 * Debounce a function
 * @param {Function} func 
 * @param {number} wait 
 * @returns {Function}
 */
export function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Confirm dialog using Bootstrap modal
 * @param {string} title 
 * @param {string} message 
 * @param {string} confirmText 
 * @param {string} confirmClass 
 * @param {boolean} htmlContent - If true, message is rendered as HTML (use with caution)
 * @returns {Promise<boolean>}
 */
export function confirmDialog(title, message, confirmText = null, confirmClass = 'btn-danger', htmlContent = false, size = 'sm') {
    // Thin delegate to components/modal.js — signature and behavior are frozen.
    return modalConfirm({ title, message, html: htmlContent, confirmText, confirmClass, size });
}

/**
 * Get chain badge HTML
 * @param {string} chain 
 * @returns {string}
 */
export function chainBadge(chain) {
    const classes = {
        'INPUT': 'bg-teal-lt',
        'OUTPUT': 'bg-blue-lt',
        'FORWARD': 'bg-purple-lt',
        'PREROUTING': 'bg-orange-lt',
        'POSTROUTING': 'bg-pink-lt'
    };
    return `<span class="badge ${classes[chain] || 'bg-secondary-lt'}">${chain}</span>`;
}

/**
 * Get action badge HTML
 * @param {string} action 
 * @returns {string}
 */
export function actionBadge(action) {
    const classes = {
        // Filter actions
        'ACCEPT': 'bg-green-lt',
        'DROP': 'bg-red-lt',
        'REJECT': 'bg-orange-lt',
        'LOG': 'bg-blue-lt',
        // NAT actions
        'SNAT': 'bg-teal-lt',
        'DNAT': 'bg-cyan-lt',
        'MASQUERADE': 'bg-purple-lt',
        'REDIRECT': 'bg-pink-lt',
        // Mangle/Raw actions
        'MARK': 'bg-yellow-lt',
        'TOS': 'bg-yellow-lt',
        'TTL': 'bg-yellow-lt',
        'NOTRACK': 'bg-gray-lt'
    };
    return `<span class="badge ${classes[action] || 'bg-secondary-lt'}">${action}</span>`;
}

/**
 * Get status badge HTML
 * @param {boolean} active 
 * @returns {string}
 */
export function statusBadge(active) {
    if (active) {
        return `<span class="badge bg-green-lt">${t('common.active')}</span>`;
    }
    return `<span class="badge bg-secondary-lt">${t('common.disabled')}</span>`;
}

/**
 * Input dialog using Bootstrap modal
 * @param {string} title - Modal title
 * @param {string} label - Input label
 * @param {string} placeholder - Input placeholder
 * @param {string} type - Input type (text, email, etc.)
 * @returns {Promise<string|null>} - Input value or null if cancelled
 */
export function inputDialog(title, label, placeholder = '', type = 'text') {
    // Thin delegate to components/modal.js — signature and behavior are frozen.
    return new Promise((resolve) => {
        const ctx = openModal({
            title,
            size: 'sm',
            body: `
                <div class="mb-3">
                    <label class="form-label">${escapeHtml(label)}</label>
                    <input type="${escapeHtml(type)}" class="form-control" data-input placeholder="${escapeHtml(placeholder)}">
                </div>
            `,
            footer: `
                <button type="button" class="btn btn-link" data-bs-dismiss="modal">${t('common.cancel')}</button>
                <button type="button" class="btn btn-primary" data-action="confirm">${t('common.confirm')}</button>
            `,
            onAction(action, mctx) {
                if (action === 'confirm') {
                    resolve(mctx.bodyEl.querySelector('[data-input]').value || null);
                    mctx.hide();
                }
            },
            onHidden() {
                if (!ctx.bodyEl.querySelector('[data-input]').value) resolve(null);
            },
        });

        ctx.bodyEl.querySelector('[data-input]').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                resolve(e.target.value || null);
                ctx.hide();
            }
        });
    });
}

/**
 * Validate IPv4 CIDR notation (e.g. 192.168.1.1/24)
 * @param {string} val
 * @returns {boolean}
 */
export function isValidCIDR(val) {
    return /^(\d{1,3}\.){3}\d{1,3}\/\d{1,2}$/.test(val);
}

/**
 * Validate IPv4 address (e.g. 192.168.1.1)
 * @param {string} val
 * @returns {boolean}
 */
export function isValidIP(val) {
    return /^(\d{1,3}\.){3}\d{1,3}$/.test(val);
}

/**
 * Copy text to clipboard with fallback
 * @param {string} text 
 * @returns {Promise<boolean>}
 */
export async function copyToClipboard(text) {
    if (!text) {
        console.warn('copyToClipboard: No text provided');
        return false;
    }

    // Try Clipboard API first (if secure context)
    if (navigator.clipboard && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(text);
            console.log('Copied to clipboard via API');
            return true;
        } catch (err) {
            console.warn('Clipboard API failed, trying fallback', err);
        }
    } else {
        console.log('Clipboard API unavailable or insecure context, using fallback');
    }

    // Fallback: textarea + execCommand
    try {
        const textArea = document.createElement('textarea');
        textArea.value = text;

        // Ensure it's not visible but part of DOM
        textArea.style.position = 'fixed';
        textArea.style.left = '-9999px';
        textArea.style.top = '0';
        textArea.setAttribute('readonly', '');
        document.body.appendChild(textArea);

        textArea.focus();
        textArea.select();
        textArea.setSelectionRange(0, 99999); // For mobile devices

        const success = document.execCommand('copy');
        document.body.removeChild(textArea);

        if (success) {
            console.log('Copied to clipboard via fallback');
            return true;
        } else {
            console.error('Fallback execCommand returned false');
            return false;
        }
    } catch (err) {
        console.error('Fallback copy failed completely', err);
        return false;
    }
}

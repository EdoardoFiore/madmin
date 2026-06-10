/**
 * MADMIN - Global Error Boundary (internal, not part of the module contract)
 *
 * Catches uncaught errors and unhandled promise rejections and surfaces them
 * as an error toast instead of failing silently (or white-screening).
 */

import { showToast } from '../utils.js';

// Noise that must never reach the user as a toast.
const IGNORED_PATTERNS = [
    /^ResizeObserver loop/,          // benign Chrome/Safari layout notification
    /^Script error\.?$/,             // opaque cross-origin errors from CDN scripts
];

const DEDUPE_WINDOW_MS = 5000;
const _recent = new Map(); // message -> timestamp

function _shouldReport(message) {
    if (!message) return false;
    if (IGNORED_PATTERNS.some(re => re.test(message))) return false;
    const now = Date.now();
    const last = _recent.get(message);
    if (last && now - last < DEDUPE_WINDOW_MS) return false;
    _recent.set(message, now);
    // Keep the dedupe map from growing unbounded
    if (_recent.size > 50) {
        for (const [msg, ts] of _recent) {
            if (now - ts > DEDUPE_WINDOW_MS) _recent.delete(msg);
        }
    }
    return true;
}

function _report(message, source) {
    if (!_shouldReport(message)) return;
    try {
        showToast(message, 'error');
    } catch (toastErr) {
        // Toast container missing (e.g. login page) — fall back to console only
        console.error('Error boundary fallback:', toastErr);
    }
    console.error(`[${source}]`, message);
}

/**
 * Install the global handlers. Call once, as early as possible in app init.
 */
export function installErrorBoundary() {
    window.addEventListener('error', (e) => {
        _report(e.message, 'uncaught');
    });

    window.addEventListener('unhandledrejection', (e) => {
        const reason = e.reason;
        const message = reason instanceof Error ? reason.message : String(reason ?? 'Unhandled rejection');
        _report(message, 'unhandledrejection');
    });
}

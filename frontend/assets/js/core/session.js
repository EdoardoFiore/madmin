/**
 * MADMIN - Session Expiry Watch (internal, not part of the module contract)
 *
 * The backend has no token-refresh endpoint, so this is warn-and-redirect:
 * decode the JWT exp claim, warn the user 5 minutes before expiry, and
 * redirect to /login?expired=1&next=<hash> when the token actually expires.
 */

import { getToken, redirectToLogin } from '../api.js';
import { t } from '../i18n.js';

const WARN_BEFORE_MS = 5 * 60 * 1000;

let _warnTimer = null;
let _expireTimer = null;

/**
 * Decode the exp claim (epoch seconds) from a JWT without verifying it.
 * Returns null when the token is missing or unparsable.
 */
function getTokenExpiry() {
    const token = getToken();
    if (!token) return null;
    try {
        const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
        return typeof payload.exp === 'number' ? payload.exp * 1000 : null;
    } catch {
        return null;
    }
}

/**
 * Start watching the current token. Call once after login state is known.
 */
export function startSessionWatch() {
    clearTimeout(_warnTimer);
    clearTimeout(_expireTimer);

    const expiry = getTokenExpiry();
    if (!expiry) return;

    const now = Date.now();
    if (expiry <= now) {
        redirectToLogin(true);
        return;
    }

    const warnIn = Math.max(0, expiry - now - WARN_BEFORE_MS);
    _warnTimer = setTimeout(() => showExpiryWarning(expiry), warnIn);
    _expireTimer = setTimeout(() => redirectToLogin(true), expiry - now);
}

/**
 * Warning modal with a live countdown. Acknowledge-only: the session cannot
 * be extended (no refresh endpoint), it just stops surprising the user.
 */
async function showExpiryWarning(expiry) {
    const { openModal } = await import('../components/modal.js');

    let countdownInterval = null;
    const remainingText = () => {
        const ms = Math.max(0, expiry - Date.now());
        const m = Math.floor(ms / 60000);
        const s = Math.floor((ms % 60000) / 1000);
        return `${m}:${String(s).padStart(2, '0')}`;
    };

    openModal({
        title: t('session.expireSoonTitle'),
        size: 'sm',
        backdropStatic: true,
        body: `
            <div class="text-center">
                <i class="ti ti-clock-exclamation text-warning" style="font-size: 3rem;"></i>
                <p class="mt-3 mb-1">${t('session.expireSoonBody')}</p>
                <div class="h2 my-2" data-session-countdown>${remainingText()}</div>
                <p class="text-muted small mb-0">${t('session.expireSoonHint')}</p>
            </div>
        `,
        footer: `<button type="button" class="btn btn-primary w-100" data-action="ack">${t('session.expireSoonAck')}</button>`,
        onShown(ctx) {
            countdownInterval = setInterval(() => {
                const el = ctx.el.querySelector('[data-session-countdown]');
                if (el) el.textContent = remainingText();
            }, 1000);
        },
        onAction(action, ctx) {
            if (action === 'ack') ctx.hide();
        },
        onHidden() {
            clearInterval(countdownInterval);
        },
    });
}

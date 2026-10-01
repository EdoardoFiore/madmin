/**
 * MADMIN - Firewall hub
 *
 * Entry point for the #firewall route. Renders a view toggle (Standard /
 * Advanced) plus an Objects shortcut, and mounts the selected sub-view. The
 * default landing view is remembered per-user.
 *
 *   #firewall            -> remembered default (standard|advanced)
 *   #firewall/standard   -> Standard (FortiGate-style) view
 *   #firewall/advanced   -> Advanced (power-user) view
 *   #firewall/objects    -> Address objects & groups
 */
import { apiPatch } from '../../api.js';
import { getUser } from '../../app.js';
import { t } from '../../i18n.js';

const MODES = ['standard', 'advanced', 'objects'];
const DEFAULTABLE = ['standard', 'advanced'];

function readPrefs() {
    const user = getUser();
    try { return JSON.parse(user?.preferences || '{}'); } catch { return {}; }
}

function defaultView() {
    const v = readPrefs().firewall_default_view;
    return DEFAULTABLE.includes(v) ? v : 'standard';
}

async function saveDefaultView(mode) {
    if (!DEFAULTABLE.includes(mode)) return;
    const user = getUser();
    if (!user) return;
    const prefs = readPrefs();
    if (prefs.firewall_default_view === mode) return;
    prefs.firewall_default_view = mode;
    const str = JSON.stringify(prefs);
    try {
        await apiPatch('/auth/me/preferences', { preferences: str });
        user.preferences = str;   // keep the in-session copy fresh
    } catch { /* non-fatal */ }
}

function toolbar(mode) {
    const seg = (m, icon, label) => `
        <input type="radio" class="btn-check" name="fw-view-mode" id="fw-mode-${m}"
               value="${m}" ${m === mode ? 'checked' : ''}>
        <label class="btn ${m === mode ? 'btn-primary' : 'btn-outline-primary'}" for="fw-mode-${m}">
            <i class="ti ti-${icon} me-1"></i>${label}
        </label>`;
    return `
        <div class="d-flex align-items-center justify-content-between mb-3 flex-wrap gap-2">
            <div class="btn-group" role="group" aria-label="${t('firewall.hub.viewToggle')}">
                ${seg('standard', 'layout-list', t('firewall.hub.standard'))}
                ${seg('advanced', 'adjustments-alt', t('firewall.hub.advanced'))}
            </div>
            <a href="#firewall/objects" class="btn ${mode === 'objects' ? 'btn-primary' : 'btn-outline-secondary'}">
                <i class="ti ti-address-book me-1"></i>${t('firewall.hub.objects')}
            </a>
        </div>`;
}

export async function render(container, params = []) {
    const requested = (params[0] || '').toLowerCase();
    const mode = MODES.includes(requested) ? requested : defaultView();

    // Remember Standard/Advanced as the default landing view.
    if (DEFAULTABLE.includes(mode)) saveDefaultView(mode);

    container.innerHTML = `
        <div id="fw-hub">
            ${toolbar(mode)}
            <div id="fw-view"></div>
        </div>`;

    // View toggle -> navigate (app.js re-renders this hub with the new param).
    container.querySelectorAll('input[name="fw-view-mode"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            window.location.hash = `#firewall/${e.target.value}`;
        });
    });

    const viewEl = container.querySelector('#fw-view');
    const rest = params.slice(1);

    let mod;
    if (mode === 'advanced') mod = await import('./advanced.js');
    else if (mode === 'objects') mod = await import('./addresses.js');
    else mod = await import('./standard.js');

    await mod.render(viewEl, rest);
}

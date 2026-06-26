/**
 * MADMIN - Firewall interface helper
 *
 * Caches the network interface list and builds interface <select> dropdowns so
 * rule fields pick a real interface instead of free-typing a name.
 */
import { apiGet } from '../../api.js';
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';

let _cache = null;

/**
 * Load (and cache) the list of network interfaces. Returns an array of
 * { name, ipv4, is_up, ... }. Pass force=true to refresh.
 */
export async function loadInterfaces(force = false) {
    if (_cache && !force) return _cache;
    try {
        const data = await apiGet('/network/interfaces');
        _cache = data.interfaces || [];
    } catch {
        _cache = [];
    }
    return _cache;
}

/** Synchronously read the cached interfaces (empty until loadInterfaces runs). */
export function cachedInterfaces() {
    return _cache || [];
}

/**
 * Build an interface <select>. The cache must be primed (loadInterfaces) first.
 *
 * @param {string} id           element id
 * @param {string} selected     currently selected interface name ('' = any)
 * @param {object} opts         { includeAny=true, anyLabel, className }
 */
export function interfaceSelect(id, selected = '', opts = {}) {
    const { includeAny = true, anyLabel = t('firewall.editor.anyInterface'), className = 'form-select' } = opts;
    const ifaces = cachedInterfaces();
    const names = ifaces.map(i => i.name);

    let options = '';
    if (includeAny) {
        options += `<option value="" ${selected ? '' : 'selected'}>${escapeHtml(anyLabel)}</option>`;
    }
    options += ifaces.map(i => {
        const label = i.ipv4 ? `${i.name} (${i.ipv4})` : i.name;
        return `<option value="${escapeHtml(i.name)}" ${i.name === selected ? 'selected' : ''}>${escapeHtml(label)}</option>`;
    }).join('');

    // Keep an unknown saved interface selectable (e.g. an iface that is currently down).
    if (selected && !names.includes(selected)) {
        options += `<option value="${escapeHtml(selected)}" selected>${escapeHtml(selected)}</option>`;
    }

    return `<select class="${className}" id="${id}">${options}</select>`;
}

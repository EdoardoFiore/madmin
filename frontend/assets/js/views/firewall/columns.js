/**
 * MADMIN - Firewall View / column visibility preferences
 */

import { apiGet, apiPatch } from '../../api.js';
import { showToast } from '../../utils.js';
import { t } from '../../i18n.js';
import { ALL_COLUMNS, DEFAULT_COLUMNS } from './constants.js';

/**
 * Load user preferences from API
 */
export async function loadUserPreferences(state) {
    try {
        const user = await apiGet('/auth/me');
        if (user.preferences) {
            state.userPreferences = JSON.parse(user.preferences);
        }
    } catch (e) {
        console.error('Failed to load preferences:', e);
        state.userPreferences = {};
    }
    updateVisibleColumns(state);
}

/**
 * Save user preferences to API
 */
async function saveUserPreferences(state) {
    try {
        await apiPatch('/auth/me/preferences', {
            preferences: JSON.stringify(state.userPreferences)
        });
    } catch (e) {
        showToast(t('firewall.savePrefError'), 'error');
    }
}

/**
 * Get visible columns ordered by definition and filtered by current table
 */
export function getOrderedVisibleColumns(state) {
    return Object.keys(ALL_COLUMNS).filter(key => {
        // Must be enabled by user
        if (!state.visibleColumns.includes(key)) return false;

        // Must be valid for current table
        const colDef = ALL_COLUMNS[key];
        if (colDef.tables && !colDef.tables.includes(state.currentTable)) return false;

        return true;
    });
}

/**
 * Render the column selector dropdown
 */
export function renderColumnSelector(state) {
    const container = document.getElementById('column-selector');
    if (!container) return;

    // Filter columns valid for current table
    const validColumns = Object.entries(ALL_COLUMNS).filter(([key, col]) => {
        if (col.tables && !col.tables.includes(state.currentTable)) return false;
        return true;
    });

    container.innerHTML = validColumns.map(([key, col]) => `
        <label class="dropdown-item">
            <input class="form-check-input m-0 me-2 column-toggle" type="checkbox"
                   value="${key}" ${state.visibleColumns.includes(key) ? 'checked' : ''}>
            ${col.label}
        </label>
    `).join('');

    // Re-attach listeners
    container.querySelectorAll('.column-toggle').forEach(chk => {
        chk.addEventListener('change', (e) => handleColumnToggle(state, e));
    });
}

/**
 * Handle column visibility toggle
 */
function handleColumnToggle(state, e) {
    const column = e.target.value;
    const checked = e.target.checked;

    if (checked) {
        if (!state.visibleColumns.includes(column)) state.visibleColumns.push(column);
    } else {
        state.visibleColumns = state.visibleColumns.filter(c => c !== column);
    }

    // Save to user preferences
    if (!state.userPreferences.firewall_columns) state.userPreferences.firewall_columns = {};
    state.userPreferences.firewall_columns[state.currentTable] = state.visibleColumns;

    // Save to backend (fire and forget)
    saveUserPreferences(state);

    // Re-render rules with the new column set
    state.rerender();
}

/**
 * Update visible columns based on current table and preferences
 */
export function updateVisibleColumns(state) {
    const tablePrefs = state.userPreferences.firewall_columns || {};
    // Ensure we start with a copy of defaults if nothing saved
    state.visibleColumns = [...(tablePrefs[state.currentTable] || DEFAULT_COLUMNS[state.currentTable])];
    renderColumnSelector(state);
}

/**
 * MADMIN - Dashboard / module widgets (FROZEN CONTRACT SURFACE)
 *
 * Loads widget metadata from GET /modules/widgets and dynamically imports
 * each module's /static/modules/{id}/views/widgets.js, which must export:
 *   { widgets: { [widget_id]: { render(), load()? } } }
 * Do not change these paths or shapes — every installed module relies on them.
 */

import { apiGet } from '../../api.js';

/**
 * Load module widgets from the API and register them in widgetMap.
 * Returns the list of registered module widget ids.
 */
export async function loadModuleWidgets(widgetMap) {
    const registeredIds = [];
    try {
        const moduleWidgets = await apiGet('/modules/widgets');
        if (!Array.isArray(moduleWidgets) || moduleWidgets.length === 0) return registeredIds;

        for (const mw of moduleWidgets) {
            // Skip if already registered
            if (widgetMap[mw.widget_id]) continue;

            try {
                // Dynamic import of the module's widgets.js
                const mod = await import(`/static/modules/${mw.module_id}/views/widgets.js`);
                const impl = mod.widgets?.[mw.widget_id];
                if (impl) {
                    widgetMap[mw.widget_id] = {
                        id: mw.widget_id,
                        title: mw.title,
                        col: mw.col || 6,
                        fixed: false,
                        render: impl.render,
                        load: impl.load || null,
                    };
                    registeredIds.push(mw.widget_id);
                }
            } catch (e) {
                console.warn(`Module widget ${mw.widget_id} load error:`, e);
            }
        }
    } catch (e) {
        // Modules API not available or no modules — silently skip
        console.debug('No module widgets available:', e.message);
    }
    return registeredIds;
}

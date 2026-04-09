/**
 * WireGuard Module - Main Entry Point
 *
 * Routes between instance list and instance detail views.
 */

import { loadModuleTranslations } from '/static/js/i18n.js';
import { checkPermission } from '/static/js/app.js';
import { renderWgList } from '/static/modules/wireguard/views/wgList.js';
import { renderWgDetail } from '/static/modules/wireguard/views/wgDetail.js';

export async function render(container, params) {
    await loadModuleTranslations('wireguard');

    const canManage = checkPermission('wireguard.manage');
    const canClients = checkPermission('wireguard.clients');

    if (params && params.length > 0) {
        await renderWgDetail(container, params[0], canManage, canClients);
    } else {
        await renderWgList(container, canManage);
    }
}

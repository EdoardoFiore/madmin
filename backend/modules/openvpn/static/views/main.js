/**
 * OpenVPN Module - Main Entry Point
 *
 * Routes between instance list and instance detail views.
 */

import { loadModuleTranslations } from '/static/js/i18n.js';
import { checkPermission } from '/static/js/app.js';
import { renderOvpnList } from '/static/modules/openvpn/views/ovpnList.js';
import { renderOvpnDetail } from '/static/modules/openvpn/views/ovpnDetail.js';

export async function render(container, params) {
    await loadModuleTranslations('openvpn');

    const canManage = checkPermission('openvpn.manage');
    const canClients = checkPermission('openvpn.clients');

    if (params && params.length > 0) {
        await renderOvpnDetail(container, params[0], canManage, canClients);
    } else {
        await renderOvpnList(container, canManage);
    }
}

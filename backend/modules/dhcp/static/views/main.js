/**
 * DHCP Module - Main Entry Point
 *
 * Routes between dashboard and subnet detail views.
 */

import { loadModuleTranslations } from '/static/js/i18n.js';
import { checkPermission } from '/static/js/app.js';
import { renderDhcpDashboard } from '/static/modules/dhcp/views/dhcpDashboard.js';
import { renderDhcpDetail } from '/static/modules/dhcp/views/dhcpDetail.js';

export async function render(container, params) {
    await loadModuleTranslations('dhcp');

    const canManage = checkPermission('dhcp.manage');
    const canReservations = checkPermission('dhcp.reservations');

    if (params && params.length > 0) {
        await renderDhcpDetail(container, params[0], canManage, canReservations);
    } else {
        await renderDhcpDashboard(container, canManage);
    }
}

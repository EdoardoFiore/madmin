/**
 * DNS Module - Main Entry Point
 *
 * Routes between dashboard and zone detail views.
 */

import { loadModuleTranslations } from '/static/js/i18n.js';
import { checkPermission } from '/static/js/app.js';
import { renderDnsStatus } from '/static/modules/dns/views/dnsStatus.js';
import { renderDnsZoneDetail } from '/static/modules/dns/views/dnsZones.js';

export async function render(container, params) {
    await loadModuleTranslations('dns');

    const perms = {
        manage: checkPermission('dns.manage'),
        zones: checkPermission('dns.zones'),
        records: checkPermission('dns.records'),
    };

    if (params && params.length > 0) {
        await renderDnsZoneDetail(container, params[0], perms);
    } else {
        await renderDnsStatus(container, perms);
    }
}

/**
 * MADMIN - Logs View
 *
 * Two-tab log viewer:
 * - Audit Log: structured API call log from DB (with user info)
 * - System Log: raw journalctl output
 */

import { apiGet } from '../../api.js';
import { t } from '../../i18n.js';
import { tabs, bindTabs } from '../../components/tabs.js';
import { renderAuditTab } from './audit.js';
import { renderSystemTab } from './system.js';

/**
 * Render the logs view
 */
export async function render(container) {
    const state = {
        auditUsers: [],
        auditPage: 1,
        auditFilters: { category: 'write', user: '', method: '', search: '', from_date: '', to_date: '' },
        contentEl: null,
    };

    // Pre-fetch user list + initial audit page in parallel before any DOM write
    const [usersData, auditPreData] = await Promise.all([
        apiGet('/logs/audit/users').catch(() => ({ users: [] })),
        apiGet('/logs/audit?page=1&per_page=50&category=write').catch(() => null),
    ]);
    state.auditUsers = usersData.users || [];

    container.innerHTML = `
        <div class="row row-deck row-cards">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        ${tabs({
                            id: 'logs-tabs',
                            active: 'audit',
                            items: [
                                { id: 'audit', label: t('logs.auditLog'), icon: 'ti-list-search' },
                                { id: 'system', label: t('logs.systemLog'), icon: 'ti-terminal' },
                            ],
                        })}
                    </div>
                    <div id="logs-tab-content"></div>
                </div>
            </div>
        </div>
    `;

    state.contentEl = document.getElementById('logs-tab-content');

    bindTabs(document.getElementById('logs-tabs'), (tabId) => {
        if (tabId === 'audit') renderAuditTab(state);
        else renderSystemTab(state);
    });

    await renderAuditTab(state, auditPreData);
}

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

    // Load user list for the audit filter
    try {
        const usersData = await apiGet('/logs/audit/users');
        state.auditUsers = usersData.users || [];
    } catch (e) {
        state.auditUsers = [];
    }

    await renderAuditTab(state);
}

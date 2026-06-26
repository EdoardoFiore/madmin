/**
 * MADMIN - Firewall editor "Select Entries" panel
 *
 * Right-side panel of the rule editor. Lists address objects & groups for the
 * currently active field (Source / Destination), lets the user toggle them, and
 * create a brand-new address object inline (without leaving the editor).
 *
 * The editor owns selection state; this component renders and reports events.
 */
import { apiPost } from '../../api.js';
import { showToast, escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';

const TYPE_ICON = { cidr: 'ti-network', range: 'ti-arrows-left-right', fqdn: 'ti-link', geo: 'ti-world' };

/**
 * @param {HTMLElement} panelEl
 * @param {object} opts
 *   objects: AddressObjectResponse[]
 *   groups:  AddressGroupResponse[]
 *   isSelected(compositeId): boolean   // 'obj:<id>' | 'grp:<id>'
 *   onToggle(compositeId): void
 *   onCreated(object): void            // new object appended to data + selected
 *   activeLabel(): string | null       // e.g. "Source"; null = no active field
 */
export function createEntriesPanel(panelEl, opts) {
    let query = '';
    let creating = false;

    function itemRow(item, composite) {
        const sel = opts.isSelected(composite);
        const icon = item.__kind === 'group' ? 'ti-stack-2' : (TYPE_ICON[item.type] || 'ti-box');
        const sub = item.__kind === 'group' ? t('firewall.entries.group') : (item.value || item.type);
        return `
            <button type="button" class="list-group-item list-group-item-action d-flex align-items-center gap-2 ${sel ? 'active' : ''}"
                    data-composite="${composite}">
                <i class="ti ${icon}"></i>
                <span class="flex-grow-1 text-truncate">${escapeHtml(item.name)}</span>
                <small class="${sel ? '' : 'text-muted'} text-truncate" style="max-width:45%">${escapeHtml(sub || '')}</small>
                ${sel ? '<i class="ti ti-check"></i>' : ''}
            </button>`;
    }

    function listHtml() {
        const q = query.toLowerCase();
        const objs = (opts.objects || [])
            .map(o => ({ ...o, __kind: 'object' }))
            .filter(o => !q || o.name.toLowerCase().includes(q) || (o.value || '').toLowerCase().includes(q));
        const grps = (opts.groups || [])
            .map(g => ({ ...g, __kind: 'group' }))
            .filter(g => !q || g.name.toLowerCase().includes(q));

        if (!objs.length && !grps.length) {
            return `<div class="text-muted small p-3">${t('common.noResults')}</div>`;
        }
        let html = '<div class="list-group list-group-flush">';
        if (objs.length) {
            html += `<div class="px-3 py-1 text-muted small text-uppercase bg-light">${t('firewall.entries.addresses')}</div>`;
            html += objs.map(o => itemRow(o, `obj:${o.id}`)).join('');
        }
        if (grps.length) {
            html += `<div class="px-3 py-1 text-muted small text-uppercase bg-light border-top">${t('firewall.entries.groups')}</div>`;
            html += grps.map(g => itemRow(g, `grp:${g.id}`)).join('');
        }
        html += '</div>';
        return html;
    }

    function createFormHtml() {
        return `
            <div class="border rounded p-2 mb-2 ${creating ? '' : 'd-none'}" id="entries-create">
                <div class="mb-2">
                    <input type="text" class="form-control form-control-sm" id="entries-new-name"
                           placeholder="${t('firewall.addr.labelName')}">
                </div>
                <div class="mb-2 d-flex gap-2">
                    <select class="form-select form-select-sm" id="entries-new-type" style="max-width:120px">
                        <option value="cidr">${t('firewall.addr.typeCidr')}</option>
                        <option value="range">${t('firewall.addr.typeRange')}</option>
                        <option value="fqdn">${t('firewall.addr.typeFqdn')}</option>
                    </select>
                    <input type="text" class="form-control form-control-sm" id="entries-new-value"
                           placeholder="192.168.1.0/24">
                </div>
                <div class="d-flex justify-content-end gap-2">
                    <button type="button" class="btn btn-sm btn-link" id="entries-new-cancel">${t('common.cancel')}</button>
                    <button type="button" class="btn btn-sm btn-primary" id="entries-new-save">${t('common.save')}</button>
                </div>
            </div>`;
    }

    function render() {
        const active = opts.activeLabel();
        panelEl.innerHTML = `
            <div class="card h-100">
                <div class="card-header py-2">
                    <div class="d-flex align-items-center w-100">
                        <strong>${t('firewall.entries.title')}</strong>
                        <button type="button" class="btn btn-sm btn-outline-primary ms-auto" id="entries-toggle-create">
                            <i class="ti ti-plus"></i>
                        </button>
                    </div>
                    <div class="small text-muted mt-1">
                        ${active ? t('firewall.entries.editingField', { field: active })
                                 : t('firewall.entries.pickFieldHint')}
                    </div>
                </div>
                <div class="card-body p-2">
                    ${createFormHtml()}
                    <input type="search" class="form-control form-control-sm mb-2" id="entries-search"
                           placeholder="${t('firewall.addr.pickerSearch')}" value="${escapeHtml(query)}">
                    <div id="entries-list" style="max-height:380px;overflow-y:auto;${active ? '' : 'opacity:.5;pointer-events:none;'}">
                        ${listHtml()}
                    </div>
                </div>
            </div>`;

        // Search
        const search = panelEl.querySelector('#entries-search');
        search.addEventListener('input', () => {
            query = search.value;
            panelEl.querySelector('#entries-list').innerHTML = listHtml();
            bindList();
        });
        // Restore focus position after a search re-render is unnecessary (list-only re-render).
        bindList();

        // Toggle create form
        panelEl.querySelector('#entries-toggle-create').addEventListener('click', () => {
            creating = !creating;
            render();
        });
        if (creating) {
            panelEl.querySelector('#entries-new-cancel').addEventListener('click', () => { creating = false; render(); });
            panelEl.querySelector('#entries-new-save').addEventListener('click', onCreate);
        }
    }

    function bindList() {
        panelEl.querySelectorAll('#entries-list [data-composite]').forEach(btn => {
            btn.addEventListener('click', () => {
                opts.onToggle(btn.dataset.composite);
                panelEl.querySelector('#entries-list').innerHTML = listHtml();
                bindList();
            });
        });
    }

    async function onCreate() {
        const name = panelEl.querySelector('#entries-new-name').value.trim();
        const type = panelEl.querySelector('#entries-new-type').value;
        const value = panelEl.querySelector('#entries-new-value').value.trim();
        if (!name || !value) {
            showToast(t('firewall.entries.nameValueRequired'), 'error');
            return;
        }
        try {
            const obj = await apiPost('/firewall/addresses', { name, type, value });
            showToast(t('firewall.addr.objectCreated'), 'success');
            creating = false;
            opts.onCreated(obj);     // editor appends to data + selects it
            render();
        } catch (err) {
            showToast(t('common.errorPrefix') + err.message, 'error');
        }
    }

    render();
    return { render };
}

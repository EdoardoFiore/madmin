/**
 * MADMIN - Firewall editor "Select Entries" panel
 *
 * Content of the right-side offcanvas of the rule editor (the editor owns the
 * offcanvas shell; this component renders into its body). Lists address objects
 * & groups for the currently active field (Source / Destination), lets the user
 * toggle them, and create a brand-new address object inline (cidr / range / fqdn
 * / geo) without leaving the editor.
 *
 * The editor owns selection state; this component renders and reports events.
 */
import { apiGet, apiPost } from '../../api.js';
import { showToast, escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';

const TYPE_ICON = { cidr: 'ti-network', range: 'ti-arrows-left-right', fqdn: 'ti-link', geo: 'ti-world' };

// Geo country list is shared across panel instances; loaded lazily on first
// time the user picks the "geo" type in the inline create form.
let geoCountries = null;

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
    let newType = 'cidr';

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
        let html = '<div class="list-group list-group-flush border rounded">';
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

    // Value field: free text for cidr/range/fqdn, country dropdown for geo.
    function valueFieldHtml() {
        if (newType === 'geo') {
            const opts = (geoCountries || [])
                .map(c => `<option value="${escapeHtml(c.code)}">${escapeHtml(c.name)} (${escapeHtml((c.code || '').toUpperCase())})</option>`)
                .join('');
            return `<select class="form-select form-select-sm" id="entries-new-value">${opts}</select>`;
        }
        const ph = { cidr: '192.168.1.0/24', range: '10.0.0.1-10.0.0.20', fqdn: 'example.com' }[newType] || '';
        return `<input type="text" class="form-control form-control-sm" id="entries-new-value" placeholder="${ph}">`;
    }

    function createFormHtml() {
        return `
            <div class="card card-sm mb-2 ${creating ? '' : 'd-none'}" id="entries-create">
                <div class="card-body">
                    <div class="mb-2">
                        <label class="form-label small mb-1">${t('firewall.addr.labelName')}</label>
                        <input type="text" class="form-control form-control-sm" id="entries-new-name">
                    </div>
                    <div class="mb-2">
                        <label class="form-label small mb-1">${t('firewall.addr.labelType')}</label>
                        <select class="form-select form-select-sm" id="entries-new-type">
                            <option value="cidr" ${newType === 'cidr' ? 'selected' : ''}>${t('firewall.addr.typeCidr')}</option>
                            <option value="range" ${newType === 'range' ? 'selected' : ''}>${t('firewall.addr.typeRange')}</option>
                            <option value="fqdn" ${newType === 'fqdn' ? 'selected' : ''}>${t('firewall.addr.typeFqdn')}</option>
                            <option value="geo" ${newType === 'geo' ? 'selected' : ''}>${t('firewall.addr.typeGeo')}</option>
                        </select>
                    </div>
                    <div class="mb-2">
                        <label class="form-label small mb-1">${t('firewall.addr.labelValue')}</label>
                        ${valueFieldHtml()}
                    </div>
                    <div class="d-flex justify-content-end gap-2">
                        <button type="button" class="btn btn-sm btn-link" id="entries-new-cancel">${t('common.cancel')}</button>
                        <button type="button" class="btn btn-sm btn-primary" id="entries-new-save">${t('common.save')}</button>
                    </div>
                </div>
            </div>`;
    }

    function render() {
        const active = opts.activeLabel();
        panelEl.innerHTML = `
            <div class="d-flex align-items-center mb-2">
                <div class="small text-muted flex-grow-1">
                    ${active ? t('firewall.entries.editingField', { field: active })
                             : t('firewall.entries.pickFieldHint')}
                </div>
                <button type="button" class="btn btn-sm btn-outline-primary ms-2" id="entries-toggle-create">
                    <i class="ti ti-plus"></i>
                </button>
            </div>
            ${createFormHtml()}
            <input type="search" class="form-control form-control-sm mb-2" id="entries-search"
                   placeholder="${t('firewall.addr.pickerSearch')}" value="${escapeHtml(query)}">
            <div id="entries-list" style="${active ? '' : 'opacity:.5;pointer-events:none;'}">
                ${listHtml()}
            </div>`;

        // Search
        const search = panelEl.querySelector('#entries-search');
        search.addEventListener('input', () => {
            query = search.value;
            panelEl.querySelector('#entries-list').innerHTML = listHtml();
            bindList();
        });
        bindList();

        // Toggle create form
        panelEl.querySelector('#entries-toggle-create').addEventListener('click', () => {
            creating = !creating;
            render();
        });
        if (creating) {
            panelEl.querySelector('#entries-new-cancel').addEventListener('click', () => { creating = false; render(); });
            panelEl.querySelector('#entries-new-save').addEventListener('click', onCreate);
            panelEl.querySelector('#entries-new-type').addEventListener('change', onTypeChange);
        }
    }

    async function onTypeChange(e) {
        newType = e.target.value;
        if (newType === 'geo') await loadGeoCountries();
        render();
    }

    async function loadGeoCountries() {
        if (geoCountries) return;
        try { geoCountries = await apiGet('/firewall/geo/countries'); }
        catch { geoCountries = []; }
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
        const value = (panelEl.querySelector('#entries-new-value').value || '').trim();
        if (!name || !value) {
            showToast(t('firewall.entries.nameValueRequired'), 'error');
            return;
        }
        try {
            const obj = await apiPost('/firewall/addresses', { name, type, value });
            showToast(t('firewall.addr.objectCreated'), 'success');
            creating = false;
            newType = 'cidr';
            opts.onCreated(obj);     // editor appends to data + selects it
            render();
        } catch (err) {
            showToast(t('common.errorPrefix') + err.message, 'error');
        }
    }

    render();
    return { render };
}

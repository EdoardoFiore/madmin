/**
 * MADMIN - Firewall rule editor (side panel)
 *
 * FortiGate-style editor in a wide right-hand offcanvas over the rule list,
 * with the "Select Entries" panel as its right column. Clicking outside or
 * Esc closes it when nothing changed and asks for confirmation otherwise;
 * onClose runs once it is gone. Two curated modes:
 *   policy      -> filter/FORWARD ACCEPT|DROP with optional NAT (policy_nat),
 *                  through the outgoing interface's address or one picked
 *                  address of the machine (to_source)
 *   portforward -> nat/PREROUTING DNAT
 * Outbound NAT has no mode of its own: it belongs to the policies.
 *
 * Source/Destination are combined fields: type a CIDR/IP (Enter) or pick/create
 * address objects via the entries panel. Mapping to the backend: a single typed
 * literal with no refs uses the rule's source/destination column; otherwise each
 * literal is materialised as an address object and everything goes through refs.
 */
import { apiGet, apiPost, apiPatch } from '../../api.js';
import { showToast, escapeHtml, confirmDialog } from '../../utils.js';
import { checkPermission, setNavigationGuard, clearNavigationGuard } from '../../app.js';
import { t } from '../../i18n.js';
import { loadInterfaces, interfaceSelect, cachedInterfaces, natSourceOptions, natSourceValue, natSourcePayload } from './interfaces.js';
import { SERVICE_PRESETS, validateRuleConstraints, isLockedForMode, terminateSessions, natChanged } from './shared.js';
import { createEntriesPanel } from './entries-panel.js';

let st = null;   // editor state

// The whole address subsystem is IPv4-only (backend enforces it on address
// objects and DNAT targets).
const IPV4_RE = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/;

export async function openEditor({ container, mode, rule = null, duplicate = false, onClose }) {
    // A rule whose action falls outside this mode's fixed action set (e.g. a
    // LOG policy, a REDIRECT port forward) can't be represented by this form:
    // opening it would silently coerce the action into something else on
    // save. The Standard view already disables edit/duplicate for these rows
    // (see rowButtons in standard.js); this is defense in depth.
    if (rule && isLockedForMode(rule, mode)) {
        showToast(t('firewall.std.manageFromAdvanced'), 'error');
        onClose?.();
        return;
    }
    if (st) return;   // one editor at a time
    const isEdit = !!rule && !duplicate;
    const ocEl = document.createElement('div');
    ocEl.className = 'offcanvas offcanvas-end fw-editor-oc';
    ocEl.tabIndex = -1;
    ocEl.setAttribute('aria-labelledby', 'fw-editor-title');
    document.body.appendChild(ocEl);
    st = {
        // container = the panel itself: every query below stays scoped to it
        container: ocEl, listContainer: container, mode, onClose,
        closing: false, oc: null,
        isEdit,
        rule: isEdit ? rule : null,
        origAction: rule?.action || null,
        objects: [], groups: [], pools: [],
        duplicate, natTouched: false,
        activeField: null,
        panel: null,
        dirty: false,
        fields: {
            source: { refs: new Set(), literals: [] },
            destination: { refs: new Set(), literals: [] },
        },
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    setNavigationGuard(() => !st?.dirty || confirmUnsaved());

    await loadInterfaces();
    try {
        const [objs, grps, pools] = await Promise.all([
            apiGet('/firewall/addresses'),
            apiGet('/firewall/address-groups'),
            mode === 'policy' ? apiGet('/firewall/nat-pools').catch(() => []) : [],
        ]);
        st.objects = objs || [];
        st.groups = grps || [];
        st.pools = pools || [];
    } catch { st.objects = []; st.groups = []; }

    // Seed direction state from the rule being edited/duplicated.
    seedDirection('source', rule);
    seedDirection('destination', rule);

    renderLayout(rule, duplicate);

    st.oc = bootstrap.Offcanvas.getOrCreateInstance(ocEl, { backdrop: true, keyboard: true, scroll: false });
    ocEl.addEventListener('hide.bs.offcanvas', onHide);
    ocEl.addEventListener('hidden.bs.offcanvas', onHidden);
    window.addEventListener('hashchange', onRouteChange);
    st.oc.show();
}

/** Backdrop click, Esc, the header X: close only once unsaved changes are confirmed. */
function onHide(e) {
    if (!st || st.closing || !st.dirty) return;
    e.preventDefault();
    confirmUnsaved().then(ok => {
        if (!st) return;
        if (ok) {
            st.closing = true;
            st.oc.hide();
        } else {
            // the confirm returned focus to <body>: give it back so Esc works again
            st.container.focus();
        }
    });
}

function onHidden() {
    teardown(true);
}

/** The route changed (the navigation guard already confirmed): drop the panel silently. */
function onRouteChange() {
    if (!st) return;
    st.skipCallback = true;
    st.closing = true;
    st.oc.hide();
}

function teardown(runCallback) {
    const s = st;
    if (!s) return;
    st = null;
    window.removeEventListener('beforeunload', onBeforeUnload);
    window.removeEventListener('hashchange', onRouteChange);
    clearNavigationGuard();
    s.oc?.dispose();
    s.container.remove();
    if (runCallback && !s.skipCallback) s.onClose?.();
}

/** Tabler modal confirm for discarding unsaved rule data (replaces window.confirm). */
function confirmUnsaved() {
    return confirmDialog(
        t('firewall.editor.unsavedTitle'),
        t('firewall.editor.unsavedBody'),
        t('firewall.editor.leaveAnyway'),
        'btn-danger',
    );
}

async function close() {
    if (!st) return;
    if (st.dirty && !(await confirmUnsaved())) return;
    if (!st) return;
    st.closing = true;
    st.oc.hide();
}

function onBeforeUnload(e) {
    if (st?.dirty) {
        e.preventDefault();
        e.returnValue = '';
    }
}

function markDirty() {
    if (st) st.dirty = true;
}

function seedDirection(field, rule) {
    if (!rule) return;
    const refs = rule[`${field}_refs`] || [];
    if (refs.length) {
        refs.forEach(r => st.fields[field].refs.add(r.object_id ? `obj:${r.object_id}` : `grp:${r.group_id}`));
    } else if (rule[field]) {
        st.fields[field].literals.push(rule[field]);
    }
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

function titleFor(mode, isEdit) {
    const k = { policy: 'policyTitle', portforward: 'portFwdTitle' }[mode];
    return (isEdit ? t('firewall.editor.editPrefix') : t('firewall.editor.newPrefix')) + ' ' + t('firewall.editor.' + k);
}

function renderLayout(rule, duplicate) {
    const { container, mode, isEdit } = st;
    container.innerHTML = `
        <div class="offcanvas-header border-bottom">
            <h3 class="offcanvas-title" id="fw-editor-title">${titleFor(mode, isEdit)}</h3>
            <button type="button" class="btn-close" data-bs-dismiss="offcanvas" aria-label="${escapeHtml(t('common.cancel'))}"></button>
        </div>
        <div class="offcanvas-body">
            <div class="row g-4">
                <div class="col-lg-7">
                    <div id="ed-form" class="row g-3">${formFields(rule)}</div>
                </div>
                <div class="col-lg-5 fw-editor-entries">
                    <div class="text-uppercase text-muted small fw-bold mb-2">
                        <i class="ti ti-box me-1"></i>${t('firewall.entries.title')}
                    </div>
                    <div id="ed-entries"></div>
                </div>
            </div>
        </div>
        <div class="border-top p-3 d-flex justify-content-end gap-2">
            <button class="btn btn-link" id="ed-cancel">${t('common.cancel')}</button>
            <button class="btn btn-primary" id="ed-save">${t('common.save')}</button>
        </div>`;

    bindForm();
    mountEntriesPanel();
    renderChips('source');
    renderChips('destination');
    updateIfaceExclusion();
    updatePortVisibility();
}

function addrFieldHtml(field, label, hint = null) {
    return `
        <div class="col-12">
            <label class="form-label">${label}</label>
            <div class="form-control fw-addr-field d-flex flex-wrap align-items-center gap-1"
                 data-field="${field}" style="min-height:38px;cursor:text;height:auto">
                <span class="fw-chips d-flex flex-wrap gap-1"></span>
                <input type="text" class="fw-addr-input border-0 flex-grow-1"
                       style="outline:none;min-width:120px;background:transparent"
                       placeholder="${t('firewall.editor.addrPlaceholder')}">
            </div>
            <small class="form-hint">${hint ?? t('firewall.editor.addrHint')}</small>
        </div>`;
}

function serviceHtml(rule) {
    const proto = rule?.protocol || '';
    const port = rule?.port || '';
    const presets = SERVICE_PRESETS.map(p =>
        `<option value="${p.protocol}|${p.port}">${p.label} (${p.protocol.toUpperCase()}/${p.port})</option>`).join('');
    return `
        <div class="col-md-4">
            <label class="form-label">${t('firewall.protocol')}</label>
            <select class="form-select" id="ed-proto">
                <option value="" ${proto ? '' : 'selected'}>${t('firewall.allProtocols')}</option>
                <option value="tcp" ${proto === 'tcp' ? 'selected' : ''}>TCP</option>
                <option value="udp" ${proto === 'udp' ? 'selected' : ''}>UDP</option>
                <option value="icmp" ${proto === 'icmp' ? 'selected' : ''}>ICMP</option>
            </select>
        </div>
        <div class="col-md-4" id="ed-port-wrap">
            <label class="form-label">${t('firewall.port')}</label>
            <input type="text" class="form-control" id="ed-port" value="${escapeHtml(port)}" placeholder="80, 443, 8000:8080">
        </div>
        <div class="col-md-4">
            <label class="form-label">${t('firewall.editor.servicePreset')}</label>
            <select class="form-select" id="ed-preset">
                <option value="">—</option>
                ${presets}
            </select>
        </div>`;
}

function nameHtml(rule) {
    return `
        <div class="col-12">
            <label class="form-label">${t('firewall.editor.name')}</label>
            <input type="text" class="form-control" id="ed-name" maxlength="255" value="${escapeHtml(rule?.comment || '')}"
                   placeholder="${t('firewall.editor.namePlaceholder')}">
        </div>`;
}

function enabledHtml(rule) {
    return `
        <div class="col-12">
            <label class="form-check form-switch">
                <input class="form-check-input" type="checkbox" id="ed-enabled" ${rule?.enabled === false ? '' : 'checked'}>
                <span class="form-check-label">${t('firewall.ruleActive')}</span>
            </label>
        </div>`;
}

function formFields(rule) {
    const { mode } = st;
    if (mode === 'policy') {
        const action = rule?.action || 'ACCEPT';
        // A new policy starts without NAT: it is turned on when the outgoing
        // interface picked is the WAN (see onOutChange), never for LAN-to-LAN,
        // VPN or inbound policies, whose servers must see the real source
        const natOn = rule ? rule.policy_nat : false;
        const deny = action === 'DROP' || action === 'REJECT';
        const natCurrent = natSourceValue(rule);
        return `
            ${nameHtml(rule)}
            <div class="col-md-6">
                <label class="form-label">${t('firewall.inInterface')}</label>
                ${interfaceSelect('ed-in', rule?.in_interface || '')}
            </div>
            <div class="col-md-6">
                <label class="form-label">${t('firewall.outInterface')}</label>
                ${interfaceSelect('ed-out', rule?.out_interface || '')}
            </div>
            ${addrFieldHtml('source', t('firewall.std.colSource'))}
            ${addrFieldHtml('destination', t('firewall.std.colDest'))}
            ${serviceHtml(rule)}
            <div class="col-md-6">
                <label class="form-label d-block">${t('firewall.action')}</label>
                <div class="btn-group" role="group">
                    <input type="radio" class="btn-check" name="ed-action" id="ed-act-accept" value="ACCEPT" ${action !== 'DROP' && action !== 'REJECT' ? 'checked' : ''}>
                    <label class="btn btn-outline-success" for="ed-act-accept"><i class="ti ti-check me-1"></i>${t('firewall.editor.accept')}</label>
                    <input type="radio" class="btn-check" name="ed-action" id="ed-act-deny" value="DROP" ${action === 'DROP' || action === 'REJECT' ? 'checked' : ''}>
                    <label class="btn btn-outline-danger" for="ed-act-deny"><i class="ti ti-ban me-1"></i>${t('firewall.editor.deny')}</label>
                </div>
            </div>
            <div class="col-md-6 ${deny ? 'd-none' : ''}" id="ed-nat-wrap">
                <label class="form-label d-block">${t('firewall.std.colNat')}</label>
                <label class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" id="ed-nat" ${natOn ? 'checked' : ''}>
                    <span class="form-check-label">${t('firewall.editor.natHint')}</span>
                </label>
            </div>
            <div class="col-md-6 offset-md-6 ${natOn && !deny ? '' : 'd-none'}" id="ed-natsrc-wrap">
                <label class="form-label">${t('firewall.nat.sourceLabel')}</label>
                <select class="form-select" id="ed-natsrc">${natSourceOptions(rule?.out_interface || '', natCurrent, { pools: st.pools })}</select>
                <small class="form-hint" id="ed-natsrc-hint">${natSourceHint(rule?.out_interface || '')}</small>
            </div>
            ${enabledHtml(rule)}`;
    }
    if (mode === 'portforward') {
        const hasIntObj = !!rule?.to_destination_object_id;
        const [ip, literalPort] = splitIpPort(rule?.to_destination);
        const iport = hasIntObj ? (rule?.to_destination_port || '') : literalPort;
        // Object targets are restricted to /32 cidr (a single host — see
        // backend effective_to_destination): a range or wider CIDR can't be
        // a DNAT rewrite target or a plain -d match on the companions.
        const intObjOptions = (st.objects || [])
            .filter(o => o.enabled && o.type === 'cidr' && o.value.endsWith('/32'));
        return `
            ${nameHtml(rule)}
            <div class="col-md-6">
                <label class="form-label">${t('firewall.inInterface')}</label>
                ${interfaceSelect('ed-in', rule?.in_interface || '')}
            </div>
            <div class="col-md-3">
                <label class="form-label">${t('firewall.protocol')}</label>
                <select class="form-select" id="ed-proto">
                    <option value="tcp" ${rule?.protocol !== 'udp' ? 'selected' : ''}>TCP</option>
                    <option value="udp" ${rule?.protocol === 'udp' ? 'selected' : ''}>UDP</option>
                </select>
            </div>
            <div class="col-md-3">
                <label class="form-label">${t('firewall.editor.extPort')}</label>
                <input type="text" class="form-control" id="ed-port" value="${escapeHtml(rule?.port || '')}" placeholder="443">
            </div>
            ${addrFieldHtml('destination', t('firewall.editor.extIp'), t('firewall.editor.extIpHint'))}
            <div class="col-md-6">
                <label class="form-label">${t('firewall.editor.intIp')}</label>
                <input type="text" class="form-control" id="ed-intip" value="${escapeHtml(ip)}"
                       placeholder="10.0.0.5" ${hasIntObj ? 'disabled' : ''}>
            </div>
            <div class="col-md-6">
                <label class="form-label">${t('firewall.editor.intPort')}</label>
                <input type="text" class="form-control" id="ed-intport" value="${escapeHtml(iport)}" placeholder="443">
            </div>
            <div class="col-12">
                <label class="form-label">${t('firewall.editor.intObj')}</label>
                <select class="form-select" id="ed-intobj">
                    <option value="">—</option>
                    ${intObjOptions.map(o => `<option value="${escapeHtml(o.id)}" ${hasIntObj && rule.to_destination_object_id === o.id ? 'selected' : ''}>${escapeHtml(o.name)} (${escapeHtml(o.value)})</option>`).join('')}
                </select>
                <small class="form-hint">${t('firewall.editor.intObjHint')}</small>
            </div>
            ${addrFieldHtml('source', t('firewall.editor.sourceRestrict'))}
            <div class="col-12">
                <label class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" id="ed-hairpin" ${rule?.hairpin ? 'checked' : ''}>
                    <span class="form-check-label">${t('firewall.editor.hairpin')}</span>
                </label>
                <small class="form-hint">${t('firewall.editor.hairpinHint')}</small>
            </div>
            ${enabledHtml(rule)}`;
    }
    return '';
}

/** NAT switch only for Accept, address select only with the switch on. */
function updateNatVisibility() {
    const c = st?.container;
    if (!c) return;
    const accept = (c.querySelector('input[name="ed-action"]:checked')?.value || 'ACCEPT') === 'ACCEPT';
    const on = c.querySelector('#ed-nat')?.checked;
    c.querySelector('#ed-nat-wrap')?.classList.toggle('d-none', !accept);
    c.querySelector('#ed-natsrc-wrap')?.classList.toggle('d-none', !(accept && on));
}

/** Hint under the NAT address select: which addresses it can offer. */
function natSourceHint(outIf) {
    return outIf ? t('firewall.nat.sourceHint') : t('firewall.nat.pickOutIface');
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

function bindForm() {
    const { container } = st;
    container.querySelector('#ed-cancel')?.addEventListener('click', close);
    container.querySelector('#ed-save')?.addEventListener('click', save);

    // Unsaved-changes tracking (chip add/remove and panel toggles mark dirty
    // where they mutate state)
    const form = container.querySelector('#ed-form');
    form?.addEventListener('input', markDirty);
    form?.addEventListener('change', markDirty);

    // Service preset -> protocol/port
    container.querySelector('#ed-preset')?.addEventListener('change', (e) => {
        if (!e.target.value) return;
        const [proto, port] = e.target.value.split('|');
        container.querySelector('#ed-proto').value = proto;
        container.querySelector('#ed-port').value = port;
        updatePortVisibility();
    });

    // Protocol "all"/ICMP have no port -> hide the port field.
    container.querySelector('#ed-proto')?.addEventListener('change', updatePortVisibility);

    // In/Out interface are mutually exclusive: a picked iface can't be the other side.
    container.querySelector('#ed-in')?.addEventListener('change', updateIfaceExclusion);
    container.querySelector('#ed-out')?.addEventListener('change', updateIfaceExclusion);

    // Policy NAT: the address select shows with the switch and follows the
    // outgoing interface (its addresses are the ones offered)
    container.querySelector('#ed-nat')?.addEventListener('change', () => {
        st.natTouched = true;
        updateNatVisibility();
    });
    // NAT belongs to accepting policies only
    container.querySelectorAll('input[name="ed-action"]').forEach(r => r.addEventListener('change', updateNatVisibility));
    container.querySelector('#ed-out')?.addEventListener('change', (e) => {
        const sel = container.querySelector('#ed-natsrc');
        if (!sel) return;
        // New policy, switch never touched: NAT on exactly when going out of the WAN
        if (!st.rule && !st.natTouched && !st.duplicate) {
            const iface = cachedInterfaces().find(i => i.name === e.target.value);
            container.querySelector('#ed-nat').checked = !!iface?.default_route;
            updateNatVisibility();
        }
        sel.innerHTML = natSourceOptions(e.target.value, sel.value, { pools: st.pools });
        container.querySelector('#ed-natsrc-hint').textContent = natSourceHint(e.target.value);
    });

    // Internal target: literal IP and address object are mutually exclusive.
    container.querySelector('#ed-intobj')?.addEventListener('change', (e) => {
        const intIp = container.querySelector('#ed-intip');
        if (!intIp) return;
        if (e.target.value) { intIp.value = ''; intIp.disabled = true; }
        else { intIp.disabled = false; }
    });
    container.querySelector('#ed-intip')?.addEventListener('input', (e) => {
        if (!e.target.value) return;
        const intObj = container.querySelector('#ed-intobj');
        if (intObj) intObj.value = '';
    });

    // Combined address fields
    container.querySelectorAll('.fw-addr-field').forEach(fieldEl => {
        const field = fieldEl.dataset.field;
        const input = fieldEl.querySelector('.fw-addr-input');
        fieldEl.addEventListener('click', (e) => {
            if (e.target.closest('.fw-chip-x')) return;
            setActive(field);
            input.focus();
        });
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                const v = input.value.trim();
                if (v) { st.fields[field].literals.push(v); input.value = ''; renderChips(field); markDirty(); }
            }
        });
    });
}

function setActive(field) {
    st.activeField = field;
    st.container.querySelectorAll('.fw-addr-field').forEach(el =>
        el.classList.toggle('border-primary', el.dataset.field === field));
    st.panel?.render();
}

/** Hide the port field when the protocol carries no port (all / ICMP). Also
 * clears its value: the engine only emits --dport for tcp/udp, so a port left
 * behind in the hidden field would be saved and silently ignored. */
function updatePortVisibility() {
    const wrap = st?.container.querySelector('#ed-port-wrap');
    if (!wrap) return;
    const proto = st.container.querySelector('#ed-proto')?.value || '';
    const hidden = proto === '' || proto === 'icmp';
    wrap.classList.toggle('d-none', hidden);
    if (hidden) {
        const portInput = st.container.querySelector('#ed-port');
        if (portInput) portInput.value = '';
    }
}

/** Grey out, in each interface select, the value already chosen in the other. */
function updateIfaceExclusion() {
    const inSel = st?.container.querySelector('#ed-in');
    const outSel = st?.container.querySelector('#ed-out');
    if (!inSel || !outSel) return;
    const apply = (sel, taken) => {
        sel.querySelectorAll('option').forEach(o => {
            o.disabled = o.value !== '' && o.value === taken;
        });
    };
    apply(inSel, outSel.value);
    apply(outSel, inSel.value);
}

function mountEntriesPanel() {
    const panelEl = st.container.querySelector('#ed-entries');
    if (!panelEl) return;
    st.panel = createEntriesPanel(panelEl, {
        objects: st.objects,
        groups: st.groups,
        isSelected: (c) => st.activeField ? st.fields[st.activeField].refs.has(c) : false,
        onToggle: (c) => {
            if (!st.activeField) return;
            const set = st.fields[st.activeField].refs;
            set.has(c) ? set.delete(c) : set.add(c);
            renderChips(st.activeField);
            markDirty();
        },
        onCreated: (obj) => {
            st.objects.push(obj);
            if (st.activeField) { st.fields[st.activeField].refs.add(`obj:${obj.id}`); renderChips(st.activeField); markDirty(); }
        },
        activeLabel: () => {
            if (!st.activeField) return null;
            return st.activeField === 'source' ? t('firewall.std.colSource') : t('firewall.std.colDest');
        },
    });
}

function renderChips(field) {
    const fieldEl = st.container.querySelector(`.fw-addr-field[data-field="${field}"]`);
    if (!fieldEl) return;
    const chipsEl = fieldEl.querySelector('.fw-chips');
    const stf = st.fields[field];

    const refChips = [...stf.refs].map(c => {
        const [k, id] = c.split(':');
        const item = k === 'obj' ? st.objects.find(o => o.id === id) : st.groups.find(g => g.id === id);
        const icon = k === 'grp' ? 'ti-stack-2' : 'ti-box';
        return chip(c, `<i class="ti ${icon} me-1"></i>${escapeHtml(item ? item.name : id)}`);
    });
    const litChips = stf.literals.map((v, i) => chip(`lit:${i}`, `<code>${escapeHtml(v)}</code>`));
    chipsEl.innerHTML = refChips.concat(litChips).join('');

    chipsEl.querySelectorAll('.fw-chip-x').forEach(x => x.addEventListener('click', (e) => {
        e.stopPropagation();
        const c = x.dataset.c;
        if (c.startsWith('lit:')) stf.literals.splice(parseInt(c.slice(4)), 1);
        else stf.refs.delete(c);
        renderChips(field);
        st.panel?.render();
        markDirty();
    }));
}

function chip(c, inner) {
    return `<span class="badge bg-azure-lt d-inline-flex align-items-center gap-1">${inner}
        <button type="button" class="fw-chip-x btn-close" data-c="${escapeHtml(c)}"
                style="font-size:.6em;filter:none;opacity:.8;width:1em;height:1em"></button></span>`;
}

// ---------------------------------------------------------------------------
// Save
// ---------------------------------------------------------------------------

/** Resolve a direction to { literal, refs[] }, creating objects for literals when needed. */
async function resolveDirection(field) {
    const stf = st.fields[field];
    const refs = [...stf.refs].map(c => {
        const [k, id] = c.split(':');
        return k === 'obj' ? { object_id: id } : { group_id: id };
    });
    if (refs.length === 0 && stf.literals.length <= 1) {
        return { literal: stf.literals[0] || null, refs: [] };
    }
    // Materialise each literal as an address object (reuse by value when possible).
    for (const value of stf.literals) {
        let obj = st.objects.find(o => o.value === value);
        if (!obj) {
            const type = value.includes('-') ? 'range' : 'cidr';
            obj = await apiPost('/firewall/addresses', { name: value, type, value });
            st.objects.push(obj);
        }
        refs.push({ object_id: obj.id });
    }
    return { literal: null, refs };
}

async function save() {
    const st0 = st;   // the panel tears down (st = null) once hidden
    const { container, mode } = st;
    const name = container.querySelector('#ed-name')?.value.trim() || null;
    const enabled = container.querySelector('#ed-enabled')?.checked !== false;

    // Phase 1: read and validate every field that doesn't need a network call.
    // Must run BEFORE resolveDirection (phase 2), which materialises literal
    // address chips as address objects via POST — if validation ran after,
    // a rejected save left those objects orphaned.
    let plain;
    if (mode === 'policy') {
        // The Deny radio only ever represents DROP or REJECT (both render
        // checked, see formFields policy branch); preserve REJECT when the
        // rule already was REJECT and Deny stays selected, otherwise DROP.
        const selected = container.querySelector('input[name="ed-action"]:checked')?.value || 'ACCEPT';
        const action = selected === 'ACCEPT' ? 'ACCEPT'
            : (st.origAction === 'REJECT' ? 'REJECT' : 'DROP');
        const proto = container.querySelector('#ed-proto').value || null;
        const natOn = action === 'ACCEPT' && container.querySelector('#ed-nat').checked;
        const natSrc = container.querySelector('#ed-natsrc')?.value || '';
        plain = {
            table_name: 'filter', chain: 'FORWARD', action,
            comment: name,
            in_interface: container.querySelector('#ed-in').value || null,
            out_interface: container.querySelector('#ed-out').value || null,
            protocol: proto,
            // The engine only matches --dport for tcp/udp; a port set under
            // any other protocol is dead data (see backend port/protocol guard).
            port: (proto === 'tcp' || proto === 'udp') ? (container.querySelector('#ed-port').value || null) : null,
            policy_nat: natOn,
            // '' = the outgoing interface's address (MASQUERADE), 'ip:x' = SNAT
            // to x, 'pool:id' = an IP pool
            ...natSourcePayload(natOn ? natSrc : ''),
            enabled,
        };
    } else if (mode === 'portforward') {
        const intObjId = container.querySelector('#ed-intobj')?.value || '';
        const iport = container.querySelector('#ed-intport').value.trim();
        // Literal IP and address object are mutually exclusive internal
        // targets (see #ed-intobj change handler); explicit nulls on both
        // branches below so switching between them clears the other on PATCH.
        let toDestination = null, toDestinationObjectId = null, toDestinationPort = null;
        if (intObjId) {
            toDestinationObjectId = intObjId;
            toDestinationPort = iport || null;
        } else {
            const ip = container.querySelector('#ed-intip').value.trim();
            if (!ip) { showToast(t('firewall.editor.intIpRequired'), 'error'); return; }
            if (!IPV4_RE.test(ip)) { showToast(t('firewall.validation.ipv4Only'), 'error'); return; }
            toDestination = iport ? `${ip}:${iport}` : ip;
        }
        plain = {
            table_name: 'nat', chain: 'PREROUTING', action: 'DNAT',
            comment: name,
            in_interface: container.querySelector('#ed-in').value || null,
            protocol: container.querySelector('#ed-proto').value || 'tcp',
            port: container.querySelector('#ed-port').value || null,
            to_destination: toDestination,
            to_destination_object_id: toDestinationObjectId,
            to_destination_port: toDestinationPort,
            hairpin: container.querySelector('#ed-hairpin')?.checked || false,
            enabled,
        };
    }

    const constraintError = validateRuleConstraints(plain);
    if (constraintError) { showToast(constraintError, 'error'); return; }

    // Phase 2: resolve address chips (may create address objects — only
    // reached once every other field has already passed validation). Every
    // mode carries both directions.
    let data;
    try {
        const src = await resolveDirection('source');
        const dst = await resolveDirection('destination');
        data = {
            ...plain,
            source: src.literal, source_refs: src.refs,
            destination: dst.literal, destination_refs: dst.refs,
        };
    } catch (err) {
        showToast(t('common.errorPrefix') + err.message, 'error');
        return;
    }

    // Phase 3: submit.
    let saved;
    try {
        if (st.isEdit) {
            saved = await apiPatch(`/firewall/rules/${st.rule.id}`, data);
            showToast(t('firewall.ruleUpdated'), 'success');
        } else {
            saved = await apiPost('/firewall/rules', data);
            showToast(t('firewall.ruleCreated'), 'success');
        }
        st.dirty = false;
        st.closing = true;
        st.oc.hide();
    } catch (err) {
        showToast(t('common.errorPrefix') + err.message, 'error');
        return;
    }

    // A newly-active DROP/REJECT policy blocks new connections, but
    // already-established ones keep flowing until conntrack is flushed —
    // offer to do it now (confirmDialog mounts on document.body, independent
    // of the editor panel being closed).
    if (mode === 'policy' && data.enabled && (data.action === 'DROP' || data.action === 'REJECT')) {
        await terminateSessions({ id: saved.id, action: data.action });
    } else if (mode === 'policy' && data.enabled && st0.rule && natChanged(st0.rule, data)) {
        // NAT is decided on a connection's first packet: open ones keep the old address
        await terminateSessions({ id: saved.id, action: data.action }, { reason: 'nat' });
    }
}

// ---------------------------------------------------------------------------

// IPv4-only (like the rest of the address subsystem): splitting on the last
// ':' would corrupt an IPv6 literal, which the backend rejects anyway.
function splitIpPort(v) {
    if (!v) return ['', ''];
    const idx = v.lastIndexOf(':');
    if (idx === -1) return [v, ''];
    return [v.slice(0, idx), v.slice(idx + 1)];
}

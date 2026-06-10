/**
 * Reverse Proxy - Access Lists tab
 *
 * List of access lists + modal "Edit Access List" with sub-tabs:
 * Details, Authorizations, Rules.
 */
import { apiGet, apiPost, apiPatch, apiDelete } from '/static/js/api.js';
import { showToast, confirmDialog, escapeHtml, emptyState } from '/static/js/utils.js';
import { t } from '/static/js/i18n.js';

const MODULE_API = '/modules/reverseproxy';
let _perms = null;
let _acls = [];

export async function renderAccessListsTab(container, perms) {
    _perms = perms;
    container.innerHTML = `
        <div class="d-flex justify-content-end px-3 pt-3 pb-3">
            ${perms.accessLists ? `
                <button class="btn btn-primary" id="revproxy-btn-new-acl">
                    <i class="ti ti-plus me-1"></i>${t('reverseproxy.addAccessList')}
                </button>` : ''}
        </div>
        <div id="revproxy-acls-table"></div>
    `;
    if (perms.accessLists) {
        document.getElementById('revproxy-btn-new-acl').addEventListener('click', () => openAclForm({}));
    }
    await reloadAcls();
}

async function reloadAcls() {
    try {
        _acls = await apiGet(`${MODULE_API}/access_lists`);
        renderTable();
    } catch (err) {
        document.getElementById('revproxy-acls-table').innerHTML =
            `<div class="alert alert-danger">${escapeHtml(err.message)}</div>`;
    }
}

function renderTable() {
    const root = document.getElementById('revproxy-acls-table');
    if (!_acls.length) {
        root.innerHTML = `<div class="p-3">${emptyState('ti-lock', t('reverseproxy.noAccessLists'), t('reverseproxy.noAccessListsHint'))}</div>`;
        return;
    }
    root.innerHTML = `<table class="table table-vcenter card-table table-hover">
        <thead><tr>
            <th>${t('reverseproxy.name')}</th>
            <th>${t('reverseproxy.users')}</th>
            <th>${t('reverseproxy.rulesCount')}</th>
            <th>${t('reverseproxy.usedBy')}</th>
            <th class="w-1"></th>
        </tr></thead>
        <tbody>${_acls.map(a => `
            <tr>
                <td><strong>${escapeHtml(a.name)}</strong></td>
                <td>${a.auths.length}</td>
                <td>${a.rules.length}</td>
                <td>${a.hosts_count || 0}</td>
                <td>
                    <div class="dropdown">
                        <button class="btn btn-ghost-secondary btn-icon" data-bs-toggle="dropdown" data-bs-strategy="fixed"><i class="ti ti-dots-vertical"></i></button>
                        <ul class="dropdown-menu dropdown-menu-end">
                            ${_perms.accessLists ? `
                            <li><a class="dropdown-item" href="#" data-action="edit" data-id="${a.id}">
                                <i class="ti ti-edit me-2"></i>${t('reverseproxy.edit')}</a></li>
                            <li><a class="dropdown-item text-danger" href="#" data-action="delete" data-id="${a.id}">
                                <i class="ti ti-trash me-2"></i>${t('reverseproxy.delete')}</a></li>` : ''}
                        </ul>
                    </div>
                </td>
            </tr>`).join('')}</tbody>
    </table>`;

    root.querySelectorAll('[data-action]').forEach(b => {
        b.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const id = b.dataset.id;
            const acl = _acls.find(a => a.id === id);
            if (!acl) return;
            if (b.dataset.action === 'edit') openAclForm({ acl });
            else if (b.dataset.action === 'delete') deleteAcl(acl);
        });
    });
}

async function deleteAcl(acl) {
    const ok = await confirmDialog(
        t('reverseproxy.confirmDeleteAcl'),
        t('reverseproxy.confirmDeleteAclMsg'),
        t('reverseproxy.delete'),
        'btn-danger',
    );
    if (!ok) return;
    try {
        await apiDelete(`${MODULE_API}/access_lists/${acl.id}`);
        showToast(t('reverseproxy.aclDeleted'), 'success');
        await reloadAcls();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// ============================================================================
// Edit/Create modal
// ============================================================================

function openAclForm({ acl = null }) {
    const isEdit = !!acl;
    const modalId = 'revproxy-acl-modal';
    document.getElementById(modalId)?.remove();

    // Working copies (so cancel doesn't mutate the table)
    const state = {
        name: acl?.name || '',
        satisfy_any: !!acl?.satisfy_any,
        pass_auth_to_upstream: !!acl?.pass_auth_to_upstream,
        // Auths: existing have username but no password; new entries also need password
        auths: (acl?.auths || []).map(a => ({ username: a.username, password: '', existing: true })),
        rules: (acl?.rules || []).map(r => ({ action: r.action, subject: r.subject, order: r.order })),
    };

    const modalEl = document.createElement('div');
    modalEl.id = modalId;
    modalEl.className = 'modal fade';
    modalEl.tabIndex = -1;
    modalEl.innerHTML = `
        <div class="modal-dialog modal-md">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">${isEdit ? t('reverseproxy.edit') + ' ' + t('reverseproxy.accessList') : t('reverseproxy.addAccessList')}</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <ul class="nav nav-tabs mb-3">
                        <li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#rpacl-details">${t('reverseproxy.tabDetails')}</button></li>
                        <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#rpacl-auths">${t('reverseproxy.authorizations')}</button></li>
                        <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#rpacl-rules">${t('reverseproxy.rules')}</button></li>
                    </ul>
                    <div class="tab-content">
                        <div class="tab-pane fade show active" id="rpacl-details">
                            <div class="mb-3">
                                <label class="form-label">${t('reverseproxy.name')}</label>
                                <input type="text" class="form-control" id="rpacl-name" value="${escapeHtml(state.name)}">
                            </div>
                            <label class="form-check form-switch">
                                <input class="form-check-input" type="checkbox" id="rpacl-satisfy" ${state.satisfy_any ? 'checked' : ''}>
                                <span class="form-check-label">${t('reverseproxy.satisfyAny')}</span>
                            </label>
                            <div class="form-hint small">${t('reverseproxy.satisfyAnyHint')}</div>
                            <label class="form-check form-switch mt-2">
                                <input class="form-check-input" type="checkbox" id="rpacl-pass-auth" ${state.pass_auth_to_upstream ? 'checked' : ''}>
                                <span class="form-check-label">${t('reverseproxy.passAuthToUpstream')}</span>
                            </label>
                        </div>
                        <div class="tab-pane fade" id="rpacl-auths">
                            <div id="rpacl-auths-list"></div>
                            <button class="btn btn-outline-primary btn-sm mt-2" id="rpacl-auth-add">
                                <i class="ti ti-plus me-1"></i>${t('reverseproxy.add')}
                            </button>
                        </div>
                        <div class="tab-pane fade" id="rpacl-rules">
                            <div id="rpacl-rules-list"></div>
                            <button class="btn btn-outline-primary btn-sm mt-2" id="rpacl-rule-add">
                                <i class="ti ti-plus me-1"></i>${t('reverseproxy.add')}
                            </button>
                            <div class="form-hint mt-3" id="rpacl-deny-all" style="display:none;">
                                <code>deny all</code> · ${t('reverseproxy.denyAllNote')}
                            </div>
                        </div>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-outline-secondary" data-bs-dismiss="modal">${t('reverseproxy.cancel')}</button>
                    <button class="btn btn-primary" id="rpacl-save">${isEdit ? t('reverseproxy.saveChanges') : t('reverseproxy.create')}</button>
                </div>
            </div>
        </div>`;
    document.body.appendChild(modalEl);
    const modal = new bootstrap.Modal(modalEl);
    modal.show();
    modalEl.addEventListener('hidden.bs.modal', () => modalEl.remove());

    renderAuths();
    renderRules();

    modalEl.querySelector('#rpacl-auth-add').addEventListener('click', () => {
        state.auths.push({ username: '', password: '', existing: false });
        renderAuths();
    });
    modalEl.querySelector('#rpacl-rule-add').addEventListener('click', () => {
        state.rules.push({ action: 'allow', subject: '', order: state.rules.length });
        renderRules();
    });
    modalEl.querySelector('#rpacl-save').addEventListener('click', async () => {
        const ok = await saveAcl(acl, state);
        if (ok) modal.hide();
    });

    function renderAuths() {
        const list = modalEl.querySelector('#rpacl-auths-list');
        list.innerHTML = state.auths.map((a, i) => `
            <div class="row g-2 align-items-center mb-2">
                <div class="col-5">
                    <input type="text" class="form-control" data-auth-username="${i}"
                           placeholder="${t('reverseproxy.username')}" value="${escapeHtml(a.username)}"
                           autocomplete="off">
                </div>
                <div class="col-6">
                    <input type="password" class="form-control" data-auth-password="${i}"
                           placeholder="${a.existing ? t('reverseproxy.passwordPlaceholder') : t('reverseproxy.password')}"
                           autocomplete="new-password">
                </div>
                <div class="col-1">
                    <button class="btn btn-ghost-danger btn-icon" data-auth-remove="${i}"><i class="ti ti-x"></i></button>
                </div>
            </div>`).join('');
        list.querySelectorAll('[data-auth-username]').forEach(el => {
            el.addEventListener('input', e => state.auths[+e.target.dataset.authUsername].username = e.target.value);
        });
        list.querySelectorAll('[data-auth-password]').forEach(el => {
            el.addEventListener('input', e => state.auths[+e.target.dataset.authPassword].password = e.target.value);
        });
        list.querySelectorAll('[data-auth-remove]').forEach(el => {
            el.addEventListener('click', () => { state.auths.splice(+el.dataset.authRemove, 1); renderAuths(); });
        });
    }

    function renderRules() {
        const list = modalEl.querySelector('#rpacl-rules-list');
        list.innerHTML = state.rules.map((r, i) => `
            <div class="row g-2 align-items-center mb-2">
                <div class="col-3">
                    <select class="form-select" data-rule-action="${i}">
                        <option value="allow" ${r.action === 'allow' ? 'selected' : ''}>${t('reverseproxy.allow')}</option>
                        <option value="deny" ${r.action === 'deny' ? 'selected' : ''}>${t('reverseproxy.deny')}</option>
                    </select>
                </div>
                <div class="col-8">
                    <input type="text" class="form-control" data-rule-subject="${i}"
                           placeholder="192.168.0.0/24" value="${escapeHtml(r.subject)}">
                </div>
                <div class="col-1">
                    <button class="btn btn-ghost-danger btn-icon" data-rule-remove="${i}"><i class="ti ti-x"></i></button>
                </div>
            </div>`).join('');
        list.querySelectorAll('[data-rule-action]').forEach(el => {
            el.addEventListener('change', e => state.rules[+e.target.dataset.ruleAction].action = e.target.value);
        });
        list.querySelectorAll('[data-rule-subject]').forEach(el => {
            el.addEventListener('input', e => state.rules[+e.target.dataset.ruleSubject].subject = e.target.value.trim());
        });
        list.querySelectorAll('[data-rule-remove]').forEach(el => {
            el.addEventListener('click', () => { state.rules.splice(+el.dataset.ruleRemove, 1); renderRules(); });
        });
        modalEl.querySelector('#rpacl-deny-all').style.display = state.rules.length ? '' : 'none';
    }
}

async function saveAcl(existing, state) {
    state.name = document.getElementById('rpacl-name').value.trim();
    state.satisfy_any = document.getElementById('rpacl-satisfy').checked;
    state.pass_auth_to_upstream = document.getElementById('rpacl-pass-auth').checked;

    if (!state.name) { showToast(t('reverseproxy.fillRequiredFields'), 'error'); return false; }

    // Auth validation: for new entries password is required;
    // for existing entries, empty password keeps the old one (backend update
    // replaces the full list, so we must re-send the existing hash — which we
    // don't have. Workaround: skip auths whose password is blank AND existing).
    const auths = [];
    for (const a of state.auths) {
        const u = (a.username || '').trim();
        if (!u) continue;
        if (a.existing && !a.password) {
            // Keep existing user untouched: backend can't preserve unknown hash,
            // so we tell user they MUST re-enter password on edit. Fail safely.
            showToast(`${t('reverseproxy.username')}: ${u} → ${t('reverseproxy.password')}`, 'error');
            return false;
        }
        auths.push({ username: u, password: a.password });
    }

    const rules = state.rules
        .filter(r => (r.subject || '').trim())
        .map((r, i) => ({ action: r.action, subject: r.subject.trim(), order: i }));

    const payload = {
        name: state.name,
        satisfy_any: state.satisfy_any,
        pass_auth_to_upstream: state.pass_auth_to_upstream,
        auths, rules,
    };

    try {
        if (existing) {
            await apiPatch(`${MODULE_API}/access_lists/${existing.id}`, payload);
        } else {
            await apiPost(`${MODULE_API}/access_lists`, payload);
        }
        showToast(t('reverseproxy.aclSaved'), 'success');
        await reloadAcls();
        return true;
    } catch (err) {
        showToast(err.message, 'error');
        return false;
    }
}

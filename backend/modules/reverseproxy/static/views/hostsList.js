/**
 * Reverse Proxy - Proxy Hosts tab
 */
import { apiGet, apiPost, apiPatch, apiDelete } from '/static/js/api.js';
import { showToast, confirmDialog, escapeHtml, emptyState, formatDate } from '/static/js/utils.js';
import { t } from '/static/js/i18n.js';
import { openHostForm } from './hostForm.js';

const MODULE_API = '/modules/reverseproxy';

let _perms = null;
let _hosts = [];
let _acls = [];

export async function renderHostsTab(container, perms) {
    _perms = perms;

    // Pre-fetch before any DOM write
    try {
        [_hosts, _acls] = await Promise.all([
            apiGet(`${MODULE_API}/hosts`),
            apiGet(`${MODULE_API}/access_lists`).catch(() => []),
        ]);
    } catch { _hosts = []; }

    container.innerHTML = `
        <div class="d-flex justify-content-between align-items-center px-3 pt-3 pb-3">
            <div class="input-icon" style="max-width: 320px;">
                <span class="input-icon-addon"><i class="ti ti-search"></i></span>
                <input type="text" id="revproxy-host-search" class="form-control"
                       placeholder="${t('reverseproxy.search')}">
            </div>
            ${perms.manage ? `
                <button class="btn btn-primary" id="revproxy-btn-new-host">
                    <i class="ti ti-plus me-1"></i>${t('reverseproxy.addProxyHost')}
                </button>` : ''}
        </div>
        <div id="revproxy-hosts-table"></div>
    `;

    // Sync: no await between innerHTML and these calls
    if (perms.manage) {
        document.getElementById('revproxy-btn-new-host').addEventListener('click', () => {
            openHostForm({ onSaved: reloadHosts, perms: _perms });
        });
    }
    document.getElementById('revproxy-host-search').addEventListener('input', renderTable);
    renderTable();
}

async function loadAcls() {
    try {
        _acls = await apiGet(`${MODULE_API}/access_lists`);
    } catch {
        _acls = [];
    }
}

async function reloadHosts() {
    try {
        [_hosts, _acls] = await Promise.all([
            apiGet(`${MODULE_API}/hosts`),
            apiGet(`${MODULE_API}/access_lists`).catch(() => _acls),
        ]);
        renderTable();
    } catch (err) {
        document.getElementById('revproxy-hosts-table').innerHTML =
            `<div class="alert alert-danger">${escapeHtml(err.message)}</div>`;
    }
}

function renderTable() {
    const root = document.getElementById('revproxy-hosts-table');
    if (!root) return;
    const filter = (document.getElementById('revproxy-host-search')?.value || '').toLowerCase().trim();
    const rows = _hosts.filter(h => {
        if (!filter) return true;
        return (h.name || '').toLowerCase().includes(filter)
            || (h.forward_host || '').toLowerCase().includes(filter)
            || (h.domains || []).some(d => (d.domain || '').includes(filter));
    });

    if (!rows.length) {
        root.innerHTML = `<div class="p-3">${emptyState('ti-server-off', t('reverseproxy.noHosts'), t('reverseproxy.noHostsHint'))}</div>`;
        return;
    }

    root.innerHTML = `<table class="table table-vcenter card-table table-hover">
            <thead><tr>
                <th>${t('reverseproxy.source')}</th>
                <th>${t('reverseproxy.destination')}</th>
                <th>${t('reverseproxy.tls')}</th>
                <th>${t('reverseproxy.access')}</th>
                <th>${t('reverseproxy.status')}</th>
                <th class="w-1"></th>
            </tr></thead>
            <tbody>${rows.map(renderRow).join('')}</tbody>
        </table>`;

    root.querySelectorAll('[data-action]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const id = btn.dataset.id;
            const action = btn.dataset.action;
            const host = _hosts.find(h => h.id === id);
            if (!host) return;
            if (action === 'edit') openHostForm({ host, onSaved: reloadHosts, perms: _perms });
            else if (action === 'delete') deleteHost(host);
            else if (action === 'enable') toggleHost(host, true);
            else if (action === 'disable') toggleHost(host, false);
            else if (action === 'cert-issue') issueCert(host);
            else if (action === 'cert-revoke') revokeCert(host);
        });
    });
}

function renderRow(h) {
    const acl = _acls.find(a => a.id === h.access_list_id);
    const tlsBadge = h.certificate
        ? (h.certificate.provider === 'letsencrypt'
            ? `<span class="badge bg-success-lt">${t('reverseproxy.tlsLetsEncrypt')}</span>`
            : `<span class="badge bg-blue-lt">${t('reverseproxy.tlsCustom')}</span>`)
        : `<span class="badge bg-secondary-lt">${t('reverseproxy.tlsNone')}</span>`;
    const accessBadge = acl
        ? `<span class="badge bg-yellow-lt">${escapeHtml(acl.name)}</span>`
        : `<span class="badge bg-secondary-lt">${t('reverseproxy.accessPublic')}</span>`;
    const statusBadge = h.enabled
        ? `<span class="badge bg-success-lt"><span class="status-dot status-dot-animated bg-success me-1"></span>${t('reverseproxy.online')}</span>`
        : `<span class="badge bg-secondary-lt">${t('reverseproxy.offline')}</span>`;

    const initial = (h.name || '?')[0].toUpperCase();
    const domains = (h.domains || []).map(d =>
        `<span class="badge bg-dark-lt me-1">${escapeHtml(d.domain)}</span>`
    ).join('');
    const dest = `${escapeHtml(h.forward_scheme)}://${escapeHtml(h.forward_host)}:${h.forward_port}`;

    const canManage = _perms.manage;
    const canCerts = _perms.certs;
    const actions = `
        <div class="dropdown">
            <button type="button" class="btn btn-ghost-secondary btn-icon" data-bs-toggle="dropdown" data-bs-strategy="fixed" aria-expanded="false">
                <i class="ti ti-dots-vertical"></i>
            </button>
            <ul class="dropdown-menu dropdown-menu-end">
                ${canManage ? `<li><a href="#" class="dropdown-item" data-action="edit" data-id="${h.id}">
                    <i class="ti ti-edit me-2"></i>${t('reverseproxy.edit')}</a></li>` : ''}
                ${canCerts ? (h.certificate
                    ? `<li><a href="#" class="dropdown-item" data-action="cert-revoke" data-id="${h.id}">
                        <i class="ti ti-shield-off me-2"></i>${t('reverseproxy.certRevoke')}</a></li>`
                    : `<li><a href="#" class="dropdown-item" data-action="cert-issue" data-id="${h.id}">
                        <i class="ti ti-shield-check me-2"></i>${t('reverseproxy.certIssue')}</a></li>`) : ''}
                ${canManage ? `<li><a href="#" class="dropdown-item" data-action="${h.enabled ? 'disable' : 'enable'}" data-id="${h.id}">
                    <i class="ti ti-${h.enabled ? 'player-pause' : 'player-play'} me-2"></i>${h.enabled ? t('reverseproxy.disable') : t('reverseproxy.enable')}</a></li>` : ''}
                ${canManage ? `<li><hr class="dropdown-divider"></li>
                    <li><a href="#" class="dropdown-item text-danger" data-action="delete" data-id="${h.id}">
                    <i class="ti ti-trash me-2"></i>${t('reverseproxy.delete')}</a></li>` : ''}
            </ul>
        </div>`;

    return `
        <tr data-host-id="${h.id}">
            <td>
                <div class="d-flex align-items-center">
                    <span class="avatar avatar-rounded bg-green-lt me-2">${escapeHtml(initial)}</span>
                    <div>
                        <div>${domains || '<span class="text-muted">–</span>'}</div>
                        <div class="text-muted small">${escapeHtml(h.name)} · ${formatDate(h.created_at)}</div>
                    </div>
                </div>
            </td>
            <td><code>${dest}</code></td>
            <td>${tlsBadge}</td>
            <td>${accessBadge}</td>
            <td>${statusBadge}</td>
            <td>${actions}</td>
        </tr>`;
}

async function deleteHost(host) {
    const ok = await confirmDialog(
        t('reverseproxy.confirmDeleteHost'),
        t('reverseproxy.confirmDeleteHostMsg'),
        t('reverseproxy.delete'),
        'btn-danger',
    );
    if (!ok) return;
    try {
        await apiDelete(`${MODULE_API}/hosts/${host.id}`);
        showToast(t('reverseproxy.hostDeleted'), 'success');
        await reloadHosts();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function toggleHost(host, enable) {
    try {
        await apiPost(`${MODULE_API}/hosts/${host.id}/${enable ? 'enable' : 'disable'}`);
        showToast(enable ? t('reverseproxy.hostEnabled') : t('reverseproxy.hostDisabled'), 'success');
        await reloadHosts();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function issueCert(host) {
    const root = document.getElementById('revproxy-hosts-table');
    const row = root?.querySelector(`tr[data-host-id="${host.id}"]`);
    if (row) {
        row.cells[2].innerHTML =
            `<span class="badge bg-secondary-lt">` +
            `<span class="spinner-border spinner-border-sm me-1" role="status" ` +
            `style="width:.65rem;height:.65rem;border-width:2px;"></span>` +
            `${t('reverseproxy.loading')}</span>`;
        row.querySelectorAll('[data-action]').forEach(b => { b.closest('li, div').style.pointerEvents = 'none'; });
    }
    try {
        await apiPost(`${MODULE_API}/hosts/${host.id}/certificate`, {});
        showToast(t('reverseproxy.certRequested'), 'success');
    } catch (err) {
        showToast(err.message, 'error');
    }
    await reloadHosts();
}

async function revokeCert(host) {
    const ok = await confirmDialog(t('reverseproxy.certRevoke'), '', t('reverseproxy.delete'), 'btn-danger');
    if (!ok) return;
    try {
        await apiDelete(`${MODULE_API}/hosts/${host.id}/certificate`);
        showToast(t('reverseproxy.certRevoked'), 'success');
        await reloadHosts();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

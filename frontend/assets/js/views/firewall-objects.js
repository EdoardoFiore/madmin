import { apiGet, apiPost, apiPatch, apiDelete } from '../api.js';
import { showToast, confirmDialog, escapeHtml } from '../utils.js';
import { setPageActions, checkPermission } from '../app.js';

const OBJECT_TYPES = ['host', 'network', 'range', 'fqdn', 'group', 'service', 'service_group'];

const TYPE_LABELS = {
    host: 'Host',
    network: 'Network',
    range: 'Range',
    fqdn: 'FQDN',
    group: 'Group',
    service: 'Service',
    service_group: 'Service Group',
};

const TYPE_BADGES = {
    host:          'bg-blue-lt',
    network:       'bg-cyan-lt',
    range:         'bg-indigo-lt',
    fqdn:          'bg-purple-lt',
    group:         'bg-teal-lt',
    service:       'bg-orange-lt',
    service_group: 'bg-red-lt',
};

const TYPE_VALUE_HINT = {
    host:          'e.g. 192.168.1.10',
    network:       'e.g. 10.0.0.0/24',
    range:         'e.g. 10.0.0.1-10.0.0.50',
    fqdn:          'e.g. example.com',
    service:       'e.g. tcp/443  or  tcp/80-8080',
    group:         null,
    service_group: null,
};

let objects = [];
let editingId = null;
let allObjects = [];

export async function render(container) {
    container.innerHTML = `
    <div class="container-xl">
      <div class="page-header d-print-none">
        <div class="row align-items-center">
          <div class="col">
            <h2 class="page-title">Firewall Objects</h2>
            <div class="text-muted mt-1">Reusable address and service aliases for firewall rules</div>
          </div>
          <div class="col-auto ms-auto d-print-none" id="page-actions"></div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div class="input-group input-group-sm w-auto me-2">
            <span class="input-group-text"><i class="ti ti-search"></i></span>
            <input type="text" id="obj-search" class="form-control" placeholder="Filter…" style="width:200px">
          </div>
          <div class="ms-2">
            <select id="obj-type-filter" class="form-select form-select-sm" style="width:160px">
              <option value="">All types</option>
              ${OBJECT_TYPES.map(t => `<option value="${t}">${TYPE_LABELS[t]}</option>`).join('')}
            </select>
          </div>
        </div>
        <div class="table-responsive">
          <table class="table table-vcenter card-table table-hover">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Value / Members</th>
                <th>Comment</th>
                <th class="w-1"></th>
              </tr>
            </thead>
            <tbody id="objects-tbody">
              <tr><td colspan="5" class="text-center text-muted py-4">Loading…</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Object Modal -->
    <div class="modal modal-blur fade" id="objectModal" tabindex="-1">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="objectModalTitle">New Object</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="mb-3">
              <label class="form-label required">Name</label>
              <input type="text" id="obj-name" class="form-control" maxlength="64" placeholder="my-servers">
            </div>
            <div class="mb-3">
              <label class="form-label required">Type</label>
              <select id="obj-type" class="form-select">
                ${OBJECT_TYPES.map(t => `<option value="${t}">${TYPE_LABELS[t]}</option>`).join('')}
              </select>
            </div>
            <div class="mb-3" id="value-group">
              <label class="form-label required">Value</label>
              <input type="text" id="obj-value" class="form-control" placeholder="">
              <div class="form-hint" id="value-hint"></div>
            </div>
            <div class="mb-3 d-none" id="members-group">
              <label class="form-label">Members</label>
              <div id="members-list" class="border rounded p-2 mb-2" style="min-height:48px;max-height:200px;overflow-y:auto"></div>
              <select id="member-select" class="form-select form-select-sm">
                <option value="">— add member —</option>
              </select>
              <div class="form-hint" id="members-hint"></div>
            </div>
            <div class="mb-3">
              <label class="form-label">Comment</label>
              <input type="text" id="obj-comment" class="form-control" maxlength="255">
            </div>
            <div class="mb-3">
              <label class="form-label">Color</label>
              <div class="d-flex gap-2 flex-wrap" id="color-picker">
                ${['#206bc4','#2fb344','#f59f00','#d63939','#ae3ec9','#4299e1','#74c0fc','#63e6be'].map(c =>
                  `<span class="color-swatch" data-color="${c}" style="background:${c};width:22px;height:22px;border-radius:4px;cursor:pointer;border:2px solid transparent;display:inline-block"></span>`
                ).join('')}
                <span class="color-swatch" data-color="" style="background:#adb5bd;width:22px;height:22px;border-radius:4px;cursor:pointer;border:2px solid transparent;display:inline-block" title="None"></span>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-link link-secondary me-auto" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn btn-primary" id="save-obj-btn">Save</button>
          </div>
        </div>
      </div>
    </div>`;

    setPageActions(document.getElementById('page-actions'));

    const canManage = await checkPermission('firewall.manage');
    if (canManage) {
        document.getElementById('page-actions').innerHTML = `
          <button class="btn btn-primary" id="add-obj-btn">
            <i class="ti ti-plus me-1"></i>New Object
          </button>`;
        document.getElementById('add-obj-btn').addEventListener('click', () => openModal());
    }

    await loadObjects();
    bindEvents();
}

async function loadObjects() {
    try {
        const data = await apiGet('/firewall/objects');
        allObjects = Array.isArray(data) ? data : (data.objects || []);
        renderTable();
    } catch (e) {
        showToast('Failed to load firewall objects', 'error');
    }
}

function renderTable() {
    const search = (document.getElementById('obj-search')?.value || '').toLowerCase();
    const typeFilter = document.getElementById('obj-type-filter')?.value || '';

    objects = allObjects.filter(o => {
        if (typeFilter && o.type !== typeFilter) return false;
        if (search && !o.name.toLowerCase().includes(search) &&
            !(o.value || '').toLowerCase().includes(search) &&
            !(o.comment || '').toLowerCase().includes(search)) return false;
        return true;
    });

    const tbody = document.getElementById('objects-tbody');
    if (!objects.length) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-4">No objects found</td></tr>`;
        return;
    }

    tbody.innerHTML = objects.map(o => {
        const badge = `<span class="badge ${TYPE_BADGES[o.type] || 'bg-secondary-lt'}">${TYPE_LABELS[o.type] || o.type}</span>`;
        const colorDot = o.color
            ? `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${escapeHtml(o.color)};margin-right:6px"></span>`
            : '';
        const value = o.type === 'group' || o.type === 'service_group'
            ? `<span class="text-muted">${(o.members || []).length} members</span>`
            : `<code>${escapeHtml(o.value || '')}</code>`;

        return `<tr>
          <td>${colorDot}<strong>${escapeHtml(o.name)}</strong></td>
          <td>${badge}</td>
          <td>${value}</td>
          <td class="text-muted">${escapeHtml(o.comment || '')}</td>
          <td>
            <div class="btn-list flex-nowrap">
              <button class="btn btn-sm btn-ghost-secondary edit-btn" data-id="${o.id}" title="Edit"><i class="ti ti-edit"></i></button>
              <button class="btn btn-sm btn-ghost-danger delete-btn" data-id="${o.id}" title="Delete"><i class="ti ti-trash"></i></button>
            </div>
          </td>
        </tr>`;
    }).join('');

    tbody.querySelectorAll('.edit-btn').forEach(btn =>
        btn.addEventListener('click', () => openModal(btn.dataset.id))
    );
    tbody.querySelectorAll('.delete-btn').forEach(btn =>
        btn.addEventListener('click', () => deleteObject(btn.dataset.id))
    );
}

function bindEvents() {
    document.getElementById('obj-search').addEventListener('input', renderTable);
    document.getElementById('obj-type-filter').addEventListener('change', renderTable);
    document.getElementById('obj-type').addEventListener('change', onTypeChange);
    document.getElementById('save-obj-btn').addEventListener('click', saveObject);
    document.getElementById('color-picker').addEventListener('click', e => {
        const swatch = e.target.closest('.color-swatch');
        if (!swatch) return;
        document.querySelectorAll('.color-swatch').forEach(s => s.style.borderColor = 'transparent');
        swatch.style.borderColor = '#000';
    });
    document.getElementById('member-select').addEventListener('change', addMember);
}

function onTypeChange() {
    const type = document.getElementById('obj-type').value;
    const isGroup = type === 'group' || type === 'service_group';
    document.getElementById('value-group').classList.toggle('d-none', isGroup);
    document.getElementById('members-group').classList.toggle('d-none', !isGroup);

    const hint = TYPE_VALUE_HINT[type];
    document.getElementById('value-hint').textContent = hint || '';
    document.getElementById('obj-value').placeholder = hint || '';

    if (isGroup) populateMemberSelect(type);
}

function populateMemberSelect(groupType) {
    const compatible = groupType === 'group'
        ? allObjects.filter(o => ['host','network','range','fqdn','group'].includes(o.type))
        : allObjects.filter(o => ['service','service_group'].includes(o.type));

    const sel = document.getElementById('member-select');
    sel.innerHTML = '<option value="">— add member —</option>' +
        compatible.map(o => `<option value="${o.id}">${escapeHtml(o.name)} (${TYPE_LABELS[o.type]})</option>`).join('');
}

let currentMembers = [];

function addMember() {
    const sel = document.getElementById('member-select');
    const id = sel.value;
    if (!id || currentMembers.includes(id)) { sel.value = ''; return; }
    const obj = allObjects.find(o => o.id === id);
    if (!obj) { sel.value = ''; return; }
    currentMembers.push(id);
    renderMembersList();
    sel.value = '';
}

function renderMembersList() {
    const list = document.getElementById('members-list');
    list.innerHTML = currentMembers.map(id => {
        const obj = allObjects.find(o => o.id === id);
        if (!obj) return '';
        return `<span class="badge bg-blue-lt me-1 mb-1">
          ${escapeHtml(obj.name)}
          <button type="button" class="btn-close btn-close-sm ms-1 remove-member" data-id="${id}" style="font-size:0.6em"></button>
        </span>`;
    }).join('');
    list.querySelectorAll('.remove-member').forEach(btn =>
        btn.addEventListener('click', () => {
            currentMembers = currentMembers.filter(m => m !== btn.dataset.id);
            renderMembersList();
        })
    );
}

function openModal(id = null) {
    editingId = id;
    currentMembers = [];

    document.getElementById('objectModalTitle').textContent = id ? 'Edit Object' : 'New Object';
    document.getElementById('obj-name').value = '';
    document.getElementById('obj-type').value = 'host';
    document.getElementById('obj-value').value = '';
    document.getElementById('obj-comment').value = '';
    document.querySelectorAll('.color-swatch').forEach(s => s.style.borderColor = 'transparent');
    renderMembersList();
    onTypeChange();

    if (id) {
        const obj = allObjects.find(o => o.id === id);
        if (!obj) return;
        document.getElementById('obj-name').value = obj.name;
        document.getElementById('obj-type').value = obj.type;
        document.getElementById('obj-value').value = obj.value || '';
        document.getElementById('obj-comment').value = obj.comment || '';
        onTypeChange();
        if (obj.members) {
            currentMembers = [...obj.members];
            renderMembersList();
        }
        if (obj.color) {
            const swatch = document.querySelector(`.color-swatch[data-color="${obj.color}"]`);
            if (swatch) swatch.style.borderColor = '#000';
        }
    }

    const el = document.getElementById('objectModal');
    const modal = bootstrap.Modal.getInstance(el) || new bootstrap.Modal(el);
    modal.show();
}

async function saveObject() {
    const name = document.getElementById('obj-name').value.trim();
    const type = document.getElementById('obj-type').value;
    const isGroup = type === 'group' || type === 'service_group';
    const value = isGroup ? null : document.getElementById('obj-value').value.trim() || null;
    const comment = document.getElementById('obj-comment').value.trim() || null;
    const selectedSwatch = document.querySelector('.color-swatch[style*="borderColor: black"], .color-swatch[style*="border-color: black"], .color-swatch[style*="border-color:black"]');
    const color = selectedSwatch?.dataset?.color || null;

    if (!name) { showToast('Name is required', 'warning'); return; }
    if (!isGroup && !value) { showToast('Value is required', 'warning'); return; }
    if (isGroup && !currentMembers.length) { showToast('Add at least one member', 'warning'); return; }

    const payload = {
        name, type, value,
        members: isGroup ? currentMembers : null,
        comment, color,
    };

    try {
        if (editingId) {
            await apiPatch(`/firewall/objects/${editingId}`, payload);
            showToast('Object updated', 'success');
        } else {
            await apiPost('/firewall/objects', payload);
            showToast('Object created', 'success');
        }
        bootstrap.Modal.getInstance(document.getElementById('objectModal'))?.hide();
        await loadObjects();
    } catch (e) {
        showToast(e.message || 'Save failed', 'error');
    }
}

async function deleteObject(id) {
    const obj = allObjects.find(o => o.id === id);
    if (!obj) return;
    const ok = await confirmDialog(`Delete object "${obj.name}"? Rules referencing it will lose this alias.`);
    if (!ok) return;
    try {
        await apiDelete(`/firewall/objects/${id}`);
        showToast('Object deleted', 'success');
        await loadObjects();
    } catch (e) {
        showToast(e.message || 'Delete failed', 'error');
    }
}

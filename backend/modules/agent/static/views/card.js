/**
 * Hub Agent — compact inline card config.
 * Loaded directly in the module card on the Modules page.
 * Exports: async function render(container, moduleId)
 */

const BASE = '/api/modules/agent';
let _cardPoll = null;

export async function render(container, moduleId) {
  container.innerHTML = `<div class="text-muted small py-1">Caricamento…</div>`;
  let status = null;
  try {
    status = await _get(`${BASE}/status`);
  } catch {
    container.innerHTML = `<div class="text-danger small">Errore caricamento stato</div>`;
    return;
  }
  _renderCard(container, status);
  _startPoll(container);
}

function _renderCard(container, status) {
  const enrolled = status.enrollment_status === 'enrolled';

  if (!enrolled) {
    container.innerHTML = `
      <div class="border-top pt-2 mt-1">
        <div class="d-flex align-items-center justify-content-between mb-2">
          <span class="badge bg-secondary-lt">Non enrollato</span>
          <button class="btn btn-xs btn-primary" id="card-enroll-btn">
            <i class="ti ti-cloud-upload me-1"></i>Connetti Hub
          </button>
        </div>
      </div>`;
    container.querySelector('#card-enroll-btn').addEventListener('click', () => _showEnrollModal());
    return;
  }

  const wsBadge = status.ws_connected
    ? `<span class="badge bg-success-lt"><i class="ti ti-circle-filled me-1 text-success" style="font-size:8px"></i>Online</span>`
    : `<span class="badge bg-warning-lt"><i class="ti ti-circle-filled me-1 text-warning" style="font-size:8px"></i>Reconnecting…</span>`;

  const hb = status.last_heartbeat_at
    ? new Date(status.last_heartbeat_at).toLocaleTimeString('it-IT')
    : '—';

  container.innerHTML = `
    <div class="border-top pt-2 mt-1">
      <div class="d-flex align-items-center justify-content-between mb-1">
        <div class="d-flex align-items-center gap-2">
          ${wsBadge}
          <span class="text-muted small text-truncate" style="max-width:160px" title="${status.hub_url || ''}">
            ${status.hub_url ? _shortUrl(status.hub_url) : '—'}
          </span>
        </div>
        <button class="btn btn-xs btn-ghost-danger" id="card-disconnect-btn" title="Disconnetti">
          <i class="ti ti-plug-connected-x"></i>
        </button>
      </div>
      <div class="text-muted" style="font-size:0.7rem">
        <span class="me-2" title="Instance ID"><i class="ti ti-fingerprint me-1"></i><code>${(status.instance_id || '').slice(0, 8)}…</code></span>
        <span title="Ultimo heartbeat"><i class="ti ti-heartbeat me-1"></i>${hb}</span>
      </div>
    </div>`;

  container.querySelector('#card-disconnect-btn').addEventListener('click', async (e) => {
    e.stopPropagation();
    const ok = await _confirm('Disconnettere dall\'Hub?', 'Tutte le chiavi SSH installate verranno rimosse.');
    if (!ok) return;
    try {
      await _post(`${BASE}/disconnect`, {});
      _stopPoll();
      const s = await _get(`${BASE}/status`);
      _renderCard(container, s);
      _startPoll(container);
    } catch (err) {
      _toast('Errore: ' + (err.detail || err), 'error');
    }
  });
}

async function _showEnrollModal() {
  let defaults = {};
  try {
    const s = await _get(`${BASE}/status`);
    defaults = s.setup_defaults || {};
  } catch { }

  // Reuse existing bootstrap modal if present, else build inline
  const existingModal = document.getElementById('agent-enroll-modal');
  if (existingModal) {
    existingModal.querySelector('#ae-cmd').value = '';
    if (defaults.hub_url) existingModal.querySelector('#ae-url').value = defaults.hub_url;
    if (defaults.enrollment_token) existingModal.querySelector('#ae-token').value = defaults.enrollment_token;
    if (defaults.instance_name) existingModal.querySelector('#ae-name').value = defaults.instance_name;
    existingModal.querySelector('#ae-error').classList.add('d-none');
    bootstrap.Modal.getOrCreateInstance(existingModal).show();
    return;
  }

  const div = document.createElement('div');
  div.id = 'agent-enroll-modal';
  div.className = 'modal modal-blur fade';
  div.tabIndex = -1;
  div.innerHTML = `
    <div class="modal-dialog modal-sm">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">Connetti all'Hub</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
        </div>
        <div class="modal-body">
          <div class="mb-3">
            <label class="form-label form-label-sm text-muted">Incolla il comando di installazione <span class="text-muted">(opzionale)</span></label>
            <div class="input-group input-group-sm">
              <input id="ae-cmd" type="text" class="form-control form-control-sm font-monospace"
                placeholder="curl … | sudo bash -s -- --token …" />
              <button class="btn btn-outline-secondary btn-sm" type="button" id="ae-parse-cmd">
                <i class="ti ti-arrow-down-circle"></i>
              </button>
            </div>
          </div>
          <div class="mb-2">
            <label class="form-label form-label-sm">URL Hub</label>
            <input id="ae-url" type="url" class="form-control form-control-sm" placeholder="https://hub.example.com:7444" value="${defaults.hub_url || ''}" />
          </div>
          <div class="mb-2">
            <label class="form-label form-label-sm">Token enrollment</label>
            <input id="ae-token" type="text" class="form-control form-control-sm font-monospace" placeholder="Token generato dall'Hub" value="${defaults.enrollment_token || ''}" />
          </div>
          <div class="mb-2">
            <label class="form-label form-label-sm">Nome istanza <span class="text-muted">(opzionale)</span></label>
            <input id="ae-name" type="text" class="form-control form-control-sm" value="${defaults.instance_name || ''}" />
          </div>
          <div id="ae-error" class="text-danger small d-none"></div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Annulla</button>
          <button type="button" class="btn btn-primary btn-sm" id="ae-submit">Connetti</button>
        </div>
      </div>
    </div>`;

  document.body.appendChild(div);
  const modal = bootstrap.Modal.getOrCreateInstance(div);

  div.querySelector('#ae-parse-cmd').addEventListener('click', () => {
    const raw = div.querySelector('#ae-cmd').value.trim();
    const urlMatch = raw.match(/https?:\/\/[^\s/]+/);
    const tokenMatch = raw.match(/--token\s+(\S+)/);
    if (!urlMatch) { div.querySelector('#ae-error').textContent = 'URL Hub non trovato nel comando'; div.querySelector('#ae-error').classList.remove('d-none'); return; }
    div.querySelector('#ae-url').value = urlMatch[0];
    if (tokenMatch) div.querySelector('#ae-token').value = tokenMatch[1];
    div.querySelector('#ae-error').classList.add('d-none');
  });

  div.querySelector('#ae-submit').addEventListener('click', async () => {
    const url = div.querySelector('#ae-url').value.trim();
    const token = div.querySelector('#ae-token').value.trim();
    const name = div.querySelector('#ae-name').value.trim() || null;
    const errEl = div.querySelector('#ae-error');
    if (!url || !token) { errEl.textContent = 'URL e token obbligatori'; errEl.classList.remove('d-none'); return; }
    const btn = div.querySelector('#ae-submit');
    btn.disabled = true; btn.textContent = 'Connessione…';
    try {
      await _post(`${BASE}/enroll`, { hub_url: url, enrollment_token: token, instance_name: name });
      modal.hide();
      // Refresh the card — find the card container
      const cardBody = document.querySelector('[data-agent-card-config]');
      if (cardBody) {
        const s = await _get(`${BASE}/status`);
        _renderCard(cardBody, s);
        _startPoll(cardBody);
      }
    } catch (err) {
      errEl.textContent = err.detail || 'Enrollment fallito';
      errEl.classList.remove('d-none');
      btn.disabled = false; btn.textContent = 'Connetti';
    }
  });

  modal.show();
}

function _shortUrl(url) {
  try { return new URL(url).host; } catch { return url.slice(0, 24); }
}

function _startPoll(container) {
  _stopPoll();
  _cardPoll = setInterval(async () => {
    try {
      const s = await _get(`${BASE}/status`);
      _renderCard(container, s);
    } catch { }
  }, 8000);
}

function _stopPoll() {
  if (_cardPoll) { clearInterval(_cardPoll); _cardPoll = null; }
}

async function _get(url) {
  const token = localStorage.getItem('madmin_token');
  const r = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw d; }
  return r.json();
}

async function _post(url, body) {
  const token = localStorage.getItem('madmin_token');
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body),
  });
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw d; }
  return r.json();
}

function _confirm(title, body = '') {
  return new Promise(resolve => {
    if (window.bootstrap?.Modal) {
      const el = document.createElement('div');
      el.className = 'modal modal-blur fade';
      el.tabIndex = -1;
      el.innerHTML = `<div class="modal-dialog modal-sm modal-dialog-centered"><div class="modal-content">
        <div class="modal-header"><h5 class="modal-title">${title}</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
        ${body ? `<div class="modal-body">${body}</div>` : ''}
        <div class="modal-footer">
          <button class="btn btn-link link-secondary me-auto" data-bs-dismiss="modal">Annulla</button>
          <button class="btn btn-danger" id="_conf-ok">Disconnetti</button>
        </div></div></div>`;
      document.body.appendChild(el);
      const m = window.bootstrap.Modal.getOrCreateInstance(el);
      let ok = false;
      el.querySelector('#_conf-ok').onclick = () => { ok = true; m.hide(); };
      el.addEventListener('hidden.bs.modal', () => { el.remove(); resolve(ok); }, { once: true });
      m.show();
    } else {
      resolve(window.confirm(title + (body ? '\n' + body : '')));
    }
  });
}

function _toast(msg, type = 'info') {
  if (window.showToast) { window.showToast(msg, type); return; }
  const colorMap = { success: 'bg-success', error: 'bg-danger', warning: 'bg-warning', info: 'bg-info' };
  const bg = colorMap[type] || colorMap.info;
  let tc = document.querySelector('.toast-container');
  if (!tc) { tc = document.createElement('div'); tc.className = 'toast-container position-fixed bottom-0 end-0 p-3'; tc.style.zIndex = '1090'; document.body.appendChild(tc); }
  const el = document.createElement('div');
  el.className = `toast align-items-center text-white ${bg} border-0 show`;
  el.setAttribute('role', 'alert');
  el.innerHTML = `<div class="d-flex"><div class="toast-body">${msg}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
  tc.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

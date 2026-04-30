/**
 * Hub Agent — compact inline card config.
 * Loaded directly in the module card on the Modules page.
 * Exports: async function render(container, moduleId)
 */

const BASE = '/api/agent';
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
    if (!confirm('Disconnettere dall\'Hub? Tutte le chiavi SSH installate verranno rimosse.')) return;
    try {
      await _post(`${BASE}/disconnect`, {});
      _stopPoll();
      const s = await _get(`${BASE}/status`);
      _renderCard(container, s);
      _startPoll(container);
    } catch (err) {
      alert('Errore: ' + (err.detail || err));
    }
  });
}

function _showEnrollModal() {
  // Reuse existing bootstrap modal if present, else build inline
  const existingModal = document.getElementById('agent-enroll-modal');
  if (existingModal) {
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
          <div class="mb-2">
            <label class="form-label form-label-sm">URL Hub</label>
            <input id="ae-url" type="url" class="form-control form-control-sm" placeholder="https://hub.example.com:7444" />
          </div>
          <div class="mb-2">
            <label class="form-label form-label-sm">Token enrollment</label>
            <input id="ae-token" type="text" class="form-control form-control-sm font-monospace" placeholder="enr_…" />
          </div>
          <div class="mb-2">
            <label class="form-label form-label-sm">Nome istanza <span class="text-muted">(opzionale)</span></label>
            <input id="ae-name" type="text" class="form-control form-control-sm" />
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

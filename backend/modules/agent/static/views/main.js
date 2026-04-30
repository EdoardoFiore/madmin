/**
 * Hub Agent — enrollment wizard + live connection status.
 */
import { apiGet, apiPost } from '/assets/js/api.js';
import { showToast, showSpinner } from '/assets/js/utils.js';

const BASE = '/api/modules/agent';
let _pollHandle = null;

export async function render(container) {
  showSpinner(container);

  let status = null;
  try {
    status = await apiGet(`${BASE}/status`);
  } catch (e) {
    container.innerHTML = `<div class="container-xl py-4"><div class="alert alert-danger">Errore caricamento stato agent: ${e.detail || e}</div></div>`;
    return;
  }

  container.innerHTML = _buildPage(status);
  _bindEvents(container, status);
  _startPolling(container);
}

function _buildPage(status) {
  const enrolled = status.enrollment_status === 'enrolled';

  return `
    <div class="page-header">
      <div class="container-xl">
        <div class="row align-items-center">
          <div class="col-auto">
            <h2 class="page-title">Hub Agent</h2>
          </div>
          <div class="col-auto ms-auto">
            ${_wsStatusBadge(status)}
          </div>
        </div>
      </div>
    </div>

    <div class="page-body">
      <div class="container-xl">
        <div class="row row-cards">

          <!-- Status card -->
          <div class="col-lg-6">
            <div class="card">
              <div class="card-header"><h3 class="card-title">Stato connessione</h3></div>
              <div class="card-body" id="status-body">
                ${_statusBody(status)}
              </div>
              ${enrolled ? `
              <div class="card-footer">
                <button id="btn-disconnect" class="btn btn-danger btn-sm">
                  <i class="ti ti-plug-connected-x me-1"></i>Disconnetti dall'Hub
                </button>
              </div>` : ''}
            </div>
          </div>

          <!-- Enrollment / config card -->
          <div class="col-lg-6">
            ${enrolled ? _connectedCard(status) : _enrollCard(status.setup_defaults || {})}
          </div>

          <!-- Active SSH keys -->
          ${enrolled ? `
          <div class="col-12">
            <div class="card">
              <div class="card-header"><h3 class="card-title">Chiavi SSH installate dall'Hub</h3></div>
              <div class="card-body p-0">
                <div id="ssh-keys-body">
                  <div class="p-3 text-muted">Caricamento…</div>
                </div>
              </div>
            </div>
          </div>` : ''}

          <!-- Event log -->
          <div class="col-12">
            <div class="card">
              <div class="card-header">
                <h3 class="card-title">Log eventi</h3>
                <div class="ms-auto">
                  <button id="btn-refresh-log" class="btn btn-sm btn-outline-secondary">
                    <i class="ti ti-refresh"></i>
                  </button>
                </div>
              </div>
              <div class="card-body p-0">
                <div id="log-body" style="max-height:320px;overflow-y:auto;">
                  <div class="p-3 text-muted">Caricamento…</div>
                </div>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>`;
}

function _wsStatusBadge(status) {
  if (status.ws_connected) {
    return `<span class="badge bg-success-lt fs-6"><i class="ti ti-circle-filled me-1 text-success"></i>Connesso all'Hub</span>`;
  }
  if (status.enrollment_status === 'enrolled') {
    return `<span class="badge bg-warning-lt fs-6"><i class="ti ti-circle-filled me-1 text-warning"></i>Disconnesso (riconnessione…)</span>`;
  }
  return `<span class="badge bg-secondary-lt fs-6"><i class="ti ti-circle-filled me-1"></i>Non enrollato</span>`;
}

function _statusBody(status) {
  if (status.enrollment_status !== 'enrolled') {
    return `<p class="text-muted mb-0">Questa istanza non è ancora connessa a nessun Hub.</p>`;
  }
  return `
    <dl class="row mb-0">
      <dt class="col-5">Hub</dt>
      <dd class="col-7 text-truncate" title="${status.hub_url || ''}">${status.hub_url || '—'}</dd>
      <dt class="col-5">Instance ID</dt>
      <dd class="col-7"><code>${status.instance_id || '—'}</code></dd>
      <dt class="col-5">Nome</dt>
      <dd class="col-7">${status.instance_name || '—'}</dd>
      <dt class="col-5">WS</dt>
      <dd class="col-7">${status.ws_connected
        ? '<span class="text-success">Connesso</span>'
        : `<span class="text-warning">Disconnesso (tentativo #${status.reconnect_attempt})</span>`
      }</dd>
      <dt class="col-5">Ultimo heartbeat</dt>
      <dd class="col-7">${status.last_heartbeat_at ? new Date(status.last_heartbeat_at).toLocaleString('it-IT') : '—'}</dd>
    </dl>`;
}

function _enrollCard(defaults = {}) {
  return `
    <div class="card">
      <div class="card-header"><h3 class="card-title">Enrollment Hub</h3></div>
      <div class="card-body">
        <p class="text-muted mb-3">
          Genera un token di enrollment su MADMIN Hub, poi incollalo qui
          per connettere questa istanza.
        </p>
        <div class="mb-2">
          <label class="form-label">URL Hub <span class="text-danger">*</span></label>
          <input id="enroll-url" type="url" class="form-control" placeholder="https://hub.example.com:7444" value="${defaults.hub_url || ''}" />
        </div>
        <div class="mb-2">
          <label class="form-label">Token enrollment (one-time) <span class="text-danger">*</span></label>
          <input id="enroll-token" type="text" class="form-control font-monospace" placeholder="enr_…" value="${defaults.enrollment_token || ''}" />
        </div>
        <div class="mb-3">
          <label class="form-label">Nome istanza</label>
          <input id="enroll-name" type="text" class="form-control" placeholder="Lascia vuoto per hostname automatico" value="${defaults.instance_name || ''}" />
        </div>
        <button id="btn-enroll" class="btn btn-primary">
          <i class="ti ti-cloud-upload me-1"></i>Connetti all'Hub
        </button>
      </div>
    </div>`;
}

function _connectedCard(status) {
  return `
    <div class="card">
      <div class="card-header"><h3 class="card-title">Connessione attiva</h3></div>
      <div class="card-body">
        <div class="alert alert-success mb-0">
          <div class="d-flex">
            <div><i class="ti ti-circle-check fs-2 me-2"></i></div>
            <div>
              <strong>Istanza enrollata e connessa.</strong><br>
              L'Hub può monitorare questa istanza e inviarle comandi via WebSocket.
            </div>
          </div>
        </div>
      </div>
    </div>`;
}

function _bindEvents(container, status) {
  // Enroll
  const btnEnroll = container.querySelector('#btn-enroll');
  if (btnEnroll) {
    btnEnroll.addEventListener('click', async () => {
      const url = container.querySelector('#enroll-url').value.trim();
      const token = container.querySelector('#enroll-token').value.trim();
      const name = container.querySelector('#enroll-name').value.trim() || null;
      if (!url || !token) { showToast('URL e token obbligatori', 'error'); return; }
      btnEnroll.disabled = true;
      btnEnroll.textContent = 'Connessione…';
      try {
        await apiPost(`${BASE}/enroll`, { hub_url: url, enrollment_token: token, instance_name: name });
        showToast('Enrollment completato', 'success');
        _stopPolling();
        const s = await apiGet(`${BASE}/status`);
        container.innerHTML = _buildPage(s);
        _bindEvents(container, s);
        _startPolling(container);
      } catch (e) {
        showToast(e.detail || 'Enrollment fallito', 'error');
        btnEnroll.disabled = false;
        btnEnroll.innerHTML = '<i class="ti ti-cloud-upload me-1"></i>Connetti all\'Hub';
      }
    });
  }

  // Disconnect
  const btnDisconnect = container.querySelector('#btn-disconnect');
  if (btnDisconnect) {
    btnDisconnect.addEventListener('click', async () => {
      if (!confirm('Disconnettere questa istanza dall\'Hub?\nTutte le chiavi SSH installate dall\'Hub verranno rimosse.')) return;
      btnDisconnect.disabled = true;
      try {
        await apiPost(`${BASE}/disconnect`, {});
        showToast('Disconnesso dall\'Hub', 'success');
        _stopPolling();
        const s = await apiGet(`${BASE}/status`);
        container.innerHTML = _buildPage(s);
        _bindEvents(container, s);
      } catch (e) {
        showToast(e.detail || 'Errore', 'error');
        btnDisconnect.disabled = false;
      }
    });
  }

  // Refresh log
  const btnLog = container.querySelector('#btn-refresh-log');
  if (btnLog) {
    btnLog.addEventListener('click', () => _refreshLog(container));
  }

  // Initial data load
  if (status.enrollment_status === 'enrolled') {
    _refreshSshKeys(container);
  }
  _refreshLog(container);
}

async function _refreshLog(container) {
  const el = container.querySelector('#log-body');
  if (!el) return;
  try {
    const logs = await apiGet(`${BASE}/logs?limit=100`);
    if (!logs.length) {
      el.innerHTML = '<div class="p-3 text-muted">Nessun evento registrato.</div>';
      return;
    }
    const levelBadge = l => {
      const map = { info: 'bg-blue-lt text-blue', warning: 'bg-yellow-lt text-yellow', error: 'bg-red-lt text-red' };
      return `<span class="badge ${map[l] || 'bg-secondary-lt'}">${l}</span>`;
    };
    el.innerHTML = `<table class="table table-sm table-vcenter table-nowrap mb-0">
      <thead><tr><th>Timestamp</th><th>Livello</th><th>Evento</th><th>Dettaglio</th></tr></thead>
      <tbody>
        ${logs.map(l => `<tr>
          <td class="text-muted">${new Date(l.ts).toLocaleString('it-IT')}</td>
          <td>${levelBadge(l.level)}</td>
          <td><code>${l.event}</code></td>
          <td class="text-muted text-truncate" style="max-width:300px">${l.detail || ''}</td>
        </tr>`).join('')}
      </tbody></table>`;
  } catch (e) {
    el.innerHTML = `<div class="p-3 text-danger">Errore: ${e.detail || e}</div>`;
  }
}

async function _refreshSshKeys(container) {
  const el = container.querySelector('#ssh-keys-body');
  if (!el) return;
  try {
    const keys = await apiGet(`${BASE}/ssh-keys`);
    if (!keys.length) {
      el.innerHTML = '<div class="p-3 text-muted">Nessuna chiave SSH installata dall\'Hub.</div>';
      return;
    }
    el.innerHTML = `<table class="table table-sm table-vcenter mb-0">
      <thead><tr><th>Assignment ID</th><th>Utente</th><th>Installata</th><th>Scadenza</th></tr></thead>
      <tbody>
        ${keys.map(k => `<tr>
          <td><code>${k.assignment_id}</code></td>
          <td>${k.target_user}</td>
          <td>${new Date(k.pushed_at).toLocaleString('it-IT')}</td>
          <td>${k.expires_at ? new Date(k.expires_at).toLocaleString('it-IT') : '<span class="text-muted">—</span>'}</td>
        </tr>`).join('')}
      </tbody></table>`;
  } catch (e) {
    el.innerHTML = `<div class="p-3 text-danger">Errore: ${e.detail || e}</div>`;
  }
}

function _startPolling(container) {
  _stopPolling();
  _pollHandle = setInterval(async () => {
    try {
      const status = await apiGet(`${BASE}/status`);
      const badge = container.querySelector('.badge.fs-6');
      if (badge) badge.outerHTML = _wsStatusBadge(status);
      const sb = container.querySelector('#status-body');
      if (sb) sb.innerHTML = _statusBody(status);
    } catch { }
  }, 5000);
}

function _stopPolling() {
  if (_pollHandle) {
    clearInterval(_pollHandle);
    _pollHandle = null;
  }
}

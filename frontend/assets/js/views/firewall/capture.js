/**
 * MADMIN - Traffic capture (tcpdump)
 *
 * Side panel opened from the firewall hub (Standard and Advanced) or from a
 * rule's row with its fields prefilled. The capture streams from
 * POST /firewall/capture/stream as NDJSON, read with fetch (the JWT goes in
 * the Authorization header, which EventSource cannot send). Closing the panel
 * or leaving the page aborts the stream, which stops tcpdump on the server.
 *
 * Every tcpdump line is inserted with textContent: it carries whatever the
 * captured packets contain.
 */
import { apiGet, apiFetch, apiDelete, _extractDetail } from '../../api.js';
import { showToast, escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';

const DOM_LINES = 5000;        // lines kept on screen
const KEPT_LINES = 50000;      // lines kept for "download text"

let cap = null;   // the open panel's state (one at a time)

/**
 * prefill: { interface, protocol, host, src, dst, net, port }, e.g. from
 * prefillFromRule.
 */
export async function openCapture({ prefill = {} } = {}) {
    if (cap) return;
    let ifaces = ['any'];
    try {
        ifaces = await apiGet('/firewall/capture/interfaces');
    } catch (err) {
        showToast(t('common.errorPrefix') + err.message, 'error');
        return;
    }
    const el = document.createElement('div');
    el.className = 'offcanvas offcanvas-end fw-capture-oc';
    el.tabIndex = -1;
    el.innerHTML = panelHtml(ifaces, prefill);
    document.body.appendChild(el);

    cap = {
        el, controller: null, id: null, running: false, paused: false,
        pending: [], lines: [], pcap: false, startedAt: 0, timer: null,
    };
    const oc = bootstrap.Offcanvas.getOrCreateInstance(el, { backdrop: true, keyboard: true });
    const onRoute = () => oc.hide();
    window.addEventListener('hashchange', onRoute);
    el.addEventListener('hidden.bs.offcanvas', () => {
        window.removeEventListener('hashchange', onRoute);
        stopStream();
        oc.dispose();
        el.remove();
        cap = null;
    });
    bind(el);
    oc.show();
}

/** Capture fields from a rule's literal match (address objects are skipped, with a notice). */
export function prefillFromRule(rule) {
    const p = {};
    // the incoming interface, else the outgoing one (a POSTROUTING rule has no -i)
    const iface = rule.in_interface || rule.out_interface;
    if (iface && !iface.endsWith('+')) p.interface = iface;
    if (['tcp', 'udp', 'icmp'].includes(rule.protocol)) p.protocol = rule.protocol;
    if (rule.port && /^\d+$/.test(String(rule.port)) && p.protocol !== 'icmp') p.port = rule.port;
    const side = (value, hostKey) => {
        if (!value) return;
        const [ip, prefix] = String(value).split('/');
        if (!prefix || prefix === '32') p[hostKey] = ip;
        else if (!p.net) p.net = value;
    };
    side(rule.source, 'src');
    side(rule.destination, 'dst');
    if ((rule.source_refs || []).length || (rule.destination_refs || []).length) {
        showToast(t('firewall.capture.refsIgnored'), 'info');
    }
    return p;
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

function panelHtml(ifaces, p) {
    const sel = (a, b) => (a === b ? 'selected' : '');
    const ifaceOpts = ifaces.map(i => `<option value="${escapeHtml(i)}" ${sel(i, p.interface || 'any')}>${
        escapeHtml(i === 'any' ? t('firewall.capture.allInterfaces') : i)}</option>`).join('');
    const input = (id, label, value, ph, cls = 'col-md-4') => `
        <div class="${cls}">
            <label class="form-label">${label}</label>
            <input class="form-control" id="${id}" value="${escapeHtml(value || '')}" placeholder="${escapeHtml(ph)}">
        </div>`;
    return `
        <div class="offcanvas-header border-bottom">
            <h3 class="offcanvas-title"><i class="ti ti-radar me-2"></i>${escapeHtml(t('firewall.capture.title'))}</h3>
            <button type="button" class="btn-close" data-bs-dismiss="offcanvas" aria-label="${escapeHtml(t('common.close'))}"></button>
        </div>
        <div class="offcanvas-body d-flex flex-column">
            <div class="alert alert-warning py-2 small mb-3">
                <i class="ti ti-eye me-1"></i>${escapeHtml(t('firewall.capture.warning'))}
            </div>
            <form id="cap-form" class="row g-2" autocomplete="off">
                <div class="col-md-4">
                    <label class="form-label">${t('firewall.capture.interface')}</label>
                    <select class="form-select" id="cap-iface">${ifaceOpts}</select>
                </div>
                <div class="col-md-4">
                    <label class="form-label">${t('firewall.protocol')}</label>
                    <select class="form-select" id="cap-proto">
                        <option value="">${t('firewall.allProtocols')}</option>
                        ${['tcp', 'udp', 'icmp', 'arp'].map(x => `<option value="${x}" ${sel(x, p.protocol)}>${x.toUpperCase()}</option>`).join('')}
                    </select>
                </div>
                ${input('cap-port', t('firewall.port'), p.port, '443')}
                ${input('cap-host', t('firewall.capture.host'), p.host, '192.168.1.10')}
                ${input('cap-src', t('firewall.source'), p.src, '192.168.1.10')}
                ${input('cap-dst', t('firewall.destination'), p.dst, '8.8.8.8')}
                <div class="col-12">
                    <a class="small" data-bs-toggle="collapse" href="#cap-adv" role="button" aria-expanded="false">
                        <i class="ti ti-adjustments me-1"></i>${t('firewall.capture.advanced')}
                    </a>
                </div>
                <div class="collapse col-12 ${p.net ? 'show' : ''}" id="cap-adv">
                    <div class="row g-2">
                        ${input('cap-net', t('firewall.capture.net'), p.net, '10.0.0.0/24')}
                        <div class="col-md-8">
                            <label class="form-label">${t('firewall.capture.bpf')}</label>
                            <input class="form-control font-monospace" id="cap-bpf" placeholder="not port 53 and (tcp[tcpflags] &amp; tcp-syn != 0)">
                            <small class="form-hint">${t('firewall.capture.bpfHint')}</small>
                        </div>
                        ${input('cap-duration', t('firewall.capture.duration'), '60', '60')}
                        ${input('cap-packets', t('firewall.capture.maxPackets'), '1000', '1000')}
                        ${input('cap-snaplen', t('firewall.capture.snaplen'), '0', '0')}
                        <div class="col-12 d-flex flex-wrap gap-3">
                            <label class="form-check mb-0"><input class="form-check-input" type="checkbox" id="cap-e">
                                <span class="form-check-label">${t('firewall.capture.linkLevel')}</span></label>
                            <label class="form-check mb-0"><input class="form-check-input" type="checkbox" id="cap-v">
                                <span class="form-check-label">${t('firewall.capture.verbose')}</span></label>
                            <label class="form-check mb-0" title="${escapeHtml(t('firewall.capture.excludePanelHint'))}">
                                <input class="form-check-input" type="checkbox" id="cap-excl" checked>
                                <span class="form-check-label">${t('firewall.capture.excludePanel')}</span></label>
                        </div>
                    </div>
                </div>
                <div class="col-12 d-flex flex-wrap gap-2 mt-2">
                    <button class="btn btn-primary" type="submit" id="cap-start"><i class="ti ti-player-play me-1"></i>${t('firewall.capture.start')}</button>
                    <button class="btn btn-danger" type="button" id="cap-stop" disabled><i class="ti ti-player-stop me-1"></i>${t('firewall.capture.stop')}</button>
                    <button class="btn btn-outline-secondary" type="button" id="cap-pause" disabled><i class="ti ti-player-pause me-1"></i><span>${t('firewall.capture.pause')}</span></button>
                    <button class="btn btn-outline-secondary" type="button" id="cap-clear"><i class="ti ti-eraser me-1"></i>${t('firewall.capture.clear')}</button>
                    <div class="ms-auto d-flex gap-2">
                        <button class="btn btn-outline-secondary" type="button" id="cap-dl-text" disabled><i class="ti ti-file-text me-1"></i>${t('firewall.capture.downloadText')}</button>
                        <button class="btn btn-outline-primary" type="button" id="cap-dl-pcap" disabled><i class="ti ti-download me-1"></i>${t('firewall.capture.downloadPcap')}</button>
                    </div>
                </div>
            </form>
            <div class="d-flex flex-wrap align-items-center gap-3 mt-3 small">
                <span id="cap-state" class="badge bg-secondary-lt">${t('firewall.capture.statusIdle')}</span>
                <span id="cap-stats" class="text-muted"></span>
                <span class="text-muted text-truncate">${t('firewall.capture.filterLabel')}: <code id="cap-filter">—</code></span>
            </div>
            <div class="d-flex flex-wrap align-items-center gap-3 mt-2">
                <input class="form-control form-control-sm fw-capture-search" id="cap-search" placeholder="${escapeHtml(t('firewall.capture.displayFilter'))}">
                <label class="form-check mb-0 small"><input class="form-check-input" type="checkbox" id="cap-autoscroll" checked>
                    <span class="form-check-label">${t('firewall.capture.autoscroll')}</span></label>
                <span id="cap-paused" class="text-warning small"></span>
            </div>
            <div id="cap-out" class="fw-capture-out mt-2 flex-grow-1" role="log" aria-live="off"></div>
        </div>`;
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

function bind(el) {
    const q = (s) => el.querySelector(s);
    q('#cap-form').addEventListener('submit', (e) => { e.preventDefault(); start(); });
    q('#cap-stop').addEventListener('click', stop);
    q('#cap-pause').addEventListener('click', togglePause);
    q('#cap-clear').addEventListener('click', () => {
        q('#cap-out').replaceChildren();
        cap.lines = [];
        cap.pending = [];
        updatePaused();
        q('#cap-dl-text').disabled = true;
    });
    q('#cap-dl-text').addEventListener('click', downloadText);
    q('#cap-dl-pcap').addEventListener('click', downloadPcap);
    q('#cap-search').addEventListener('input', applySearch);
}

function readSpec() {
    const q = (s) => cap.el.querySelector(s);
    const val = (s) => q(s).value.trim() || null;
    const num = (s, d) => {
        const v = q(s).value.trim();
        return v === '' ? d : parseInt(v, 10);
    };
    return {
        interface: q('#cap-iface').value,
        protocol: val('#cap-proto'),
        port: val('#cap-port') ? parseInt(q('#cap-port').value, 10) : null,
        host: val('#cap-host'),
        src: val('#cap-src'),
        dst: val('#cap-dst'),
        net: val('#cap-net'),
        bpf: val('#cap-bpf'),
        duration: num('#cap-duration', 60),
        max_packets: num('#cap-packets', 1000),
        snaplen: num('#cap-snaplen', 0),
        link_level: q('#cap-e').checked,
        verbose: q('#cap-v').checked,
        exclude_panel: q('#cap-excl').checked,
    };
}

async function start() {
    if (!cap || cap.running) return;
    const state = cap;
    state.controller = new AbortController();
    state.id = null;
    state.pcap = false;
    setRunning(true);
    setState('statusStarting', 'bg-azure-lt');
    let resp;
    try {
        resp = await apiFetch('/firewall/capture/stream', {
            method: 'POST', body: JSON.stringify(readSpec()), signal: state.controller.signal,
        });
    } catch (err) {
        setRunning(false);
        setState('statusIdle', 'bg-secondary-lt');
        if (err.name !== 'AbortError') showToast(t('common.errorPrefix') + err.message, 'error');
        return;
    }
    if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        setRunning(false);
        setState('statusIdle', 'bg-secondary-lt');
        showToast(t('common.errorPrefix') + _extractDetail(body), 'error');
        return;
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let ended = false;
    try {
        for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            let i;
            while ((i = buf.indexOf('\n')) >= 0) {
                const line = buf.slice(0, i);
                buf = buf.slice(i + 1);
                if (!line) continue;
                const ev = JSON.parse(line);
                if (ev.t === 'end') ended = true;
                handle(state, ev);
            }
        }
    } catch (err) {
        if (err.name !== 'AbortError' && cap === state) showToast(t('common.errorPrefix') + err.message, 'error');
    } finally {
        if (cap === state) {
            setRunning(false);
            if (!ended) setState('reason_client', 'bg-secondary-lt', true);
        }
    }
}

function handle(state, ev) {
    if (cap !== state) return;
    const q = (s) => state.el.querySelector(s);
    switch (ev.t) {
    case 'start':
        state.id = ev.id;
        state.startedAt = Date.now();
        q('#cap-filter').textContent = ev.filter || t('firewall.capture.noFilter');
        setState('statusRunning', 'bg-green-lt');
        break;
    case 'pkt':
        addLines(ev.lines);
        break;
    case 'stats':
        q('#cap-stats').textContent = [
            t('firewall.capture.packets', { n: ev.packets }),
            ev.dropped ? t('firewall.capture.dropped', { n: ev.dropped }) : null,
            t('firewall.capture.elapsed', { s: ev.elapsed }),
        ].filter(Boolean).join(' · ');
        break;
    case 'end':
        state.pcap = !!ev.pcap;
        q('#cap-dl-pcap').disabled = !state.pcap;
        setState('reason_' + ev.reason, ev.reason === 'error' ? 'bg-red-lt' : 'bg-secondary-lt', true);
        if (ev.error) showToast(ev.error, 'error');
        break;
    default:
        break;   // hb
    }
}

/** Stop button: the server ends the stream with reason "stopped". */
async function stop() {
    if (!cap?.running) return;
    if (cap.id) {
        try {
            await apiDelete(`/firewall/capture/${cap.id}`);
            return;
        } catch { /* fall back to dropping the stream */ }
    }
    cap.controller?.abort();
}

/** Panel closed: dropping the stream stops tcpdump on the server. */
function stopStream() {
    if (cap?.running) cap.controller?.abort();
}

function setRunning(on) {
    const q = (s) => cap.el.querySelector(s);
    cap.running = on;
    q('#cap-start').disabled = on;
    q('#cap-stop').disabled = !on;
    q('#cap-pause').disabled = !on;
    q('#cap-form').querySelectorAll('input, select').forEach(x => { x.disabled = on; });
    if (on) {
        q('#cap-dl-pcap').disabled = true;
    } else if (cap.paused) {
        togglePause();   // show what was held back
    }
}

function setState(key, cls, ended = false) {
    const badge = cap.el.querySelector('#cap-state');
    badge.className = `badge ${cls}`;
    badge.textContent = ended
        ? t('firewall.capture.statusEnded', { reason: t('firewall.capture.' + key) })
        : t('firewall.capture.' + key);
}

// ---------------------------------------------------------------------------
// Output
// ---------------------------------------------------------------------------

function addLines(lines) {
    cap.lines.push(...lines);
    if (cap.lines.length > KEPT_LINES) cap.lines.splice(0, cap.lines.length - KEPT_LINES);
    cap.el.querySelector('#cap-dl-text').disabled = false;
    if (cap.paused) {
        cap.pending.push(...lines);
        if (cap.pending.length > DOM_LINES) cap.pending.splice(0, cap.pending.length - DOM_LINES);
        updatePaused();
        return;
    }
    render(lines);
}

function render(lines) {
    const out = cap.el.querySelector('#cap-out');
    const term = cap.el.querySelector('#cap-search').value.trim().toLowerCase();
    const frag = document.createDocumentFragment();
    for (const line of lines) {
        const div = document.createElement('div');
        div.textContent = line;
        if (term && !line.toLowerCase().includes(term)) div.hidden = true;
        frag.appendChild(div);
    }
    out.appendChild(frag);
    while (out.childElementCount > DOM_LINES) out.firstElementChild.remove();
    if (cap.el.querySelector('#cap-autoscroll').checked) out.scrollTop = out.scrollHeight;
}

function togglePause() {
    cap.paused = !cap.paused;
    const btn = cap.el.querySelector('#cap-pause');
    btn.querySelector('span').textContent = t(cap.paused ? 'firewall.capture.resume' : 'firewall.capture.pause');
    btn.querySelector('i').className = `ti ${cap.paused ? 'ti-player-play' : 'ti-player-pause'} me-1`;
    if (!cap.paused && cap.pending.length) {
        const held = cap.pending;
        cap.pending = [];
        render(held);
    }
    updatePaused();
}

function updatePaused() {
    cap.el.querySelector('#cap-paused').textContent = cap.paused
        ? t('firewall.capture.paused', { n: cap.pending.length }) : '';
}

function applySearch() {
    const term = cap.el.querySelector('#cap-search').value.trim().toLowerCase();
    for (const div of cap.el.querySelector('#cap-out').children) {
        div.hidden = !!term && !div.textContent.toLowerCase().includes(term);
    }
}

// ---------------------------------------------------------------------------
// Downloads
// ---------------------------------------------------------------------------

function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function stamp() {
    return new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
}

function downloadText() {
    saveBlob(new Blob([cap.lines.join('\n') + '\n'], { type: 'text/plain' }), `capture-${stamp()}.txt`);
}

async function downloadPcap() {
    if (!cap?.id || !cap.pcap) return;
    try {
        const resp = await apiFetch(`/firewall/capture/${cap.id}/pcap`, { method: 'GET' });
        if (!resp.ok) {
            const body = await resp.json().catch(() => ({}));
            throw new Error(_extractDetail(body));
        }
        const name = /filename="?([^";]+)"?/.exec(resp.headers.get('Content-Disposition') || '')?.[1]
            || `capture-${stamp()}.pcap`;
        saveBlob(await resp.blob(), name);
    } catch (err) {
        showToast(t('common.errorPrefix') + err.message, 'error');
    }
}

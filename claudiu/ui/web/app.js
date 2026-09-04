"use strict";
/* ClaudIU web View. Talks ONLY the UI protocol (docs/UI-PROTOCOL.md).
   Multi-session: one Session object per tab; the status strip, controls
   and composer always reflect the ACTIVE session. */

const $ = (sel, root = document) => root.querySelector(sel);
const sessions = new Map();   // sid -> Session
let active = null;            // Session
let profiles = [];

async function api(path, opts = {}) {
  const resp = await fetch(path, {headers: {"Content-Type": "application/json"},
                                  ...opts});
  if (!resp.ok) {
    let detail = "";
    try { const j = await resp.json(); detail = j.error || j.install_hint || ""; } catch (e) {}
    throw new Error(`${path}: ${resp.status} ${detail}`.trim());
  }
  return resp.json();
}

/* ---------------- launcher ---------------- */

async function initLauncher() {
  ({profiles} = await api("/api/profiles"));
  const sel = $("#profile");
  for (const p of profiles) {
    const o = document.createElement("option");
    o.value = p.id;
    o.textContent = p.name + (p.install_ok ? "" : " (adapter missing)");
    o.disabled = !p.install_ok;
    sel.append(o);
  }
  sel.onchange = () => {
    const p = profiles.find(x => x.id === sel.value);
    const items = (p ? p.caveats : []).map(c => {
      const li = document.createElement("li"); li.textContent = c.text;
      return li;
    });
    // which runtime the adapter will be pointed at (profile env_resolve)
    for (const [k, v] of Object.entries((p && p.env_resolved) || {})) {
      const li = document.createElement("li");
      li.className = "runtime";
      li.textContent = `runtime: ${k} → ${v}`;
      items.push(li);
    }
    $("#caveats").replaceChildren(...items);
  };
  sel.onchange();
  $("#start").onclick = () => startSession(null);
  $("#refresh-recent").onclick = loadRecent;
  $("#tab-add").onclick = showLauncher;
  // the last directory a session was started in (this browser only)
  try {
    const last = localStorage.getItem(CWD_KEY);
    if (last && !$("#cwd").value) $("#cwd").value = last;
    const think = localStorage.getItem(THINK_KEY);
    if (think) $("#thinking").value = think;
  } catch (e) {}
  initPicker();
  await restoreSessions();
}

/* The sessions live in the SERVER, not the page: a reload (or a second
   browser) must find the ones already running instead of stranding them.
   Attaching replays every event the session has emitted. */
async function restoreSessions() {
  let live = [];
  try {
    ({sessions: live} = await api("/api/sessions"));
  } catch (e) { return; }
  let last = null;
  let wanted = null;
  try { wanted = sessionStorage.getItem(ACTIVE_KEY); } catch (e) {}
  for (const info of live) {
    if (sessions.has(info.id)) continue;
    const S = new Session(info.id, info.profile, info.cwd);
    if (info.title) S.title = info.title;
    sessions.set(info.id, S);
    S.connect();
    last = S;
    if (info.id === wanted) last = S;
  }
  const target = (wanted && sessions.get(wanted)) || last;
  if (target && !active) activate(target);
}

/* ---------------- folder picker ----------------
   A page cannot learn an absolute path from the OS folder dialog, so the
   server lists directories (GET /api/dirs) and the dialog walks them. */

const THINK_KEY = "claudiu.thinking";
const CWD_KEY = "claudiu.cwd";

async function browseTo(path) {
  const dlg = $("#dirpick");
  let data;
  try {
    data = await api("/api/dirs?path=" + encodeURIComponent(path || ""));
  } catch (e) {
    if (path) return browseTo("");        // typed path is not a directory
    $("#dirpick-error").textContent = e.message;
    $("#dirpick-error").hidden = false;
    return;
  }
  $("#dirpick-error").hidden = true;
  dlg.dataset.path = data.path;
  dlg.dataset.parent = data.parent || "";
  $("#dirpick-path").textContent = data.path;
  $("#dirpick-up").disabled = !data.parent;
  $("#dirpick-roots").replaceChildren(...data.roots.map(r => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = r;
    b.onclick = () => browseTo(r);
    return b;
  }));
  const list = $("#dirpick-list");
  if (!data.dirs.length) { list.replaceChildren(li("(no subfolders)")); return; }
  list.replaceChildren(...data.dirs.map(d => {
    const item = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button"; b.textContent = d.name; b.dataset.name = d.name;
    b.title = d.name;                   // the column may ellipsize it
    b.onclick = () => browseTo(d.path);
    item.append(b);
    return item;
  }));
  list.scrollTop = 0;
}

function initPicker() {
  const dlg = $("#dirpick");
  $("#browse").onclick = () => {
    dlg.showModal();
    browseTo($("#cwd").value.trim());
  };
  $("#dirpick-up").onclick = () => {
    if (dlg.dataset.parent) browseTo(dlg.dataset.parent);
  };
  $("#dirpick-cancel").onclick = () => dlg.close();
  $("#dirpick-use").onclick = () => {
    if (dlg.dataset.path) $("#cwd").value = dlg.dataset.path;
    dlg.close();
    $("#cwd").focus();
  };
}

async function loadRecent() {
  const cwd = $("#cwd").value.trim();
  const list = $("#recent-list");
  $("#recent").hidden = false;
  if (!cwd) { list.replaceChildren(li("pick a project directory first")); return; }
  list.replaceChildren(li("looking…"));
  try {
    const data = await api(`/api/profiles/${$("#profile").value}/sessions?cwd=` +
                           encodeURIComponent(cwd));
    if (data.error) list.replaceChildren(li(`not available: ${data.error}`));
    else if (!data.sessions.length) list.replaceChildren(li("none found"));
    else list.replaceChildren(...data.sessions.map(s => {
      const item = li(`${s.title || "(untitled)"} — ${s.sessionId}` +
                      (s.updatedAt ? ` · ${s.updatedAt}` : ""));
      const b = document.createElement("button");
      b.textContent = "Resume";
      b.dataset.resume = s.sessionId;
      // resume in the directory the AGENT recorded for that session
      b.onclick = () => startSession(s.sessionId, s.cwd || cwd);
      item.prepend(b);
      return item;
    }));
  } catch (e) {
    list.replaceChildren(li(`error: ${e.message}`));
  }
}

function li(text) {
  const el = document.createElement("li"); el.textContent = text; return el;
}

async function startSession(resume, resumeCwd) {
  const profile = $("#profile").value;
  const cwd = (resume && resumeCwd) ? resumeCwd : $("#cwd").value.trim();
  if (resume && resumeCwd) $("#cwd").value = resumeCwd;
  if (!cwd) { alertBanner("pick a project directory first"); return; }
  const thinking = $("#thinking").value;
  try { localStorage.setItem(THINK_KEY, thinking); } catch (e) {}
  // Session-CREATION options: thinking cannot be changed later over ACP.
  const client_options = {
    summarized: {thinking: {type: "adaptive", display: "summarized"}},
    omitted: {thinking: {type: "adaptive", display: "omitted"}},
    off: {thinking: {type: "disabled"}},
  }[thinking] || {};
  const body = JSON.stringify({profile, cwd, resume, client_options});
  let id;
  try {
    ({id} = await api("/api/sessions", {method: "POST", body}));
  } catch (e) {
    alertBanner(e.message);
    return;
  }
  try { localStorage.setItem(CWD_KEY, cwd); } catch (e) {}
  const S = new Session(id, profile, cwd);
  sessions.set(id, S);
  activate(S);
  S.connect();
}

function alertBanner(text) {
  const ul = $("#caveats");
  const el = li("⚠ " + text);
  el.className = "error";
  ul.prepend(el);
}

/* ---------------- tabs ---------------- */

function showLauncher() {
  active = null;
  $("#launcher").hidden = false;
  $("#workspace").hidden = true;
  for (const S of sessions.values()) S.tab.classList.remove("active");
  $("#tab-add").classList.add("active");
}

const ACTIVE_KEY = "claudiu.active";

function activate(S) {
  active = S;
  try { sessionStorage.setItem(ACTIVE_KEY, S.sid); } catch (e) {}
  $("#launcher").hidden = true;
  $("#workspace").hidden = false;
  $("#tab-add").classList.remove("active");
  for (const other of sessions.values()) {
    other.pane.hidden = other !== S;
    other.tab.classList.toggle("active", other === S);
  }
  S.renderAll();
  $("#prompt-input").focus();
}

function closeSession(S) {
  S.closing = true;                    // a pending retry must not revive it
  fetch(`/api/sessions/${S.sid}`, {method: "DELETE"}).catch(() => {});
  if (S.ws) { S.ws.onclose = null; S.ws.close(); }
  S.pane.remove();
  S.tab.remove();
  sessions.delete(S.sid);
  if (active === S) {
    const next = sessions.values().next().value;
    if (next) activate(next); else showLauncher();
  }
}

document.addEventListener("keydown", (e) => {
  if (e.altKey && /^[1-9]$/.test(e.key)) {
    const S = [...sessions.values()][Number(e.key) - 1];
    if (S) { activate(S); e.preventDefault(); }
  } else if (e.altKey && e.key.toLowerCase() === "n") {
    showLauncher(); e.preventDefault();
  }
});

/* ---------------- session ---------------- */

class Session {
  constructor(sid, profile, cwd) {
    this.sid = sid; this.profile = profile; this.cwd = cwd;
    this.state = "starting"; this.title = null;
    this.agg = {}; this.tools = new Map(); this.queue = [];
    this.mode = {current: null, available: []};
    this.model = {current: null, available: []};
    this.config = []; this.plan = []; this.usage = null; this.commands = [];
    // Chips count what happened and KEEP it: clicking one opens the
    // drawer, it never throws the entries away (that is what "surfaced,
    // never dropped" means — 2026-09-04, Fabio: "it seems to go away").
    this.chips = {".drift-chip": {n: 0, label: "drift", lines: []},
                  ".anomaly-chip": {n: 0, label: "anomalies", lines: []}};
    this.anomalyOpen = false;
    this.turnStarted = null; this.lastActivity = null;
    this.stderr = [];             // adapter stderr lines: drawer, never inline
    this.stderrOpen = false;
    this.turnAgentNodes = [];     // agent text nodes of the running turn
    this.lastSeq = 0;             // resume cursor: highest seq we hold
    this.serverState = null;      // last state the SERVER reported
    this.retries = 0; this.closing = false;
    this.pane = document.createElement("div");
    this.pane.className = "pane";
    this.pane.dataset.session = sid;
    $("#conversation").append(this.pane);
    this.tab = document.createElement("button");
    this.tab.className = "tab";
    this.tab.onclick = () => activate(this);
    const x = document.createElement("span");
    x.className = "close"; x.textContent = "×"; x.title = "close session";
    x.onclick = (e) => { e.stopPropagation(); closeSession(this); };
    this.tabLabel = document.createElement("span");
    this.tab.append(this.tabLabel, x);
    $("#tab-add").before(this.tab);
    this.renderTab();
  }

  get isActive() { return active === this; }

  /* The socket drops for ordinary reasons — the server restarts, the laptop
     sleeps. The SESSION is still alive on the server, so the View comes back
     to it by itself, asking only for what it missed (`?after=`); before this,
     a dropped socket left the tab dead until someone thought to reload. */
  connect() {
    this.ws = new WebSocket(`ws://${location.host}/ws/sessions/${this.sid}` +
                            `?after=${this.lastSeq}`);
    this.ws.onopen = () => {
      this.retries = 0;
      // the replay starts after our cursor, so nothing re-announces the
      // state we were in: restore it ourselves.
      if (this.serverState) this.setState(this.serverState);
      while (this.queue.length) this.ws.send(this.queue.shift());
    };
    this.ws.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      if (typeof ev.seq === "number" && ev.seq > this.lastSeq)
        this.lastSeq = ev.seq;
      this.handle(ev);
    };
    this.ws.onclose = (e) => this.dropped(e);
  }

  dropped(e) {
    if (this.closing) return;              // we closed it on purpose
    const code = e && e.code;
    if (code === 4403 || code === 4404) {  // retrying cannot help either one
      this.setState(code === 4404 ? "closed" : "failed");
      this.note(code === 4404
        ? "this session is no longer on the server — reload the page to see "
          + "what is running"
        : "the server refused this connection — reload the page to sign in "
          + "again");
      return;
    }
    this.setState("reconnecting");
    const wait = Math.min(500 * 2 ** this.retries++, 15000);
    setTimeout(() => { if (!this.closing) this.connect(); }, wait);
  }

  /* A line about the client itself: it belongs to the harness lane, not to
     the conversation. */
  note(text) {
    this.breakAgg();
    this.addBlock("client_note", null, `— ${text} —`, "harness");
  }

  send(obj) {
    const wire = JSON.stringify(obj);
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(wire);
    else this.queue.push(wire);
  }

  /* ----- rendering of session-scoped chrome ----- */
  renderTab() {
    const base = this.cwd.replace(/[\\/]+$/, "").split(/[\\/]/).pop();
    this.tabLabel.textContent = this.title || `${this.profile} · ${base}`;
    this.tab.dataset.state = this.state;
    this.tab.title = `${this.profile} — ${this.cwd} — ${this.state}`;
  }

  renderAll() {
    this.renderTab();
    this.renderStatus();
    this.renderControls();
    this.renderPlan();
    this.renderStderrDrawer();
    showWorking(this, this.state === "turn");
  }

  renderStatus() {
    if (!this.isActive) return;
    $("#status .state").textContent = this.state;
    // Prefer the config option's display name ("Manual", "Fable") when the
    // agent offers mode/model that way; fall back to the legacy fields.
    const modeCfg = this.configCurrent("mode"), modelCfg = this.configCurrent("model");
    $("#status .mode").textContent = modeCfg ? modeCfg.name : (this.mode.current || "");
    const modelEl = $("#status .model");
    modelEl.textContent = modelCfg ? modelCfg.name : (this.model.current || "");
    modelEl.title = modelCfg && modelCfg.value !== modelCfg.name ? String(modelCfg.value) : "";
    const u = this.usage;
    const usageEl = $("#status .usage");
    if (u && u.size) {
      const pct = Math.round(100 * u.used / u.size);
      usageEl.textContent = `${fmtK(u.used)} / ${fmtK(u.size)} (${pct}%)` +
        (u.cost ? ` · ${fmtCost(u.cost)}` : "");
      usageEl.style.setProperty("--pct", pct + "%");
    } else usageEl.textContent = "";
    for (const [sel, c] of Object.entries(this.chips)) {
      const chip = $("#status " + sel);
      chip.hidden = c.n === 0;
      chip.textContent = `${c.label} (${c.n})`;
      chip.title = "click to read them";
      chip.onclick = () => {
        this.anomalyOpen = !this.anomalyOpen;
        this.renderAnomalyDrawer();
      };
    }
    const sc = $("#status .stderr-chip");
    sc.hidden = this.stderr.length === 0;
    sc.textContent = `log (${this.stderr.length})`;   // stderr = diagnostics, not errors
    sc.onclick = () => { this.stderrOpen = !this.stderrOpen; this.renderStderrDrawer(); };
    $("#send").disabled = this.state !== "ready";
    $("#cancel").hidden = this.state !== "turn";
  }

  renderStderrDrawer() {
    if (!this.isActive) return;
    this.renderAnomalyDrawer();
    const d = $("#stderr-drawer");
    d.hidden = !this.stderrOpen || this.stderr.length === 0;
    $("pre", d).textContent = this.stderr.join("\n");
  }

  /* Current value of a config option, with its display name. */
  configCurrent(id) {
    const opt = this.config.find(o => o.id === id);
    if (!opt) return null;
    const hit = (opt.options || []).find(o => o.value === opt.currentValue);
    return {value: opt.currentValue,
            name: hit ? (hit.name || String(hit.value)) : String(opt.currentValue)};
  }

  renderControls() {
    if (!this.isActive) return;
    // Newer agents offer mode/model as config options too: the config option
    // wins and the legacy select hides — never two controls for one thing.
    const cfgIds = new Set(this.config.map(o => o.id));
    fillSelect($("#mode"), cfgIds.has("mode") ? [] :
               this.mode.available.map(m => [m.id, m.name || m.id, m.description]),
               this.mode.current);
    fillSelect($("#model"), cfgIds.has("model") ? [] :
               this.model.available.map(m => [m.modelId, m.name || m.modelId, m.description]),
               this.model.current);
    const box = $("#config-options");
    box.replaceChildren(...this.config.map(opt => {
      const wrap = document.createElement("label");
      wrap.className = "config-option";
      wrap.title = opt.description || "";
      wrap.textContent = opt.name + " ";
      if (opt.type === "boolean") {
        const cb = document.createElement("input");
        cb.type = "checkbox"; cb.checked = !!opt.currentValue;
        cb.dataset.config = opt.id;
        cb.onchange = () => this.send({cmd: "set_config_option",
                                       config: opt.id, value: cb.checked});
        wrap.append(cb);
      } else {
        const sel = document.createElement("select");
        sel.dataset.config = opt.id;
        for (const o of opt.options || []) {
          const el = document.createElement("option");
          el.value = o.value; el.textContent = o.name || o.value;
          if (o.description) el.title = o.description;
          sel.append(el);
        }
        sel.value = opt.currentValue;
        sel.onchange = () => this.send({cmd: "set_config_option",
                                       config: opt.id, value: sel.value});
        wrap.append(sel);
      }
      return wrap;
    }));
  }

  renderPlan() {
    if (!this.isActive) return;
    $("#plan").hidden = this.plan.length === 0;
    $("#plan").replaceChildren(...this.plan.map(e => {
      const row = document.createElement("div");
      row.textContent = `${e.status || "?"} — ${e.content || ""}`;
      return row;
    }));
  }

  setState(s) {
    this.state = s;
    if (s === "turn") this.turnStarted = Date.now();
    this.renderTab();
    this.renderStatus();
    showWorking(this, s === "turn");
  }

  touch(text) {
    this.lastActivity = {ts: Date.now(), text};
  }

  /* ----- conversation blocks ----- */
  /* Which lane a row belongs to; rows with no lane (the agent's answer and
     your own prompts) can never be switched off. */
  addBlock(kind, role, text, lane) {
    const key = kind + ":" + (role || "");
    const rich = kind === "message_chunk" && role === "agent";   // markdown-lite
    if (this.agg.currentKey === key && this.agg.node) {
      if (text) { const m = $(".marker", this.agg.node); if (m) m.remove(); }
      const node = this.agg.node;
      node.rawText = (node.rawText || "") + text;
      // Only the unfinished tail is re-rendered. Re-rendering the whole
      // message on every chunk was quadratic AND wiped out any selection
      // the reader had made inside it, so an answer could not be copied
      // until the turn ended (audit 2026-09-04).
      if (rich) growRich(node, $(".text", node));
      else $(".text", node).append(text);
      return node;
    }
    const div = document.createElement("div");
    div.dataset.kind = kind;
    if (role) div.dataset.role = role;
    if (lane) div.dataset.lane = lane;
    const span = document.createElement("span");
    span.className = "text";
    div.rawText = text;
    if (rich) {
      span.append(document.createElement("span"),      // settled
                  document.createElement("span"));     // still arriving
      span.children[0].className = "settled";
      span.children[1].className = "arriving";
      div.stableEnd = 0; div.safeEnd = 0; div.scanned = 0;
      div.fenceOpen = false;
      growRich(div, span);
    } else span.textContent = text;
    div.append(span);
    this.appendRow(div);
    this.agg.currentKey = key;
    this.agg.node = div;
    if (rich) this.turnAgentNodes.push(div);
    return div;
  }

  /* Agent text produced BEFORE a tool call is a step, not the answer. */
  markInterim() {
    for (const n of this.turnAgentNodes) n.dataset.interim = "1";
  }

  appendRow(node) {
    const working = $(".working", this.pane);
    if (working) working.before(node); else this.pane.append(node);
    // Only follow when the reader is already at the bottom: yanking the view
    // down while they read further up is what made scrolling unusable.
    if (this.isActive) scrollIfFollowing();
  }

  breakAgg() { this.agg.currentKey = null; }

  /* ----- event dispatch ----- */
  handle(ev) {
    const d = ev.data;
    if (ev.kind !== "session_state") this.touch(summarize(ev));
    switch (ev.kind) {
      case "session_state":
        if (d.state === "turn") this.turnAgentNodes = [];
        this.serverState = d.state;
        this.setState(d.state); break;
      case "replay_truncated":
        // The server's replay buffer is bounded; the JSONL record is not.
        this.note(`events ${d.from_seq}–${d.to_seq} are not replayed here `
                  + "(the server keeps a bounded buffer; the session record "
                  + "on disk has them all)");
        break;
      case "message_chunk": {
        const node = this.addBlock("message_chunk", d.role, d.text,
          d.role === "thought" ? "thinking"
            : d.parent_tool_call_id ? "subagents" : null);
        if (d.role === "thought" && !$(".text", node).textContent &&
            !$(".marker", node)) {
          const m = document.createElement("span");
          m.className = "marker"; m.textContent = "· thinking ·";
          node.prepend(m);
        }
        break;
      }
      case "tool_call":
      case "tool_call_update":
        this.breakAgg(); this.markInterim(); this.renderTool(ev); break;
      case "plan": this.plan = d.entries; this.renderPlan(); break;
      case "commands": this.commands = d.commands; break;
      case "mode":
        if (d.available.length) this.mode.available = d.available;
        this.mode.current = d.current || this.mode.current;
        this.renderStatus(); this.renderControls(); break;
      case "model":
        if (d.available.length) this.model.available = d.available;
        this.model.current = d.current || this.model.current;
        this.renderStatus(); this.renderControls(); break;
      case "config_option": this.config = d.options; this.renderControls(); break;
      case "usage": this.usage = d; this.renderStatus(); break;
      case "rate_limit": recordRateLimit(d); break;
      case "session_info":
        if (d.title !== undefined) this.title = d.title;
        this.renderTab(); break;
      case "stderr": this.renderStderr(ev); break;
      case "permission_request": queuePermission(this, ev); break;
      case "permission_resolved": resolvePermission(this, d.request); break;
      case "elicitation_request": queueElicitation(this, ev); break;
      case "elicitation_resolved": {
        const titles = fieldTitles(this, d.request);
        closeElicitation(this, d.request);
        this.breakAgg();
        this.addBlock("elicitation_resolved", null,
          d.action === "accept"
            ? `\u2014 you answered: ${describeAnswer(d.content, titles)} \u2014`
            : `\u2014 question skipped${d.source === "failsafe"
                ? " (no answer in time)" : ""} \u2014`, "events");
        break;
      }
      case "turn_ended":
        this.breakAgg();
        this.addBlock("turn_ended", null, `— turn ended (${d.stop_reason}) —`,
          "events");
        break;
      case "fs_request":
        this.breakAgg();
        this.addBlock("fs_request", null,
          `agent ${d.op} ${d.path} ${d.allowed ? "✓" : "✗ blocked"}`,
          "events");
        break;
      case "drift": this.bumpChip(".drift-chip", d.flags.join("\n")); break;
      case "anomaly":
        this.bumpChip(".anomaly-chip", `${d.category}: ${d.detail}`);
        this.breakAgg();
        addRawToggle(this.addBlock("anomaly", null,
          `⚠ ${d.category}: ${d.detail}`, "harness"), ev);
        break;
      case "unrecognized":
        this.breakAgg();
        addRawToggle(this.addBlock("unrecognized", null,
          `unrecognized protocol data (${d.why})`, "harness"), ev);
        break;
      default:
        this.breakAgg();
        addRawToggle(this.addBlock("unrecognized", null,
          `unknown event kind ${ev.kind}`, "harness"), ev);
    }
  }

  bumpChip(sel, detail) {
    const c = this.chips[sel];
    c.n += 1;
    c.lines.push(`${new Date().toLocaleTimeString()}  ${detail}`);
    this.renderStatus();
    this.renderAnomalyDrawer();
  }

  /* Everything both chips have collected, in one drawer. Dismissing is an
     explicit act with its own button, never a side effect of looking. */
  renderAnomalyDrawer() {
    if (!this.isActive) return;
    const lines = [...this.chips[".anomaly-chip"].lines,
                   ...this.chips[".drift-chip"].lines];
    const d = $("#anomaly-drawer");
    d.hidden = !this.anomalyOpen || lines.length === 0;
    $("pre", d).textContent = lines.join("\n");
    $("#anomaly-clear").onclick = () => {
      for (const c of Object.values(this.chips)) { c.n = 0; c.lines = []; }
      this.anomalyOpen = false;
      this.renderStatus();
      this.renderAnomalyDrawer();
    };
  }

  renderStderr(ev) {
    // Recorded by the engine; shown OUT of the conversation flow: a chip
    // with the count in the status strip, a drawer on click. Never dropped.
    this.stderr.push(ev.data.line);
    this.renderStatus();
    this.renderStderrDrawer();
  }

  /* Tool calls: one row per toolCallId, updates merge into it. */
  renderTool(ev) {
    const d = ev.data;
    const id = d.toolCallId || `anon-${ev.seq}`;
    let entry = this.tools.get(id);
    if (!entry) {
      const node = document.createElement("div");
      node.dataset.kind = "tool_call";
      node.dataset.toolCall = id;
      node.dataset.lane = "tools";
      const head = document.createElement("div");
      head.className = "tool-head";
      const det = document.createElement("details");
      const sum = document.createElement("summary");
      sum.textContent = "details";
      const body = document.createElement("div");
      body.className = "tool-body";
      det.append(sum, body);
      node.append(head, det);
      addRawToggle(node, ev);
      this.appendRow(node);
      entry = {node, head, body, data: {}};
      this.tools.set(id, entry);
    }
    for (const [k, v] of Object.entries(d)) {
      if (v !== null && v !== undefined && k !== "sessionUpdate") entry.data[k] = v;
    }
    const t = entry.data;
    // A tool call stamped with a parent belongs to a subagent, and so does
    // the Task row that owns it (marked retroactively, since the parent row
    // arrives first and only its children reveal the relationship).
    const parent = (t._meta && t._meta.claudeCode
                    && t._meta.claudeCode.parentToolUseId) || null;
    const toolName = (t._meta && t._meta.claudeCode
                      && t._meta.claudeCode.toolName) || "";
    if (parent || toolName === "Task") entry.node.dataset.lane = "subagents";
    if (parent) {
      const owner = this.tools.get(parent);
      if (owner) owner.node.dataset.lane = "subagents";
    }
    entry.head.textContent =
      `${t.kind || "tool"} · ${t.title || id} [${t.status || "pending"}]`;
    entry.node.dataset.status = t.status || "pending";
    entry.body.replaceChildren(...(t.content || []).map(renderToolContent));
    if (t.locations && t.locations.length) {
      const loc = document.createElement("div");
      loc.className = "locations";
      loc.textContent = t.locations.map(l => l.path + (l.line ? `:${l.line}` : "")).join(", ");
      entry.body.append(loc);
    }
    if (entry.body.children.length && expandTools()) {
      entry.node.querySelector("details").open = true;
    }
  }
}

/* ---------------- markdown-lite for agent text ----------------
   Fenced code, headings, **bold**, *em*, `code`, [text](url). Built from
   DOM nodes only — the text is never interpreted as HTML. */
/* The text a chunk completes never changes again, so it is rendered once
   into `.settled` and left alone; only `.arriving` is rebuilt. A line ends
   the settled part only when it is OUTSIDE a code fence — splitting inside
   one would render half a code block as prose. The fence state is carried
   forward, so each character is scanned once. */
function growRich(node, el) {
  const raw = node.rawText;
  let i = node.scanned;
  for (;;) {
    const nl = raw.indexOf("\n", i);
    if (nl < 0) break;                        // no complete line left
    if (/^\s*```/.test(raw.slice(i, nl))) node.fenceOpen = !node.fenceOpen;
    i = nl + 1;
    if (!node.fenceOpen) node.safeEnd = i;
  }
  node.scanned = i;
  const settled = el.children[0], arriving = el.children[1];
  if (node.safeEnd > node.stableEnd) {
    settled.append(...richNodes(raw.slice(node.stableEnd, node.safeEnd)));
    node.stableEnd = node.safeEnd;
  }
  arriving.replaceChildren(...richNodes(raw.slice(node.stableEnd)));
}

function renderRich(el, text) {
  el.replaceChildren(...richNodes(text));
}

function richNodes(text) {
  const el = document.createDocumentFragment();
  const lines = text.split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const fence = line.match(/^\s*```(\w*)\s*$/);
    if (fence) {
      const buf = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) buf.push(lines[i++]);
      if (i < lines.length) i++;                     // closing fence
      const pre = document.createElement("pre");
      pre.className = "code";
      if (fence[1]) pre.dataset.lang = fence[1];
      pre.textContent = buf.join("\n");
      el.append(pre);
      continue;
    }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      const s = document.createElement("span");
      s.className = "md-h";
      s.append(...inlineRich(h[2]));
      el.append(s);
    } else {
      el.append(...inlineRich(line));
    }
    i++;
    if (i < lines.length) el.append("\n");
  }
  return [...el.childNodes];
}

function inlineRich(s) {
  const out = [];
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\([^)\s]+\))/g;
  let last = 0, m;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index));
    const tok = m[0];
    let node;
    if (m[1]) { node = document.createElement("code"); node.textContent = tok.slice(1, -1); }
    else if (m[2]) { node = document.createElement("strong"); node.className = "hl"; node.textContent = tok.slice(2, -2); }
    else if (m[3]) { node = document.createElement("em"); node.textContent = tok.slice(1, -1); }
    else {
      const mm = tok.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
      node = document.createElement("span");
      node.className = "md-link"; node.textContent = mm[1]; node.title = mm[2];
    }
    out.push(node);
    last = m.index + tok.length;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}

function fmtK(n) { return n >= 1000 ? (n / 1000).toFixed(n >= 100000 ? 0 : 1) + "k" : String(n); }
function fmtCost(c) {
  const a = Number(c.amount);
  if (!isFinite(a)) return `${c.amount} ${c.currency || ""}`.trim();
  return `${a >= 0.01 ? a.toFixed(2) : a.toFixed(4)} ${c.currency || ""}`.trim();
}

function fillSelect(sel, pairs, current) {
  if (pairs.length) {
    sel.hidden = false;
    sel.replaceChildren(...pairs.map(([v, label, title]) => {
      const o = document.createElement("option");
      o.value = v; o.textContent = label;
      if (title) o.title = title;      // long descriptions live in the tooltip
      return o;
    }));
  } else sel.hidden = true;
  if (current !== null && current !== undefined) sel.value = current;
  const chosen = sel.selectedOptions[0];
  if (chosen && chosen.title) sel.title = chosen.title;
}

function summarize(ev) {
  const d = ev.data;
  switch (ev.kind) {
    case "message_chunk": return d.role === "thought" ? "thinking" : "agent text";
    case "tool_call": case "tool_call_update":
      return `${ev.kind}: ${d.title || d.toolCallId || ""}`.trim();
    case "stderr": return "adapter stderr";
    case "permission_request": return "waiting for your approval";
    case "elicitation_request": return "waiting for your answer";
    default: return ev.kind;
  }
}

/* ---------------- tool content & diffs ---------------- */

function renderToolContent(item) {
  if (item.type === "diff") return renderDiff(item);
  if (item.type === "content" && item.content && item.content.type === "text") {
    const pre = document.createElement("pre");
    pre.className = "tool-text";
    pre.textContent = item.content.text;
    return pre;
  }
  const pre = document.createElement("pre");
  pre.className = "tool-text";
  pre.textContent = JSON.stringify(item, null, 2);
  return pre;
}

function renderDiff(item) {
  const box = document.createElement("div");
  box.className = "diff";
  const path = document.createElement("div");
  path.className = "diff-path";
  path.textContent = item.path || "";
  box.append(path);
  const oldLines = item.oldText == null ? [] : item.oldText.split("\n");
  const newLines = (item.newText || "").split("\n");
  for (const [op, text] of lineDiff(oldLines, newLines)) {
    const row = document.createElement("div");
    row.className = op === "+" ? "add" : op === "-" ? "del" : "ctx";
    row.textContent = `${op} ${text}`;
    box.append(row);
  }
  return box;
}

// Line-level LCS diff; falls back to whole-file replace when too large.
function lineDiff(a, b) {
  if (a.length * b.length > 250000) {
    return [...a.map(l => ["-", l]), ...b.map(l => ["+", l])];
  }
  const n = a.length, m = b.length;
  const dp = Array.from({length: n + 1}, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1
                               : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push([" ", a[i]]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push(["-", a[i]]); i++; }
    else { out.push(["+", b[j]]); j++; }
  }
  while (i < n) out.push(["-", a[i++]]);
  while (j < m) out.push(["+", b[j++]]);
  return out;
}

/* ---------------- raw frame escape hatch ---------------- */

function addRawToggle(node, ev) {
  const btn = document.createElement("button");
  btn.className = "raw-toggle";
  btn.textContent = "{}";
  btn.title = `raw frame #${ev.raw_ref ?? "-"}`;
  btn.onclick = () => {
    let pre = $("pre.raw", node);
    if (pre) { pre.remove(); return; }
    pre = document.createElement("pre");
    pre.className = "raw";
    pre.textContent = JSON.stringify(ev, null, 2);
    node.append(pre);
  };
  node.append(btn);
}

/* ---------------- liveness: the working row ---------------- */

let workingTimer = null;

function showWorking(S, on) {
  const existing = $("#working");
  if (!S.isActive) return;
  if (!on) {
    if (existing) existing.remove();
    if (workingTimer) { clearInterval(workingTimer); workingTimer = null; }
    return;
  }
  if (existing && existing.parentElement === S.pane) return;
  if (existing) existing.remove();
  const w = document.createElement("div");
  w.id = "working";
  w.className = "working";
  const render = () => {
    const secs = Math.round((Date.now() - (S.turnStarted || Date.now())) / 1000);
    const la = S.lastActivity;
    const ago = la ? Math.round((Date.now() - la.ts) / 1000) : null;
    w.textContent = `agent working… ${secs}s` +
      (la ? ` · last activity ${ago}s ago (${la.text})` : " · waiting for first event") +
      " — Stop cancels the turn";
    w.classList.toggle("stale", ago !== null && ago > 60);
  };
  render();
  if (workingTimer) clearInterval(workingTimer);
  workingTimer = setInterval(render, 1000);
  S.pane.append(w);
  scrollIfFollowing();
}

/* ---------------- the account's limits ----------------

   Rate limits belong to the ACCOUNT, not to a session: whichever session
   hears about a window, the panel at the top right shows the latest state
   of each one. Windows nobody reported are simply not shown — this View
   never invents a number it was not told. */

const WINDOW_LABELS = {
  five_hour: "5h",
  seven_day: "7d",
};

/* The agent decides which windows exist — per-model ones appear and
   disappear as the account changes (Fabio has a Fable meter in the desktop
   app). So the label is DERIVED from the name rather than looked up in a
   list we would have to keep guessing at: `seven_day_fable` reads "7d
   Fable" the first time it ever arrives. */
function windowLabel(type) {
  for (const [prefix, short] of Object.entries(WINDOW_LABELS)) {
    if (type === prefix) return short;
    if (!type.startsWith(prefix + "_")) continue;
    const words = type.slice(prefix.length + 1).split("_")
      .filter(w => w !== "included");
    return short + " " + words.map(w => w === "overage" ? "+credits"
      : w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
  }
  return type.replace(/_/g, " ");
}
const limitWindows = new Map();     // window name -> latest reading

/* The agent reports its windows in `unifiedWindows`
   ({utilization: 0..1, resetsAt}) and keeps the account-wide status and the
   credits fields at the top level; a simpler payload carries a single
   window as top-level `rateLimitType` + `utilization`. Both shapes are
   rendered, neither is invented.

   2026-09-04: only the top-level shape was read, and the live payload has
   no top-level `utilization` at all — so the panel showed a single chip,
   for a single window, with no number in it. */
function recordRateLimit(d) {
  d = d || {};
  const windows = (typeof d.unifiedWindows === "object" &&
                   d.unifiedWindows) || null;
  const entries = windows && Object.keys(windows).length
    ? Object.entries(windows).map(([type, w]) => [type, w || {}])
    : [[d.rateLimitType || "unknown", d]];
  const credits = creditsNote(d);
  for (const [type, w] of entries) {
    limitWindows.set(type, {
      utilization: typeof w.utilization === "number" ? w.utilization
                                                     : d.utilization,
      resetsAt: w.resetsAt || d.resetsAt,
      status: d.status, credits, raw: d,
    });
  }
  renderAccount();
}

function fmtReset(epochSeconds) {
  if (!epochSeconds) return "";
  const when = new Date(epochSeconds * 1000);
  const mins = Math.round((when - Date.now()) / 60000);
  if (mins <= 0) return "resets now";
  if (mins < 60) return `resets in ${mins} min`;
  const hours = Math.floor(mins / 60);
  return hours < 24 ? `resets in ${hours} h ${mins % 60} min`
                    : `resets ${when.toLocaleString()}`;
}

/* Short on the chip (it sits in a corner), spelled out in the tooltip.
   EC = extra credits. The agent reports the STATE of the credits and never
   a balance — there is no amount, in any currency, anywhere in the
   rate-limit payload — so none is shown. */
function creditsNote(d) {
  if (d.isUsingOverage || d.overageInUse) return "EC in use";
  if (d.overageDisabledReason === "out_of_credits") return "EC out";
  if (d.canUserPurchaseCredits) return "EC available";
  if (d.overageStatus) return `EC ${d.overageStatus}`;
  return "";
}

function renderAccount() {
  const el = $("#account");
  const entries = [...limitWindows.entries()];
  el.hidden = entries.length === 0;
  el.replaceChildren(...entries.map(([type, w]) => {
    const span = document.createElement("span");
    span.className = "window";
    span.dataset.window = type;
    if (w.status) span.dataset.status = w.status;
    const label = windowLabel(type);
    // `utilization` is a FRACTION of the window: 0.55 is 55 %.
    const pct = typeof w.utilization === "number"
      ? Math.round(w.utilization * 100) + "%" : "—";
    const b = document.createElement("b");
    b.textContent = pct;
    span.append(label + " ", b);
    if (w.credits) span.append(" · " + w.credits);
    span.title = [`${label}: ${pct} used`, `status: ${w.status || "?"}`,
                  fmtReset(w.resetsAt),
                  w.credits && `${w.credits}  (EC = extra credits; the agent `
                    + `reports their state, never a balance)`,
                  "", "as the agent reported it:",
                  JSON.stringify(w.raw, null, 1)]
      .filter(v => v === "" || Boolean(v)).join("\n");
    return span;
  }));
}

/* ---------------- following the bottom ----------------

   The conversation follows new rows only while the reader is AT the bottom.
   Scroll up and it stays put; a "jump to latest" button appears and puts
   you back in the stream. */

const FOLLOW_SLACK = 40;          // px from the bottom that still counts

function atBottom() {
  const el = $("#conversation");
  return el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_SLACK;
}

function scrollIfFollowing() {
  const el = $("#conversation");
  if (following) el.scrollTop = el.scrollHeight;
  renderJumpButton();
}

function renderJumpButton() {
  $("#jump-bottom").hidden = following;
}

let following = true;

function initFollow() {
  const el = $("#conversation");
  el.addEventListener("scroll", () => {
    following = atBottom();
    renderJumpButton();
  });
  $("#jump-bottom").onclick = () => {
    following = true;
    el.scrollTop = el.scrollHeight;
    renderJumpButton();
  };
  renderJumpButton();
}

/* ---------------- lanes (what the conversation shows) ----------------

   Five switches, applied to the conversation as a whole: a lane that is off
   is GONE from the page, not dimmed. The choice is remembered per browser. */

const LANES = [
  ["thinking", "the model's own summary of its reasoning"],
  ["tools", "tool calls made by the main agent"],
  ["subagents", "Task rows and everything a subagent did"],
  ["events", "turn separators, file access, answers you gave"],
  ["harness", "adapter log rows, anomalies, drift, unknown frames"],
];
const LANE_KEY = "claudiu.lanes";

function hiddenLanes() {
  try {
    return new Set(JSON.parse(localStorage.getItem(LANE_KEY) || "[]"));
  } catch (e) { return new Set(); }
}

function applyLanes(hidden) {
  const el = $("#conversation");
  for (const [lane] of LANES) el.classList.toggle("hide-" + lane, hidden.has(lane));
  for (const b of $("#lanes").children) {
    b.setAttribute("aria-pressed",
                   hidden.has(b.dataset.laneToggle) ? "false" : "true");
  }
  try { localStorage.setItem(LANE_KEY, JSON.stringify([...hidden])); } catch (e) {}
}

function initLanes() {
  const hidden = hiddenLanes();
  $("#lanes").replaceChildren(...LANES.map(([lane, title]) => {
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.laneToggle = lane;
    b.textContent = lane;
    b.title = title;
    b.onclick = () => {
      const now = hiddenLanes();
      if (now.has(lane)) now.delete(lane); else now.add(lane);
      applyLanes(now);
      scrollIfFollowing();
    };
    return b;
  }));
  applyLanes(hidden);
}

/* ---------------- permissions (modal, queued across sessions) ---------------- */

const permQueue = [];   // {S, ev}
let permOpen = null;

const KIND_ORDER = {allow_once: 0, reject_once: 1, reject_always: 2,
                    allow_always: 3};

function queuePermission(S, ev) {
  permQueue.push({S, ev});
  if (!permOpen) showNextPermission();
}

function resolvePermission(S, requestId) {
  if (permOpen && permOpen.S === S && permOpen.ev.data.request === requestId) {
    $("#permission").close();
    permOpen = null;
    showNextPermission();
  } else {
    const idx = permQueue.findIndex(p => p.S === S && p.ev.data.request === requestId);
    if (idx >= 0) permQueue.splice(idx, 1);
  }
}

function showNextPermission() {
  const next = permQueue.shift();
  if (!next) return;
  permOpen = next;
  const {S, ev} = next;
  $("#perm-session").textContent = sessions.size > 1 ? `— ${S.tabLabel.textContent}` : "";
  $("#perm-tool").textContent = JSON.stringify(ev.data.tool_call, null, 2);
  const warn = $("#perm-warning");
  const outside = ev.data.outside_boundary || [];
  if (outside.length) {
    warn.hidden = false;
    warn.textContent = "⚠ Touches paths OUTSIDE the project boundary — " +
      "shell commands are not confined by this client; your answer is " +
      "the only control:\n" + outside.join("\n");
  } else warn.hidden = true;
  const options = [...ev.data.options].sort((a, b) =>
    (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9));
  $("#perm-options").replaceChildren(...options.map((o, i) => {
    const b = document.createElement("button");
    b.dataset.option = o.optionId;
    b.dataset.kind = o.kind;
    b.textContent = `${i + 1}. ${o.name} (${o.kind})` +
      (o.kind === "allow_always" ? " — standing grant for this session" : "");
    b.onclick = () => S.send({cmd: "permission", request: ev.data.request,
                              option: o.optionId});
    return b;
  }));
  $("#permission").showModal();
}

$("#permission").addEventListener("cancel", (e) => e.preventDefault());

/* ---------------- elicitation (the agent's own questions) ----------------

   `elicitation/create`, form mode: the schema's properties become one
   fieldset each — a titled `oneOf`/`enum` string is a radio group, an array
   with `anyOf`/`enum` items is a checkbox group, a plain string is a text
   box (this is how the "Other" field arrives), booleans and numbers get
   their own controls. A property type this View does not understand is
   NEVER rendered as some other control: it is named and left out.        */

const elicQueue = [];   // {S, ev}
let elicOpen = null;
// "<sid>:<request>" -> {field: human title}. Kept from the request so the
// answered row can name the question ("Colour: Blue"), not the wire key.
// Keyed by SESSION too: request ids restart at 1 in every session, so two
// live sessions used to overwrite each other's titles (audit 2026-09-04).
const elicTitles = new Map();

function titleKey(S, requestId) { return `${S.sid}:${requestId}`; }

function fieldTitles(S, requestId) {
  const key = titleKey(S, requestId);
  const titles = elicTitles.get(key) || {};
  elicTitles.delete(key);
  return titles;
}

function queueElicitation(S, ev) {
  const props = (ev.data.schema && ev.data.schema.properties) || {};
  elicTitles.set(titleKey(S, ev.data.request), Object.fromEntries(
    Object.entries(props).map(([field, prop]) =>
      [field, (prop && prop.title) || field])));
  elicQueue.push({S, ev});
  if (!elicOpen) showNextElicitation();
}

function closeElicitation(S, requestId) {
  if (elicOpen && elicOpen.S === S && elicOpen.ev.data.request === requestId) {
    $("#elicitation").close();
    elicOpen = null;
    showNextElicitation();
  } else {
    const i = elicQueue.findIndex(p => p.S === S && p.ev.data.request === requestId);
    if (i >= 0) elicQueue.splice(i, 1);
  }
}

function enumOptions(prop) {
  // titled options (`oneOf` / `items.anyOf`) or bare `enum` strings
  const titled = prop.oneOf || (prop.items && prop.items.anyOf);
  if (Array.isArray(titled)) {
    return titled.map(o => ({value: o.const, title: o.title || o.const,
                             description: o.description}));
  }
  const bare = prop.enum || (prop.items && prop.items.enum);
  if (Array.isArray(bare)) return bare.map(v => ({value: v, title: v}));
  return null;
}

function choiceLabel(field, opt, type) {
  const label = document.createElement("label");
  const input = document.createElement("input");
  input.type = type;
  input.name = field;
  input.value = opt.value;
  label.append(input, document.createTextNode(" " + opt.title));
  if (opt.description) {
    const d = document.createElement("span");
    d.className = "opt-desc";
    d.textContent = " — " + opt.description;
    label.append(d);
  }
  return label;
}

function renderField(form, field, prop) {
  const box = document.createElement("fieldset");
  box.dataset.field = field;
  box.dataset.type = prop.type || "";
  const legend = document.createElement("legend");
  legend.textContent = prop.title || field;
  box.append(legend);
  if (prop.description) {
    const d = document.createElement("div");
    d.className = "field-desc";
    d.textContent = prop.description;
    box.append(d);
  }
  const options = enumOptions(prop);
  if (prop.type === "string" && options) {
    for (const o of options) box.append(choiceLabel(field, o, "radio"));
  } else if (prop.type === "array" && options) {
    for (const o of options) box.append(choiceLabel(field, o, "checkbox"));
  } else if (prop.type === "boolean") {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox"; input.dataset.field = field; input.name = field;
    input.checked = prop.default === true;
    label.append(input, document.createTextNode(" yes"));
    box.append(label);
  } else if (prop.type === "string" || prop.type === "number" ||
             prop.type === "integer") {
    const input = document.createElement("input");
    input.type = prop.type === "string" ? "text" : "number";
    input.dataset.field = field;
    if (prop.default !== undefined && prop.default !== null) {
      input.value = prop.default;
    }
    box.append(input);
  } else {
    const note = document.createElement("div");
    note.className = "unsupported";
    note.textContent = `this client cannot render a ${prop.type || "?"} ` +
      `field (${field}); it is left unanswered`;
    box.append(note);
  }
  form.append(box);
}

function collectAnswers(form) {
  const content = {};
  for (const box of form.querySelectorAll("fieldset")) {
    const field = box.dataset.field;
    if (box.dataset.type === "array") {
      const picked = [...box.querySelectorAll("input[type=checkbox]:checked")]
        .map(i => i.value);
      if (picked.length) content[field] = picked;
      continue;
    }
    const radio = box.querySelector("input[type=radio]:checked");
    if (radio) { content[field] = radio.value; continue; }
    const free = box.querySelector("input[data-field]");
    if (!free) continue;
    if (free.type === "checkbox") { content[field] = free.checked; continue; }
    const raw = free.value.trim();
    if (!raw) continue;
    content[field] = free.type === "number" ? Number(raw) : raw;
  }
  return content;
}

function describeAnswer(content, titles = {}) {
  const parts = Object.entries(content || {}).map(([k, v]) =>
    `${titles[k] || k}: ${Array.isArray(v) ? v.join(", ") : v}`);
  return parts.length ? parts.join(" · ") : "(nothing)";
}

function showNextElicitation() {
  const next = elicQueue.shift();
  if (!next) return;
  elicOpen = next;
  const {S, ev} = next;
  $("#elic-session").textContent =
    sessions.size > 1 ? `— ${S.tabLabel.textContent}` : "";
  $("#elic-message").textContent = ev.data.message || "";
  const form = $("#elic-form");
  form.replaceChildren();
  const props = (ev.data.schema && ev.data.schema.properties) || {};
  for (const [field, prop] of Object.entries(props)) {
    renderField(form, field, prop || {});
  }
  $("#elicitation").showModal();
}

$("#elic-submit").onclick = () => {
  if (!elicOpen) return;
  const {S, ev} = elicOpen;
  S.send({cmd: "elicitation", request: ev.data.request, action: "accept",
          content: collectAnswers($("#elic-form"))});
};
$("#elic-skip").onclick = () => {
  if (!elicOpen) return;
  const {S, ev} = elicOpen;
  S.send({cmd: "elicitation", request: ev.data.request, action: "decline"});
};
$("#elicitation").addEventListener("cancel", (e) => e.preventDefault());

/* ---------------- composer ---------------- */

const promptEl = $("#prompt-input");

/* The box is two rows until the text needs more, then grows to the CSS cap
   (30vh) and scrolls. A fixed three-row box ate a third of a short window. */
function sizeComposer() {
  promptEl.style.height = "auto";
  promptEl.style.height = Math.min(promptEl.scrollHeight + 2,
                                   Math.round(innerHeight * 0.3)) + "px";
}
promptEl.addEventListener("input", sizeComposer);
addEventListener("resize", sizeComposer);

function sendPrompt() {
  const text = promptEl.value.trim();
  if (!active || !text || active.state !== "ready") return;
  active.breakAgg();
  active.addBlock("message_chunk", "user", text);
  active.breakAgg();
  active.send({cmd: "prompt", text});
  promptEl.value = "";
  sizeComposer();
  const pal = $("#palette");
  if (pal) pal.hidden = true;
}

$("#send").onclick = sendPrompt;

/* View preference: tool results collapsed by default (like the terminal);
   the checkbox opens them all and persists per browser. */
function expandTools() {
  try { return localStorage.getItem("claudiu.expandTools") === "1"; } catch (e) { return false; }
}
function applyExpandTools(on) {
  try { localStorage.setItem("claudiu.expandTools", on ? "1" : "0"); } catch (e) {}
  for (const det of document.querySelectorAll('[data-kind="tool_call"] details')) {
    det.open = on && $(".tool-body", det).children.length > 0;
  }
}
const expandBox = $("#expand-tools");
expandBox.checked = expandTools();
expandBox.onchange = () => applyExpandTools(expandBox.checked);
$("#cancel").onclick = () => active && active.send({cmd: "cancel"});

/* Archiving is the session publisher's job, not ours: the server runs the
   installed tool and we report exactly what it said. */
$("#archive").onclick = async () => {
  if (!active) return;
  const note = $("#archive-note");
  note.hidden = false;
  note.className = "";
  note.textContent = "archiving…";
  try {
    const r = await api(`/api/sessions/${active.sid}/archive`,
                        {method: "POST", body: "{}"});
    note.textContent = r.output && r.output.length
      ? "archived:\n" + r.output.join("\n")
      : "the archiver reported no output";
  } catch (e) {
    note.className = "error";
    note.textContent = e.message;
  }
};
promptEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendPrompt(); }
});
$("#mode").onchange = () => active && active.send({cmd: "set_mode", mode: $("#mode").value});
$("#model").onchange = () => active && active.send({cmd: "set_model", model: $("#model").value});

/* Command palette: '/' in an empty composer lists agent-advertised
   commands. Submit only on explicit send — never auto-issue. */
promptEl.addEventListener("input", () => {
  const v = promptEl.value;
  const pal = $("#palette");
  if (!v.startsWith("/") || !active || !active.commands.length) {
    if (pal) pal.hidden = true;
    return;
  }
  ensurePalette().hidden = false;
  renderPalette(v.slice(1).toLowerCase());
});

function ensurePalette() {
  let pal = $("#palette");
  if (!pal) {
    pal = document.createElement("div");
    pal.id = "palette";
    $("#composer").prepend(pal);
  }
  return pal;
}

function renderPalette(filter) {
  const pal = $("#palette");
  const cmds = active.commands.filter(c => c.name.toLowerCase().includes(filter));
  pal.replaceChildren(...cmds.map(c => {
    const b = document.createElement("button");
    b.textContent = `/${c.name} — ${c.description || ""}`;
    b.onclick = () => { promptEl.value = `/${c.name} `; pal.hidden = true; promptEl.focus(); };
    return b;
  }));
  if (!cmds.length) pal.hidden = true;
}

document.addEventListener("keydown", (e) => {
  const dlg = $("#permission");
  if (dlg.open && /^[1-9]$/.test(e.key) && !e.altKey) {
    const btn = $("#perm-options").children[Number(e.key) - 1];
    if (btn) btn.click();
  }
  if (e.key === "Escape") {
    const pal = $("#palette");
    if (pal && !pal.hidden) { pal.hidden = true; e.preventDefault(); return; }
    // an open dialog owns its own Escape (the approval one refuses it)
    if (document.querySelector("dialog[open]")) return;
    // In the terminal Esc interrupts the agent. So it does here.
    if (active && active.state === "turn") {
      active.send({cmd: "cancel"});
      e.preventDefault();
    }
  }
});

/* Every other key behaves the way it does in a terminal: it types. With the
   focus anywhere but a field — on a tab, on the conversation — a printable
   key moves it to the composer and the character lands there (no
   preventDefault: the keystroke types itself once the box has focus). */
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.altKey || e.metaKey || e.key.length !== 1) return;
  if (document.querySelector("dialog[open]")) return;
  const t = e.target;
  if (t && (t.isContentEditable ||
            /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || ""))) return;
  const box = $("#prompt-input");
  if (box && !box.disabled) box.focus();
});

/* ---------------- theme, help and settings ----------------

   The OS decides until the reader says otherwise; the choice is this
   browser's, and it is applied before anything is drawn. */

const THEME_KEY = "claudiu.theme";

function applyTheme(theme) {
  if (theme && theme !== "system") {
    document.documentElement.dataset.theme = theme;
  } else {
    delete document.documentElement.dataset.theme;
  }
  try { localStorage.setItem(THEME_KEY, theme || "system"); } catch (e) {}
}

function storedTheme() {
  try { return localStorage.getItem(THEME_KEY) || "system"; } catch (e) { return "system"; }
}

const HELP = [
  ["The five lanes", "Switches in the status strip: thinking, tools, " +
   "subagents, events, harness. Switching one off removes those rows from " +
   "the page entirely; your prompts and the agent's answers are never hidden."],
  ["Thinking", "What the agent is ASKED to think is chosen per session in " +
   "the launcher (summarized / omitted / off) — ACP fixes it when the " +
   "session starts. The lane switch only decides whether you see it."],
  ["Following the conversation", "New rows scroll into view only while you " +
   "are at the bottom. Scroll up to read and it stays put; “↓ jump to " +
   "latest” brings you back."],
  ["Chips", "log = the adapter's own diagnostics (not errors). anomalies " +
   "and drift = things this client did not expect; clicking opens them and " +
   "keeps them until you dismiss them."],
  ["Account limits", "Top right: each rate-limit window the agent has " +
   "reported (5 h, 7 d, per model, extra credits) with how much is used."],
  ["Approvals and questions", "The agent's permission requests and its own " +
   "multiple-choice questions arrive as dialogs; digits 1-9 answer an " +
   "approval, “Other” answers a question in your own words."],
  ["Archive", "Hands the conversation to claude-session-publisher, which " +
   "writes it into your usual archive directory."],
  ["Keyboard — every shortcut there is",
   "Esc stops the agent mid-turn (and closes the command list first, if it " +
   "is open) · Enter sends · Shift+Enter starts a new line · “/” in an " +
   "empty composer lists the agent's commands · Alt+N starts a session · " +
   "Alt+1…9 switches to that tab · 1…9 answers an open approval dialog · " +
   "Esc in a dialog closes it, except an approval, which will not be " +
   "dismissed unanswered. Every other key types: press one anywhere and it " +
   "goes to the composer, as it would in a terminal."],
  ["Sessions", "They live in the server: reloading the page reattaches to " +
   "everything still running. Only one attachment per agent session."],
];

function initChrome() {
  applyTheme(storedTheme());
  const help = $("#help");
  $("#help-body").replaceChildren(...HELP.map(([term, text]) => {
    const box = document.createElement("div");
    const h = document.createElement("h3");
    h.textContent = term;
    const p = document.createElement("div");
    p.textContent = text;
    box.append(h, p);
    return box;
  }));
  $("#help-button").onclick = () => help.showModal();
  $("#help-close").onclick = () => help.close();
  const config = $("#config");
  const theme = $("#theme");
  theme.value = storedTheme();
  theme.onchange = () => applyTheme(theme.value);
  const box = $("#config-expand-tools");
  box.checked = expandTools();
  box.onchange = () => {
    applyExpandTools(box.checked);
    $("#expand-tools").checked = box.checked;
  };
  $("#config-button").onclick = () => { box.checked = expandTools(); config.showModal(); };
  $("#config-close").onclick = () => config.close();
}

initChrome();
initLauncher();
initLanes();
initFollow();
sizeComposer();
showLauncher();

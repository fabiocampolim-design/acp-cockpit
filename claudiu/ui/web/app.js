"use strict";
/* CLAUDIU web View. Talks ONLY the UI protocol (docs/UI-PROTOCOL.md).
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
  } catch (e) {}
  initPicker();
}

/* ---------------- folder picker ----------------
   A page cannot learn an absolute path from the OS folder dialog, so the
   server lists directories (GET /api/dirs) and the dialog walks them. */

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
  const body = JSON.stringify({profile, cwd, resume});
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

function activate(S) {
  active = S;
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
    this.chips = {".drift-chip": {n: 0, label: "drift", title: ""},
                  ".anomaly-chip": {n: 0, label: "anomalies", title: ""}};
    this.turnStarted = null; this.lastActivity = null;
    this.stderr = [];             // adapter stderr lines: drawer, never inline
    this.stderrOpen = false;
    this.turnAgentNodes = [];     // agent text nodes of the running turn
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

  connect() {
    this.ws = new WebSocket(`ws://${location.host}/ws/sessions/${this.sid}`);
    this.ws.onopen = () => { while (this.queue.length) this.ws.send(this.queue.shift()); };
    this.ws.onmessage = (m) => this.handle(JSON.parse(m.data));
    this.ws.onclose = () => this.setState("disconnected");
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
      chip.title = c.title;
      chip.onclick = () => { c.n = 0; c.title = ""; this.renderStatus(); };
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
  addBlock(kind, role, text) {
    const key = kind + ":" + (role || "");
    const rich = kind === "message_chunk" && role === "agent";   // markdown-lite
    if (this.agg.currentKey === key && this.agg.node) {
      if (text) { const m = $(".marker", this.agg.node); if (m) m.remove(); }
      const node = this.agg.node;
      node.rawText = (node.rawText || "") + text;
      if (rich) renderRich($(".text", node), node.rawText);
      else $(".text", node).textContent += text;
      return node;
    }
    const div = document.createElement("div");
    div.dataset.kind = kind;
    if (role) div.dataset.role = role;
    const span = document.createElement("span");
    span.className = "text";
    div.rawText = text;
    if (rich) renderRich(span, text); else span.textContent = text;
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
    if (this.isActive) node.scrollIntoView({block: "end"});
  }

  breakAgg() { this.agg.currentKey = null; }

  /* ----- event dispatch ----- */
  handle(ev) {
    const d = ev.data;
    if (ev.kind !== "session_state") this.touch(summarize(ev));
    switch (ev.kind) {
      case "session_state":
        if (d.state === "turn") this.turnAgentNodes = [];
        this.setState(d.state); break;
      case "message_chunk": {
        const node = this.addBlock("message_chunk", d.role, d.text);
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
      case "session_info":
        if (d.title !== undefined) this.title = d.title;
        this.renderTab(); break;
      case "stderr": this.renderStderr(ev); break;
      case "permission_request": queuePermission(this, ev); break;
      case "permission_resolved": resolvePermission(this, d.request); break;
      case "elicitation_request": queueElicitation(this, ev); break;
      case "elicitation_resolved":
        closeElicitation(this, d.request);
        this.breakAgg();
        this.addBlock("elicitation_resolved", null,
          d.action === "accept"
            ? `\u2014 you answered: ${describeAnswer(d.content)} \u2014`
            : `\u2014 question skipped${d.source === "failsafe"
                ? " (no answer in time)" : ""} \u2014`);
        break;
      case "turn_ended":
        this.breakAgg();
        this.addBlock("turn_ended", null, `— turn ended (${d.stop_reason}) —`);
        break;
      case "fs_request":
        this.breakAgg();
        this.addBlock("fs_request", null,
          `agent ${d.op} ${d.path} ${d.allowed ? "✓" : "✗ blocked"}`);
        break;
      case "drift": this.bumpChip(".drift-chip", d.flags.join("\n")); break;
      case "anomaly":
        this.bumpChip(".anomaly-chip", `${d.category}: ${d.detail}`);
        this.breakAgg();
        addRawToggle(this.addBlock("anomaly", null,
          `⚠ ${d.category}: ${d.detail}`), ev);
        break;
      case "unrecognized":
        this.breakAgg();
        addRawToggle(this.addBlock("unrecognized", null,
          `unrecognized protocol data (${d.why})`), ev);
        break;
      default:
        this.breakAgg();
        addRawToggle(this.addBlock("unrecognized", null,
          `unknown event kind ${ev.kind}`), ev);
    }
  }

  bumpChip(sel, detail) {
    const c = this.chips[sel];
    c.n += 1;
    c.title = (c.title ? c.title + "\n" : "") + detail;
    this.renderStatus();
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
function renderRich(el, text) {
  el.replaceChildren();
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
  w.scrollIntoView({block: "end"});
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

function queueElicitation(S, ev) {
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

function describeAnswer(content) {
  const parts = Object.entries(content || {}).map(([k, v]) =>
    `${k}: ${Array.isArray(v) ? v.join(", ") : v}`);
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

function sendPrompt() {
  const text = promptEl.value.trim();
  if (!active || !text || active.state !== "ready") return;
  active.breakAgg();
  active.addBlock("message_chunk", "user", text);
  active.breakAgg();
  active.send({cmd: "prompt", text});
  promptEl.value = "";
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
  if (e.key === "Escape" && $("#palette") && !$("#palette").hidden) {
    $("#palette").hidden = true;
    e.preventDefault();
  }
});

initLauncher();
showLauncher();

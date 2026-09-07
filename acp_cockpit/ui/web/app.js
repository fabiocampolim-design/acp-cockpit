// SPDX-License-Identifier: Apache-2.0
"use strict";
/* acp-cockpit web View. Talks ONLY the UI protocol (docs/UI-PROTOCOL.md).
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
    renderLaunchChoices(p);
  };
  sel.onchange();
  $("#start").onclick = () => startSession(null);
  $("#refresh-recent").onclick = loadRecent;
  $("#tab-add").onclick = showLauncher;
  await restoreLauncherSettings();
  initPicker();
  await restoreSessions();
}

/* Session-creation choices are the AGENT's (its profile lists them, with
   the option payloads the agent reads): one select per choice, rendered
   into #launch-choices whenever the profile changes. The View knows no
   option shape of its own (2026-09-06: the thinking select and its
   payloads were hardcoded here). */
let launcherMemory = {};        // server-side memory, read once

function renderLaunchChoices(p) {
  const box = $("#launch-choices");
  box.replaceChildren(...((p && p.launch_choices) || []).map(c => {
    const label = document.createElement("label");
    label.htmlFor = c.id;
    label.append(c.label + " ");
    const sel = document.createElement("select");
    sel.id = c.id;
    sel.dataset.launchChoice = c.id;
    if (c.title) sel.title = c.title;
    for (const o of c.options) {
      const el = document.createElement("option");
      el.value = o.value; el.textContent = o.text;
      sel.append(el);
    }
    let remembered = null;
    try { remembered = localStorage.getItem(choiceKey(c.id)); } catch (e) {}
    const want = remembered || launcherMemory[c.id];
    if (want && c.options.some(o => o.value === want)) sel.value = want;
    label.append(sel);
    return label;
  }));
}

function choiceKey(id) { return `acpcockpit.${id}`; }

/* The chosen option of every launch choice, and what it asks the agent for. */
function launchSelection(p) {
  const values = {}, client_options = {};
  for (const c of (p && p.launch_choices) || []) {
    const sel = $(`#launch-choices select[data-launch-choice="${c.id}"]`);
    const opt = c.options.find(o => o.value === (sel && sel.value));
    if (!opt) continue;
    values[c.id] = opt.value;
    Object.assign(client_options, opt.client_options || {});
  }
  return {values, client_options};
}

/* What the launcher was last started with. This browser's own memory wins
   — it is the most recent thing this person did here — and the server's
   copy is the fallback that makes a fresh browser, a cleared profile or a
   second machine open on the right project instead of an empty form. */
async function restoreLauncherSettings() {
  const local = {};
  try {
    local.profile = localStorage.getItem(PROFILE_KEY);
    local.cwd = localStorage.getItem(CWD_KEY);
  } catch (e) {}
  let remote = {};
  try { remote = await api("/api/settings"); } catch (e) {}
  launcherMemory = (remote && remote.choices) || {};
  const pick = (k) => local[k] || remote[k] || "";
  const sel = $("#profile");
  const wanted = pick("profile");
  if (wanted && [...sel.options].some(o => o.value === wanted && !o.disabled)) {
    sel.value = wanted;
  }
  sel.onchange();            // renders the choices with the memory applied
  if (!$("#cwd").value) $("#cwd").value = pick("cwd");
}

function rememberLauncherSettings(profile, cwd, choices) {
  try {
    localStorage.setItem(PROFILE_KEY, profile);
    localStorage.setItem(CWD_KEY, cwd);
    for (const [id, v] of Object.entries(choices)) localStorage.setItem(choiceKey(id), v);
  } catch (e) {}
  // and on the server, for the next browser that has never been here
  // choices are the PROFILE's, in their own object: spread flat they shared a
  // namespace with cwd and profile, so a launch choice called `cwd`
  // overwrote the project directory (review 2026-09-06)
  api("/api/settings", {method: "POST",
                        body: JSON.stringify({profile, cwd, choices})})
    .catch(() => {});
}

/* The sessions live in the SERVER, not the page: a reload (or a second
   browser) must find the ones already running instead of stranding them.
   Attaching replays every event the session has emitted. */
async function restoreSessions() {
  let live = [];
  try {
    ({sessions: live} = await api("/api/sessions"));
  } catch (e) {
    document.body.dataset.restored = "failed";
    return;
  }
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
  // The page has decided what it opens on. Anything that wants to act on
  // the launcher (a test, a script) waits for this rather than racing the
  // reattach, which used to hide the launcher again under a click.
  document.body.dataset.restored = "1";
}

/* The pinned schema and the installed adapter against the latest published
   versions (`/api/drift`). The route existed and nothing called it, so the
   reader never learnt the adapter was two releases behind (2026-09-05). It is
   asked once per page load; the answer feeds Help and, when something is
   behind, a chip at the top right. */
let driftInfo = null;

async function checkVersions() {
  try { driftInfo = await api("/api/drift"); } catch (e) { driftInfo = {error: e.message}; }
  const chip = $("#update-chip");
  const flags = (driftInfo && driftInfo.flags) || [];
  chip.hidden = flags.length === 0;
  if (flags.length) {
    chip.textContent = "update";
    chip.title = "behind the latest published version:\n" + flags.join("\n") +
      "\n(details in Help)";
  }
}

function describeVersions() {
  const d = driftInfo;
  if (!d) return "not checked yet.";
  if (d.error) return `could not be read: ${d.error}`;
  const lines = [`Pinned ACP schema: ${d.pinned_schema}.`];
  if (!d.online) {
    lines.push("The online check is off (--no-drift-online), so whether the " +
               "schema or the adapter is behind the latest release is not known.");
  } else if (d.latest) {
    lines.push(`Latest schema release: ${d.latest.schema || "?"}.`);
    if (d.adapter_package) {
      lines.push(`Adapter ${d.adapter_package}: installed ` +
                 `${d.latest.adapter_installed || "unknown"}, latest ` +
                 `${d.latest.adapter_latest || "?"}.`);
    }
    lines.push((d.flags || []).length
      ? "Behind: " + d.flags.join("; ") + "."
      : "Nothing is behind.");
  } else if ((d.flags || []).length) {
    lines.push(d.flags.join("; "));
  }
  return lines.join(" ");
}

/* ---------------- folder picker ----------------
   A page cannot learn an absolute path from the OS folder dialog, so the
   server lists directories (GET /api/dirs) and the dialog walks them. */

const PROFILE_KEY = "acpcockpit.profile";
const CWD_KEY = "acpcockpit.cwd";

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

/* The picker fills whichever box asked for it (the launcher's project
   directory, the archive destination). */
let pickTarget = null;

function browseInto(input) {
  pickTarget = input;
  $("#dirpick").showModal();
  browseTo(input.value.trim());
}

function initPicker() {
  const dlg = $("#dirpick");
  $("#browse").onclick = () => browseInto($("#cwd"));
  $("#dirpick-up").onclick = () => {
    if (dlg.dataset.parent) browseTo(dlg.dataset.parent);
  };
  $("#dirpick-cancel").onclick = () => dlg.close();
  $("#dirpick-use").onclick = () => {
    const target = pickTarget || $("#cwd");
    if (dlg.dataset.path) target.value = dlg.dataset.path;
    dlg.close();
    target.focus();
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
    else list.replaceChildren(...[...data.sessions].sort(byRecency).map(s => {
      const item = li(`${s.title || "(untitled)"} — ${when(s.updatedAt)}`);
      item.title = `${s.sessionId}\n${s.updatedAt || "no timestamp reported"}`;
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

/* Newest first — the one you want is almost always the last one you left.
   A session the agent dated with nothing sorts to the bottom rather than
   pretending to be new. */
function byRecency(a, b) {
  const at = Date.parse(a.updatedAt || "") || 0;
  const bt = Date.parse(b.updatedAt || "") || 0;
  return bt - at;
}

/* "3 min ago", "yesterday 14:02", "12 Aug 09:31" — the timestamp the agent
   reported, in a shape a reader can use. */
function when(iso) {
  if (!iso) return "no date reported";
  const t = Date.parse(iso);
  if (!t) return iso;
  const mins = Math.round((Date.now() - t) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const when = new Date(t);
  const hhmm = when.toTimeString().slice(0, 5);
  const days = Math.floor((new Date().setHours(0, 0, 0, 0) -
                           new Date(t).setHours(0, 0, 0, 0)) / 86400000);
  if (days === 0) return `today ${hhmm}`;
  if (days === 1) return `yesterday ${hhmm}`;
  if (days < 7) return `${days} days ago, ${hhmm}`;
  return when.toLocaleDateString(undefined, {day: "numeric", month: "short"}) +
    " " + hhmm;
}

function li(text) {
  const el = document.createElement("li"); el.textContent = text; return el;
}

async function startSession(resume, resumeCwd) {
  const profile = $("#profile").value;
  const cwd = (resume && resumeCwd) ? resumeCwd : $("#cwd").value.trim();
  if (resume && resumeCwd) $("#cwd").value = resumeCwd;
  if (!cwd) { alertBanner("pick a project directory first"); return; }
  // Session-CREATION options (thinking, for Claude): the profile's choices,
  // with the payload the agent reads — nothing the View made up.
  const {values, client_options} =
    launchSelection(profiles.find(x => x.id === profile));
  const body = JSON.stringify({profile, cwd, resume, client_options});
  let id;
  try {
    ({id} = await api("/api/sessions", {method: "POST", body}));
  } catch (e) {
    alertBanner(e.message);
    return;
  }
  rememberLauncherSettings(profile, cwd, values);
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

/* Where the active tab's reader is, kept on the session before the tab
   goes out of view (a switch to another tab OR to the launcher). */
function stashScroll() {
  if (!active) return;
  active.scrollTop = $("#conversation").scrollTop;
  active.following = following;
}

function showLauncher() {
  stashScroll();
  active = null;
  $("#launcher").hidden = false;
  $("#workspace").hidden = true;
  for (const S of sessions.values()) S.tab.classList.remove("active");
  $("#tab-add").classList.add("active");
}

const ACTIVE_KEY = "acpcockpit.active";

function activate(S) {
  // The conversation is one scroll container with one pane visible at a
  // time, so each tab remembers where its reader was (and whether they were
  // following) across a switch — 2026-09-05, before this the position and
  // the follow state leaked from one tab to the next.
  if (active !== S) stashScroll();
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
  const el = $("#conversation");
  following = S.following === undefined ? true : S.following;
  el.scrollTop = following ? el.scrollHeight : (S.scrollTop || 0);
  renderJumpButton();
  $("#prompt-input").focus();
}

function closeSession(S) {
  S.closing = true;                    // a pending retry must not revive it
  if (active === S) closeArchive();
  // A dialog belonging to a session that no longer exists can never be
  // answered: its only closer needs an event from the socket we are about to
  // drop, and both dialogs refuse Escape by design. The modal then covers the
  // page and nothing but a reload gets it back (review 2026-09-06).
  dropDialogsOf(S);
  fetch(`/api/sessions/${S.sid}`, {method: "DELETE"}).catch(() => {});
  if (S.ws) { S.ws.onclose = null; S.ws.close(); }
  paneGrowth.unobserve(S.pane);   // the observer holds the pane alive otherwise
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
    this.modelsUsed = [];         // canonical ids the API has reported
    this.suggestion = null;       // the agent's guess at the next prompt
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
    // Every other way the content can get taller — a tool result opening,
    // the working line rewrapping, a diff arriving — without a row being
    // appended. The observer is the belt to appendRow's braces.
    paneGrowth.observe(this.pane);
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
    // who is on the other side, as initialize reported it
    const who = this.agentInfo
      ? ` — ${this.agentInfo.name || "agent"} ${this.agentInfo.version || ""}`.trimEnd()
      : "";
    this.tab.title = `${this.profile} — ${this.cwd} — ${this.state}${who}`;
  }

  renderAll() {
    this.renderTab();
    this.renderSuggestion();
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
    // The API's own id for what is running (`claude-opus-5`), not the
    // adapter's short label — it is the thing to quote in a bug report.
    // It arrives in the usage meta's per-model tally; until the first
    // reading, the selector's name is all there is (Fabio, 2026-09-04).
    const modelEl = $("#status .model");
    const chosen = modelCfg ? modelCfg.value : this.model.current;
    const canonical = this.canonicalModel(chosen);
    const label = modelCfg ? modelCfg.name : (this.model.current || "");
    modelEl.textContent = canonical || label;
    modelEl.dataset.canonical = canonical ? "1" : "";
    modelEl.title = [label && `selected: ${label}`,
                     chosen && `option value: ${chosen}`,
                     canonical ? `model id reported by the API: ${canonical}`
                       : "the API has not reported a model id yet"]
      .filter(Boolean).join("\n");
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

  /* Offered, never sent: it fills the composer and waits, because the one
     thing a predicted prompt must not do is prompt. */
  renderSuggestion() {
    if (!this.isActive) return;
    const box = $("#suggestion");
    box.hidden = !this.suggestion || this.state !== "ready";
    if (box.hidden) return;
    box.replaceChildren();
    const use = document.createElement("button");
    use.type = "button";
    use.className = "take";
    use.textContent = this.suggestion;
    use.title = "put this in the composer (it is not sent)";
    use.onclick = () => {
      const input = $("#prompt-input");
      input.value = this.suggestion;
      input.focus();
      sizeComposer();
      this.suggestion = null;
      this.renderSuggestion();
    };
    const drop = document.createElement("button");
    drop.type = "button";
    drop.className = "drop";
    drop.textContent = "×";
    drop.title = "dismiss";
    drop.onclick = () => { this.suggestion = null; this.renderSuggestion(); };
    box.append(use, drop);
  }

  renderStderrDrawer() {
    if (!this.isActive) return;
    this.renderAnomalyDrawer();
    const d = $("#stderr-drawer");
    d.hidden = !this.stderrOpen || this.stderr.length === 0;
    $("pre", d).textContent = this.stderr.join("\n");
  }

  /* The API's id for the model behind a choice. `models_used` is the
     per-model tally the agent sends with usage; the option value ("opus")
     is a prefix of, or contained in, the real id ("claude-opus-5"). No
     match, no guess: the caller falls back to the label. */
  canonicalModel(chosen) {
    if (!this.modelsUsed || !this.modelsUsed.length) return null;
    if (chosen) {
      const key = String(chosen).replace(/\[.*$/, "").toLowerCase();
      const hit = this.modelsUsed.find(m => m.toLowerCase().includes(key)) ||
        this.modelsUsed.find(m => key.includes(m.toLowerCase()));
      if (hit) return hit;
    }
    return this.modelsUsed[this.modelsUsed.length - 1];
  }

  /* Current value of a config option, with its display name. */
  configCurrent(id) {
    const opt = this.config.find(o => o.id === id);
    if (!opt) return null;
    const hit = (opt.options || []).find(o => o.value === opt.currentValue);
    return {value: opt.currentValue,
            name: hit ? (hit.name || String(hit.value)) : String(opt.currentValue)};
  }

  /* The session has left "starting". Until then the panel shows one line
     instead of shuffling its contents into place.

     This used to ALSO require config options or modes, which ACP makes
     optional: an agent that reports neither stayed "settling" for ever and
     the CSS hid the lane switches and the tool-output toggle with the rest —
     client-side controls that have nothing to do with the agent. The engine
     emits mode, model, config_option and the early-update replay BEFORE
     `ready`, so the state is already the readiness signal (2026-09-06). */
  get settled() {
    return this.state !== "starting";
  }

  renderControls() {
    if (!this.isActive) return;
    $("#workspace").dataset.settling = this.settled ? "" : "1";
    // Newer agents offer mode/model as config options too: the config option
    // wins and the legacy select hides — never two controls for one thing.
    const cfgIds = new Set(this.config.map(o => o.id));
    fillSelect($("#mode"), cfgIds.has("mode") ? [] :
               this.mode.available.map(m => [m.id, m.name || m.id, m.description]),
               this.mode.current);
    fillSelect($("#model"), cfgIds.has("model") ? [] :
               this.model.available.map(m => [m.modelId, m.name || m.modelId, m.description]),
               this.model.current);
    let settling = $("#toolbar .controls .settling");
    if (!settling) {
      settling = document.createElement("span");
      settling.className = "settling";
      $("#toolbar .controls").prepend(settling);
    }
    settling.textContent = this.state === "starting"
      ? "starting the agent…" : "waiting for the agent's options…";
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
    if (this.isActive) this.renderControls();
    // a suggestion is for the gap between turns, not for the middle of one
    if (s === "turn") this.suggestion = null;
    this.renderSuggestion();
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
  addBlock(kind, role, text, lane, speaker) {
    // The key is the whole speaker identity — kind, role, WHOSE work it is,
    // and the lane that identity puts it in. Keying on kind+role alone let
    // subagent text and the agent's own answer share a row, and the row kept
    // the first one's lane: hiding subagents then hid the agent's answer,
    // which this client promises never happens (review 2026-09-06).
    const key = [kind, role || "", speaker || "", lane || ""].join(":");
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
      // The row GREW; no row was added. Following only on append is why a
      // long streamed answer scrolled off the bottom as it arrived
      // (Fabio, 2026-09-04).
      if (this.isActive) scrollIfFollowing();
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
        if (d.agent_info) this.agentInfo = d.agent_info;
        this.serverState = d.state;
        this.setState(d.state); break;
      case "vendor_update": {
        // A session/update kind outside the schema that this adapter is
        // KNOWN to send: shown as itself, in its lane, never as drift.
        this.breakAgg();
        const lane = String(d.kind).startsWith("subagent") ? "subagents" : "events";
        const summary = Object.entries(d.update || {})
          .filter(([k]) => k !== "sessionUpdate" && k !== "_meta")
          .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`)
          .join(" · ");
        addRawToggle(this.addBlock("vendor_update", null,
          `${d.kind}${summary ? " — " + summary : ""}`, lane), ev);
        break;
      }
      case "replay_truncated":
        // The server's replay buffer is bounded; the JSONL record is not.
        this.note(`events ${d.from_seq}–${d.to_seq} are not replayed here `
                  + "(the server keeps a bounded buffer; the session record "
                  + "on disk has them all)");
        break;
      case "message_chunk": {
        const node = this.addBlock("message_chunk", d.role, d.text,
          d.role === "thought" ? "thinking"
            : d.parent_tool_call_id ? "subagents" : null,
          d.parent_tool_call_id);
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
      case "usage":
        this.usage = d;
        if (d.models_used && d.models_used.length)
          this.modelsUsed = d.models_used;
        this.renderStatus(); break;
      case "rate_limit": recordRateLimit(d); break;
      case "auth_status": recordAuthStatus(d); break;
      case "prompt_suggestion":
        this.suggestion = d.text;
        this.renderSuggestion();
        break;
      case "session_info":
        if (d.title !== undefined) this.title = d.title;
        this.renderTab(); break;
      case "stderr": this.renderStderr(ev); break;
      case "permission_request": queuePermission(this, ev); break;
      case "permission_resolved":
        resolvePermission(this, d.request);
        // The reader chose nothing: say what happened instead, where the
        // conversation's events are (an auto-rejection or a withdrawal used
        // to close the dialog and leave no trace on the page).
        if (d.source && d.source !== "user") {
          this.breakAgg();
          this.addBlock("permission_resolved", null,
            d.source === "agent"
              ? "— approval request withdrawn by the agent —"
              : "— approval request auto-rejected (no answer in time) —",
            "events");
        }
        break;
      case "elicitation_request": queueElicitation(this, ev); break;
      case "elicitation_resolved": {
        const titles = fieldTitles(this, d.request);
        closeElicitation(this, d.request);
        this.breakAgg();
        this.addBlock("elicitation_resolved", null,
          d.action === "accept"
            ? `\u2014 you answered: ${describeAnswer(d.content, titles)} \u2014`
            : d.action === "cancel"
              ? "\u2014 question withdrawn by the agent \u2014"
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
    // the row that owns it (marked retroactively, since the parent row
    // arrives first and only its children reveal the relationship). The
    // engine stamps `parent_tool_call_id` from the agent's own `_meta`.
    const parent = t.parent_tool_call_id || null;
    if (parent) entry.node.dataset.lane = "subagents";
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
  // Tearing down does not need S to be the visible session. In practice the
  // next active session's own showWorking(_, false) clears this, which is why
  // no stale row was ever seen — but the guard was still on the wrong side of
  // the teardown, and relying on another session to do the cleanup is not a
  // property worth keeping (review 2026-09-06).
  if (!on) {
    if (existing) existing.remove();
    if (workingTimer) { clearInterval(workingTimer); workingTimer = null; }
    return;
  }
  if (!S.isActive) return;
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
    scrollIfFollowing();      // the line rewraps as the text grows
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
    return short + words.map(w => w === "overage" ? "+EC"
      : " " + w.charAt(0).toUpperCase() + w.slice(1)).join("");
  }
  return type.replace(/_/g, " ");
}
const limitWindows = new Map();     // window name -> latest reading
// Extra credits belong to the ACCOUNT, not to a window: one state, and the
// most recent report wins.
let limitCredits = null;

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
  limitCredits = creditsNote(d) || limitCredits;
  for (const [type, w] of entries) {
    limitWindows.set(type, {
      utilization: typeof w.utilization === "number" ? w.utilization
                                                     : d.utilization,
      resetsAt: w.resetsAt || d.resetsAt,
      status: d.status, raw: d,
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
/* Extra credits: one word and a colour. Green means the account may spend
   them, red means it may not; the state the agent actually reported is in
   the chip's tooltip, because "allowed" and "in use" are both green and a
   reader who wants the difference should be able to find it. */
function creditsNote(d) {
  if (!d.overageStatus && !d.isUsingOverage && !d.overageInUse &&
      d.overageDisabledReason === undefined &&
      d.canUserPurchaseCredits === undefined) return null;
  const ok = d.isUsingOverage || d.overageInUse ||
    d.overageStatus === "allowed" || d.canUserPurchaseCredits === true;
  return {
    ok,
    detail: d.isUsingOverage || d.overageInUse ? "extra credits in use"
      : d.overageDisabledReason === "out_of_credits" ? "out of extra credits"
      : d.overageStatus ? `extra credits: ${d.overageStatus}`
      : d.canUserPurchaseCredits ? "extra credits available"
      : "extra credits unavailable",
  };
}

/* The account the agent runs as (`_auth/status_update`): the label on a
   chip, the e-mail and organisation only in the tooltip — a screenshot of
   the page should not carry an address by default. Account-wide; the
   latest report wins. */
function recordAuthStatus(d) {
  const chip = $("#auth-chip");
  const acct = (d && d.account) || {};
  const label = (d && d.label) || acct.plan || (d && d.kind) || "";
  chip.hidden = !label;
  if (!label) return;
  chip.textContent = label;
  chip.title = ["the account the agent is running as:",
                acct.email && `  ${acct.email}`,
                acct.organization && `  ${acct.organization}`,
                acct.plan && `  plan: ${acct.plan}`].filter(Boolean).join("\n");
}

function renderAccount() {
  const el = $("#account");
  const entries = [...limitWindows.entries()];
  el.hidden = entries.length === 0;
  // Extra credits are ACCOUNT-wide, so they are one badge beside the
  // windows, not a repeat on each of them (three "EC"s in a row, seen
  // live 2026-09-04).
  const credits = limitCredits;
  const badge = [];
  if (credits) {
    const ec = document.createElement("i");
    ec.className = "ec";
    ec.dataset.ok = credits.ok ? "1" : "0";
    ec.textContent = "EC";
    ec.title = `${credits.detail} — the agent reports the state of extra `
      + "credits, never a balance";
    badge.push(ec);
  }
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
    span.title = [`${label}: ${pct} used`, `status: ${w.status || "?"}`,
                  fmtReset(w.resetsAt),

                  "", "as the agent reported it:",
                  JSON.stringify(w.raw, null, 1)]
      .filter(v => v === "" || (v && typeof v === "string")).join("\n");
    return span;
  }), ...badge);
}

/* ---------------- following the bottom ----------------

   The conversation follows new rows only while the reader is AT the bottom.
   Scroll up and it stays put; a "jump to latest" button appears and puts
   you back in the stream. */

const FOLLOW_SLACK = 40;          // px from the bottom that still counts

/* The conversation always ends with something live — the working line, its
   timer rewriting itself every second — so "the last message" is only ever
   visible if the view follows the pane's HEIGHT, not just its row count. */
const paneGrowth = new ResizeObserver(() => scrollIfFollowing());

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
const LANE_KEY = "acpcockpit.lanes";

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

/* Everything a departing session still had waiting for an answer. Both
   queues and both open dialogs, so a closed session leaves no modal behind
   (review 2026-09-06). */
function dropDialogsOf(S) {
  for (let i = permQueue.length - 1; i >= 0; i--) {
    if (permQueue[i].S === S) permQueue.splice(i, 1);
  }
  for (let i = elicQueue.length - 1; i >= 0; i--) {
    if (elicQueue[i].S === S) elicQueue.splice(i, 1);
  }
  if (permOpen && permOpen.S === S) {
    $("#permission").close();
    permOpen = null;
    showNextPermission();
  }
  if (elicOpen && elicOpen.S === S) {
    $("#elicitation").close();
    elicOpen = null;
    showNextElicitation();
  }
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
  if (active) { active.suggestion = null; active.renderSuggestion(); }
  const text = promptEl.value.trim();
  if (!active || !text || active.state !== "ready") return;
  // The row is NOT drawn here: the server echoes the prompt as a user
  // message chunk (an event every attached View replays), and drawing it
  // locally too doubled it — and a reload used to lose it (2026-09-06).
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
  try { return localStorage.getItem("acpcockpit.expandTools") === "1"; } catch (e) { return false; }
}
function applyExpandTools(on) {
  try { localStorage.setItem("acpcockpit.expandTools", on ? "1" : "0"); } catch (e) {}
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
/* ---------------- archiving ----------------

   A side panel, not a banner: where to save, which formats, what happened.
   The server says which formats it can actually write — all of them with
   claude-session-publisher installed, plain Markdown without it — so the
   panel never offers a choice that would fail. */

const ARCHIVE_DEST_KEY = "acpcockpit.archiveDest";

function archivePanel() { return $("#archive-panel"); }

function closeArchive() {
  archivePanel().hidden = true;
  $("#archive-note").hidden = true;
}

async function openArchive() {
  if (!active) return;
  const panel = archivePanel();
  const note = $("#archive-note");
  note.hidden = true;
  note.className = "";
  panel.hidden = false;
  const dest = $("#archive-dest");
  const warn = $("#archive-warning");
  const box = $("#archive-formats");
  box.replaceChildren(li("asking the server what it can write…"));
  let caps;
  try {
    caps = await api(`/api/sessions/${active.sid}/archive`);
  } catch (e) {
    warn.hidden = false;
    warn.textContent = e.message;
    box.replaceChildren();
    return;
  }
  warn.hidden = !caps.warning;
  if (caps.warning) warn.textContent = caps.warning;
  let remembered = null;
  try { remembered = localStorage.getItem(ARCHIVE_DEST_KEY); } catch (e) {}
  if (!dest.value) dest.value = remembered || caps.default_dest || "";
  box.replaceChildren(...caps.formats.map(f => {
    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = f;
    cb.checked = (caps.default_formats || []).includes(f);
    label.append(cb, document.createTextNode(f));
    return label;
  }));
}

async function runArchive() {
  if (!active) return;
  const note = $("#archive-note");
  const dest = $("#archive-dest").value.trim();
  const formats = [...document.querySelectorAll("#archive-formats input:checked")]
    .map(cb => cb.value);
  if (!formats.length) {
    note.hidden = false;
    note.className = "error";
    note.textContent = "pick at least one format";
    return;
  }
  try { localStorage.setItem(ARCHIVE_DEST_KEY, dest); } catch (e) {}
  note.hidden = false;
  note.className = "";
  note.textContent = "saving…";
  const S = active;
  try {
    const r = await api(`/api/sessions/${S.sid}/archive`, {
      method: "POST",
      body: JSON.stringify({dest, formats}),
    });
    const where = (r.output || []).join("\n");
    note.textContent = where
      ? (r.fallback ? "saved (simple Markdown):\n" : "saved:\n") + where
      : "the archiver reported no output";
    // and a line in the conversation's harness lane, so the record of what
    // you did is where the rest of the session's history is
    if (where) S.note(`archived to ${(r.output || []).join(", ")}`);
  } catch (e) {
    note.className = "error";
    note.textContent = e.message;
  }
}

$("#archive").onclick = () => {
  if (archivePanel().hidden) openArchive(); else closeArchive();
};
$("#archive-close").onclick = closeArchive;
$("#archive-run").onclick = runArchive;
$("#archive-browse").onclick = () => browseInto($("#archive-dest"));
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

/* The 1-9 shortcut answers the approval dialog — but only when that dialog
   is the one the user is answering. It used to test `dlg.open` alone: the
   elicitation dialog keeps its own queue and can sit on top, so a digit typed
   into one of ITS fields clicked an option underneath, and the options are
   sorted allow_once first — "1" granted an unreviewed permission (review
   2026-09-06). Any other open dialog, or a focused field, means the digit is
   not meant for us. */
function typingInAField(t) {
  return !!t && (t.isContentEditable ||
                 /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || ""));
}

document.addEventListener("keydown", (e) => {
  const dlg = $("#permission");
  const otherDialog = [...document.querySelectorAll("dialog[open]")]
        .some((d) => d !== dlg);
  if (dlg.open && /^[1-9]$/.test(e.key) &&
      !e.altKey && !e.ctrlKey && !e.metaKey &&
      !otherDialog && !typingInAField(e.target)) {
    const btn = $("#perm-options").children[Number(e.key) - 1];
    if (btn) { e.preventDefault(); btn.click(); }
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
  if (typingInAField(t)) return;
  // A focused button keeps Space (it presses it) — but only Space: a mouse
  // click leaves the button focused, and the letters typed next still
  // belong to the composer (review 2026-09-05).
  if (t && /^(BUTTON|SUMMARY|A)$/.test(t.tagName || "") && e.key === " ") return;
  const box = $("#prompt-input");
  if (box && !box.disabled) box.focus();
});

/* ---------------- theme, help and settings ----------------

   The OS decides until the reader says otherwise; the choice is this
   browser's, and it is applied before anything is drawn. */

const THEME_KEY = "acpcockpit.theme";

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
  ["The five lanes", "Switches in the panel under the prompt, with the " +
   "other session controls: thinking, tools, subagents, events, harness. " +
   "Switching one off removes those rows from the page entirely; your " +
   "prompts and the agent's answers are never hidden."],
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
  ["Archive", "Opens a panel beside the conversation: where to save, and " +
   "which formats. With claude-session-publisher installed you get its " +
   "full document (HTML, Markdown, text, LaTeX, PDF, fidelity report); " +
   "without it this client writes a plain Markdown transcript from the " +
   "session " +
   "record and says so. Nothing covers the conversation, and the panel " +
   "closes."],
  ["The model in the strip", "The API's own id for what is running — " +
   "`claude-opus-5`, not `Opus` — as soon as the agent reports one, because " +
   "that is the string worth quoting in a bug report. The selector's label " +
   "and the option value are in the tooltip."],
  ["Keyboard — every shortcut there is",
   "Esc stops the agent mid-turn (and closes the command list first, if it " +
   "is open) · Enter sends · Shift+Enter starts a new line · “/” in an " +
   "empty composer lists the agent's commands · Alt+N starts a session · " +
   "Alt+1…9 switches to that tab · 1…9 answers an open approval dialog · " +
   "Esc in a dialog closes it, except an approval, which will not be " +
   "dismissed unanswered. Every other key types: press one anywhere and it " +
   "goes to the composer, as it would in a terminal."],
  ["Prompt suggestions", "After a turn the agent may offer a guess at " +
   "your next prompt, above the composer. Clicking it fills the box — it " +
   "is never sent for you. Most adapters forward none, so the strip is " +
   "usually absent."],
  ["Who can see this conversation",
   "This is a local program: it binds 127.0.0.1, serves this browser, " +
   "and runs the agent's adapter as a child process on your machine. Your " +
   "prompts go exactly where they would if you ran the agent in a " +
   "terminal — no further. It has no account, no telemetry and no " +
   "analytics, and the transcripts in the records directory never leave " +
   "the machine. The one outbound call it makes is the drift check " +
   "(api.github.com and registry.npmjs.org, versions only); " +
   "--no-drift-online turns it off. What the AGENT does with your " +
   "conversation is between you and whoever you authenticated to, exactly " +
   "as in the terminal."],
  ["Two things the terminal asks and this does not",
   "The Claude Code terminal occasionally shows a session-quality survey " +
   "(\"How is Claude doing in this session?\") and its own data-usage " +
   "notices. Both are drawn by the CLI itself and are not protocol " +
   "messages — there is no message type for either — so no ACP client can " +
   "relay them. Nothing is being hidden from you here; the wire simply " +
   "does not carry them."],
  ["Sessions", "They live in the server: reloading the page reattaches to " +
   "everything still running. Only one attachment per agent session."],
];

function initChrome() {
  applyTheme(storedTheme());
  const help = $("#help");
  const renderHelp = () => {
    const entries = [...HELP, ["Versions", "Protocol and adapter versions, " +
      "as checked when this page loaded: " + describeVersions()]];
    $("#help-body").replaceChildren(...entries.map(([term, text]) => {
      const box = document.createElement("div");
      const h = document.createElement("h3");
      h.textContent = term;
      const p = document.createElement("div");
      p.textContent = text;
      box.append(h, p);
      return box;
    }));
  };
  $("#help-button").onclick = () => { renderHelp(); help.showModal(); };
  $("#update-chip").onclick = () => { renderHelp(); help.showModal(); };
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
/* One failed fetch used to leave a blank, inert launcher and an unhandled
   rejection in the console, with nothing on screen to say why (2026-09-06). */
initLauncher().catch((e) => {
  const box = $("#launcher-error");
  box.hidden = false;
  box.textContent = "Could not load the agent list from this server: " +
    (e && e.message ? e.message : e) +
    ". Reload the page; if it keeps failing, check the server is still running.";
});
initLanes();
initFollow();
sizeComposer();
showLauncher();
checkVersions();

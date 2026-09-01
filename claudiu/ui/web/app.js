"use strict";
/* CLAUDIU web View. Talks ONLY the UI protocol (docs/UI-PROTOCOL.md). */

const $ = (sel) => document.querySelector(sel);
let ws = null, sid = null, turnActive = false;

async function api(path, opts = {}) {
  const resp = await fetch(path, {headers: {"Content-Type": "application/json"},
                                  ...opts});
  if (!resp.ok) throw new Error(`${path}: ${resp.status}`);
  return resp.json();
}

async function initLauncher() {
  const {profiles} = await api("/api/profiles");
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
    $("#caveats").replaceChildren(...(p ? p.caveats : []).map(c => {
      const li = document.createElement("li"); li.textContent = c.text;
      return li;
    }));
  };
  sel.onchange();
  $("#start").onclick = startSession;
}

async function startSession() {
  const body = JSON.stringify({profile: $("#profile").value,
                               cwd: $("#cwd").value.trim()});
  const {id} = await api("/api/sessions", {method: "POST", body});
  sid = id;
  $("#launcher").hidden = true;
  $("#workspace").hidden = false;
  connect();
}

const sendQueue = [];

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws/sessions/${sid}`);
  ws.onopen = () => {
    while (sendQueue.length) ws.send(sendQueue.shift());
  };
  ws.onmessage = (m) => handleEvent(JSON.parse(m.data));
  ws.onclose = () => setState("disconnected");
}

let uiState = "starting";

function setState(s) {
  uiState = s;
  $("#status .state").textContent = s;
  turnActive = (s === "turn");
  $("#send").disabled = (s !== "ready");
  $("#cancel").hidden = !turnActive;
}

const agg = {};   // aggregation state for consecutive same-role chunks

function addBlock(kind, role, text) {
  const key = kind + ":" + (role || "");
  if (agg.currentKey === key && agg.node) {
    if (text) {
      const marker = agg.node.querySelector(".marker");
      if (marker) marker.remove();   // real text replaces the placeholder
    }
    agg.node.querySelector(".text").textContent += text;
    return agg.node;
  }
  const div = document.createElement("div");
  div.dataset.kind = kind;
  if (role) div.dataset.role = role;
  const span = document.createElement("span");
  span.className = "text";
  span.textContent = text;
  div.append(span);
  $("#conversation").append(div);
  agg.currentKey = key;
  agg.node = div;
  div.scrollIntoView({block: "end"});
  return div;
}

function addRawToggle(node, ev) {
  const btn = document.createElement("button");
  btn.className = "raw-toggle";
  btn.textContent = "{}";
  btn.title = `raw frame #${ev.raw_ref ?? "-"}`;
  btn.onclick = () => {
    let pre = node.querySelector("pre.raw");
    if (pre) { pre.remove(); return; }
    pre = document.createElement("pre");
    pre.className = "raw";
    pre.textContent = JSON.stringify(ev, null, 2);
    node.append(pre);
  };
  node.append(btn);
}

function handleEvent(ev) {
  const d = ev.data;
  switch (ev.kind) {
    case "session_state":
      setState(d.state);
      break;
    case "message_chunk": {
      const node = addBlock("message_chunk", d.role, d.text);
      // Claude's adapter sends thought chunks with EMPTY text (thinking is
      // redacted). Show that thinking happened rather than an empty block.
      if (d.role === "thought" && !node.querySelector(".text").textContent
          && !node.querySelector(".marker")) {
        const m = document.createElement("span");
        m.className = "marker";
        m.textContent = "· thinking ·";
        node.prepend(m);
      }
      break;
    }
    case "model": {
      const sel = $("#model");
      if (d.available.length) {
        sel.hidden = false;
        sel.replaceChildren(...d.available.map(m => {
          const o = document.createElement("option");
          o.value = m.modelId;
          o.textContent = m.name || m.modelId;
          if (m.description) o.title = m.description;
          return o;
        }));
      }
      if (d.current) sel.value = d.current;
      $("#status .model").textContent = d.current || "";
      break;
    }
    case "stderr": {
      agg.currentKey = null;
      const node = document.createElement("div");
      node.dataset.kind = "stderr";
      const det = document.createElement("details");
      const sum = document.createElement("summary");
      sum.textContent = "adapter stderr";
      const pre = document.createElement("pre");
      pre.textContent = d.line;
      det.append(sum, pre);
      node.append(det);
      addRawToggle(node, ev);
      $("#conversation").append(node);
      break;
    }
    case "tool_call":
    case "tool_call_update": {
      agg.currentKey = null;
      const node = addBlock(ev.kind, null,
        `${d.title || d.kind || "tool"} [${d.status || ""}]`);
      addRawToggle(node, ev);
      break;
    }
    case "plan":
      $("#plan").hidden = d.entries.length === 0;
      $("#plan").replaceChildren(...d.entries.map(e => {
        const li = document.createElement("div");
        li.textContent = `${e.status || "?"} — ${e.content || ""}`;
        return li;
      }));
      break;
    case "commands":
      window._commands = d.commands;
      break;
    case "mode": {
      const sel = $("#mode");
      if (d.available.length) {
        sel.hidden = false;
        sel.replaceChildren(...d.available.map(m => {
          const o = document.createElement("option");
          o.value = m.id; o.textContent = m.name || m.id;
          return o;
        }));
      }
      if (d.current) sel.value = d.current;
      $("#status .mode").textContent = d.current || "";
      break;
    }
    case "permission_request":
      showPermission(ev);
      break;
    case "permission_resolved":
      $("#permission").close();
      break;
    case "turn_ended":
      agg.currentKey = null;
      addBlock("turn_ended", null, `— turn ended (${d.stop_reason}) —`);
      break;
    case "fs_request":
      agg.currentKey = null;
      addBlock("fs_request", null,
        `agent ${d.op} ${d.path} ${d.allowed ? "✓" : "✗ blocked"}`);
      break;
    case "drift":
      bumpChip(".drift-chip", "drift", d.flags.join("\n"));
      break;
    case "anomaly":
      bumpChip(".anomaly-chip", "anomalies", `${d.category}: ${d.detail}`);
      agg.currentKey = null;
      addRawToggle(addBlock("anomaly", null,
        `⚠ ${d.category}: ${d.detail}`), ev);
      break;
    case "unrecognized":
      agg.currentKey = null;
      addRawToggle(addBlock("unrecognized", null,
        `unrecognized protocol data (${d.why})`), ev);
      break;
    default:
      agg.currentKey = null;
      addRawToggle(addBlock("unrecognized", null,
        `unknown event kind ${ev.kind}`), ev);
  }
}

const chipCounts = {};
function bumpChip(sel, label, detail) {
  const chip = $("#status " + sel);
  chipCounts[sel] = (chipCounts[sel] || 0) + 1;
  chip.hidden = false;
  chip.textContent = `${label} (${chipCounts[sel]})`;
  chip.title = (chip.title ? chip.title + "\n" : "") + detail;
  chip.onclick = () => {           // acknowledge: clear the chip
    chip.hidden = true; chip.title = ""; chipCounts[sel] = 0;
  };
}

// Safe ordering for the approval dialog regardless of the agent's order:
// one-shot answers first, standing grants last (and visibly cautionary).
const KIND_ORDER = {allow_once: 0, reject_once: 1, reject_always: 2,
                    allow_always: 3};

function showPermission(ev) {
  const tc = ev.data.tool_call;
  $("#perm-tool").textContent = JSON.stringify(tc, null, 2);
  const warn = $("#perm-warning");
  const outside = ev.data.outside_boundary || [];
  if (outside.length) {
    warn.hidden = false;
    warn.textContent = "⚠ Touches paths OUTSIDE the project boundary — " +
      "shell commands are not confined by this client; your answer is " +
      "the only control:\n" + outside.join("\n");
  } else {
    warn.hidden = true;
  }
  const box = $("#perm-options");
  const options = [...ev.data.options].sort((a, b) =>
    (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9));
  box.replaceChildren(...options.map((o, i) => {
    const b = document.createElement("button");
    b.dataset.option = o.optionId;
    b.dataset.kind = o.kind;
    b.textContent = `${i + 1}. ${o.name} (${o.kind})` +
      (o.kind === "allow_always" ? " — standing grant for this session" : "");
    b.onclick = () => send({cmd: "permission",
                            request: ev.data.request, option: o.optionId});
    return b;
  }));
  $("#permission").showModal();
}

function send(obj) {
  const wire = JSON.stringify(obj);
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(wire);
  else sendQueue.push(wire);   // flushed by ws.onopen
}

function sendPrompt() {
  const text = $("#prompt-input").value.trim();
  if (!text || uiState !== "ready") return;
  agg.currentKey = null;
  addBlock("message_chunk", "user", text);
  agg.currentKey = null;
  send({cmd: "prompt", text});
  $("#prompt-input").value = "";
  const pal = $("#palette");
  if (pal) pal.hidden = true;
}

$("#send").onclick = sendPrompt;
$("#cancel").onclick = () => send({cmd: "cancel"});
$("#prompt-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendPrompt(); }
});
$("#mode").onchange = () => send({cmd: "set_mode", mode: $("#mode").value});
$("#model").onchange = () => send({cmd: "set_model", model: $("#model").value});

/* Command palette: '/' in an empty composer lists agent-advertised
   commands. Submit only on explicit send — never auto-issue. */
const promptEl = $("#prompt-input");
promptEl.addEventListener("input", () => {
  const v = promptEl.value;
  const pal = $("#palette");
  if (!v.startsWith("/") || !window._commands?.length) {
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
  const cmds = window._commands.filter(c =>
    c.name.toLowerCase().includes(filter));
  pal.replaceChildren(...cmds.map(c => {
    const b = document.createElement("button");
    b.textContent = `/${c.name} — ${c.description || ""}`;
    b.onclick = () => {
      promptEl.value = `/${c.name} `;
      pal.hidden = true;
      promptEl.focus();
    };
    return b;
  }));
  if (!cmds.length) pal.hidden = true;
}

document.addEventListener("keydown", (e) => {
  const dlg = $("#permission");
  if (dlg.open && /^[1-9]$/.test(e.key)) {
    const btn = $("#perm-options").children[Number(e.key) - 1];
    if (btn) btn.click();
  }
  if (e.key === "Escape" && $("#palette") && !$("#palette").hidden) {
    $("#palette").hidden = true;
    e.preventDefault();
  }
});
$("#permission").addEventListener("cancel", (e) => e.preventDefault());

initLauncher();

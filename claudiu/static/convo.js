// claudiu/static/convo.js
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Fabio Campolim
// The controlled conversation view: rendered from GET /api/conversation,
// never from the raw terminal. See docs/superpowers/specs/2026-08-31-*.
"use strict";
window.ClaudiuConvo = (function () {
  const LANES = { thinking: "thinking", tool: "tool", event: "event" };

  function q(tab, sel) { return tab.pane.querySelector(sel); }

  // Wire a tab's conversation controls once, at openTab time.
  function init(app, tab) {
    tab.convo = { seq: 0, els: new Map(), atBottom: true, filter: "" };
    const body = q(tab, ".convo-body");

    body.addEventListener("scroll", () => {
      const nearBottom = body.scrollHeight - body.scrollTop
        - body.clientHeight < 40;
      tab.convo.atBottom = nearBottom;
      q(tab, ".convo-jump").hidden = nearBottom;
    });
    q(tab, ".convo-jump").addEventListener("click", () => {
      body.scrollTop = body.scrollHeight;
    });

    for (const cb of tab.pane.querySelectorAll(".lane")) {
      cb.addEventListener("change", () => applyLanes(tab));
    }
    const search = q(tab, ".convo-search");
    search.addEventListener("input", () => {
      tab.convo.filter = search.value.trim().toLowerCase();
      applyFilter(tab);
    });

    const send = () => {
      const ta = q(tab, ".composer-input");
      const text = ta.value;
      if (!text.trim()) return;
      app.sendToPty(tab, text + "\r");
      ta.value = "";
      ta.style.height = "auto";
    };
    q(tab, ".composer-send").addEventListener("click", send);
    const ta = q(tab, ".composer-input");
    ta.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); send(); }
    });
    ta.addEventListener("input", () => {  // grow with content, capped
      ta.style.height = "auto";
      ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
    });

    q(tab, ".show-term").addEventListener("click", () => toggleTerminal(app, tab));
    q(tab, ".esc-btn").addEventListener("click", () => app.sendToPty(tab, "\x1b"));
  }

  function toggleTerminal(app, tab) {
    const raw = tab.pane.classList.toggle("rawterm");
    q(tab, ".show-term").textContent = raw ? "▤ Hide terminal"
      : "▤ Show terminal";
    if (raw) { app.sendSize(tab, true); tab.term.focus(); }
  }

  function applyLanes(tab) {
    const body = q(tab, ".convo-body");
    for (const cb of tab.pane.querySelectorAll(".lane")) {
      body.classList.toggle("hide-" + cb.dataset.lane, !cb.checked);
    }
  }

  function applyFilter(tab) {
    const f = tab.convo.filter;
    for (const [, el] of tab.convo.els) {
      el.classList.toggle("nomatch",
        f !== "" && !el.textContent.toLowerCase().includes(f));
    }
  }

  function fmtTokens(n) {
    return n >= 1000 ? Math.round(n / 1000) + "k" : String(n);
  }

  // Apply meta, title, permission, and render/patch turns.
  function update(app, tab, data) {
    const meta = data.meta || {};
    q(tab, ".cwd-frame").textContent = meta.cwd
      ? (meta.cwd + (meta.gitBranch ? "  (" + meta.gitBranch + ")" : "")) : "";
    const title = q(tab, ".title-box");
    if (document.activeElement !== title) title.value = data.title || "";

    const model = q(tab, ".model-frame");
    if (meta.model || meta.context_tokens != null) {
      const bits = [];
      if (meta.model) bits.push(meta.model);
      if (meta.context_tokens != null) {
        bits.push(fmtTokens(meta.context_tokens) +
          (meta.context_pct != null ? " · " + Math.round(meta.context_pct) + "%" : ""));
      }
      model.textContent = bits.join("  ·  ");
    } else { model.textContent = ""; }

    renderPermission(app, tab, data.permission);

    const body = q(tab, ".convo-body");
    for (const turn of data.turns || []) {
      const existing = tab.convo.els.get(turn.seq);
      if (!existing) {
        const el = renderTurn(turn);
        tab.convo.els.set(turn.seq, el);
        body.appendChild(el);
        if (turn.seq > tab.convo.seq) tab.convo.seq = turn.seq;
      } else if (turn.kind === "tool") {
        patchTool(existing, turn);  // a result may have arrived since
      }
    }
    applyLanes(tab);
    if (tab.convo.filter) applyFilter(tab);
    if (tab.convo.atBottom) body.scrollTop = body.scrollHeight;
    else q(tab, ".convo-jump").hidden = false;
  }

  function renderPermission(app, tab, perm) {
    const box = q(tab, ".perm");
    if (!perm) { box.hidden = true; box.textContent = ""; return; }
    if (box.dataset.prompt === perm.prompt &&
        box.dataset.n === String(perm.options.length)) return;  // unchanged
    box.dataset.prompt = perm.prompt;
    box.dataset.n = String(perm.options.length);
    box.textContent = "";
    const p = document.createElement("div");
    p.className = "perm-q"; p.textContent = perm.prompt;
    box.appendChild(p);
    const row = document.createElement("div");
    row.className = "perm-row";
    for (const opt of perm.options) {
      const b = document.createElement("button");
      b.className = opt.key === "1" ? "primary" : "ghost";
      b.textContent = opt.key + ". " + opt.label;
      b.addEventListener("click", () => app.sendToPty(tab, opt.key + "\r"));
      row.appendChild(b);
    }
    box.appendChild(row);
    box.hidden = false;
  }

  function turnLabel(turn) {
    if (turn.kind === "human") return "you";
    if (turn.kind === "assistant") return "claude";
    if (turn.kind === "thinking") return "thinking";
    if (turn.kind === "tool") return turn.name || "tool";
    if (turn.kind === "compact") return "compacted";
    return turn.badge || "event";
  }

  function renderTurn(turn) {
    const el = document.createElement("div");
    el.className = "turn turn-" + turn.kind + (turn.sub ? " is-sub" : "");
    const head = document.createElement("div");
    head.className = "turn-head";
    const who = document.createElement("span");
    who.className = "who"; who.textContent = turnLabel(turn);
    head.appendChild(who);
    if (turn.sub) {
      const s = document.createElement("span");
      s.className = "chip"; s.textContent = "subagent"; head.appendChild(s);
    }
    el.appendChild(head);

    if (turn.kind === "thinking") {
      el.appendChild(collapsible("thought", turn.text, false));
    } else if (turn.kind === "tool") {
      const sig = document.createElement("div");
      sig.className = "tool-sig";
      sig.textContent = (turn.input_summary || "");
      el.appendChild(sig);
      el.appendChild(toolResult(turn));
    } else {
      const body = document.createElement("div");
      body.className = "turn-body";
      body.textContent = turn.text || "";
      if (turn.interrupted) body.classList.add("interrupted");
      el.appendChild(body);
    }
    return el;
  }

  function toolResult(turn) {
    if (!turn.resolved) {
      const w = document.createElement("div");
      w.className = "tool-wait"; w.textContent = "running…";
      return w;
    }
    const label = turn.is_error ? "error" : "output";
    const det = collapsible(label, turn.result || "(no output)",
      turn.is_error);
    if (turn.result_truncated) det.classList.add("truncated");
    return det;
  }

  function collapsible(summary, text, open) {
    const det = document.createElement("details");
    det.className = "coll";
    if (open) det.open = true;
    const sm = document.createElement("summary");
    sm.textContent = summary;
    det.appendChild(sm);
    const pre = document.createElement("pre");
    pre.textContent = text;
    det.appendChild(pre);
    return det;
  }

  function patchTool(el, turn) {
    const sig = el.querySelector(".tool-sig");
    const wait = el.querySelector(".tool-wait");
    const det = el.querySelector("details");
    if (turn.resolved && (wait || !det)) {
      const fresh = toolResult(turn);
      if (wait) el.replaceChild(fresh, wait);
      else el.appendChild(fresh);
      el.classList.toggle("has-error", !!turn.is_error);
    }
    if (sig) sig.textContent = turn.input_summary || "";
  }

  return { init, update, toggleTerminal };
})();

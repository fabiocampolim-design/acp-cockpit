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
      // Text and the submitting Enter MUST be separate frames: Claude Code
      // treats "text\r" arriving as one burst as a bracketed paste and
      // inserts a newline instead of submitting (verified live).
      app.sendToPty(tab, text);
      app.sendToPty(tab, "\r");
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

    q(tab, ".term-toggle").addEventListener("click", () => toggleTerminal(app, tab));
    q(tab, ".esc-btn").addEventListener("click", () => app.sendToPty(tab, "\x1b"));
    tab.perm = { sig: null, stable: null };
  }

  function toggleTerminal(app, tab) {
    const raw = tab.pane.classList.toggle("rawterm");
    q(tab, ".term-toggle").textContent = raw ? "▤ Conversation" : "▤ Terminal";
    if (raw) { app.sendSize(tab, true); tab.term.focus(); }
    else tab.pane.querySelector(".composer-input")?.focus();
  }

  // ---- permission prompt, parsed from xterm's RENDERED buffer -----------
  // The raw pty byte stream is full of cursor-move redraws, so "lines" there
  // are not visual lines and options parse wrong (a real Yes/No/… prompt
  // once yielded only "3. No"). xterm has already resolved the redraws into
  // a grid, so we read the options from there. We only ever render buttons
  // when the parse is unambiguous AND stable across two polls, and we
  // re-verify at click time -- otherwise we tell the user to open the
  // terminal. Sending the wrong key here could approve a destructive action.
  const PROMPT_RE = /(do you want to|would you like to|do you want to proceed)/i;
  const OPT_RE = /^\s*[❯>▶*·-]?\s*([1-9])[.)]\s+(.+?)\s*$/;
  const FOOTER_RE = /(esc to cancel|tab to amend|shift\+tab)/i;

  function readPermission(tab) {
    const b = tab.term && tab.term.buffer && tab.term.buffer.active;
    if (!b) return null;
    const rows = [];
    for (let i = Math.max(0, b.length - 60); i < b.length; i++) {
      rows.push(b.getLine(i).translateToString(true));
    }
    let pi = -1;
    for (let i = rows.length - 1; i >= 0; i--) {
      if (PROMPT_RE.test(rows[i])) { pi = i; break; }
    }
    if (pi < 0) return null;
    const options = [];
    for (let i = pi + 1; i < rows.length; i++) {
      const m = rows[i].match(OPT_RE);
      if (m) options.push({ key: m[1], label: m[2].trim() });
    }
    // must be a clean, contiguous 1..n set of at least two options
    if (options.length < 2) return null;
    for (let k = 0; k < options.length; k++) {
      if (options[k].key !== String(k + 1)) return null;
    }
    const prompt = rows[pi].trim();
    const sig = prompt + "||" + options.map((o) => o.key + ":" + o.label).join("|");
    return { prompt, options, sig };
  }

  function renderPermission(app, tab) {
    const box = q(tab, ".perm");
    const now = readPermission(tab);
    // stability: only trust a parse seen identically twice in a row
    const stable = now && now.sig === tab.perm.sig ? now : null;
    tab.perm.sig = now ? now.sig : null;
    tab.perm.stable = stable;

    if (stable) {
      if (box.dataset.sig === stable.sig) { box.hidden = false; return; }
      box.dataset.sig = stable.sig;
      box.textContent = "";
      const p = document.createElement("div");
      p.className = "perm-q"; p.textContent = stable.prompt;
      box.appendChild(p);
      const row = document.createElement("div");
      row.className = "perm-row";
      for (const opt of stable.options) {
        const b = document.createElement("button");
        b.className = opt.key === "1" ? "primary" : "ghost";
        b.textContent = opt.key + ". " + opt.label;
        b.addEventListener("click", () => answerPermission(app, tab, opt));
        row.appendChild(b);
      }
      box.appendChild(row);
      box.hidden = false;
      return;
    }
    // a prompt is up (server says waiting) but we can't parse it safely:
    // never guess -- send the user to the terminal
    box.dataset.sig = "";
    if (tab.state === "waiting") {
      box.innerHTML = "";
      const w = document.createElement("div");
      w.className = "perm-q";
      w.textContent = "⚠ Claude is asking for confirmation. Open the terminal to answer:";
      box.appendChild(w);
      const t = document.createElement("button");
      t.className = "primary"; t.textContent = "▤ Open terminal";
      t.addEventListener("click", () => {
        if (!tab.pane.classList.contains("rawterm")) toggleTerminal(app, tab);
      });
      box.appendChild(t);
      box.hidden = false;
    } else {
      box.hidden = true;
    }
  }

  function answerPermission(app, tab, opt) {
    // re-verify against the CURRENT buffer: the key must still map to the
    // same label, or we refuse to send and fall back to the terminal
    const fresh = readPermission(tab);
    const match = fresh && fresh.options.find((o) => o.key === opt.key);
    if (!match || match.label !== opt.label) {
      renderPermission(app, tab);  // re-render (will show fallback/new options)
      return;
    }
    app.sendToPty(tab, opt.key);  // digit only; the menu confirms on the number
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

    renderPermission(app, tab);  // parsed client-side from xterm's buffer

    // surface any transcript records the parser did not recognise, so a
    // future Claude Code schema change is visible, never a silent drop
    const warn = q(tab, ".fidelity");
    const un = meta.unaccounted && Object.keys(meta.unaccounted).length;
    if (warn) {
      if (un) {
        warn.hidden = false;
        warn.textContent = "⚠ " + Object.values(meta.unaccounted)
          .reduce((a, b) => a + b, 0) + " unrecognized record(s)";
        warn.title = "record types not rendered: "
          + Object.keys(meta.unaccounted).join(", ");
      } else { warn.hidden = true; }
    }

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

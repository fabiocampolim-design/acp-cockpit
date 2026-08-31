// claudiu/static/app.js
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Fabio Campolim
"use strict";

window.Claudiu = {
  cfg: null,
  tabs: new Map(),
  activeId: null,

  async api(path, opts) {
    const resp = await fetch(path, Object.assign({
      headers: { "Content-Type": "application/json" },
    }, opts));
    if (resp.status === 204) return null;
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const err = new Error(body.error || `HTTP ${resp.status}`);
      err.status = resp.status;
      throw err;
    }
    return body;
  },

  applyTheme() {
    const t = this.cfg.theme;
    const root = document.documentElement.style;
    root.setProperty("--bg", t.background);
    root.setProperty("--fg", t.foreground);
    root.setProperty("--accent", t.blue);
  },

  tabList() { return Array.from(this.tabs.values()); },

  async openSession(body) {
    const info = await this.api("/api/sessions", {
      method: "POST", body: JSON.stringify(body),
    });
    this.openTab(info);
  },

  openTab(info) {
    const C = this;
    const el = document.createElement("button");
    el.className = "tab";
    el.innerHTML = '<span class="light"></span><span class="title"></span>' +
      '<span class="gauge" hidden><i></i></span><span class="pct"></span>' +
      '<span class="dot"></span>';
    el.querySelector(".title").textContent = info.title || info.id;
    el.addEventListener("click", () => C.activate(info.id));
    el.addEventListener("dblclick", () => window.ClaudiuUI?.renameTab(tab));
    document.getElementById("tabbar").appendChild(el);

    const pane = document.createElement("div");
    pane.className = "pane";
    pane.innerHTML = '<div class="strip reconnect">reconnecting…</div>' +
      '<div class="promptstrip" hidden title="your last prompt — click to expand">' +
      '<span class="mark">❯</span><span class="text"></span></div>' +
      '<div class="termhost"></div><div class="endstate"></div>';
    document.getElementById("panes").appendChild(pane);

    let fontSize = this.cfg.font_size;
    try {
      const saved = localStorage.getItem("claudiu-font-" + info.id);
      if (saved) fontSize = parseInt(saved, 10) || fontSize;
    } catch (e) { /* storage may be unavailable; default is fine */ }

    const term = new Terminal({
      fontFamily: this.cfg.font_family,
      fontSize: fontSize,
      theme: this.cfg.theme,
      scrollback: this.cfg.scrollback_lines,
      cursorBlink: false,
      cursorStyle: "bar",
      // bold text keeps its own colour instead of jumping to the bright
      // variant -- part of keeping the palette calm
      drawBoldTextInBrightColors: false,
    });
    const fit = new FitAddon.FitAddon();
    const search = new SearchAddon.SearchAddon();
    term.loadAddon(fit);
    term.loadAddon(search);
    term.loadAddon(new WebLinksAddon.WebLinksAddon());

    const tab = {
      id: info.id, title: info.title || info.id, cwd: info.cwd,
      args: info.args || [], ended: false, term, fit, search,
      ws: null, el, pane, attempts: 0, state: "unknown", lastSize: "",
    };
    this.tabs.set(info.id, tab);
    this.updateTabHints();
    term.open(pane.querySelector(".termhost"));
    // Every change of the terminal's box -- window resize, the prompt
    // strip appearing, the pane becoming visible -- goes through one
    // debounced path, so the pty sees the final size once instead of a
    // burst of intermediate ones (ConPTY repaints badly under a burst,
    // leaving Claude's UI drawn in only part of the pane).
    tab.observer = new ResizeObserver(() => C.scheduleResize(tab));
    tab.observer.observe(pane.querySelector(".termhost"));
    const strip = pane.querySelector(".promptstrip");
    strip.addEventListener("click", () => {
      strip.classList.toggle("expanded");
    });
    term.onData((d) => {
      if (tab.ws && tab.ws.readyState === WebSocket.OPEN) {
        tab.ws.send(JSON.stringify(["stdin", d]));
      }
    });
    this.connect(tab);
    this.activate(info.id);
    return tab;
  },

  connect(tab) {
    const C = this;
    const ws = new WebSocket(`ws://${location.host}/ws/${tab.id}`);
    tab.ws = ws;
    ws.onopen = () => {
      tab.attempts = 0;
      tab.pane.classList.remove("reconnecting");
      tab.term.reset(); // server replays its buffer from scratch
      // The replay burst that follows isn't new output the user hasn't
      // seen -- it's scrollback they already had. Suppress "unseen"
      // until it's had time to land.
      tab.replaying = true;
      setTimeout(() => { tab.replaying = false; }, 250);
      C.sendSize(tab, true); // a fresh connection always needs the size
    };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg[0] === "stdout") {
        tab.term.write(msg[1]);
        if (C.activeId !== tab.id && !tab.replaying) tab.el.classList.add("unseen");
      } else if (msg[0] === "disconnect") {
        C.markEnded(tab, msg[1]);
      }
    };
    ws.onclose = (ev) => {
      if (tab.ended || !C.tabs.has(tab.id)) return;
      if (ev.code === 4404) { C.markEnded(tab); return; }
      tab.pane.classList.add("reconnecting");
      const delay = Math.min(500 * 2 ** tab.attempts, 10000);
      tab.attempts += 1;
      setTimeout(() => {
        if (!tab.ended && C.tabs.has(tab.id)) C.connect(tab);
      }, delay);
    };
  },

  scheduleResize(tab) {
    clearTimeout(tab.resizeTimer);
    tab.resizeTimer = setTimeout(() => this.sendSize(tab), 120);
  },

  sendSize(tab, force) {
    // A hidden pane (display:none) proposes no dimensions; fitting it
    // would shrink the terminal to its minimum and resize the pty to
    // match -- exactly the half-drawn screen this guards against.
    const dims = tab.fit.proposeDimensions();
    if (!dims || !dims.rows || !dims.cols) return;
    tab.fit.fit();
    const size = tab.term.rows + "x" + tab.term.cols;
    if (!force && size === tab.lastSize) return;
    if (tab.ws && tab.ws.readyState === WebSocket.OPEN) {
      tab.lastSize = size;
      tab.ws.send(JSON.stringify(["set_size", tab.term.rows, tab.term.cols,
        tab.pane.clientHeight, tab.pane.clientWidth]));
    }
  },

  // ---- status strip: last prompt, busy/ready light, context gauge ----
  applyStatus(tab, st) {
    const prev = tab.state;
    tab.state = st.state;
    for (const s of ["busy", "ready", "unknown"]) {
      tab.el.classList.toggle("state-" + s, st.state === s);
    }
    // a turn finishing off-screen is the moment worth flagging
    if (prev === "busy" && st.state === "ready" && this.activeId !== tab.id) {
      tab.el.classList.add("unseen");
    }
    const strip = tab.pane.querySelector(".promptstrip");
    if (st.last_prompt) {
      strip.querySelector(".text").textContent = st.last_prompt;
      strip.hidden = false;
    } else {
      strip.hidden = true;
    }
    const gauge = tab.el.querySelector(".gauge");
    const pctEl = tab.el.querySelector(".pct");
    if (st.context_pct === null || st.context_pct === undefined) {
      gauge.hidden = true;
      pctEl.textContent = "";
      return;
    }
    const pct = Math.max(0, Math.min(100, st.context_pct));
    const level = pct >= this.cfg.context_danger_pct ? "danger"
      : pct >= this.cfg.context_warn_pct ? "warn" : "ok";
    gauge.className = "gauge ctx-" + level;
    gauge.hidden = false;
    gauge.querySelector("i").style.width = pct + "%";
    pctEl.textContent = Math.round(pct) + "%";
    const used = Math.round((st.context_tokens || 0) / 1000);
    const total = Math.round(this.cfg.context_window_tokens / 1000);
    gauge.title = pctEl.title =
      `context ${st.context_pct}% — ${used}k of ${total}k tokens`;
  },

  startStatusPolling() {
    const tick = async () => {
      if (!document.hidden && this.tabs.size) {
        try {
          const data = await this.api("/api/status");
          for (const [id, st] of Object.entries(data.sessions || {})) {
            const tab = this.tabs.get(id);
            if (tab && !tab.ended) this.applyStatus(tab, st);
          }
        } catch (e) { /* next tick retries; the terminal itself is unaffected */ }
      }
      setTimeout(tick, this.cfg.status_poll_ms);
    };
    tick();
  },

  markEnded(tab, code) {
    tab.ended = true;
    tab.exitCode = code === undefined ? null : code;
    tab.pane.classList.remove("reconnecting");
    tab.pane.classList.add("ended");
    window.ClaudiuUI?.fillEndState(tab);
  },

  activate(id) {
    const tab = this.tabs.get(id);
    if (!tab) return;
    this.activeId = id;
    for (const t of this.tabs.values()) {
      t.el.classList.toggle("active", t.id === id);
      t.pane.classList.toggle("active", t.id === id);
    }
    tab.el.classList.remove("unseen");
    requestAnimationFrame(() => { this.sendSize(tab); tab.term.focus(); });
  },

  // tooltips carry each tab's switch key (positions shift when tabs close)
  updateTabHints() {
    const sc = this.cfg.shortcuts;
    this.tabList().forEach((t, i) => {
      const key = sc["tab_" + (i + 1)];
      t.el.title = (key ? window.ClaudiuKeys.pretty(key) + " · " : "") +
        "double-click to rename";
    });
  },

  removeTab(id) { // removes the view only; the session keeps running
    const tab = this.tabs.get(id);
    if (!tab) return;
    tab.ended = true; // stop reconnect attempts
    if (tab.ws) tab.ws.close();
    if (tab.observer) tab.observer.disconnect();
    clearTimeout(tab.resizeTimer);
    tab.term.dispose();
    tab.el.remove();
    tab.pane.remove();
    this.tabs.delete(id);
    this.updateTabHints();
    const rest = this.tabList();
    if (rest.length) this.activate(rest[rest.length - 1].id);
    else this.activeId = null;
  },

  async killSession(id) {
    try {
      await this.api(`/api/sessions/${id}`, { method: "DELETE" });
    } catch (e) {
      if (e.status !== 404) { // anything but "already gone" keeps the tab
        window.ClaudiuUI?.alertBox("Could not kill session: " + e.message);
        return;
      }
    }
    this.removeTab(id);
  },

  sendText(text, send) {
    const tab = this.tabs.get(this.activeId);
    if (!tab || !tab.ws || tab.ws.readyState !== WebSocket.OPEN) return;
    tab.ws.send(JSON.stringify(["stdin", text + (send ? "\r" : "")]));
    tab.term.focus();
  },

  setFont(tab, delta) {
    if (!tab) return;
    let size = delta === 0 ? this.cfg.font_size
      : (tab.term.options.fontSize || this.cfg.font_size) + delta;
    size = Math.max(8, Math.min(40, size));
    tab.term.options.fontSize = size;
    try { localStorage.setItem("claudiu-font-" + tab.id, String(size)); }
    catch (e) { /* per-viewer convenience only */ }
    this.sendSize(tab);
  },

  handleShortcut(ev) {
    const sc = this.cfg.shortcuts;
    const active = this.tabs.get(this.activeId);
    const list = this.tabList();
    const idx = list.findIndex((t) => t.id === this.activeId);
    const acts = {
      tab_prev: () => idx > 0 && this.activate(list[idx - 1].id),
      tab_next: () => idx >= 0 && idx < list.length - 1 &&
        this.activate(list[idx + 1].id),
      new_session: () => window.ClaudiuUI?.openLauncher(),
      close_tab: () => active && window.ClaudiuUI?.confirmClose(active),
      font_bigger: () => this.setFont(active, +1),
      font_smaller: () => this.setFont(active, -1),
      font_reset: () => this.setFont(active, 0),
      search: () => active && window.ClaudiuUI?.openSearch(active),
      snippet_palette: () => window.ClaudiuUI?.openPalette(),
      help: () => window.ClaudiuUI?.openHelp(),
    };
    for (let n = 1; n <= 9; n++) {
      acts["tab_" + n] = () => list[n - 1] && this.activate(list[n - 1].id);
    }
    for (const [name, action] of Object.entries(acts)) {
      if (sc[name] && window.ClaudiuKeys.matches(ev, sc[name])) {
        ev.preventDefault();
        ev.stopPropagation();
        action();
        return;
      }
    }
  },

  async boot() {
    const data = await this.api("/api/config");
    this.cfg = data.config;
    this.applyTheme();
    window.ClaudiuUI?.init(this, data.warnings || []);
    window.addEventListener("keydown", (ev) => this.handleShortcut(ev), true);
    // window resizes reach each terminal through its ResizeObserver
    document.getElementById("newtab").addEventListener("click",
      () => window.ClaudiuUI?.openLauncher());
    const listed = await this.api("/api/sessions");
    for (const info of listed.sessions) this.openTab(info);
    if (!listed.sessions.length) window.ClaudiuUI?.openLauncher();
    this.startStatusPolling();
  },
};

document.addEventListener("DOMContentLoaded", () => {
  window.Claudiu.boot().catch((e) => {
    document.body.insertAdjacentHTML("beforeend",
      '<div class="overlay"><div class="dialog"><p></p></div></div>');
    document.querySelector(".overlay:last-child p").textContent =
      "CLAUDIU failed to start: " + e.message;
  });
});

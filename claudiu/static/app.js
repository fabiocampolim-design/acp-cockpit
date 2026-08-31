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
    el.innerHTML = '<span class="title"></span><span class="dot"></span>';
    el.querySelector(".title").textContent = info.title || info.id;
    el.addEventListener("click", () => C.activate(info.id));
    el.addEventListener("dblclick", () => window.ClaudiuUI?.renameTab(tab));
    document.getElementById("tabbar").appendChild(el);

    const pane = document.createElement("div");
    pane.className = "pane";
    pane.innerHTML = '<div class="strip reconnect">reconnecting…</div>' +
      '<div class="termhost"></div><div class="endstate"></div>';
    pane.querySelector(".termhost").style.height = "100%";
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
    });
    const fit = new FitAddon.FitAddon();
    const search = new SearchAddon.SearchAddon();
    term.loadAddon(fit);
    term.loadAddon(search);
    term.loadAddon(new WebLinksAddon.WebLinksAddon());

    const tab = {
      id: info.id, title: info.title || info.id, cwd: info.cwd,
      args: info.args || [], ended: false, term, fit, search,
      ws: null, el, pane, attempts: 0,
    };
    this.tabs.set(info.id, tab);
    term.open(pane.querySelector(".termhost"));
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
      C.sendSize(tab);
    };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg[0] === "stdout") {
        tab.term.write(msg[1]);
        if (C.activeId !== tab.id) tab.el.classList.add("unseen");
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

  sendSize(tab) {
    tab.fit.fit();
    if (tab.ws && tab.ws.readyState === WebSocket.OPEN) {
      tab.ws.send(JSON.stringify(["set_size", tab.term.rows, tab.term.cols,
        tab.pane.clientHeight, tab.pane.clientWidth]));
    }
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

  removeTab(id) { // removes the view only; the session keeps running
    const tab = this.tabs.get(id);
    if (!tab) return;
    tab.ended = true; // stop reconnect attempts
    if (tab.ws) tab.ws.close();
    tab.term.dispose();
    tab.el.remove();
    tab.pane.remove();
    this.tabs.delete(id);
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
    window.addEventListener("resize", () => {
      const tab = this.tabs.get(this.activeId);
      if (tab) this.sendSize(tab);
    });
    document.getElementById("newtab").addEventListener("click",
      () => window.ClaudiuUI?.openLauncher());
    const listed = await this.api("/api/sessions");
    for (const info of listed.sessions) this.openTab(info);
    if (!listed.sessions.length) window.ClaudiuUI?.openLauncher();
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

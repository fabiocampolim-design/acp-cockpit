// claudiu/static/ui.js
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Fabio Campolim
"use strict";
window.ClaudiuUI = (function () {
  let app = null;

  function el(id) { return document.getElementById(id); }
  function show(id) { el(id).hidden = false; }
  function hideAll() {
    for (const id of ["launcher", "palette", "search", "confirm"]) {
      el(id).hidden = true;
    }
    const tab = app && app.tabs.get(app.activeId);
    if (tab) tab.term.focus();
  }

  function choice(label, sub, onpick) {
    const b = document.createElement("button");
    b.className = "choice";
    b.innerHTML = "<span></span> <small></small>";
    b.querySelector("span").textContent = label;
    b.querySelector("small").textContent = sub || "";
    b.addEventListener("click", onpick);
    return b;
  }

  async function startSession(body) {
    hideAll();
    try { await app.openSession(body); }
    catch (e) { alertBox("Could not start session: " + e.message); }
  }

  function alertBox(text) {
    el("confirm-text").textContent = text;
    const row = el("confirm-buttons");
    row.textContent = "";
    const ok = document.createElement("button");
    ok.className = "primary";
    ok.textContent = "OK";
    ok.addEventListener("click", hideAll);
    row.appendChild(ok);
    show("confirm");
    ok.focus();
  }

  async function openLauncher() {
    hideAll();
    const projBox = el("launcher-projects");
    projBox.textContent = "";
    for (const p of app.cfg.projects) {
      projBox.appendChild(choice(p.name, p.path, () =>
        startSession({ path: p.path, args: p.args, title: p.name })));
    }
    if (!app.cfg.projects.length) {
      projBox.innerHTML = '<small class="hint">none configured — add "projects" to config.json</small>';
    }
    const resBox = el("launcher-resume");
    resBox.innerHTML = '<small class="hint">scanning…</small>';
    show("launcher");
    el("launcher-path").focus();
    try {
      const data = await app.api("/api/resume");
      resBox.textContent = "";
      // Skip projects whose directory no longer exists -- --resume would
      // just spawn `claude` nowhere usable.
      const found = data.projects.filter((p) => p.exists !== false);
      for (const proj of found.slice(0, 8)) {
        for (const s of proj.sessions.slice(0, 2)) {
          resBox.appendChild(choice(s.summary, proj.path, () =>
            startSession({ path: proj.path, args: ["--resume", s.id] })));
        }
      }
      if (!resBox.childNodes.length) {
        resBox.innerHTML = '<small class="hint">no recent sessions found</small>';
      }
    } catch (e) {
      resBox.innerHTML = '<small class="hint"></small>';
      resBox.querySelector("small").textContent = "scan failed: " + e.message;
    }
  }

  function openPalette() {
    hideAll();
    const input = el("palette-input");
    input.value = "";
    renderPalette("");
    show("palette");
    input.focus();
  }

  function fuzzyMatch(filter, text) {
    // Subsequence match: every char of filter appears in text, in order.
    let i = 0;
    for (const ch of text) {
      if (i < filter.length && ch === filter[i]) i++;
    }
    return i === filter.length;
  }

  function renderPalette(filter) {
    const list = el("palette-list");
    list.textContent = "";
    const f = filter.toLowerCase();
    for (const s of app.cfg.snippets) {
      if (f && !fuzzyMatch(f, s.name.toLowerCase()) &&
          !fuzzyMatch(f, s.text.toLowerCase())) continue;
      list.appendChild(choice(s.name, s.text.slice(0, 60), () => {
        hideAll();
        app.sendText(s.text, s.send);
      }));
    }
    if (!list.childNodes.length) {
      list.innerHTML = '<small class="hint">no matching snippets — add "snippets" to config.json</small>';
    }
  }

  function openSearch(tab) {
    hideAll();
    const input = el("search-input");
    input.value = "";
    input.onkeydown = (ev) => {
      if (ev.key === "Enter" && ev.shiftKey) {
        tab.search.findPrevious(input.value);
        ev.preventDefault();
      } else if (ev.key === "Enter") {
        tab.search.findNext(input.value);
        ev.preventDefault();
      }
    };
    show("search");
    input.focus();
  }

  function confirmClose(tab) {
    hideAll();
    el("confirm-text").textContent =
      `Close "${tab.title}"? The session keeps running unless you kill it.`;
    const row = el("confirm-buttons");
    row.textContent = "";
    const mk = (label, cls, fn) => {
      const b = document.createElement("button");
      b.className = cls;
      b.textContent = label;
      b.addEventListener("click", fn);
      row.appendChild(b);
      return b;
    };
    mk("Close view", "primary", () => { hideAll(); app.removeTab(tab.id); });
    mk("Kill session", "danger", () => { hideAll(); app.killSession(tab.id); });
    mk("Cancel", "ghost", hideAll);
    show("confirm");
  }

  function renameTab(tab) {
    const span = tab.el.querySelector(".title");
    span.contentEditable = "true";
    span.focus();
    document.getSelection().selectAllChildren(span);
    const done = async (commit) => {
      span.contentEditable = "false";
      const title = span.textContent.trim();
      if (commit && title && title !== tab.title) {
        try {
          await app.api(`/api/sessions/${tab.id}`, {
            method: "PATCH", body: JSON.stringify({ title }),
          });
          tab.title = title;
        } catch (e) {
          span.textContent = tab.title;
          alertBox("Rename failed: " + e.message);
        }
      } else {
        span.textContent = tab.title;
      }
    };
    span.onblur = () => done(true);
    span.onkeydown = (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); span.blur(); }
      if (ev.key === "Escape") { ev.preventDefault(); done(false); }
    };
  }

  function fillEndState(tab) {
    const box = tab.pane.querySelector(".endstate");
    box.textContent = "";
    const p = document.createElement("p");
    const code = tab.exitCode;
    p.textContent = (code === null || code === undefined)
      ? `session "${tab.title}" ended`
      : `session "${tab.title}" ended (exit ${code})`;
    box.appendChild(p);
    const row = document.createElement("div");
    row.className = "row";
    const mk = (label, cls, fn) => {
      const b = document.createElement("button");
      b.className = cls;
      b.textContent = label;
      b.addEventListener("click", fn);
      row.appendChild(b);
    };
    mk("Restart", "primary", async () => {
      try {
        await app.openSession({ path: tab.cwd, args: tab.args,
          title: tab.title });
        app.removeTab(tab.id);
      } catch (e) { alertBox("Restart failed: " + e.message); }
    });
    mk("Resume", "ghost", async () => {
      try {
        const data = await app.api("/api/resume");
        const proj = data.projects.find((pr) => pr.path === tab.cwd);
        if (!proj || !proj.sessions.length) {
          alertBox("No recent session found for " + tab.cwd);
          return;
        }
        await app.openSession({ path: tab.cwd,
          args: ["--resume", proj.sessions[0].id], title: tab.title });
        app.removeTab(tab.id);
      } catch (e) { alertBox("Resume failed: " + e.message); }
    });
    mk("Close", "ghost", () => app.removeTab(tab.id));
    box.appendChild(row);
  }

  function init(appRef, warnings) {
    app = appRef;
    const bar = el("snippetbar");
    for (const s of app.cfg.snippets) {
      const b = document.createElement("button");
      b.className = "snippet";
      b.textContent = s.name;
      b.title = s.text;
      b.addEventListener("click", () => app.sendText(s.text, s.send));
      bar.appendChild(b);
    }
    el("palette-input").addEventListener("input",
      (ev) => renderPalette(ev.target.value));
    el("launcher-start").addEventListener("click", () => {
      const path = el("launcher-path").value.trim();
      if (path) startSession({ path });
    });
    el("launcher-path").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") el("launcher-start").click();
    });
    window.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") hideAll();
    });
    for (const w of warnings) console.warn("[claudiu config]", w);
  }

  return { init, openLauncher, openPalette, openSearch, confirmClose,
    renameTab, fillEndState, alertBox };
})();

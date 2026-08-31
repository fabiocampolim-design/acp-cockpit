// claudiu/static/ui.js
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Fabio Campolim
"use strict";
window.ClaudiuUI = (function () {
  let app = null;

  function el(id) { return document.getElementById(id); }
  function show(id) { el(id).hidden = false; }
  const OVERLAYS = ["launcher", "palette", "search", "confirm", "help"];

  function hideAll() {
    for (const id of OVERLAYS) el(id).hidden = true;
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

  let browsePath = null;  // folder currently shown in the picker

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
    el("launcher-browser").hidden = true;  // start collapsed
    el("launcher-path").value = "";
    populateRecent();
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
      for (const proj of found) {
        for (const s of proj.sessions.slice(0, 3)) {
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

  async function populateRecent() {
    const sel = el("launcher-recent");
    sel.innerHTML = "";
    let items = [];
    try { items = (await app.api("/api/recent")).recent || []; }
    catch (e) { /* dropdown is a convenience; ignore */ }
    if (!items.length) {
      const o = document.createElement("option");
      o.textContent = "Recent folders — none yet"; o.disabled = true;
      o.selected = true; sel.appendChild(o); sel.disabled = true;
      return;
    }
    sel.disabled = false;
    const head = document.createElement("option");
    head.value = ""; head.textContent = "Recent folders…"; head.selected = true;
    sel.appendChild(head);
    for (const it of items) {
      const o = document.createElement("option");
      o.value = it.path; o.textContent = `${it.name}  —  ${it.path}`;
      sel.appendChild(o);
    }
  }

  function toggleBrowser() {
    const box = el("launcher-browser");
    box.hidden = !box.hidden;
    if (!box.hidden) browseTo(el("launcher-path").value.trim());
  }

  async function browseTo(path) {
    const box = el("launcher-dirs");
    box.innerHTML = '<small class="hint">scanning…</small>';
    let data;
    try { data = await app.api("/api/dirs?path=" + encodeURIComponent(path || "")); }
    catch (e) { box.innerHTML = ""; box.textContent = "could not read: " + e.message; return; }
    browsePath = data.path || "";
    if (browsePath) el("launcher-path").value = browsePath;
    el("launcher-crumb").textContent = data.path || "This PC (drives)";
    el("launcher-usehere").disabled = !browsePath;
    el("launcher-newfolder").disabled = !browsePath;
    box.textContent = "";
    if (data.parent !== null && data.parent !== undefined) {
      box.appendChild(choice("⬆  ..", "up one level", () => browseTo(data.parent)));
    }
    for (const d of data.dirs) {
      box.appendChild(choice("📁  " + d.name, "", () => browseTo(d.path)));
    }
    if (data.error) {
      const s = document.createElement("small");
      s.className = "hint"; s.textContent = data.error; box.appendChild(s);
    } else if (!data.dirs.length && data.parent === null) {
      box.innerHTML = '<small class="hint">no drives found</small>';
    } else if (!data.dirs.length) {
      const s = document.createElement("small");
      s.className = "hint"; s.textContent = "no sub-folders here";
      box.appendChild(s);
    }
  }

  function newFolder() {
    if (!browsePath) return;
    const box = el("launcher-dirs");
    const row = document.createElement("div");
    row.className = "row newfolder";
    const input = document.createElement("input");
    input.placeholder = "new folder name";
    const ok = document.createElement("button");
    ok.className = "primary"; ok.textContent = "Create";
    const cancel = document.createElement("button");
    cancel.className = "ghost"; cancel.textContent = "Cancel";
    row.append(input, ok, cancel);
    box.prepend(row);
    input.focus();
    const create = async () => {
      const name = input.value.trim();
      if (!name) { input.focus(); return; }
      try {
        const res = await app.api("/api/mkdir", {
          method: "POST",
          body: JSON.stringify({ parent: browsePath, name }),
        });
        browseTo(res.path);  // step into the folder just created
      } catch (e) { alertBox("Could not create folder: " + e.message); }
    };
    ok.addEventListener("click", create);
    cancel.addEventListener("click", () => row.remove());
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); create(); }
      if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); row.remove(); }
    });
  }

  // human labels for the config "shortcuts" keys; tab_1..tab_9 collapse
  // into one row.
  const SHORTCUT_LABELS = [
    ["tab_1", "switch to tab 1 … 9"], ["tab_prev", "previous tab"],
    ["tab_next", "next tab"], ["new_session", "new session"],
    ["close_tab", "close tab"], ["search", "search scrollback"],
    ["snippet_palette", "snippet palette"], ["font_bigger", "font bigger"],
    ["font_smaller", "font smaller"], ["font_reset", "font reset"],
    ["help", "this list"],
  ];

  function shortcutRows() {
    const sc = app.cfg.shortcuts;
    const pretty = window.ClaudiuKeys.pretty;
    return SHORTCUT_LABELS
      .filter(([name]) => sc[name])
      .map(([name, label]) => {
        const keys = name === "tab_1" && sc.tab_9
          ? [pretty(sc.tab_1), "…", pretty(sc.tab_9)] : [pretty(sc[name])];
        return { label, keys };
      });
  }

  function openHelp() {
    hideAll();
    const table = el("help-table");
    table.textContent = "";
    for (const row of shortcutRows()) {
      const tr = document.createElement("tr");
      const keysTd = document.createElement("td");
      for (const k of row.keys) {
        if (k === "…") { keysTd.append(" … "); continue; }
        const kbd = document.createElement("kbd");
        kbd.textContent = k;
        keysTd.appendChild(kbd);
      }
      const labelTd = document.createElement("td");
      labelTd.textContent = row.label;
      tr.append(keysTd, labelTd);
      table.appendChild(tr);
    }
    show("help");
    el("help-dialog").focus(); // keystrokes must not fall through to the pty
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
    // discoverability: the launcher auto-opens on first load, so it is the
    // one place every user sees; the title bar buttons reflect remaps too.
    const sc = app.cfg.shortcuts;
    const pretty = window.ClaudiuKeys.pretty;
    const hint = ["Esc closes"];
    if (sc.tab_1 && sc.tab_9) {
      hint.push(`${pretty(sc.tab_1)}…${pretty(sc.tab_9)} switch tabs`);
    }
    if (sc.help) hint.push(`${pretty(sc.help)} lists every shortcut`);
    el("launcher-hint").textContent = hint.join(" · ");
    if (sc.new_session) {
      el("newtab").title = `New session (${pretty(sc.new_session)})`;
    }
    if (sc.help) el("helpbtn").title = `Keyboard shortcuts (${pretty(sc.help)})`;
    el("helpbtn").addEventListener("click", openHelp);
    el("palette-input").addEventListener("input",
      (ev) => renderPalette(ev.target.value));
    el("launcher-start").addEventListener("click", () => {
      const path = el("launcher-path").value.trim();
      if (path) startSession({ path });
    });
    el("launcher-path").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") el("launcher-start").click();
    });
    el("launcher-browse").addEventListener("click", toggleBrowser);
    el("launcher-usehere").addEventListener("click", () => {
      if (browsePath) startSession({ path: browsePath });
    });
    el("launcher-newfolder").addEventListener("click", newFolder);
    el("launcher-recent").addEventListener("change", (ev) => {
      if (ev.target.value) {
        el("launcher-path").value = ev.target.value;
        ev.target.selectedIndex = 0;  // back to the "Recent folders…" header
        el("launcher-path").focus();
      }
    });
    // Capture phase: with a terminal focused, xterm.js handles Escape on
    // its textarea and stops propagation, so a bubble-phase listener
    // would never see it and no overlay could be closed by key.
    window.addEventListener("keydown", (ev) => {
      if (ev.key !== "Escape") return;
      if (!OVERLAYS.some((id) => !el(id).hidden)) return;
      ev.preventDefault();
      ev.stopPropagation();
      hideAll();
    }, true);
    for (const w of warnings) console.warn("[claudiu config]", w);
  }

  return { init, openLauncher, openPalette, openSearch, openHelp,
    confirmClose, renameTab, fillEndState, alertBox };
})();

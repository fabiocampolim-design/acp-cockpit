# Changelog

All notable changes to CLAUDIU are documented in this file.

## 0.1.0 — 2026-08-30

Initial release.

- Local Tornado server binding `127.0.0.1` only, spawning `claude` CLI
  sessions in pseudo-terminals (ConPTY on Windows) via Terminado.
- Browser tabbed interface (vanilla HTML/CSS/JS, vendored xterm.js — no
  build step, no CDN dependency at runtime) with full terminal fidelity per
  tab.
- Sessions survive browser refresh/close; websocket reconnect with backoff
  and a visible "reconnecting…" strip; one dead session never disturbs
  another.
- Resume scanner over `~/.claude/projects` offering one-click
  `claude --resume` after a crash.
- Snippets bar and fuzzy-searchable palette (`Ctrl+k`); configurable
  project launcher.
- Per-tab adjustable font size (remembered in `localStorage`); scrollback
  search with highlighting; rename a tab by double-click.
- Calm, low-contrast dark theme, fully driven by config values.
- One human-editable JSON config file (`~/.claudiu/config.json`, or
  `$CLAUDIU_CONFIG`) covering port, `claude` command, buffer caps, fonts,
  theme, shortcuts, projects, and snippets.
- Per-run audit log (command line, versions, warnings, outcome);
  `--verbose`/`--quiet`/`--log-dir`.
- REST API (`/api/sessions`, `/api/config`, `/api/resume`) and one
  websocket per tab (`/ws/<id>`, terminado protocol).
- Full test suite (unit, integration, end-to-end via Playwright, docs and
  licence guards) green with pyflakes on Windows, Linux, and macOS CI.
- `docs/build_manual.py`: renders `docs/USER_MANUAL.md` to a committed
  `USER_MANUAL.html` (and `.pdf` when pandoc + xelatex are on PATH), with a
  stdlib-only Markdown fallback when they are not.
- `CITATION.cff` for citing the software.

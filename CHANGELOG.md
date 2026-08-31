# Changelog

All notable changes to CLAUDIU are documented in this file.

## Unreleased

- Shortcut discoverability: a `?` button in the tab bar and `Alt+h` open a
  help overlay rendered from the live `shortcuts` config; tab tooltips
  name their switch key; the launcher footer hints at tab switching and
  the help key. Single-letter keys display upper-case (`Alt+H`).
- Sessions spawned by CLAUDIU no longer inherit Claude Code's nested-session
  environment markers when the server itself was launched from inside a
  Claude Code session, so the CLI keeps transcript saving on (it used to
  warn "Transcript saving is off — inherited CLAUDE_CODE_CHILD_SESSION
  marker").
- Favicon (`favicon.svg`); `/favicon.ico` redirects to it instead of
  logging a 404 warning on every page load.
- Tests: vendored publication-conformance checker (`tests/conformance.py`)
  with a wiring test that runs it against the repo in CI.

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

### Deferred to a follow-up

- A `~/.claude/keybindings.json` helper (spec-listed) that would keep
  CLAUDIU's shortcuts and Claude Code's own keybindings from colliding —
  intentionally not in this release.
- A light theme — only the calm dark theme ships; `theme` is fully
  config-driven so a light palette can be supplied by hand today.

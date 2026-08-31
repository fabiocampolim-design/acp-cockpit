# CLAUDIU — Browser interface for Claude Code sessions — Design

*Working codename: CLAUDIU (never ships; public name chosen later in the
publication playbook's Phase 3 with a GitHub + PyPI collision check, Fabio
decides).*

Date: 2026-08-30. Status: **approved by Fabio** (brainstorming session,
sections 1–3 each approved individually).

## Problem

Working with Claude Code in terminal windows causes real physical strain:
tiny fonts, endless scroll, harsh colors, no tabs, and interfaces that crash
or lose sessions. Fabio needs a stable, eye-friendly, keyboard-driven
interface for running **several Claude Code sessions at once**, built to be
published on GitHub to the claude-session-publisher standard (the
publication playbook — the author's internal repo-publishing standard).

## Decisions made (with Fabio, 2026-08-30)

1. **Form factor:** local web app in the browser. A Python server on the PC;
   Chrome opens `http://localhost:<port>`.
2. **Fidelity:** terminal-in-browser. Each tab embeds a real interactive
   `claude` process rendered by xterm.js — 100% identical CLI behavior
   (skills, plugins, slash commands, permission prompts). The browser layer
   adds tabs, fonts, themes, shortcuts; it does not reinterpret the stream.
3. **Server core:** Python + **Terminado** (Jupyter's terminal-over-WebSocket
   component, on Tornado) + **pywinpty** (ConPTY on Windows). No from-scratch
   PTY plumbing; no Node.js.
4. **Shortcuts wanted (all four):** interface keyboard shortcuts, prompt
   snippet buttons/palette, project launchers, and help configuring Claude
   Code's own `~/.claude/keybindings.json`.
5. **Eye comfort:** dark low-contrast default theme; reduced visual noise.
   Font default ~16px monospace, per-tab adjustable.
6. **Resilience (all four):** sessions survive browser refresh/close;
   post-crash resume list; one dead session never affects the server or
   other tabs; long sessions stay fast via capped scrollback.

## Architecture

```
Chrome ── http://localhost:8642 ──────────────────────────┐
  │  index.html + app.js + xterm.js  (static, no build step)
  │
  ├─ REST  /api/sessions, /api/projects, /api/snippets, /api/resume
  └─ WebSocket /ws/<session-id>  (one per tab)
                     │
              Python server (Tornado + Terminado)
                     │
       SessionManager ── one ConPTY per session ── claude.exe
                     └─ per-session ring buffer (capped scrollback)
```

One Python process; one page in Chrome. Sessions and their scrollback live
in the **server**; the browser is a disposable view.

## Components

Each has one job, a clear interface, and is testable alone.

1. **Server app (`app.py`)** — Tornado application: serves the static
   frontend, the REST API, and the per-session WebSockets. Port fixed by
   default (e.g. 8642), configurable. Binds to localhost only.
2. **SessionManager (`sessions.py`)** — creates and kills `claude` processes
   in ConPTYs via terminado/pywinpty. Holds a capped ring buffer of each
   session's raw output (default ~10k lines, configurable) and replays it to
   a (re)connecting browser. Sessions exist independently of any browser
   connection. Each session's handling is exception-walled: a failure marks
   that session dead and never propagates.
3. **Resume scanner (`resume.py`)** — reads `~/.claude/projects/` metadata to
   list recent Claude Code sessions per project directory, so the UI can
   offer one-click `claude --resume <session-id>` in the right folder after
   a browser/PC crash. Unknown/new record types are counted and reported,
   never dropped silently (publication-playbook rule 14).
4. **Config (`config.py`)** — one human-editable JSON file: projects list,
   snippets, keyboard shortcut map, theme values, font size, port,
   scrollback cap, claude executable path. Default location in the home
   directory with an environment-variable override (rule 11 pattern). This
   file is what gets committed to GitHub to sync the setup across machines.
5. **Frontend (`static/`)** — plain HTML/CSS/vanilla JS. xterm.js plus the
   fit, search, and web-links addons, **vendored** into the repo (pinned
   versions, no CDN dependency at runtime, no npm, no bundler). No
   framework. All interface state that matters lives server-side.

## Interface & UX

**Tabs.** Slim tab bar; one tab per live session, named by project folder
(renamable). `+` opens the project launcher. A tab with unseen output shows
a subtle static dot — nothing flashes or moves.

**Keyboard shortcuts** (interface-level; all remappable in config):

| Key | Action |
|---|---|
| `Alt+1`…`Alt+9` | switch to tab N |
| `Alt+Left` / `Alt+Right` | previous / next tab |
| `Alt+T` | new session (launcher dialog) |
| `Alt+W` | close tab — asks; killing the session requires explicit confirm, closing only the view leaves it running |
| `Alt+=` / `Alt+-` / `Alt+0` | font size per tab, persisted |
| `Ctrl+Shift+F` | search scrollback (highlighting) |
| `Ctrl+K` | snippet palette |

Defaults are Alt-based deliberately: Chrome **reserves** `Ctrl+T`,
`Ctrl+W`, `Ctrl+Tab` and `Ctrl+1..9` at browser level — a page cannot
intercept them, so they must never be interface defaults. Shortcut keys the
CLI needs (plain `Ctrl+C`, `Ctrl+R`, arrows, …) are never intercepted; the
config lets Fabio remap any collision found in practice, and the manual
documents which keys the browser owns.

**Snippets.** `"snippets": [{"name": ..., "text": ..., "send": bool}]` in
config. Shown as a discreet bar under the tab strip and in a
fuzzy-searchable palette (`Ctrl+K`). Choosing one types the text into the
active session; `send: true` also presses Enter.

**Project launcher.** Config lists working folders (`name`, `path`, optional
startup args such as `--continue`). New-session dialog shows that list plus
a browse option; one click starts `claude` in the chosen directory. A
second list shows recent resumable sessions per project (from the resume
scanner), each starting `claude --resume <id>`.

**Theme ("for the eyes").** Dark, low-contrast default: near-black (not
pure-black) background, warm-gray (not white) foreground, muted ANSI
palette, generous line-height and padding, steady (non-blinking) cursor.
All colors are CSS custom properties driven by the config file — every
value tunable and committable. A light theme is out of scope for v1
(recorded decision). Default font ~16px monospace; browser zoom works on
top of everything.

**Claude Code keybindings.** Separate small deliverable after the app runs:
configure `~/.claude/keybindings.json` (via the keybindings-help skill) and
commit that file alongside the app config.

## Data flow

Page load → `GET /api/sessions` → render tab bar → for each open tab,
connect its WebSocket → server replays the ring buffer → live PTY output
streams to xterm.js. Keystrokes go browser → WebSocket → PTY. Resize events
(fit addon) go to the PTY so `claude` always sees the true terminal size.
Creating a session: `POST /api/sessions {project, args}` → SessionManager
spawns `claude` in a ConPTY → returns session id → frontend opens the tab
and its WebSocket.

## Error handling & resilience

- **Browser refresh/close:** server-side sessions unaffected; reconnect
  replays scrollback. WebSocket drops auto-reconnect with backoff behind a
  visible "reconnecting…" strip — never a silent freeze.
- **PC/Chrome crash:** on next start, the resume scanner's list offers
  one-click `--resume` per recent session.
- **Session death:** the tab flips to a calm state — "session ended
  (exit N) — [Restart] [Resume] [Close]" — other tabs and the server are
  untouched.
- **Server:** single process started from a `.bat`/shortcut; localhost-only.
  Every REST/WS failure surfaces as a human-readable message in the UI,
  never a blank page. An audit log per run (rule 12): command line,
  versions, warnings, outcome; `--verbose`/`--quiet`; `--log-dir`.
- **Long sessions:** ring buffer and xterm scrollback both capped
  (configurable); search operates within the cap. Full-history archiving
  stays claude-session-publisher's job (recorded decision, YAGNI).

## Testing (publication-playbook rules 5, 14, 15)

- **Unit:** config load/validate/defaults; ring buffer (wrap, replay,
  cap); resume scanner against synthetic `~/.claude/projects` fixtures
  (including an unknown record type, asserting it is counted not dropped).
- **Integration:** spawn a real PTY running a harmless command; assert
  round-trip I/O, resize, and buffer replay on reconnect. Runs on all CI
  OSes (this is what proves the terminado layer per platform).
- **End-to-end (artefact, not return code):** Playwright loads the page,
  opens a session, types, and asserts the rendered terminal text — reading
  the produced screen back, per rule 14.
- **Docs guards:** tests fail when a config key, REST endpoint, or default
  shortcut is missing from `docs/USER_MANUAL.md` or `AGENTS.md`, and when
  the README's stated check count drifts (rule 15).
- **Static:** pyflakes over the whole tree as its own CI step before the
  suite (rule 5). CI: GitHub Actions on Windows + Linux + macOS.

## Publishing plan (publication-playbook phases)

Developed in a local working folder under the working codename. Then:
Phase 1 audit → Phase 2 harden → Phase 3 naming (GitHub +
PyPI collision check; Fabio decides) → Phase 4 README as product page
(badges, honest neighbour comparison — ttyd, Wetty, VS Code terminal,
existing Claude web UIs — showcase, CRediT table) → Phase 5 repo mechanics
(private first; noreply author identity; Apache-2.0 + NOTICE + SPDX
headers; `### Disclaimer` and non-affiliation note — Anthropic/Claude named
only to identify what the tool talks to) → Phase 6 after-publishing.
`VERSION`, `CHANGELOG.md`, annotated tags, GitHub Releases via `gh`. Enters
the publication playbook's queue as a new row. PyPI publication evaluated per rule S10
(decision recorded either way).

## Out of scope for v1 (recorded decisions, not omissions)

- Split panes / multiple windows; remote access from other devices;
  multi-user or session sharing.
- Transcript rendering/export (claude-session-publisher owns it).
- Light/sepia theme (config makes it possible later; not built now).
- Reinterpreting Claude output into rich widgets (the terminal-in-browser
  fidelity decision supersedes it).
- Linux/macOS interactive polish beyond CI-proven basics (the server and
  tests run there; Fabio's daily platform is Windows).

## Success criteria

1. Several `claude` sessions run side by side in tabs; behavior identical
   to the plain CLI.
2. Closing/refreshing Chrome loses nothing; a PC crash costs at most one
   click per session to resume.
3. One session dying never disturbs another; the page never freezes on
   hours of output.
4. Everything reachable by keyboard; snippets and project launches are one
   action each.
5. Fabio can look at it for hours without eye strain — and every visual
   parameter he'd want to tune is one committed config line away.
6. The repo passes the publication playbook's bar: suite + pyflakes green on 3 OSes,
   manual + AGENTS.md guarded by tests, licence/disclaimer guards in place.

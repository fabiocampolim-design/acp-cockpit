# AGENTS.md — machine-oriented reference for CLAUDIU

This file is for coding agents (and humans in a hurry) working on this
repository. It is a complete, literal description of the app's surface —
config keys, HTTP/WS routes, CLI flags, file map, and test commands — kept
in sync with the code by the guard tests in `tests/test_docs_guards.py`.
For prose explanations and screenshots-in-words, see
`docs/USER_MANUAL.md`.

## What this is

CLAUDIU (working codename) is a local Tornado web server that runs one or
more `claude` CLI processes in ConPTYs/PTYs and exposes them as tabs in a
browser page, via xterm.js on the frontend and Terminado on the backend.
Single Python package `claudiu/`, no build step, no bundler.

## Run it

```
pip install -e .
python -m claudiu
```

or, on Windows, double-click `run_claudiu.bat`. The server binds
`127.0.0.1` only and opens the default browser at
`http://127.0.0.1:<port>/` unless `--no-browser` is given.

## Config

One JSON file, human-editable. Default location `~/.claudiu/config.json`
(created with defaults on first run if missing); override the path with the
`CLAUDIU_CONFIG` environment variable or the `--config` flag. Unknown keys
in the file are kept as-is and reported as a warning, never rejected.

Every key of `claudiu.config.DEFAULTS`:

| Key | Default | Meaning |
|---|---|---|
| `port` | `8642` | TCP port the server listens on (127.0.0.1 only) |
| `claude_command` | `["claude"]` | argv used to spawn each session; a list so extra fixed arguments can be prepended |
| `replay_chunks` | `2000` | max buffered output chunks per session, replayed to a (re)connecting websocket |
| `scrollback_lines` | `10000` | xterm.js scrollback cap in the browser |
| `font_size` | `16` | default terminal font size in px |
| `font_family` | `"Consolas, 'Cascadia Mono', monospace"` | terminal font stack |
| `theme` | 16-color xterm theme object | background/foreground/cursor/selection and the 16 ANSI colors, all CSS-color strings |
| `claude_theme` | `"dark-ansi"` | appended to every spawn as `--settings {"theme": ...}` unless the caller passes `--settings`; `""` disables. Only the `*-ansi` Claude Code themes route through `theme` -- the others print truecolor |
| `status_poll_ms` | `2000` | browser poll interval for `GET /api/status` |
| `context_window_tokens` | `200000` | denominator of the context gauge |
| `context_warn_pct` | `50` | gauge amber threshold (percent) |
| `context_danger_pct` | `75` | gauge red threshold (percent), must be >= `context_warn_pct` |
| `ui_theme` | `"system"` | chrome theme: `system` / `light` / `dark`; a per-browser toggle overrides it in localStorage |
| `permission_patterns` | list of 4 | substrings that flag a busy session as `waiting` when found in its pty output (ANSI stripped, caseless) |
| `recent_max` | `15` | cap on `~/.claudiu/recent.json` |
| `shortcuts` | see Shortcuts table below | interface keyboard shortcut map |
| `projects` | `[]` | list of `{"name", "path", "args": []}` launcher entries |
| `snippets` | `[]` | list of `{"name", "text", "send": false}` prompt-snippet entries |

Validation (`claudiu.config._validate`): `port` must be an int in
1–65535; `claude_command` a non-empty list of strings (a bare string is
coerced to a one-element list); `replay_chunks`, `scrollback_lines`,
`font_size`, `status_poll_ms`, `context_window_tokens` positive ints;
`recent_max` positive int; `context_warn_pct` <= `context_danger_pct`,
both ints in 0-100; `ui_theme` one of system/light/dark;
`permission_patterns` a list of strings; `claude_theme` a string; `theme` and `shortcuts` must be JSON objects;
each `projects[i]` needs `name` and `path` (`args` defaults to `[]`); each
`snippets[i]` needs `name` and `text` (`send` defaults to `false`).

## Shortcuts (`DEFAULTS["shortcuts"]`)

| Action | Default key |
|---|---|
| `tab_1` … `tab_9` | `Alt+1` … `Alt+9` |
| `tab_prev` | `Alt+ArrowLeft` |
| `tab_next` | `Alt+ArrowRight` |
| `new_session` | `Alt+t` |
| `close_tab` | `Alt+w` |
| `font_bigger` | `Alt+=` |
| `font_smaller` | `Alt+-` |
| `font_reset` | `Alt+0` |
| `search` | `Ctrl+Shift+f` |
| `snippet_palette` | `Ctrl+k` |

All remappable in config. Never bind a shortcut to bare `Escape`: the
shortcut handler runs in the capture phase and would suppress the
dialog-closing `Escape` handler in `static/ui.js`.

## Routes (`claudiu.app.ROUTES`)

| Route | Description |
|---|---|
| `GET /api/sessions` | list live sessions |
| `POST /api/sessions` | create a session (body: path, args, title) |
| `PATCH /api/sessions/<id>` | rename a session (body: title) |
| `DELETE /api/sessions/<id>` | kill a session |
| `GET /api/config` | effective config plus load warnings |
| `GET /api/resume` | recent resumable Claude sessions |
| `GET /api/status` | per-session status: last prompt, busy/ready, context use |
| `GET /api/conversation` | controlled conversation model for a session (query: id) |
| `GET /api/recent` | recently launched folders (`~/.claudiu/recent.json`) |
| `GET /api/dirs` | list sub-directories of a path (launcher folder picker) |
| `POST /api/mkdir` | create a folder (body: parent, name) |
| `WS /ws/<id>` | terminal stream (terminado protocol) |

`GET /api/resume` scans the real `~/.claude/projects` directory of the
user running the server — not a fixture, not the browser's user.

`GET /api/status` returns `{"sessions": {<id>: status}}` for live sessions,
where status is `{exists, state: busy|ready|unknown, last_prompt,
context_tokens, context_pct, mtime}` read by `claudiu.status.read_status`
from the tail of the session's transcript
(`~/.claude/projects/<slug>/<session_id>.jsonl`). `SessionManager.build_argv`
pins that id by appending `--session-id <uuid4>` to every spawn that does
not already carry `--session-id`/`--resume <id>`/`--continue`; the file is
located lazily (`find_transcript`) and re-read only when its mtime/size
changes. The slug is the absolute cwd with every non-alphanumeric character
replaced by `-` (`claudiu.status.project_slug`).

`GET /api/conversation?id=<sid>` (`claudiu.sessions.conversation` ->
`claudiu.conversation.parse_conversation`) returns `{exists, meta, turns,
title, permission}`: turns are typed (`human`/`assistant`/`thinking`/`tool`/
`event`/`compact`, tool turns paired with their result by `tool_use_id`,
sidechain turns flagged `sub`), parsing is cached by (mtime,size), and the
pty-derived `title` (OSC 0/2 via `status.window_title`) and `permission`
(`status.parse_permission`) are always fresh. The browser renders it in
`static/convo.js`; the raw xterm terminal is hidden behind a "Show terminal"
toggle and only drives stdin + the escape hatch.

`GET /api/dirs?path=` (`claudiu.browse.list_dirs`) lists a folder's
sub-directories plus its parent; an empty path lists drive roots on
Windows. `POST /api/mkdir` (`claudiu.browse.make_dir`) creates one folder
under an existing parent (rejects separators). `GET /api/recent`
(`claudiu.recent`) reads `~/.claudiu/recent.json`, which `POST
/api/sessions` appends to on every launch. The `waiting` status is added
by `claudiu.status.apply_permission`, which scans the session's replay
buffer tail for `permission_patterns` (the transcript has no blocked-prompt
record).

Everything else (`GET /(.*)`) is served as a static file from
`claudiu/static/`, `index.html` as the default document.

## CLI flags (`claudiu.cli.build_parser`)

| Flag | Help |
|---|---|
| `--config` | path to config.json (default: `~/.claudiu/config.json`, or `$CLAUDIU_CONFIG`) |
| `--port` | override the config port (config default: 8642) |
| `--log-dir` | directory for audit logs (default: `<config dir>/logs`) |
| `--no-browser` | do not open the browser automatically |
| `--verbose` | debug output on the console |
| `--quiet` | warnings and errors only on the console |
| `--version` | print `claudiu <VERSION>` and exit |
| `--help` | argparse's automatic help flag; prints the argument summary and exits |

## File map

```
claudiu/__init__.py      VERSION
claudiu/__main__.py      `python -m claudiu` entry point
claudiu/cli.py            argument parsing, audit logging, server startup
claudiu/app.py             Tornado application, ROUTES, REST handlers
claudiu/sessions.py       SessionManager: ConPTYs, replay buffers, metadata
claudiu/resume.py           ~/.claude/projects scanner for --resume lists
claudiu/status.py           transcript-tail reader: last prompt, busy/ready/waiting, context; OSC title; permission parse
claudiu/conversation.py     full transcript parser -> typed turns for the conversation view
claudiu/recent.py           recently launched folders (~/.claudiu/recent.json)
claudiu/browse.py           launcher folder picker: list_dirs + make_dir
claudiu/static/           index.html, app.js, ui.js, convo.js, keys.js, app.css
claudiu/static/vendor/    pinned xterm.js + addons (see VENDORED.md)
docs/USER_MANUAL.md       human-oriented manual
docs/build_manual.py       renders USER_MANUAL.md to USER_MANUAL.html/.pdf
docs/superpowers/         design specification and implementation plan (historical record)
tests/                    unit, integration, e2e, docs/licence guard tests
run_claudiu.bat           Windows double-click launcher
```

## Rebuilding the manual

`docs/USER_MANUAL.md` is the source of truth; the committed
`docs/USER_MANUAL.html` (and `.pdf`, when available) are built from it.
After editing the manual, regenerate and commit both:

```
python docs/build_manual.py
```

Uses `pandoc`/`xelatex` when on `PATH`; falls back to a stdlib-only
Markdown renderer for the HTML otherwise (never fails on a missing tool).

## Test commands

```
python -m pytest tests -v
python -m pyflakes claudiu tests
```

Playwright end-to-end tests (`tests/test_e2e.py`) additionally require
`pip install -e .[e2e]` and `playwright install chromium`.

`tests/conformance.py` is a byte-identical vendored copy of an external
publication-conformance checker; `tests/test_githubify_conformance.py`
runs it against the repo and, when the canonical copy is reachable (via a
gitignored `.githubify-rules` pointer file at the repo root), asserts the
two are identical. Never edit the vendored file — re-copy it.

## Hard rules

- Never commit a `config.json` containing personal paths (project
  directories, usernames) to the *public* repository. The shipped default
  config is generated at first run, not tracked in git.
- Vendored frontend files under `claudiu/static/vendor/` are pinned by
  version and SHA-256 hash in `VENDORED.md`. Update them only deliberately,
  recording the new version and hash — never silently.
- Keep this file, `docs/USER_MANUAL.md`, and `README.md` in sync with
  `config.DEFAULTS`, `app.ROUTES`, and `cli.build_parser()` — the guard
  tests in `tests/test_docs_guards.py` enforce it and fail the suite on
  drift.

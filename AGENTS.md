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
| `shortcuts` | see Shortcuts table below | interface keyboard shortcut map |
| `projects` | `[]` | list of `{"name", "path", "args": []}` launcher entries |
| `snippets` | `[]` | list of `{"name", "text", "send": false}` prompt-snippet entries |

Validation (`claudiu.config._validate`): `port` must be an int in
1–65535; `claude_command` a non-empty list of strings (a bare string is
coerced to a one-element list); `replay_chunks`, `scrollback_lines`,
`font_size` positive ints; `theme` and `shortcuts` must be JSON objects;
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
| `WS /ws/<id>` | terminal stream (terminado protocol) |

`GET /api/resume` scans the real `~/.claude/projects` directory of the
user running the server — not a fixture, not the browser's user.

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
claudiu/static/           index.html, app.js, ui.js, keys.js, app.css
claudiu/static/vendor/    pinned xterm.js + addons (see VENDORED.md)
docs/USER_MANUAL.md       human-oriented manual
docs/superpowers/         design spec and implementation plan
tests/                    unit, integration, e2e, docs/licence guard tests
run_claudiu.bat           Windows double-click launcher
```

## Test commands

```
python -m pytest tests -v
python -m pyflakes claudiu tests
```

Playwright end-to-end tests (`tests/test_e2e.py`) additionally require
`pip install -e .[e2e]` and `playwright install chromium`.

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

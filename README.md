# CLAUDIU (working codename)

CLAUDIU is a local, browser-based tabbed interface for running several
Claude Code sessions at once: a small Python server spawns real `claude`
CLI processes in pseudo-terminals and streams them into browser tabs via
xterm.js, so every tab is a real terminal — same colors, same prompts, same
keybindings — while the browser layer adds tabs, a calmer eye-friendly
theme, adjustable fonts, prompt snippets, and a project launcher on top.

## Quick start

```
pip install -e .
python -m claudiu
```

or, on Windows, double-click `run_claudiu.bat`. The server binds
`127.0.0.1` only and opens `http://127.0.0.1:8642/` in your default
browser.

## What it guarantees

- **Full terminal fidelity** — each tab is a real `claude` process; skills,
  plugins, slash commands, and permission prompts behave exactly as in a
  plain terminal.
- **Sessions never die with the browser** — refreshing or closing Chrome
  never kills a session; it lives on the server until you close it.
- **Dropped connections never fail silently** — a lost websocket
  reconnects automatically with backoff behind a visible "reconnecting…"
  strip.
- **A PC crash costs at most one click per session** — the resume scanner
  offers `claude --resume` for every recent project.
- **One dead session never disturbs another** — every session's I/O is
  exception-walled.
- **A conversation you can actually read** — by default each session
  renders as a clean, stable conversation (from Claude Code's transcript
  JSON), not the raw redrawing terminal: collapsible tool output and
  thinking, lane filters, a composer, permission prompts as buttons. The
  real terminal is one click away for menus.
- **You can see where every session stands** — each tab shows your last
  prompt, whether Claude is working, waiting for your input, or done, and
  how full its context is (green → amber → red), read from Claude Code's
  own transcript.
- **A launcher that gets out of the way** — browse to any folder (or make
  a new one), pick a recent one, or start a configured project, with
  resume-after-crash one click away. Light, dark, or system theme.
- **Everything reachable by keyboard** — remappable shortcuts, a snippet
  palette, and a project launcher, all one action away.
- **Every visual parameter is a committed config line** — theme colors,
  fonts, and shortcuts all live in one human-editable JSON file.
- **Localhost only** — the server never binds beyond `127.0.0.1`.

See `docs/USER_MANUAL.md` for the full feature list, configuration
reference, and known limitations, and `AGENTS.md` for the machine-oriented
reference (every config key, route, and CLI flag).

Verified by 103 checks (pytest + pyflakes, Windows/Linux/macOS CI) plus two
Playwright end-to-end checks.

## How it was built

Designed and implemented with Claude Code from a written specification and
an implementation plan (both kept in `docs/`).

## Licence

Apache License, Version 2.0 — see `LICENSE` and `NOTICE`.

### Disclaimer

This software is provided "as is", without warranties or conditions of any
kind, express or implied. The authors and contributors are not liable for
any damages of any character — direct, indirect, incidental, or
consequential — arising out of or in connection with its use. You alone
are responsible for using it lawfully and for complying with the terms of
every third-party service it touches (including Anthropic's own terms for
Claude and Claude Code).

This project is independent and not affiliated with, endorsed by, or
supported by Anthropic. "Claude" and "Claude Code" are used only to
identify the software this tool talks to.

*(Badges are added at publication time — recorded decision.)*

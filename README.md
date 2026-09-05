# ClaudIU

A **browser client for AI coding agents speaking the Agent Client Protocol
(ACP)** — Windows-native (no WSL, no pty), agent-agnostic, and built around
one guarantee: *nothing that crosses the wire is ever lost or silently
misread*. The first configured agent is Claude Code via the
[`claude-agent-acp`](https://github.com/agentclientprotocol/claude-agent-acp)
adapter.

> Working name only. This project is not affiliated with, endorsed by, or
> sponsored by Anthropic or Zed Industries.

## Why

Terminal UIs redraw screens; scraping them is guesswork. ACP delivers the
same conversation as structured JSON-RPC over stdio: messages, thoughts,
tool calls with diffs, permission requests with typed options. ClaudIU
renders that stream in a browser, records every frame verbatim, and flags
anything it does not recognize — so a protocol change is a visible event,
never a silent misrender. As of 2026-08 the ACP ecosystem is editors (Zed,
JetBrains, Neovim, Emacs); a browser client is the missing piece.

## Quickstart

```
npm install -g @agentclientprotocol/claude-agent-acp   # the Claude adapter
pip install -e .                                 # Python >= 3.11
python -m claudiu
```

Open the printed `http://127.0.0.1:<port>/?token=...` URL, pick an agent,
pick a project directory, start the session. The port is OS-assigned each
run unless you pass `--port`. If a `claude` CLI is installed, the adapter
is pointed at it instead of the older copy it bundles (the launcher shows
which runtime resolved; `agents/PROFILE-SCHEMA.md` → `env_resolve`).
For a stable address, pin the port and keep the token:
`python -m claudiu --port 8642 --token-file ~/.claudiu/token` — bookmark the
printed URL once (the token file is owner-only; treat it like a password).

## Architecture

Four layers, one-way knowledge, swappable at each seam:

```
ui/web        View        vanilla JS, no build; speaks docs/UI-PROTOCOL.md
server/       Controller  Tornado; auth, process spawn, WS bridge
core/         Model       pure stdlib; JSON-RPC, ACP state machine,
                          flight recorder, drift sentinel, path policy
agents/*.toml Data        everything agent-specific (see PROFILE-SCHEMA.md)
```

- **Sessions outlive the browser**: they live in the server, so a reload
  reattaches and a dropped socket reconnects by itself, asking only for
  the events it missed.
- **Swap the UI**: implement `docs/UI-PROTOCOL.md` (enforced in tests).
- **Swap the server**: implement the three ports in `claudiu/core/ports.py`.
- **Add an agent**: write one TOML profile; the engine never changes.

## Losslessness & drift

- Every protocol frame, in and out, is appended verbatim to a per-session
  JSONL record **before** interpretation, along with every client action
  (prompts, permission answers, policy decisions). Each rendered event
  carries a `raw_ref` back into that record. Records are kept for ever
  unless you ask otherwise (`--records-keep-days N`); they hold the whole
  conversation, and the server says how much it is holding at startup.
- Unknown methods, update kinds, fields, or enum values are checked against
  a registry pinned to a vendored ACP schema release (`vendor/acp/VERSION`)
  — mismatches surface as `drift` events in the UI and the log, with the
  offending frame. `tools/check_schema_drift.py` diffs the registry against
  the schema at dev time; `/api/drift` compares the pin and the installed
  adapter against the latest published versions (disable with
  `--no-drift-online`).
- Anything the renderer does not understand becomes an explicit
  `unrecognized` element — visible, expandable to the raw frame, never
  dropped.

## Security model

- Binds `127.0.0.1` only; every request and WebSocket — the UI files
  included — carries a per-launch random token (cookie, constant-time
  compare). A `Host` that is not loopback, or an `Origin` that is not
  this server's own **port included**, is refused: cookies are not
  scoped by port, so any other local web page would otherwise arrive
  authenticated. Strict CSP; no external resources.
- ACP lets the agent ask the client to read/write files: every such request
  is checked against the session's path boundary (project directory;
  symlink-resolved) and refused outside it. **Shell commands the agent runs
  itself are not confined by this** — they execute agent-side; the approval
  dialog flags any out-of-boundary paths it can see and your answer is the
  control ("Always Allow" is a standing grant for the session). The
  `terminal` capability is deliberately not advertised in v1.
- Adapter subprocesses run with a scrubbed environment (profile
  `env_scrub`, then the profile's own `env_resolve`/`env_set` additions —
  recorded as the session's first record) and are terminated with their
  session. Records never contain the auth token.

## Development

```
python -m pytest tests/ -q          # full suite (e2e needs playwright)
CLAUDIU_CONTRACT=1 python -m pytest tests/contract/ -q   # real adapter
python -m pyflakes claudiu tools tests
python tools/check_schema_drift.py
```

Verified by 207 checks (plus the opt-in real-adapter contract test). See
`AGENTS.md` for the working rules and `docs/superpowers/specs/` for the
design history — the research notes and the approved specifications the
implementation followed. The v0.1 terminal-mirror app that preceded the ACP pivot is
kept out of this repository, with its own history.

## License

Apache-2.0 (see `LICENSE`, `NOTICE`). Vendored data: the ACP schema
(Apache-2.0), pinned in `vendor/acp/`.

### Disclaimer

This software is provided "as is", without warranty of any kind, express
or implied. In no event shall the authors be liable for any claim, damages
or other liability arising from its use. It drives AI coding agents that
can modify files in the directories you point them at; review what you
approve.

# ClaudIU

A **browser client for AI coding agents** that speaks the
[Agent Client Protocol](https://github.com/agentclientprotocol/agent-client-protocol)
directly — no terminal, no TUI, nothing scraped off a screen. Windows-native
(no WSL, no pty), agent-agnostic, and built around one guarantee: *nothing
that crosses the wire is lost or silently misread*. The first configured
agent is Claude Code, through the
[`claude-agent-acp`](https://github.com/agentclientprotocol/claude-agent-acp)
adapter.

> Working name only. This project is not affiliated with, endorsed by, or
> sponsored by Anthropic or Zed Industries.

![ClaudIU rendering a session: tabs and account limits pinned top right,
the conversation with tool rows, the predicted next prompt over the
composer, and the session controls beneath it](docs/screenshot.png)

*(The conversation above is the repository's own scripted test agent, not a
real session.)*

## What you get

**Nothing is left out, because nothing is redrawn.** A terminal client shows
you a screen; whatever is not on the screen is gone, and a client that
scrapes one is guessing. ClaudIU is an ACP client: the conversation arrives
as structured JSON-RPC, is written to a per-session record *before* it is
interpreted, and is then rendered as itself. The model's **thinking**, tool
calls with their **diffs**, **permission requests** with the agent's own
typed options, the agent's **own questions** as forms, **plans**, **subagent
transcripts**, slash commands, token usage, cost, and your account's
rate-limit windows — all of it is data, and all of it is on the page.
Anything the client does not recognise becomes a visible `unrecognized`
element rather than a gap.

**The view holds still.** This is a reading tool, so it behaves like one.
New rows scroll into view only while you are already at the bottom — scroll
up to read and the page stays where you put it. Streamed text is appended,
never re-rendered, so you can select and copy an answer *while it is still
arriving*. The control panel waits until the session has settled instead of
rearranging itself for the first few seconds. Tabs shrink the way a
browser's do rather than pushing the account chips off the screen. No
flicker, no jumping.

**Sessions outlive the browser.** They live in the server, not the page.
Reload and it reattaches to everything still running; drop the socket — a
restart, a sleeping laptop — and it reconnects on its own, asking only for
the events it missed. Resume what the agent itself remembers, newest first,
each dated.

**And the rest of it is in there too**: five lane switches that remove whole
categories of row from the page, an approvals dialog that flags paths
outside the project boundary, an archive panel that writes the conversation
to disk (a full document
through `claude-session-publisher` when it is installed, or a plain Markdown
transcript written from the record when it is not), a
drift sentinel that tells you when the protocol has moved, per-session
thinking settings, light and dark themes, and a keyboard that works the way
a terminal's does — `Esc` interrupts, everything else types.

## Quickstart

```
npm install -g @agentclientprotocol/claude-agent-acp   # the Claude adapter
pip install -e .                                       # Python >= 3.11
python -m claudiu
```

Open the printed `http://127.0.0.1:<port>/?token=...` URL, pick an agent,
pick a project directory, start the session. The port is OS-assigned each
run unless you pass `--port`. If a `claude` CLI is installed, the adapter is
pointed at it instead of the older copy it bundles (the launcher shows which
runtime resolved; `agents/PROFILE-SCHEMA.md` → `env_resolve`). For a stable
address, pin the port and keep the token:
`python -m claudiu --port 8642 --token-file ~/.claudiu/token` — bookmark the
printed URL once (the token file is owner-only; treat it like a password).

`docs/USER_MANUAL.md` is the full manual.

## Architecture

Four layers, one-way knowledge, swappable at each seam:

```
ui/web        View        vanilla JS, no build; speaks docs/UI-PROTOCOL.md
server/       Controller  Tornado; auth, process spawn, WS bridge
core/         Model       pure stdlib; JSON-RPC, ACP state machine,
                          flight recorder, drift sentinel, path policy
agents/*.toml Data        everything agent-specific (see PROFILE-SCHEMA.md)
```

- **Swap the UI**: implement `docs/UI-PROTOCOL.md` (enforced in tests).
- **Swap the server**: implement the three ports in `claudiu/core/ports.py`.
- **Add an agent**: write one TOML profile; the engine never changes.
  `agents/local-*.toml` is yours and is never tracked.

## Losslessness & drift

- Every protocol frame, in and out, is appended verbatim to a per-session
  JSONL record **before** interpretation, along with every client action
  (prompts, permission answers, policy decisions). Each rendered event
  carries a `raw_ref` back into that record. Records are kept for ever
  unless you ask otherwise (`--records-keep-days N`); they hold the whole
  conversation, and the server says how much it is holding at startup.
- Unknown methods, update kinds, fields or enum values are checked against a
  registry pinned to a vendored ACP schema release (`vendor/acp/VERSION`) —
  mismatches surface as `drift` events in the UI and the log, with the
  offending frame. `tools/check_schema_drift.py` diffs the registry against
  the schema at dev time; `/api/drift` compares the pin and the installed
  adapter against the latest published versions (disable with
  `--no-drift-online`).
- Anything the renderer does not understand becomes an explicit
  `unrecognized` element — visible, expandable to the raw frame, never
  dropped.

**Where the limit actually is.** ClaudIU can only render what the *adapter*
forwards, and `claude-agent-acp` 0.73 discards some of what the Agent SDK
produces — prompt suggestions, among others. That is not hidden: each agent
profile carries `caveats` which the launcher shows before you start a
session, so you know what this client cannot see and why.

## Security model

- Binds `127.0.0.1` only; every request and WebSocket — the UI files
  included — carries a per-launch random token (cookie, constant-time
  compare). A `Host` that is not loopback, or an `Origin` that is not this
  server's own **port included**, is refused: cookies are not scoped by port,
  so any other local web page would otherwise arrive authenticated. Strict
  CSP; no external resources.
- ACP lets the agent ask the client to read and write files: every such
  request is checked against the session's path boundary (the project
  directory, symlink-resolved) and refused outside it. **Shell commands the
  agent runs itself are not confined by this** — they execute agent-side;
  the approval dialog flags any out-of-boundary paths it can see and your
  answer is the control ("Always Allow" is a standing grant for the
  session). The `terminal` capability is deliberately not advertised in v1.
- Adapter subprocesses run with a scrubbed environment (profile `env_scrub`,
  then the profile's own `env_resolve`/`env_set` additions — recorded as the
  session's first record) and are terminated with their session. Records
  never contain the auth token.

## Development

```
python -m pytest tests/ -q          # full suite (e2e needs playwright)
CLAUDIU_CONTRACT=1 python -m pytest tests/contract/ -q   # real adapter
python -m pyflakes claudiu tools tests
python tools/check_schema_drift.py
```

Verified by 207 checks (plus the opt-in real-adapter contract test), on
Linux, Windows and macOS. See `AGENTS.md` for the working rules,
`docs/DESIGN.md` for the reasoning and `docs/superpowers/specs/` for the
design history — the research notes and the approved specifications the
implementation followed. The v0.1 terminal-mirror app that preceded the ACP
pivot is kept out of this repository, with its own history.

## License

Apache-2.0 (see `LICENSE`, `NOTICE`). Vendored data: the ACP schema
(Apache-2.0), pinned in `vendor/acp/`.

### Disclaimer

This software is provided "as is", without warranty of any kind, express or
implied. In no event shall the authors be liable for any claim, damages or
other liability arising from its use. It drives AI coding agents that can
modify files in the directories you point them at; review what you approve.

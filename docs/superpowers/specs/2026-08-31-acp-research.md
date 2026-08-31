# ACP research — dropping WSL, learning from toad (2026-08-31)

Research notes for the pivot decision. No code in this document derives from
toad: **toad is AGPL-3.0 — we never copy, port, or paraphrase its source.**
Everything below is (a) live protocol observation from our own test sessions,
(b) the open ACP specification (agentclientprotocol.com), (c) behavior-level
observation of toad as a user, (d) a file-name-level inventory of its package.

## 1. The headline: ACP needs no WSL — toad did

WSL was **toad's** requirement (its runtime doesn't support native Windows),
not ACP's. The Claude adapter `@zed-industries/claude-code-acp` is a Node
program speaking newline-delimited JSON-RPC 2.0 over **plain stdio pipes** —
no pty, no terminal emulation at all.

**Verified on native Windows (2026-08-31, scratchpad `acp_native_test.py`):**
node v24.19.0 + `npm i -g @zed-industries/claude-code-acp` + Python
`subprocess.Popen` with pipes → `initialize` → `session/new` →
`session/prompt` → streamed `agent_message_chunk`s → exact reply
`NATIVE-WINDOWS-ACP-OK`, `stopReason: end_turn`. Auth picked up the existing
`~/.claude/.credentials.json` with no login flow.

Two operational facts (both already known to CLAUDIU, both bit again):
- Spawn must scrub `CLAUDECODE` + `CLAUDE_CODE_*` from the child env, or the
  SDK refuses with the nested-session guard (same fix as sessions.py).
- The npm shim is `%APPDATA%\npm\claude-code-acp.cmd` on Windows.

**Consequence:** the CLAUDIU architecture stays 100 % native Windows —
Tornado server spawns the adapter per session with `subprocess` (simpler than
pywinpty), talks ndjson over pipes, pushes structured events over the
existing WebSocket. WSL, toad, and the pty are all out of the ACP path.

## 2. What the handshake actually advertises (observed live)

`initialize` result: `promptCapabilities {image, embeddedContext}`,
`mcpCapabilities {http, sse}`, `loadSession: true`,
`sessionCapabilities {fork, list, resume}` — i.e. **resume/fork/list of
Claude Code sessions comes free through the protocol** (CLAUDIU's resume
scanner over `~/.claude/projects/` becomes a fallback, not the mechanism).

`session/new` result carries **permission modes as data**: `default`,
`acceptEdits`, `plan`, `dontAsk` (+ `session/set_mode` to switch). The mode
selector becomes a real dropdown, not keystrokes into a TUI.

First `session/update` is `available_commands_update`: the slash commands
arrive as a structured list. Commands are data, not text.

## 3. Client surface we must implement (ACP spec + observation)

Required: `initialize`, `session/new`, `session/prompt`,
`session/cancel` (notification), and handling the agent→client request
`session/request_permission`. Optional but wanted: `session/load`/`resume`,
`session/set_mode`, `fs/read_text_file` + `fs/write_text_file` (advertise
them so diffs/edits flow through us), `terminal/*` (adapter can delegate
shell execution to the client — we already own a terminal stack).

`session/update` kinds to render: `agent_message_chunk`,
`agent_thought_chunk`, `user_message_chunk`, `tool_call` /
`tool_call_update` (id, title, kind read/edit/execute/…, status
pending→in_progress→completed/failed, content incl. **diff objects**,
file locations), `plan` (structured todo list), `available_commands_update`,
`current_mode_update`.

`session/request_permission`: options each with `optionId`, `name`, `kind ∈
{allow_once, allow_always, reject_once, reject_always}`; response selects an
optionId (or `cancelled`). **This replaces the entire xterm-buffer permission
parser** — the exact surface whose byte-scrape mis-parsed a 3-option prompt
to one wrong option is delivered as typed JSON.

Framing: JSON-RPC 2.0, one JSON object per `\n`-terminated line, over stdio.

## 4. Do's and don'ts learned from toad (as users, not from its code)

**Do (toad got these right):**
- Approval request as a **full diff view** (file path, +n/−n, rendered
  changed lines) with allow-once / allow-always / reject as first-class
  options and single-key bindings. This is the gold standard; CLAUDIU's
  permission UI should render `tool_call` diff content the same way.
- Collapsible tool-call rows inline in the conversation (we already do this
  in convo.js — keep).
- Plan panel fed by the structured `plan` updates.
- Project file tree that live-refreshes when the agent writes.
- `serve` mode: same UI, browser-delivered — validates CLAUDIU's premise.

**Don't (observed failures — Fabio, 2026-08-31):**
- **Don't reimplement slash commands as fake-TUI autocomplete.** In toad,
  typing `/model` pops a command list; typing past the list issues a bare
  `/model` that returns nothing usable. Lesson: treat
  `available_commands_update` as the source of truth, submit a command only
  on explicit selection/Enter, and always render the agent's response to it;
  if a command's interactive follow-up isn't supported, say so instead of
  swallowing it.
- **Don't drop the escape hatch.** An ACP agent is *not* the interactive
  `claude` TUI: menus like `/model`'s picker have no protocol equivalent
  yet. CLAUDIU's differentiator stands: ACP mode for the conversation, the
  real pty TUI one toggle away for anything the protocol can't carry.
- Don't ship a terminal-lookalike text input in the browser with terminal
  keybindings half-working; use a real composer (ours already exists).

## 5. Behavior-level feature inventory of toad (file names only)

Modules observed (names, not contents): acp/, jsonrpc, protocol, agent
schema/registry, sessions db + history + session_tracker, conversation
markdown export, plan, danger (approvals), fuzzy path completion +
directory watcher, screens/widgets/visuals, ANSI handling, gist sharing,
settings. Useful as a checklist of what a mature agent client accumulates —
nothing here is copied.

## 6. Proposed CLAUDIU-ACP architecture (for Fabio's approval)

- Keep: Tornado server, tabs, WS transport, convo.js rendering (markdown,
  collapsibles, lane filters), composer, audit log, theme system, config,
  Host/Origin guards.
- New: `acp.py` — per-session adapter subprocess (env-scrubbed, pipes),
  JSON-RPC framing, request routing; WS relays `session/update` verbatim to
  the browser; permission requests become the existing permission-button UI
  but fed typed options (fail-safe path stays: reject + open terminal).
- Demote: pty/xterm path becomes the explicit "real TUI" mode (per tab);
  transcript-JSONL polling remains only for viewing *foreign/old* sessions.
- Adapter is a runtime npm dependency (`@zed-industries/claude-code-acp`,
  Apache-2.0) — installed by the user like `claude` itself, never vendored.
- The stdin audit log extends to ACP: log every `session/prompt`,
  `session/set_mode`, and permission response with ids.

**Status: research only — no implementation until Fabio approves.**

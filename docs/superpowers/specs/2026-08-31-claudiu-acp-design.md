# CLAUDIU-ACP — design specification (2026-08-31)

Approved section-by-section by Fabio on 2026-08-31 (sections 1–3 in chat).
Supersedes the pty-centred design (`2026-08-30-claudiu-design.md`) and the
conversation-view design (`2026-08-31-conversation-view-design.md`) as the
product direction; both remain valid as history of the archived v0.1 app.
Research base: `2026-08-31-acp-research.md`.

## 1. What this is

A **browser client for AI coding agents over the Agent Client Protocol
(ACP)**, Windows-native, no WSL, no pty. The first (and for now only)
configured agent is Claude Code via the `@zed-industries/claude-code-acp`
adapter (Apache-2.0, installed by the user via npm, never vendored).

As of 2026-08, no native web/browser ACP client exists in the ecosystem
(Zed, JetBrains, Neovim and Emacs are all editors) — this fills a real gap.

## 2. Requirements (Fabio, 2026-08-31 17:55)

R1. **Feature complete** — everything that goes in and out of the AI
    interface, with full record and control. Not "rich": complete.
R2. **Drift awareness** — if the protocol/agent feature set or behaviour
    changes over time, it is logged and surfaced so the implementation can
    be adapted in a timely manner.
R3. **AI-agnostic engine** — agent-specific features, caveats and quirks
    live in configuration files separate from the engine, even if the
    abstraction is imperfect at first.
R4. **MVC** — the UI must be swappable (future desktop/mobile/other OS).
R5. **Server-agnostic** — the engine must not depend on server specifics;
    another server implementation must be possible.
R6. **Minimal shipping** — no third-party software beyond the bare
    unavoidable minimum; external systems used as agnostically as possible.
R7. **Compliance & losslessness** — fully comply with the AI interface and
    its rules; lose no information in either direction; all commands
    complete, compliant, easy to use; anything out of order clearly flagged
    and properly logged; smooth but very robust UX; full cybersecurity best
    practice; best practices for this product type generally.

## 3. Decisions (approved 2026-08-31)

D1. **Pure ACP client.** The pty stack (pywinpty, Terminado, xterm.js) is
    not carried over. The v0.1 terminal app is parked as a fallback tool.
D2. **Same project, old app archived.** CLAUDIU remains the project (and
    working codename — never ships). v0.1 moves to `archive/claudiu-v0.1/`
    per KEEP rule 20: gitignored, with its own `.git` preserving its
    history. The ACP client is built fresh at the top level.
D3. **Localhost-only, auth built in.** v1 binds 127.0.0.1 only, but every
    request and WS upgrade carries a session token from day one, so a later
    LAN/mobile opening adds TLS + login without redesign.
D4. **Approach A** — layered engine with ports (below); library-based (B)
    and thin-bridge (C) approaches rejected (B: dependency + hides the wire
    from record/drift; C: logic in the view kills MVC and server-side
    record).

## 4. Architecture (Approach A)

Four layers, strict one-way knowledge:

```
ui/web  (View)      — vanilla JS, no build step
   ▲  UI protocol (documented WS events + REST commands)
server/ (Controller)— Tornado implementation of the ports
   ▲  ports.py (AgentProcess, EventSink, Store)
core/   (Model)     — pure-stdlib ACP engine
   ▲  agent profile (data, not code)
agents/*.toml       — per-agent configuration
```

- `core/` imports nothing outside the stdlib and never does real I/O
  directly; it is usable from any server or a CLI test harness.
- `server/` is one implementation of the ports; the port interfaces are the
  documented seam for alternative servers (R5).
- `ui/web/` talks only the documented UI protocol; any future UI (desktop,
  mobile) speaks the same protocol (R4). That protocol document
  (`docs/UI-PROTOCOL.md`) is a deliverable, kept in lockstep with the code.
- `agents/claude.toml` is the only place Claude is named (R3).

### 4.1 core/ — components

- **`protocol.py`** — newline-delimited JSON-RPC 2.0 framing over pipes:
  one JSON object per line; request/response matching by id; dispatch of
  agent→client requests and notifications; malformed lines surfaced as
  anomalies, never crashes. Knows JSON-RPC, not ACP semantics.
- **`acp.py`** — the ACP client state machine:
  - `initialize` with the latest protocol version we support (integer,
    MAJOR-only per spec); on unsupported version in the response, close the
    connection and inform the user (spec SHOULD → we do it).
  - Capability negotiation; capabilities omitted by the peer are treated as
    UNSUPPORTED (spec MUST).
  - Session lifecycle: `session/new`, `session/load`, resume/fork/list
    (advertised by the Claude adapter), `session/prompt`, `session/cancel`,
    `session/set_mode`.
  - Agent→client handling: `session/request_permission` (typed options:
    allow_once / allow_always / reject_once / reject_always),
    `fs/read_text_file`, `fs/write_text_file`, `terminal/*` — each gated by
    policy (§7) and answered only via engine events.
  - `session/update` normalization: agent_message_chunk,
    agent_thought_chunk, user_message_chunk, tool_call, tool_call_update
    (diff content, locations, status), plan, available_commands_update,
    current_mode_update — plus an explicit `unrecognized` event for
    anything else (R7 losslessness).
  - Extensibility rules honoured: `_meta` passed through and recorded;
    unknown extension requests answered `-32601`; unknown notifications
    tolerated per spec but logged and flagged by the sentinel (R2); we
    never add custom fields at the root of spec types.
- **`record.py`** — flight recorder: per-session append-only JSONL.
  Every frame in and out, verbatim, timestamped, direction-tagged, written
  **before interpretation**; plus client-side actions (prompt submitted,
  permission answered, mode changed, policy decision taken). Replayable;
  the engine can re-emit a session's UI events from its record.
- **`sentinel.py`** — drift detection (§6).
- **`ports.py`** — abstract interfaces: `AgentProcess` (spawn with scrubbed
  env / write line / read line / kill), `EventSink` (typed engine events
  out), `Store` (records, config). Implemented by `server/`, faked in
  tests.

### 4.2 agents/ — profiles as data

`agents/claude.toml` (first profile; schema documented in-repo):

- adapter command + args + install hint (`npm i -g
  @zed-industries/claude-code-acp`); working-dir policy;
- env scrub list: `CLAUDECODE`, `CLAUDE_CODE_*` (nested-session guard);
- auth method notes (uses `~/.claude/.credentials.json`; login hint);
- capability expectations & quirks (loadSession, fork/list/resume, modes
  default/acceptEdits/plan/dontAsk);
- vendor `_meta` extension names to surface (goal, session-failure,
  permission extensions);
- known caveats to display (e.g. "/model interactive picker has no
  protocol equivalent — flagged as unsupported");
- display name/icon.

The engine consumes any conforming profile; adding an agent is writing a
file (R3).

### 4.3 server/ — the Controller (Tornado)

Implements the ports: spawns adapter subprocesses (pipes, scrubbed env,
tracked, killed on close), bridges engine events to WebSocket, REST for
session management (create/list/resume/close, agent profiles, drift
status), serves the static UI. Auth + origin policy in §7. Tornado is the
single shipped third-party runtime dependency (R6); stdlib has no
WebSocket server, and hand-rolling one is a security anti-practice.

### 4.4 ui/web/ — the View

Vanilla JS, no build step, no external resources. Renders typed engine
events: conversation lanes (message / thought / tool), collapsible tool
rows with diff rendering (the toad-quality approval screen), plan panel,
permission dialog fed by typed options with single-key bindings and a
fail-safe reject, command palette driven by `available_commands_update`
(submit only on explicit selection; responses always rendered; unsupported
follow-ups labelled, never swallowed), mode selector from session modes,
drift/anomaly status chips, session tabs, theme system carried over from
v0.1 concepts. Every rendered element can reveal its raw frame (escape
hatch into the record).

## 5. Data flow

Prompt: UI → WS → server → engine: record → `session/prompt` → adapter.
Updates: adapter → engine: record raw → sentinel check → normalize → typed
event → EventSink → WS → UI render.
Agent requests (permission/fs/terminal): adapter → engine: record → policy
check (§7) → blocking engine event → UI answer (timeout policy,
fail-safe reject) → record → reply to adapter.
Anomalies (§8) and drift flags ride the same event stream.

Losslessness (R7): raw frames are the source of truth; typed events carry
a pointer to their raw frame; unrecognized material becomes a visible
`unrecognized` event — structural fidelity accounting.

## 6. Drift sentinel (R2)

- The ACP `schema.json` from a **pinned release** of
  `agentclientprotocol/agent-client-protocol` is vendored in-repo.
- A dev-time script compiles it into a compact registry (known methods,
  update kinds, per-type field sets, enum values) — no runtime third-party
  validator (R6).
- Runtime: every frame checked by membership tests. Unknown method →
  spec-compliant response **plus** logged, UI-visible drift flag with the
  raw frame. Unknown field / update kind / enum value → same flag.
- Startup + on-demand (config `drift.network_checks`, default on, can be
  disabled): compare pinned schema release and installed adapter version
  against latest published; report "behind by N releases" in log + UI.
- Updating: bump the pinned schema, rerun the compiler, diff the registry —
  the diff is the to-do list for catching up (timely, actionable).

## 7. Security (R7, D3)

- Bind 127.0.0.1 only. Per-launch random token required on every REST call
  and WS upgrade (delivered once via launch URL, then cookie-bound;
  constant-time comparison). Host/Origin allowlist (DNS-rebinding guard).
  Strict CSP; no external resources; no inline event handlers.
- ACP's client-side powers are the sharpest edge — the agent asks **us** to
  read/write files and run terminals. Policy layer: every `fs/*` and
  `terminal/*` request checked against a per-session path boundary
  (session cwd + explicit user-granted allowlist, symlink-resolved);
  then routed through the permission UI unless covered by a standing
  grant. Check + decision recorded.
- Child processes: scrubbed env at spawn, tracked, terminated on session
  close and server shutdown; no orphans.
- The record stores protocol traffic and client actions — never our auth
  token or the process environment.
- Commits/publication follow KEEP/GITHUBIFY (noreply identity, private
  first, conformance).

## 8. Errors & anomalies (R7 "flag anything out of order")

Typed anomaly events, each logged with its raw frame and shown as a UI
status chip — never silently absorbed:
JSON-RPC error responses; malformed/non-JSON lines; id mismatches;
updates for unknown sessions; messages illegal in the current state;
adapter stderr bursts; adapter exit/EOF (→ session `failed-recoverable`,
record preserved, resume offered); request timeouts (fail-safe reject for
permissions); version-negotiation failure (close + user message).
Shutdown: `session/cancel` active turns, then terminate children cleanly.

## 9. Testing

- TDD throughout (house rule).
- **Engine tier (CI, no Claude):** scripted fake adapter driven by ndjson
  fixture transcripts — happy paths, permission flows, fs/terminal
  requests, every anomaly class of §8, synthetic drift frames, version
  mismatch, capability combinations (spec: support all peer combinations).
- **Contract tier (opt-in, real adapter):** the same scenarios against
  `claude-code-acp`, like v0.1's e2e tier; catches adapter drift the
  fixtures can't.
- **Security tests:** token/Host/Origin rejection, path-boundary escapes
  (including symlinks), env scrub verification.
- **UI tier:** Playwright against the fake-adapter server.
- 3-OS CI matrix, pyflakes, vendored conformance checker carry over.

## 10. Dependencies policy (R6)

Shipped runtime: Python stdlib + Tornado. Dev/test only: pytest,
playwright, pyflakes. External at user's choice: node + the adapter
(user-installed, version surfaced by the sentinel). Vendored: the pinned
ACP `schema.json` (data, versioned, licence-noted). No JS dependencies.

## 11. Migration & non-goals

Migration: create `archive/claudiu-v0.1/` (own `.git`, gitignored, KEEP
rule 20) holding the entire v0.1 app; top level restarts with the new
layout; docs/ history and KEEP/GITHUBIFY wiring stay.

Non-goals for v1 (recorded, not designed): LAN/mobile access (D3 keeps the
door open), desktop/mobile UIs (R4 keeps the seam), multiple simultaneous
agent types (R3 keeps the seam).

Terminal capability, explicit v1 stance: `fs.readTextFile` and
`fs.writeTextFile` are advertised and implemented in v1; `terminal` is
**not advertised** in v1 (the Claude adapter falls back to running
commands through its own SDK executor, losing nothing functionally). It
is a declared-unsupported capability (spec-compliant), listed as a caveat
in `agents/claude.toml`, and a roadmap item — never faked.

## 12. References

- ACP spec: agentclientprotocol.com (overview, initialization,
  extensibility, schema pages; fetched 2026-08-31).
- Schema releases: github.com/agentclientprotocol/agent-client-protocol.
- Adapter: github.com/zed-industries/claude-code-acp (Apache-2.0).
- Native-Windows proof + toad lessons: `2026-08-31-acp-research.md`
  (commit 2532cd0). Toad is AGPL — behaviour-level lessons only, no code.

# Changelog

All notable changes to CLAUDIU are documented in this file.

## Unreleased (2026-09-04)

### audit fixes

A full-scope audit of the project (report in the dev machine's control
plane) found eleven things; these are the ones fixed here.

- **Any local web page could reach the API.** The host/origin guard accepted
  every `http://127.0.0.1:<any port>` origin — but cookies are *not* scoped
  by port, so a page served from any other port on the loopback interface
  arrived carrying our token, and a `text/plain` POST (a CORS "simple
  request", so no preflight to stop it) was executed. It could not read the
  answer, so it could not drive a session, but it could start one in any
  directory. The origin must now equal this server's own address **and
  port**, on the REST routes and on the WebSocket alike, where it is the
  only defence there is.
- **The UI files were served without a token.** `/ui/*` was mounted as a
  bare static handler, outside the guard: no token, no host or origin check,
  no CSP header. Nothing secret lives in those three files, but the README
  said every request carried a token and that was not true. It is now.
- **The account panel showed one window and no number.** It read
  `utilization` from the top level of the rate-limit payload; the payload
  the agent actually sends has no `utilization` there at all, and carries
  every window inside `unifiedWindows` as a *fraction* (0.55 = 55 %). So the
  5 h chip read "5h —" and the 7 d window was never shown. Every reported
  window now gets its own chip with its real percentage, and the agent's own
  payload sits in the tooltip. The test fixture had invented the shape it
  was testing; it now carries a payload captured from a real session.
- **The folder picker opens wide enough to read.** A home directory of 55
  folders showed eight of them behind a scrollbar that was there the moment
  the dialog opened. The dialog is wider and the list is a responsive grid,
  so an ordinary directory fits whole; long names ellipsize with the full
  name in the tooltip.
- Docs and hygiene: `AGENTS.md` and `docs/DESIGN.md` still said "0.2";
  `AGENTS.md` still named the pre-rename `claude-code-acp` for the contract
  tier and listed two of the three files a release must bump; the README
  pointed readers at a directory that is gitignored; `.gitattributes` pinned
  two files that no longer exist; three lines mangled by an earlier patch
  were reflowed; and this file had two `## Unreleased` sections.

### daily-use round 9

- **Errors from the REST API are JSON, always.** A malformed request body
  reached `json.loads` unguarded and Tornado answered with its HTML 500
  page, which the View cannot read (found restoring sessions from the
  command line). Bad bodies are a 400 with an `error` field, and every
  error response from these routes is JSON now.

- **Anomalies stopped disappearing when you looked at them.** The chip's
  click handler zeroed the counter and threw the details away - the exact
  opposite of the losslessness contract. Clicking now opens a drawer with
  every anomaly and drift flag, and dismissing them is a separate button.
  UI-PROTOCOL says so for any View.
- **Account limits at the top right.** `_meta._claude/rateLimit` rides on
  usage updates and was being dropped; it now becomes its own `rate_limit`
  event (account-wide, passed through whole) and the View shows one chip per
  window the agent has reported - 5 h, 7 d, per-model, extra credits - with
  utilization, status colour and reset time.
- **Help (?) and Settings (gear) buttons.** Help explains the lanes, chips,
  keyboard and where session options live; Settings holds the browser-level
  choices: **theme** (system / dark / light, remembered) and whether tool
  output starts open. The palette answers to the choice in both directions
  instead of only following the OS.

### daily-use round 8

- **The conversation follows you, not the other way round.** New rows scroll
  into view only while you are at the bottom; scrolled up, the view stays
  put and a **jump to latest** button brings you back.
- **Five lane switches** in the status strip - thinking, tools, subagents,
  events, harness - each removing those rows from the page entirely
  (remembered per browser). Documented as a View contract in
  `docs/UI-PROTOCOL.md` so any front-end offers the same thing.
- **Thinking is chosen where the session is created**: a launcher control
  (summarized / omitted / off) sent as `client_options` and merged over the
  profile's, because ACP cannot change it mid-session. `off` requests no
  thinking at all.
- **Subagent transcripts arrive**: the client advertises the adapter's
  `subagent-transcript` capability, and `message_chunk` carries
  `parent_tool_call_id` so subagent text can be filed (and hidden) as its own
  lane instead of masquerading as the main agent's.
- **A reload no longer strands a running session.** Sessions live in the
  server; the View now reattaches to every live one on load and returns you
  to the tab you were in.
- **One attachment per agent session.** Resuming an agent session that
  another live session already holds is refused with a 409 naming the
  holder - two adapters would write the same transcript file.
- **Archive button**: hands the session to claude-session-publisher
  (`--archiver` / `CLAUDIU_ARCHIVER`), which writes it into the usual
  archive directory; the tool is never vendored in (rule 21).
- **The composer stopped eating short windows**: the prompt box starts at two
  rows and grows with the text to a 30vh cap, and the toolbar is one compact
  row. At 420 px tall the composer used to take 36 % of the window.
- The product is spelled **ClaudIU**.

## 0.3.0 - 2026-09-04 - thinking, questions, and a client that fits daily use

Everything below shipped between 0.2.0 (2026-08-31) and this release,
during two weeks of daily use against claude-agent-acp 0.73.

### the agent can ask questions (2026-09-04)

- **AskUserQuestion works over ACP.** The adapter disables that tool
  unless the client advertises `elicitation.form`; CLAUDIU now does, and
  handles `elicitation/create` (form mode) as a modal form - single-select
  questions as radios, multi-select as checkboxes, each question's "Other"
  box as free text, plus **Skip**. Answers travel back as
  `{"action": "accept", "content": {...}}` over the new `elicitation` WS
  command and are written into the conversation. A property type the View
  cannot render is named and left unanswered, never mis-rendered as
  something else; `url`-mode elicitation is not advertised and is answered
  "cancel" with an anomaly. Unanswered questions decline themselves on the
  same fail-safe timer that rejects stale permissions (decline, not
  cancel: the agent continues without an answer). Engine, server,
  protocol-doc and end-to-end tests.

### thinking summaries (2026-09-04)

- **Thinking arrives with text.** The empty thought chunks were never
  adapter redaction: recent models return *summarized* thinking, and only
  when the Agent SDK is asked for it. New profile field `client_options`
  is sent verbatim with `session/new`, `session/load` and `session/resume`
  as `_meta.claudeCode.options` - the extension point the Claude adapter
  merges into its SDK call - and `agents/claude.toml` now asks for
  `thinking = {type = "adaptive", display = "summarized"}`. The engine
  validates the shape and nothing else; a profile that asks for nothing
  sends no `_meta`. The launcher caveat says what thinking now is (a
  summary, never the raw text, which the API does not offer for these
  models). Profile, engine and docs-guard tests; new guard: every
  `AgentProfile` field must appear in `agents/PROFILE-SCHEMA.md`.

### launcher fixes (2026-09-03)

- **Tab bar squashed to a sliver.** The body is a 100vh flex column and
  the tab bar could shrink; once the launcher's caveat list outgrew a
  short window the bar collapsed to a thin strip with the `+` pushed above
  the top edge. The bar is now `flex: none` and the launcher scrolls
  inside the body instead of growing it. End-to-end test at a 900×420
  viewport.
- **Folder picker for the project directory.** A **Browse…** button next
  to the field opens a dialog that walks the filesystem through the new
  `GET /api/dirs` route (subdirectories only, dot-directories last, drive
  roots as one-click chips, **↑ Up**, **Use this folder**). A browser page
  cannot learn an absolute path from the OS folder dialog, so the server
  lists; the route is token-gated like every other and exposes nothing
  the token does not already grant. The browser remembers the last
  directory a session was started in (`localStorage`). Server, security,
  end-to-end and protocol-doc tests.

### daily-use assessment (2026-09-01 23:00)

- **Plan-mode exit re-asserts the mode.** Approving a plan makes the CLI
  leave plan mode, but the adapter sends no `current_mode_update`, so the
  strip kept saying "Plan" (dangerous when the answer was "use auto
  mode"). New profile field `permission_mode_followups` maps an approval
  option to the mode it implies; the engine issues `session/set_mode`,
  which the agent echoes back. Tests for the rule and for rejection.
- Caveats added: AskUserQuestion is not loaded in adapter sessions (the
  agent asks in plain text); plan-exit mode handling.
- `docs/DESIGN.md` §5: roadmap pins (adapter fork parked, prompt
  suggestions, prompt queueing, image paste, publication).
- Verified live for the assessment: Stop mid-turn (`cancelled`), plan mode
  end to end, MCP servers present (same set as the terminal), resume with
  history, approvals with the agent's own options.

### live-test round 5 (2026-09-01 late)

- **Resume now replays the conversation.** The engine preferred
  `session/resume`, which the spec defines as attaching *without* the
  previous messages; a resumed session therefore opened empty ("no tool
  output") with only the adapter's log line to look at. `session/load`
  (history replayed as ordinary events) is used whenever the agent
  advertises `loadSession`; `session/resume` remains the fallback.
- The status-strip chip for adapter stderr is now **`log (n)`** — it is
  the adapter's diagnostics, not an error channel.
- Frames arriving after a session is closed are still recorded; the record
  closes when the adapter process has exited (was: `ValueError: I/O
  operation on closed file` in the server log).
- Toolbar: more horizontal space between the selectors and the buttons.

### live-test round 4 (2026-09-01 evening)

- **Resume from the launcher failed with a bare `400`.** Cause: an empty
  directory field — the listing endpoint accepted it (`Path("")` is the
  server's own directory, so it listed CLAUDIU's own sessions) and the
  resume then posted the empty cwd. Now: the listing rejects an empty or
  non-directory cwd (`400` + JSON reason), `POST /api/sessions` answers
  `400` with a JSON `error` the View shows verbatim, the View refuses to
  query with an empty field, and **Resume uses the directory the agent
  recorded for that session** (and refills the field).
- **Adapter stderr left the conversation**: a counted `stderr (n)` chip in
  the status strip opens a drawer; nothing inline, nothing dropped.
- **Approval buttons**: standing grants are dashed/amber but no longer look
  disabled; a third button appears only when the agent offers a third
  option (Claude does so per tool).
- **Tool output collapsed by default**, with an "expand tool output"
  checkbox in the toolbar (remembered per browser).
- **Visual hierarchy and markdown-lite**: agent text produced before a tool
  call renders attenuated (a step), the final answer bright; tool rows dim
  with a status dot; `**bold**` in the accent colour, `` `code` `` and
  fenced blocks monospaced, headings emphasised — DOM nodes, never HTML.
- **`--token-file`** keeps the auth token across launches; with `--port`
  the URL is stable and bookmarkable.

### post-outage resume (2026-09-01)

- **The adapter's bundled Claude CLI was refused by the API.** After the
  default model moved to a newer family, every prompt failed with
  `Claude Code 2.1.44 does not support this model; version 2.1.251 or newer
  is required` — claude-code-acp 0.16.2 (the newest release) ships CLI
  2.1.44 inside its Agent SDK, while the installed `claude` was 2.1.257.
  New profile field **`env_resolve`** (variable → command name, resolved on
  `PATH` at spawn, *after* the scrub — the `CLAUDE_CODE_*` guard would strip
  an inherited value — with `env_set` winning): the Claude profile sets
  `CLAUDE_CODE_EXECUTABLE = "claude"`, so the user's CLI runs instead of the
  bundled copy. Verified against the real adapter: the turn completes, zero
  drift flags. What resolved is the first record of every session
  (`action: "spawn"`), is returned by `GET /api/profiles` (`env_resolved`)
  and shown in the launcher; caveat `bundled-cli` states the trade (the
  older SDK prints harmless "Unexpected case" stderr lines for message
  types newer than it knows).
- A `session/prompt` answered with a JSON-RPC **error now ends the turn**:
  `turn_ended` carries `stop_reason: "error"` plus `error {code, message}`,
  and the `turn-error` anomaly shows the message text instead of a dict
  repr. Found by the contract test, which waits for the turn end.

- **Adapter migrated to `@agentclientprotocol/claude-agent-acp` 0.73.0.**
  `@zed-industries/claude-code-acp` is deprecated on npm (renamed) and
  frozen at 0.16.2; the successor ships Agent SDK 0.3.257 (current CLI),
  still honours `CLAUDE_CODE_EXECUTABLE`, advertises `list`/`resume`/`fork`,
  and emits `usage_update` (the context gauge works, with cost) and
  `session_info_update`. Model choice moved from the vendor
  `session/set_model` method to standard **config options** (`mode`,
  `model`, `effort`, `agent`): the View shows one control per thing (a
  config option hides the legacy select) and the status strip shows the
  option's display name. New profile field `npm_package` names the package
  for `GET /api/drift` (`adapter_package`, `?profile=<id>`); the server no
  longer hardcodes an adapter. Contract tier against 0.73.0: PASS, zero
  drift.
- **Composer layout**: prompt on top, one toolbar row beneath — selectors
  left with short labels (descriptions as tooltips), Stop/Send right.
- Known gap, stated in the launcher: Claude Code's predicted next-prompt
  suggestions do not cross ACP yet (the adapter neither enables the SDK's
  `promptSuggestions` option nor forwards `prompt_suggestion`).

### first live-test feedback (2026-08-31 20:41)

Every item traced to its recorded frames before fixing:
- `[hidden]` was overridden by author `display:` rules — the command
  palette never folded back and the workspace was visible under the
  launcher. Root fix: `[hidden] { display: none !important }`.
- Adapter stderr (Claude's slash-command echo, ~100 lines for `/context`)
  was surfaced as anomalies and not recorded. Now recorded (`dir: "err"`)
  and shown as collapsible low-severity `stderr` rows; the anomaly chip is
  reserved for real anomalies, chips carry counts and clear on click.
- Thinking arrives as empty chunks (redacted); the view now shows a
  "· thinking ·" marker instead of an invisible block.
- Model selection: `session/new` advertises models and the adapter's
  `session/set_model` works — model selector added (`set_model` command,
  `model` event); the "no /model" caveat is retired.
- Approval dialog: options ordered one-shot first / standing grants last
  (the adapter lists "Always Allow" first), standing grants visibly
  cautionary, and a prominent warning listing any paths outside the
  session boundary mentioned by the tool call — shell execution is
  agent-side and cannot be fenced by the client; caveat + README updated.
- Registry: five schema methods added (`session/close|delete|list|resume|
  set_config_option`); the drift tool now scans all schema strings.
- Third round (21:54, "proceed with the rest"): **multi-session tabs**
  (Alt+1…9, Alt+N, close), **resume** (launcher lists the agent's own
  sessions via `session/list`; attach with `session/resume`), **tool-call
  rows merged by id with rendered diffs**, **context gauge** from
  `usage_update`, agent-set **session titles**, generic **config-option
  selectors** (`session/set_config_option`), and the working row now
  reports *last activity* so a stall is distinguishable from progress.
- Second round (21:21): model options now show their description ("Default
  (recommended) — Opus 4.6 · …" — Opus was there under "Default"); a
  pulsing "agent working… Ns" row with the Stop hint shows during long
  turns (`/insights`); consecutive stderr lines coalesce into one row.

## 0.2.0 — 2026-08-31 — the ACP pivot

CLAUDIU is now a **browser client for AI coding agents over the Agent
Client Protocol** — Windows-native, no WSL, no pty, no screen-scraping.
Design history: `docs/superpowers/specs/2026-08-31-acp-research.md` and
`.../2026-08-31-claudiu-acp-design.md` (decisions D1–D4); plan:
`docs/superpowers/plans/2026-08-31-claudiu-acp.md`.

- v0.1 (the terminal-mirror app) archived to `archive/claudiu-v0.1` with
  its own git history (KEEP rule 20); the tree restarts around a four-layer
  architecture: TOML agent profiles → pure-stdlib core (sans-I/O JSON-RPC,
  ACP state machine, JSONL flight recorder, drift sentinel, path policy) →
  Tornado server (token auth, env-scrubbed adapter subprocesses, WS bridge)
  → vanilla-JS web UI (documented seam: `docs/UI-PROTOCOL.md`).
- Losslessness: every frame recorded verbatim before interpretation;
  unknown protocol data surfaces as visible drift/unrecognized/anomaly
  events, each with access to its raw frame.
- Drift watch: ACP schema pinned (`vendor/acp/VERSION`, schema-v1.21.0);
  dev-time registry diff (`tools/check_schema_drift.py`, which caught
  `config_option_update` / `session_info_update` / `usage_update` on day
  one) and an online pin-vs-latest check on `/api/drift`.
- Security: per-launch token on REST+WS, Host/Origin guards, CSP,
  session path boundary for agent fs requests, `terminal` capability
  deliberately not advertised, scrubbed child environments.
- Tests: engine tier against scripted fixtures, server tier, security
  suite, Playwright e2e, and an opt-in contract tier that passed against
  the real `claude-code-acp` adapter with zero drift flags.

## 0.1.x (archived)

- Permission buttons hardened for safety: options are now parsed
  client-side from xterm's rendered buffer (the raw pty byte stream
  mis-parsed a real 3-option prompt down to one wrong option), shown only
  when the parse is an unambiguous contiguous set and stable across two
  polls, and re-verified against the live buffer at click time; when the
  parse is uncertain the view refuses to guess and points to the terminal.
- Input audit log: every stdin frame sent to a session is logged at one
  choke point (`claudiu.audit`) with length, control-char count and a
  bounded preview -- an auditable record of everything issued.
- Fidelity accounting: the conversation parser reports any unrecognised
  transcript record type in `meta.unaccounted`, and the view shows a
  warning chip, so a Claude Code schema change is visible, never silent.
- Fixed the terminal toggle vanishing in raw-terminal mode (it now lives
  at pane level, reachable from both views).
- Manual & fidelity test plan added: `docs/TESTPLAN.md`.

- Controlled conversation view (new default per session): CLAUDIU renders
  the conversation from Claude Code's transcript JSON
  (`GET /api/conversation`, `claudiu/conversation.py`, `static/convo.js`)
  instead of the raw terminal -- working dir + window title (OSC 0/2)
  header, a scrollable frame with collapsible tool output and thinking,
  lane checkboxes (thinking/tools/events/subagents) + search, model +
  tokens, live state, a composer, and permission prompts as Yes/No
  buttons. Polled ~1s; the raw terminal is hidden behind a "Show terminal"
  escape hatch for menus/pickers the JSON can't represent. Design:
  `docs/superpowers/specs/2026-08-31-conversation-view-design.md`.

- Third session state: **waiting for your input**. When a session is busy
  and its terminal shows a permission/confirmation prompt (matched against
  the new `permission_patterns` config), its tab light switches to a faster
  accent-coloured pulse. Claude Code's transcript has no record for a
  blocked prompt, so this is read from the terminal output.
- Redesigned launcher: "Any folder" on top with a filesystem browser, a
  "New folder" button (`POST /api/mkdir`), and a recently-used-folders
  dropdown (`GET /api/recent`, backed by `~/.claudiu/recent.json`,
  `recent_max`); two independently scrolling columns below for Projects
  and Resume recent. New `GET /api/dirs` folder picker.
- Interface theme: `ui_theme` (`system` / `light` / `dark`) plus a tab-bar
  toggle remembered per browser; a full light palette. The terminal keeps
  its own xterm `theme` in every mode.
- "Jump to latest" button in a tab when you have scrolled up.

- Status strip: each pane shows the last prompt typed in that session
  (click to expand); each tab carries a busy/ready light and a context
  gauge (green → amber → red at `context_warn_pct` / `context_danger_pct`
  of `context_window_tokens`). Read from the tail of Claude Code's own
  transcript via a new `GET /api/status` route, polled every
  `status_poll_ms`; sessions are spawned with an explicit `--session-id`
  so the transcript is known.
- Soft colours: sessions start with Claude Code's `dark-ansi` theme
  (`claude_theme`, `""` to opt out) so every colour it prints goes through
  the 16-entry `theme` palette instead of hard-coded truecolor; that
  palette is further muted (bright variants only a shade lighter) and bold
  text no longer switches to the bright colours.
- Terminal sizing: every terminal resizes through one debounced
  ResizeObserver path, a hidden pane is never fitted, and unchanged sizes
  are not resent -- the pty sees one final size per resize instead of a
  burst, which is what left Claude's UI drawn in only part of the pane.
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

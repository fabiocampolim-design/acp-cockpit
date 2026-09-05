# Changelog

All notable changes to CLAUDIU are documented in this file.

## Unreleased

- **Renamed to `acp-cockpit`** — the project, the Python package
  (`python -m acp_cockpit`), the distribution and the documentation. The
  name a reader sees in the interface is now a separate, configurable
  thing: `ACP_COCKPIT_UINAME`, from the environment or `uiname.toml`,
  shipped as **ClaudIU**. Over 15 characters is truncated with an ellipsis,
  because the name sits in a browser tab, a heading and a dialog title; a
  blank or broken value falls back to the default rather than leaving the
  interface nameless. The server substitutes it into the page rather than
  letting the browser fetch it, so nobody watches the name change one
  request after the page arrives.
- The data directory follows the name: `~/.acp-cockpit`. **An existing
  `~/.claudiu` with records in it keeps being used** — a project changing
  its name is no reason to strand somebody's transcripts, and quietly
  starting an empty directory beside a full one is the worst of both. Once
  the new directory exists it wins; an empty old one never does.
- **One upgrade note**: the session cookie is now `acp_cockpit_token`, so a
  browser holding the old one is signed out once. Opening the printed
  `?token=` URL again fixes it — a bookmarked pinned-port URL does this by
  itself.

## 0.4.0 - 2026-09-05 - the audit, and a client that holds still

A full-scope audit of the project (eleven findings, all closed) and six
rounds of daily use. The headline is that the two things you notice most —
that nothing jumps under your eyes, and that a dropped connection is not the
end of a session — are now true by construction rather than by luck.

- **Security.** The host/origin guard accepted every
  `http://127.0.0.1:<any port>` origin, and cookies are not scoped by port,
  so any other local web page arrived authenticated. Origin must now equal
  this server's own address *and port*, on the WebSocket too. `/ui/*` was
  served with no token and no CSP at all; it is behind the same guard now,
  and revalidates rather than being cached, because "reload the page" is
  this client's documented recovery and it has to actually refetch.
- **The view holds still.** Following ran only when a row was *added*, so a
  streamed answer — one row that grows — scrolled off the bottom while it
  was written. Settled text is now rendered once and never touched again,
  which also means an answer can be selected and copied while it arrives.
  The control panel waits until the session has settled instead of shuffling
  for its first seconds.
- **Sessions survive.** A dropped socket reconnects on its own with a cursor
  and asks only for what it missed; the replay buffer is bounded and names
  any range it had to drop instead of leaving a silent gap.
- **Archiving works without claude-session-publisher**, writing a plain
  Markdown transcript from the session's own record, in a side panel that
  never covers the conversation.
- **The account panel was reading a field the agent never sends** — every
  window now shows its real percentage, and extra credits are one badge.
- Prompt suggestions, a canonical model id in the strip, models ordered by
  capability, a launcher that remembers, a dated resume list, `Esc` to
  interrupt, records retention, and a good deal of layout work.

Full detail in the rounds below.

## Unreleased

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

### daily-use round 13 (2026-09-04)

- **The launcher remembers what you last started** — agent, directory,
  thinking — in this browser *and* on the server, so a new browser or a
  cleared profile opens on the right project instead of an empty form
  (`/api/settings`). Preferences, not state: a corrupt store costs three
  dropdowns and nothing else.
- **Resumable sessions are dated and newest first**: "2 h ago", "yesterday
  14:02", with the session id in the tooltip. One the agent never dated says
  so and sorts last instead of pretending to be recent.
- **The control panel waits instead of shuffling.** A session announces
  itself in pieces, and rendering each as it landed made the panel rearrange
  itself for a couple of seconds at every start. It shows one quiet line
  until the agent is ready and has said what it offers.
- **Extra credits are a word and a colour**: `EC` green when the account may
  spend them, red when it may not, with the reported state in the tooltip.
  The overage window's label is `7d+EC` rather than `7d +credits`.
- **Extra credits are one badge, not three.** They belong to the account,
  not to a window, and repeating `EC` on every chip was noise (seen live on
  a three-window account). One badge beside the windows, the most recent
  report wins.
- **The launcher's two columns start level**: the caveats now begin at the
  height of the name rather than the first field.

### daily-use round 12 (2026-09-04)

- **Prompt suggestions, when an adapter forwards them.** After a turn the
  agent's guess at your next prompt appears as a dashed strip over the
  composer: click to put it in the box — never sent for you — or dismiss it.
  It clears when a turn starts and when you send. The carrier is an
  otherwise empty message chunk, and it stays out of the conversation:
  a prediction is not something the agent said.
  `claude-agent-acp` 0.73 forwards none of these, so with the stock adapter
  the strip never appears and nothing changes. The ACPUPSTREAM project holds
  the two-line adapter change that makes them arrive, the reproduction, and
  the issue drafted for upstream.
- **Found by using it: two regressions from round 11 and a caching gap.**
  The lane switches, moved into the composer, had inherited its button style
  and become five filled accent buttons that dominated the panel — they are
  quiet outlined switches again. The context gauge drew an empty bordered box
  in the status strip until the agent first reported usage. And the UI files
  went out with no cache directive, so a browser could serve its own copy
  from heuristic freshness: "reload the page" is this client's documented
  recovery from half of what goes wrong, and it only works if the reload
  fetches the new file. They revalidate now (`Cache-Control: no-cache`, with
  the ETag keeping it at a 304).
- **`agents/local-*.toml` is yours.** Profiles matching that name load
  exactly like the shipped ones and are never tracked, so a profile pointing
  at a local adapter build keeps its machine-specific path out of the
  repository.

### daily-use round 11 (2026-09-04)

- **The conversation follows the last message again.** Following only ran
  when a *row was added*, so a long answer arriving chunk by chunk — one row,
  growing — scrolled off the bottom while it was written, under a working
  line that rewrites itself every second. Any growth of the conversation now
  follows it (a `ResizeObserver` on the pane, plus the explicit calls), so
  the end of the text stays in view.
- **One panel for the session controls.** The five lane switches moved from
  the status strip down beside the selectors, under the prompt. The toolbar
  wraps properly instead of leaving a hole between the two groups at half
  width, and short windows get a more compact composer.
- **Archiving is a side panel, not a banner.** It opens beside the
  conversation (under it on a narrow window), never covers it, and closes.
  It offers a destination — with a folder picker, remembered per browser —
  and a checkbox per format the server can actually write. What was written
  is listed there and noted once in the harness lane. The old "archived:"
  note sat on top of the conversation with no way to dismiss it.
- **Archiving works without claude-session-publisher.** It used to refuse
  (501). Now the server writes a plain Markdown transcript from the session's
  own record — prompts, answers, thinking, tool-call titles — warns that it
  is the simpler one, and says so in the file too. With the publisher
  configured you get its full document, and the destination is passed
  through as `--archive-dir`.
- **The status strip names the model the API named.** `claude-opus-5`, not
  `Opus` — the canonical id, taken from the agent's own per-model tally
  (`_meta.quota.model_usage`), which is the only place it appears. The
  selector's label and the option value are in the tooltip. `usage` carries
  `models_used` for any View.
- **Tabs never push the account chips off the screen.** The strip scrolls on
  its own; help, settings and the limit chips are pinned right. Labels shrink
  as tabs multiply, browser-style, down to a couple of letters, and past that
  the oldest tabs scroll out of sight.
- **The launcher is two columns** on a wide window: the form on the left,
  what the agent wants you to know on the right. One column when there is no
  room, scrolling either way.

### daily-use round 10 (2026-09-04)

- **The models are offered by decreasing capability** — default, Fable, Opus,
  Sonnet, Haiku — instead of the order the adapter happens to send them in
  (default, Sonnet, Fable, Opus, Haiku). The order is agent DATA, not code:
  `config_option_order` in the profile, matched as substrings of a choice's
  value and name, so a versioned id like `claude-fable-5-1[1m]` keeps being
  recognised as Fable when the version moves. Nothing is renamed, dropped or
  invented, and a choice nothing matches keeps its place after the rest.
- **Esc stops the agent**, the way it does in the terminal — and with the
  command list open it closes that first, while inside a dialog it stays the
  dialog's own key (an approval still refuses to be dismissed unanswered).
- **Every other key types.** Press one with the focus anywhere on the page
  and the character lands in the composer, as a terminal always types at the
  prompt.
- **Every shortcut is written down**, in Help and in the user manual: Esc,
  Enter, Shift+Enter, `/`, Alt+N, Alt+1…9, digits for an approval, and the
  typing rule above.
- **Account windows are labelled from what arrives**, not from a list this
  client keeps guessing at: a per-model meter (`7d Fable`, `7d Opus`) reads
  correctly the first time the agent ever reports it. `7d +credits` is the
  seven-day window with extra credits included.
- **The credits state is abbreviated on the chip** — `EC in use`, `EC
  available`, `EC out` — with the words spelled out in the tooltip. There is
  no amount and no currency, because the agent does not send one: the
  rate-limit payload carries the *state* of extra credits and never a
  balance. The manual says so where it would otherwise be looked for.

### audit fixes, round 2

The rest of the audit's list, the four findings about living with the client
day to day.

- **A dropped socket no longer kills the tab.** The session lives in the
  server, so losing the WebSocket — a restart, a sleeping laptop — never
  ended it; but the View just said *disconnected* and sat there until
  somebody thought to reload. It now reconnects on its own with a backoff,
  asking only for the events it missed (`?after=<seq>`), and restores the
  state it was in. Two closes it does not retry, because retrying cannot
  help: a refused login and a session the server no longer has. Both say so.
- **The replay buffer is bounded, and says what it dropped.** Every event of
  every session was kept in memory for the life of the process and re-sent
  in full on every attach. It now keeps the most recent 2,000 per session,
  and a client asking for older ones is told exactly which range it will not
  get (`replay_truncated`) rather than being handed a silent gap. The JSONL
  record on disk is, as ever, the complete copy.
- **Streaming text can be selected while it streams.** Every chunk
  re-rendered the whole message, which was quadratic and — the part you
  could feel — wiped out any selection you had made inside it, so an answer
  could not be copied until the turn ended. Only the unfinished tail is
  rebuilt now; settled lines are rendered once and left alone, and the split
  never lands inside a code fence.
- **Two live sessions no longer confuse each other's questions.** The map
  holding a form's field titles was keyed by request id alone, and request
  ids restart at 1 in every session, so the second question overwrote the
  first's labels.
- **Records have a retention policy.** `--records-keep-days N` deletes
  records older than N days at startup; the default keeps everything,
  because deleting a transcript is your decision, and the server now prints
  how many sessions and how many megabytes it is holding.
- The build plans the specs were executed from are no longer tracked: the
  repo publishes the research notes and the approved specifications
  (`docs/superpowers/specs/`), which are the design history a reader wants;
  the task-by-task plans were a record of the making, and stay on the
  machine that did it.

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
  (`--archiver` / `ACP_COCKPIT_ARCHIVER`), which writes it into the usual
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

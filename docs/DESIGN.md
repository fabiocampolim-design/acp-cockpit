# Design notes — CLAUDIU

What this program is trying to be, the decisions that shaped it, what each
one cost, and what was rejected. `README.md` is the product page and
`AGENTS.md` the inventory; this file is the *why*. The design history in
full — research notes, the approved specification and the implementation
plan — is under `docs/superpowers/` (`specs/2026-08-31-acp-research.md`,
`specs/2026-08-31-claudiu-acp-design.md`, `plans/2026-08-31-claudiu-acp.md`).

## 1. The problem framing

The author wanted to run AI coding agents (Claude Code first) from a
browser instead of a terminal — for eye strain, for stability, and because
a browser page can hold several long sessions side by side without a
terminal multiplexer. The first version (0.1, archived in
`archive/claudiu-v0.1`) mirrored the real terminal UI into the browser
through a pseudo-terminal and *read the screen back* to offer buttons for
permission prompts. It worked, and it was fragile by construction: a
full-screen terminal application repaints with escape codes, its prompt
wording changes between releases, and one mis-parsed permission prompt
(three options read as one, wrong, option) showed that scraping a screen
can never be a safety boundary.

The Agent Client Protocol (ACP) removes the guesswork: the same
conversation arrives as structured JSON-RPC over stdio — messages, thoughts,
tool calls with diffs, permission requests with typed options, config
options, usage. CLAUDIU 0.2 is a browser client for that protocol, with
one guarantee: **nothing that crosses the wire is lost or silently
misread.**

## 2. Decisions and their trade-offs

| Decision | Why | What it costs / what was rejected |
|---|---|---|
| **Pure ACP; the agent runs behind a stdio adapter** (`claude-agent-acp`), no pseudo-terminal, no screen reading. | Structured data is the only safe basis for buttons that grant permissions. | The real terminal UI is not shown; anything the adapter does not forward is invisible (see §4). The 0.1 pty mirror was archived, not kept as a second mode — two rendering paths would have doubled every safety argument. |
| **Every frame is recorded verbatim before interpretation** (`core/record.py`, one JSONL per session); the View gets typed events with a `raw_ref` back into the record. | The record is the ground truth and the audit trail; a rendering bug can be diagnosed from it after the fact (every fix in the first live-test rounds was root-caused from a record). | Records contain the conversation; disk use grows with use; the user must treat the directory as private. |
| **Unknown protocol data is a visible event**, never a dropped one: `unrecognized` rows with raw access, `drift` and `anomaly` chips; a dev-time registry diff against the pinned ACP schema and an online pin-vs-latest check. | A protocol change must announce itself in the UI, not corrupt the rendering quietly. The sentinel caught three new update kinds on day one. | Noise when the protocol moves; the answer is to widen the registry, never to filter. |
| **Four layers with one-way knowledge**: TOML agent profiles → pure-stdlib core (sans-I/O JSON-RPC, ACP state machine, recorder, sentinel, path policy) → Tornado server (auth, subprocesses, WebSocket bridge) → vanilla-JS View speaking a documented protocol (`docs/UI-PROTOCOL.md`, enforced by tests). | Each seam is swappable: another agent is a profile, another server implements three small ports, another front-end implements the UI protocol. | Some duplication between the engine's event vocabulary and the View; the UI protocol must be maintained as a contract. |
| **The engine never names an agent.** Everything Claude-specific is data in `agents/claude.toml`: command, environment scrub (the nested-session guard), runtime resolution, known vendor `_meta` extensions, caveats shown in the launcher. | Keeps the core honest and testable against scripted fixtures; adding an agent needs no code. | Profile-level knobs accumulate (`env_scrub`, `env_set`, `env_resolve`, `npm_package`, caveats); each is documented in `agents/PROFILE-SCHEMA.md`. |
| **Prefer the user's installed CLI over the copy the adapter bundles** (`env_resolve`: `CLAUDE_CODE_EXECUTABLE` → the `claude` on PATH). | The adapter pins an Agent SDK that pins a CLI; the API refused that bundled copy for a new model on 2026-09-01 with zero local changes. The user's CLI auto-updates. The choice is shown in the launcher and written as the first record of every session. | Two CLIs coexist on the machine; an SDK older than the CLI it drives may log unknown message types. |
| **Adapter as a runtime dependency the user installs, never vendored.** | Licensing clarity, independent upgrades, no stale copy inside this repo. | Upstream renames and deprecations must be watched (the adapter was renamed once already; `GET /api/drift` reports installed vs latest for the profile's `npm_package`). |
| **Security model: 127.0.0.1 only, a random bearer token per launch (cookie, constant-time compare), foreign Host/Origin refused, strict CSP, no external resources.** Optional `--token-file` keeps the token across launches for a stable URL. | Localhost is not a trust boundary; other local processes and DNS-rebinding pages must not reach the session. | No multi-user, no remote access by design; the persistent token file must be treated like a password. |
| **Agent file access is confined to the project directory** (symlink-resolved) for `fs/*` requests; **the `terminal` capability is deliberately not advertised.** | The client can only fence what it is asked to do; advertising a terminal would hand the agent a shell through the client's own hands. | Shell commands the agent runs *itself* are not confined by the client — the approval dialog flags out-of-boundary paths it can see and the user's answer is the control; the caveat says so in the launcher, the README and the manual. |
| **Approval dialog: one-shot options first, standing grants last and visibly distinct; digits 1–9; no Escape-to-dismiss; fail-safe reject after a timeout.** | Standing grants ("always allow") are the dangerous answer; the adapter lists them first, the user pressed it under time pressure once. | The order differs from the terminal's; the number of buttons is the agent's (two or three per tool). |
| **Plain-text-first rendering, markdown-lite built from DOM nodes, never HTML.** | Agent output is untrusted text; `innerHTML` is not an option under the CSP or in principle. | No tables, no images, no nested lists — enough emphasis to read, not a document renderer. |
| **Visual hierarchy borrowed from the terminal**: interim agent text (before a tool call) attenuated, the final answer bright, tool rows dim with a status dot, tool output collapsed by default, adapter stderr in a drawer. | Readers scan for the answer; steps are context. | A heuristic ("text before a tool call is a step") that can misjudge a two-part answer. |
| **Vanilla JS, no build step, vendored nothing in the View.** | Anyone can read the whole client in one sitting; no toolchain to rot. | No components, no types; discipline instead of tooling. |

## 3. What was rejected

- **toad** (Will McGugan's ACP terminal/browser client): a real product that
  does the structured-UI part well, but Linux/macOS with Windows only via
  WSL, AGPL, and it runs Claude as an ACP agent through the same adapter; a
  hands-on test hit a blocking `/model` bug. It informed this design at the
  behaviour level; no code was taken.
- **Driving the CLI's headless `stream-json` protocol directly** (the Agent
  SDK wire format): lossless and stable, but it means writing a whole agent
  client with its own permission UI and no ecosystem; ACP gives the same
  structure plus other agents for free.
- **Keeping the 0.1 terminal mirror as a second mode**: every safety
  argument would have to be made twice.

## 4. Open questions

- **What the adapter drops.** `claude-agent-acp` 0.73 explicitly discards
  the SDK's `prompt_suggestion` (the terminal's predicted next prompt) and
  `tool_use_summary`, and ignores `system` notifications other than
  init/compacting/compact boundary (hooks, tasks, persisted files — its
  issue #1030). CLAUDIU cannot show what never reaches it; the options are
  upstream requests or a patched fork of the adapter (Apache-2.0).
- **Thinking text — answered (2026-09-04).** The empty chunks were not
  redaction by the adapter: recent models return *summarized* thinking or
  none, and the summaries are only produced when the SDK is asked for them.
  The profile now asks (`client_options.thinking`, forwarded as
  `_meta.claudeCode.options` on session creation), so thoughts arrive as
  the model's own summary. Raw thinking text is not on offer from the API
  for these models and no client can show it.
- **Publication.** Name and collision check, first CI run on Linux/macOS
  (the README check-count test assumes Playwright is installed), and a
  release cadence are the author's calls.

## 5. Roadmap pins (2026-09-01, after the first day of live use)

Recorded decisions, not open questions — each waits for the stated trigger.

- **A CLAUDIU-owned fork of the adapter is parked** (the author: "pin").
  The facts stay on record (§4); the trigger is a dropped message that
  blocks daily work, or upstream declining the patches.
- **Prompt suggestions** wait for upstream (`prompt_suggestion` is dropped
  by the adapter); the request is drafted.
- **AskUserQuestion — done (2026-09-04).** The adapter disabled the tool
  only because this client did not advertise `elicitation.form`; it does
  now, and the questions arrive as ACP form elicitations rendered as a
  modal form. URL-mode elicitation stays unadvertised and is answered
  "cancel" with an anomaly if one ever arrives.
- **Plan-mode exit**: the adapter sends no mode update after
  `ExitPlanMode`; the profile's `permission_mode_followups` re-asserts the
  implied mode. Remove the rule when the adapter announces the change.
- **Prompt queueing while a turn runs** is agent-supported
  (`_meta.claudeCode.promptQueueing`) but the View gates Send on `ready`.
  Trigger: the author asking for it — the terminal allows typing ahead.
- **Image paste and `@file` completion** in the composer: not built;
  the adapter advertises image prompts. Trigger: need.
- **Version bump and publication** wait for a "better state" (the author,
  2026-09-01); rule-26 files are in place.


# UI Protocol — the View seam

Any UI (web, desktop, mobile) implementing this document is a full ClaudIU
front-end. The bundled `acp_cockpit/ui/web/` consumes exactly this protocol and
nothing else. `tests/test_docs_sync.py` enforces that this document stays in
lockstep with the code.

## 1. Authentication

The server prints a launch URL `http://127.0.0.1:<port>/?token=<token>` once
per run (with `--token-file` the token persists across runs). Opening it sets the `acp_cockpit_token` cookie (HttpOnly, SameSite
Strict) and redirects to `/`. Every REST call and WebSocket upgrade must
carry that cookie; anything else is `403`. The server binds 127.0.0.1 only
and rejects foreign `Host`/`Origin` headers.

## 2. REST routes

### `GET /api/profiles`
```json
{"profiles": [{"id": "claude", "name": "Claude Code",
               "caveats": [{"id": "model-picker", "text": "..."}],
               "install_ok": true,
               "install_hint": "npm install -g @agentclientprotocol/claude-agent-acp",
               "env_resolved": {"CLAUDE_CODE_EXECUTABLE": "C:\\Users\\me\\.local\\bin\\claude.exe"}}]}
```
`env_resolved` is what the profile's `env_resolve` table resolved on this
machine (empty when nothing resolved); show it so the user knows which
runtime the adapter is pointed at.

### `POST /api/sessions` — body `{"profile": "claude", "cwd": "C:\\work\\proj"}`

Optional `resume` (an agent session id) attaches to an existing agent
session; optional `client_options` (an object) is merged over the profile's
`client_options` and sent to the agent as `_meta.claudeCode.options` — this
is where session-CREATION choices live, `thinking` above all, because ACP
offers no way to change them later. A non-object `client_options` is a 400.

**One attachment per agent session.** Resuming an agent session that another
live session already holds is a **409** with `{"error": ..., "session":
"<sid>"}` naming the session that holds it: two adapters attached to one
agent session write the same transcript file.
Returns `{"id": "<sid>"}`. Errors: `400` bad profile/cwd (JSON body
`{"error": "..."}` — show it verbatim); `424` adapter not installed (body
carries `install_hint`). Add `"resume": "<agent session
id>"` (from the listing below) to attach to an existing agent session
instead of creating one: `session/load` when the agent advertises
`loadSession` — the conversation so far is replayed as ordinary events
before `session_state: ready` — else `session/resume`, which attaches
without history.

### `GET /api/profiles/<id>/sessions?cwd=<dir>`
Sessions the *agent* knows for that directory — a throwaway adapter is
spawned for `session/list` and closed. `{"sessions": [{"sessionId",
"cwd", "title", "updatedAt"}], "error": null|str}`. `400` with
`{"sessions": [], "error": "..."}` when `cwd` is empty or not a directory
(an empty cwd would list the server's own directory). Resume with the
`cwd` the agent reports for the session, not with whatever the field holds.

### `GET /api/sessions`
```json
{"sessions": [{"id": "ab12", "profile": "claude",
               "cwd": "C:\\work\\proj", "state": "ready",
               "title": "Fix the widget", "agent_session": "<agent id>"}]}
```

### `DELETE /api/sessions/<sid>` — closes the session. `{"ok": true}`.

### `GET /api/settings` · `POST /api/settings`

The launcher's last-used choices — `{"profile", "cwd", "thinking"}`, any of
them null — kept beside the records so a browser that has never been here
opens on the right project instead of an empty form. Preferences, not state:
a View should prefer its own memory when it has one, and treat a corrupt or
missing store as empty. POST keeps only those three keys, and only strings.

### `GET /api/dirs?path=<dir>`
The launcher's folder picker (a page cannot learn an absolute path from
the OS folder dialog, so the server walks the tree). Empty `path` = the
home directory.
```json
{"path": "C:\\work", "parent": "C:\\", "roots": ["C:\\", "D:\\"],
 "dirs": [{"name": "proj", "path": "C:\\work\\proj"}], "error": null}
```
`path` comes back resolved (native form, symlinks followed); `parent` is
`null` at a filesystem root; `roots` are the drives on Windows and `["/"]`
elsewhere; `dirs` holds subdirectories only (files never appear), plain
names first and dot-directories last, sorted case-insensitively. `400`
with `"dirs": []` and `error` set when `path` is not a directory or cannot
be listed. Exposure equals what the token already grants (a session may be
started in any directory); the route is gated like every other.

### `GET /api/sessions/<sid>/archive`

What this server can actually write, so a View never offers a choice that
would fail: `{"publisher": bool, "formats": [...], "default_formats": [...],
"default_dest": "<path>", "agent_session": "<id>|null", "warning": null or a
sentence saying the full publisher is not configured}`. With
claude-session-publisher: html, markdown, text, latex, pdf. Without it:
markdown, written by ClaudIU itself.

### `POST /api/sessions/<sid>/archive` — body `{"formats": ["html", "markdown"], "dest": "<directory>"}`

Writes the conversation. With the publisher configured it hands the
session's agent-session id to `transcript_archiver.py` (named by the
server's `--archiver` / `ACP_COCKPIT_ARCHIVER`; the tool is never vendored in)
and passes `--archive-dir`. **Without it the server writes a plain Markdown
transcript from the session's own record** and marks the answer
`"fallback": true` with a `warning` — refusing to save anything because
an optional tool is missing is not an acceptable answer. Both answer
`{"ok": true, "output": ["<file>", ...]}`; **400** for a format this server
cannot write, **409** before the session has an agent session, **502** when
the writer itself fails.

### `GET /api/drift`
```json
{"pinned_schema": "schema-v1.21.0", "flags": [], "online": true,
 "adapter_package": "@agentclientprotocol/claude-agent-acp",
 "latest": {"schema": "schema-v1.21.0", "adapter_latest": "x.y.z",
            "adapter_installed": "x.y.z"}}
```
`flags` non-empty means the pinned protocol schema or the installed adapter
is behind the latest published version — surface it. `adapter_package` is
the checked profile's `npm_package` (`?profile=<id>` picks the profile;
default: the first profile that declares one; `null` = no adapter check).

## 3. WebSocket

`GET /ws/sessions/<sid>?after=<seq>` (cookie-authenticated). The server
replays what the client does not have — everything when `after` is absent or
`0`, otherwise only events with a higher `seq` — and then streams live.

**A View must reconnect by itself.** The session lives in the server, so a
dropped socket (a restart, a sleeping laptop) is not the end of it: reopen
the socket with `after=<the highest seq you hold>`, which is what keeps the
reconnect from replaying the conversation a second time. Close codes `4403`
(authentication) and `4404` (no such session) are final — retrying cannot
help; anything else should be retried with a backoff. The replay resumes
after your cursor, so nothing re-announces the state you were in: keep the
last `session_state` yourself and restore it when the socket reopens.

Client → server messages are JSON commands:

```json
{"cmd": "prompt", "text": "the user's message"}
{"cmd": "cancel"}
{"cmd": "set_mode", "mode": "acceptEdits"}
{"cmd": "set_model", "model": "sonnet"}
{"cmd": "set_config_option", "config": "effort", "value": "low"}
{"cmd": "permission", "request": 44, "option": "allow"}
{"cmd": "elicitation", "request": 77, "action": "accept",
 "content": {"question_0": "Blue", "question_1": ["Ice"]}}
{"cmd": "elicitation", "request": 77, "action": "decline"}
```

`elicitation` answers an `elicitation_request`. `accept` carries the
`content` object the form produced (values may be strings, numbers,
booleans or string arrays, per the requested schema); `decline` carries
none and means "the user answered nothing" — the agent continues without
an answer, so it is also the fail-safe. Fields the View could not render
are simply absent from `content`.

`set_model` uses the agent's `session/set_model` extension (listed in the
profile's `extensions`); agents without it answer with an error that
surfaces as an `anomaly`.

A malformed or ill-timed command comes back as an `anomaly` event with
category `command-error` (it never kills the socket).

## 4. Events

Every server → client message is one event:

```json
{"kind": "...", "session": "<sid>", "seq": 7,
 "ts": "2026-08-31T18:00:00.000+00:00", "data": {...}, "raw_ref": 12}
```

| Kind | `data` payload | Rendering intent |
|---|---|---|
| `session_state` | `state` (`starting`/`ready`/`turn`/`failed`/`closed`), `detail`; the `ready` that follows initialize also carries `agent_info` (`{name, version, title}` from the agent's `initialize` response, or null) | Status strip; disable composer unless `ready`. Show `agent_info` where a reader would look for "which agent, which version" (ClaudIU: the tab tooltip and the status strip's tooltip). |
| `message_chunk` | `role` (`agent`/`user`/`thought`), `text`, `parent_tool_call_id` (the tool call that owns it, or null) | Append to the conversation; aggregate consecutive chunks of one role; `thought` dimmed/collapsible. A non-null `parent_tool_call_id` means a **subagent** said it — file it under that tool call, not the main agent. |
| `tool_call` | ACP toolCall passthrough (`toolCallId`, `title`, `kind`, `status`, `content`, `locations`, …) | Collapsible tool row; render diff content when present. |
| `tool_call_update` | same shape, partial | Update the matching row by `toolCallId`. |
| `plan` | `entries` (list of `{content, status, priority}`) | Plan panel. |
| `commands` | `commands` (list of `{name, description, input}`) | Command palette source. |
| `mode` | `current`, `available` (list of `{id, name}`) | Mode selector. |
| `model` | `current`, `available` (list of `{modelId, name, description}`) | Model selector (from `session/new`'s `models`; empty `available` = current changed only). |
| `stderr` | `line` | Adapter stderr: count it in a chip, show it in a drawer on demand — out of the conversation flow, never dropped (the engine records it). |
| `usage` | `used`, `size` (tokens), `cost` (`{amount, currency}` or null), `models_used` (the canonical model ids the agent has billed this session to, e.g. `["claude-opus-5"]`, from its own per-model tally; empty until it reports one) | Context gauge in the status strip. `models_used` is the only place the API's real model id appears — a config option carries the adapter's short value and label — so show it where a reader would quote it. |
| `rate_limit` | the agent's ACCOUNT rate-limit state, passed through whole. Claude reports the windows in `unifiedWindows` — a map of window name (`five_hour`, `seven_day`, `seven_day_overage_included`, ...) to `{utilization, resetsAt}` — and keeps `status`, `rateLimitType`, `resetsAt` and the overage/credits fields at the top level; a simpler payload has a single window as top-level `rateLimitType` + `utilization`. **`utilization` is a fraction (0.55 = 55 %).** | Account-wide, not session state: show the latest state of EVERY window reported, somewhere permanent (ClaudIU: top right, one chip each). Never invent a window that was not reported, and do not read only the top level — the usual payload carries no `utilization` there at all. |
| `prompt_suggestion` | `text` | The agent's guess at your next prompt, offered after a turn. Offer it, never send it: the reader accepts or ignores it (ClaudIU: a chip over the composer that fills the box). Most adapters do not forward these — claude-agent-acp 0.73 discards the SDK message — so a View must work perfectly without ever seeing one. |\n| `session_info` | `title`, `updatedAt` (either may be null) | Session/tab title set by the agent. |
| `config_option` | `options` — the FULL current set of `SessionConfigOption` (`id`, `name`, `type` `select`/`boolean`, `currentValue`, `options` for selects) | Generic selectors; changing one sends `set_config_option`. |
| `permission_request` | `request` (id), `tool_call`, `options` (list of `{optionId, name, kind}`), `outside_boundary` (absolute paths mentioned by the tool call that fall outside the session boundary) | Modal approval dialog; explicit choice required. Non-empty `outside_boundary` MUST be shown prominently: shell execution is agent-side and the user's answer is the only control. Present one-shot options before standing grants. |
| `permission_resolved` | `request`, `option`, `source` (`user`/`failsafe`/`agent`) | Close the dialog; show fail-safe rejections distinctly. `agent` means the agent withdrew the request (`$/cancel_request`) — the answer was `cancelled`, nobody chose. |
| `elicitation_request` | `request` (id), `message`, `schema` (the requested JSON Schema: `properties`, each a `string` — with `oneOf`/`enum` for single-select — `array` with `items.anyOf`/`items.enum` for multi-select, `boolean`, `number`, `integer`), `tool_call_id` (or null) | Modal form dialog. A single-select renders as radios, a multi-select as checkboxes, a plain string as a text box (this is how an "Other" free-text field arrives). A property type the View does not understand MUST NOT be rendered as another control — name it and leave it unanswered. Offer an explicit skip (`decline`). |
| `elicitation_resolved` | `request`, `action` (`accept`/`decline`/`cancel`), `content` (what was answered, or null), `source` (`user`/`failsafe`/`agent`) | Close the dialog and record the answer in the conversation; a `failsafe` decline means nobody answered in time; `cancel` with source `agent` means the agent withdrew its own question (`$/cancel_request`). |
| `fs_request` | `op` (`read`/`write`), `path`, `allowed` | Inline notice of agent file access and the policy verdict. |
| `turn_ended` | `stop_reason`; when `"error"` also `error` `{code, message}` | Turn separator; re-enable composer. A failed `session/prompt` still ends the turn (the same message arrives first as a `turn-error` anomaly). |
| `vendor_update` | `kind` (the `sessionUpdate` value), `update` (the whole update object) | A `session/update` kind outside the ACP schema that this agent's adapter is KNOWN to send (`vendor_update_kinds` in the registry — claude-agent-acp's `subagent_spawned`, `subagent_state_update`, `async_task_*`). Known is not drift, so no chip; render it as a collapsible row naming the kind, with raw access. `subagent_*` belongs to the `subagents` lane, the rest to `events`. |
| `replay_truncated` | `from_seq`, `to_seq` | The server's replay buffer no longer holds that range (it keeps the most recent events, not the whole session; the JSONL record keeps everything). Say so where the reader can see it — silently skipping a gap is the one thing this protocol does not do. Transport, not agent traffic. |
| `anomaly` | `category`, `detail` | MUST be surfaced (chip + inline row); never dropped. Reading them MUST NOT destroy them: ClaudIU's chip opened and *cleared* the list in one click until 2026-09-04 — dismissal is a separate, explicit act. |
| `drift` | `flags` (list of strings) | MUST be surfaced (chip with details); protocol has outgrown the client. |
| `unrecognized` | `why`, `frame` | MUST be surfaced; render as an explicit unknown with raw access. Also used for a message content block that is not text (an image, a resource) and for any notification this client does not act on (`elicitation/complete`): recognised by name, not rendered, so shown. |

## 4a. Lanes — what a View may hide

Every conversation row belongs to a lane, and a View SHOULD let the reader
switch each one off. Off means **gone from the page**, not dimmed:

| Lane | Rows |
|---|---|
| `thinking` | `message_chunk` with `role: "thought"` |
| `tools` | `tool_call` / `tool_call_update` rows of the main agent |
| `subagents` | rows carrying `parent_tool_call_id` (or the tool call that owns them) |
| `events` | `turn_ended`, `fs_request`, `elicitation_resolved` |
| `harness` | `stderr`, `anomaly`, `drift`, `unrecognized` |

The agent's own answer and the user's prompts have no lane and are never
hidden. Hiding a lane is a VIEW choice and never changes what the client
asks the agent for — the one exception is thinking, which is a session
creation option (`client_options.thinking`) because ACP cannot change it
mid-session.

## 5. Ordering guarantees

`seq` strictly increases per session (gaps impossible). WS attach replays,
in order, everything after the client's cursor before any live event, so a
reconnect is lossless in the ordinary case. The buffer is bounded, so a
client that was away long enough may be told a range was dropped — with
`replay_truncated`, naming exactly which. The JSONL record is the lossless
copy; the buffer is a convenience.

## 6. The losslessness contract

`raw_ref` points to the line number in the session's JSONL record
(`--records` dir) holding the verbatim protocol frame behind the event.
A conforming UI must offer a way to reveal it, and must render `anomaly`,
`drift`, and `unrecognized` events visibly — dropping them breaks the
product's core guarantee.

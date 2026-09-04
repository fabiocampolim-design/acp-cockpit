# UI Protocol — the View seam

Any UI (web, desktop, mobile) implementing this document is a full CLAUDIU
front-end. The bundled `claudiu/ui/web/` consumes exactly this protocol and
nothing else. `tests/test_docs_sync.py` enforces that this document stays in
lockstep with the code.

## 1. Authentication

The server prints a launch URL `http://127.0.0.1:<port>/?token=<token>` once
per run (with `--token-file` the token persists across runs). Opening it sets the `claudiu_token` cookie (HttpOnly, SameSite
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

`GET /ws/sessions/<sid>` (cookie-authenticated). The server first replays
every event the session has emitted so far, then streams live. Client →
server messages are JSON commands:

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
| `session_state` | `state` (`starting`/`ready`/`turn`/`failed`/`closed`), `detail` | Status strip; disable composer unless `ready`. |
| `message_chunk` | `role` (`agent`/`user`/`thought`), `text` | Append to the conversation; aggregate consecutive chunks of one role; `thought` dimmed/collapsible. |
| `tool_call` | ACP toolCall passthrough (`toolCallId`, `title`, `kind`, `status`, `content`, `locations`, …) | Collapsible tool row; render diff content when present. |
| `tool_call_update` | same shape, partial | Update the matching row by `toolCallId`. |
| `plan` | `entries` (list of `{content, status, priority}`) | Plan panel. |
| `commands` | `commands` (list of `{name, description, input}`) | Command palette source. |
| `mode` | `current`, `available` (list of `{id, name}`) | Mode selector. |
| `model` | `current`, `available` (list of `{modelId, name, description}`) | Model selector (from `session/new`'s `models`; empty `available` = current changed only). |
| `stderr` | `line` | Adapter stderr: count it in a chip, show it in a drawer on demand — out of the conversation flow, never dropped (the engine records it). |
| `usage` | `used`, `size` (tokens), `cost` (`{amount, currency}` or null) | Context gauge in the status strip. |
| `session_info` | `title`, `updatedAt` (either may be null) | Session/tab title set by the agent. |
| `config_option` | `options` — the FULL current set of `SessionConfigOption` (`id`, `name`, `type` `select`/`boolean`, `currentValue`, `options` for selects) | Generic selectors; changing one sends `set_config_option`. |
| `permission_request` | `request` (id), `tool_call`, `options` (list of `{optionId, name, kind}`), `outside_boundary` (absolute paths mentioned by the tool call that fall outside the session boundary) | Modal approval dialog; explicit choice required. Non-empty `outside_boundary` MUST be shown prominently: shell execution is agent-side and the user's answer is the only control. Present one-shot options before standing grants. |
| `permission_resolved` | `request`, `option`, `source` (`user`/`failsafe`) | Close the dialog; show fail-safe rejections distinctly. |
| `elicitation_request` | `request` (id), `message`, `schema` (the requested JSON Schema: `properties`, each a `string` — with `oneOf`/`enum` for single-select — `array` with `items.anyOf`/`items.enum` for multi-select, `boolean`, `number`, `integer`), `tool_call_id` (or null) | Modal form dialog. A single-select renders as radios, a multi-select as checkboxes, a plain string as a text box (this is how an "Other" free-text field arrives). A property type the View does not understand MUST NOT be rendered as another control — name it and leave it unanswered. Offer an explicit skip (`decline`). |
| `elicitation_resolved` | `request`, `action` (`accept`/`decline`), `content` (what was answered, or null), `source` (`user`/`failsafe`) | Close the dialog and record the answer in the conversation; a `failsafe` decline means nobody answered in time. |
| `fs_request` | `op` (`read`/`write`), `path`, `allowed` | Inline notice of agent file access and the policy verdict. |
| `turn_ended` | `stop_reason`; when `"error"` also `error` `{code, message}` | Turn separator; re-enable composer. A failed `session/prompt` still ends the turn (the same message arrives first as a `turn-error` anomaly). |
| `anomaly` | `category`, `detail` | MUST be surfaced (chip + inline row); never dropped. |
| `drift` | `flags` (list of strings) | MUST be surfaced (chip with details); protocol has outgrown the client. |
| `unrecognized` | `why`, `frame` | MUST be surfaced; render as an explicit unknown with raw access. |

## 5. Ordering guarantees

`seq` strictly increases per session (gaps impossible). WS attach replays
the full buffer in order before live events; reconnecting is therefore
lossless.

## 6. The losslessness contract

`raw_ref` points to the line number in the session's JSONL record
(`--records` dir) holding the verbatim protocol frame behind the event.
A conforming UI must offer a way to reveal it, and must render `anomaly`,
`drift`, and `unrecognized` events visibly — dropping them breaks the
product's core guarantee.

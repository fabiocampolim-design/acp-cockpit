# CLAUDIU — controlled conversation view (design)

*2026-08-31. Supersedes nothing; extends the base design with a second,
fully-controlled way to view and drive a session.*

## Problem

Claude Code's TUI redraws a full-screen Ink/React app with raw cursor
moves: text and frame are entangled, it reflows on every resize, the
thinking line and menus flicker, and the reading experience is poor.
Fabio wants a **stable, uncluttered screen that CLAUDIU fully controls**,
with the raw terminal output hidden.

## Feasibility (what the sources can and cannot give us)

- **Transcript JSONL** (`~/.claude/projects/<slug>/<id>.jsonl`) is
  append-only history. It **perfectly** captures the *conversation*:
  prompts, assistant text, thinking blocks, tool calls + results, system
  events, `cwd`, `gitBranch`, model, token `usage`, `permissionMode`,
  compact boundaries, subagents, queued messages. Its **schema is stable**
  — the same record types/fields appear across all 15 Claude Code versions
  on this machine (2.1.233 … 2.1.251).
- **The pty stream** is the only source for *interactive* surfaces:
  the permission dialog's options, slash-command autocomplete, `/model`
  and plan selectors, the `@`-file picker, arrow-key menus, the live
  thinking spinner, and the **window title** (OSC 0/2 escape). These are
  **not** in the transcript, and per the changelog they **change often**.

**Conclusion.** Render the conversation from JSON (safe, stable). Keep the
pty for input and for the interactive surfaces JSON can't model. Move only
*individual, stable* surfaces (the permission prompt) into controlled UI.
A permanent **raw-terminal escape hatch** covers everything else. Full
reimplementation of menus ("Option 3") is deferred and probably never
worth it given surface churn; the architecture leaves room for it by
making each controlled surface an independent, removable layer.

## Architecture

Each tab keeps **both**:

1. a **hidden xterm** bound to the pty websocket — it owns stdin (the
   composer and permission buttons send through it) and is the
   **escape hatch**: a toggle unhides it for menus/selectors, then hides
   it again;
2. a **conversation view** rendered from `GET /api/conversation?id=<sid>`,
   polled every ~1 s (reusing the status poller's cadence and its
   mtime/size cache — a turn list is re-parsed only when the file grows).

Default: conversation visible, terminal hidden. No token-by-token stream
(polled), which is the calm behaviour Fabio wants.

### Backend

- `claudiu/conversation.py` — `parse_conversation(path) -> {meta, turns}`.
  Turn `kind` ∈ `human | assistant | thinking | tool | event | compact |
  subagent`. Each turn carries `seq`, `ts`, and kind-specific fields
  (assistant: `text`, `model`; thinking: `text`; tool: `name`,
  `input_summary`, `result`, `is_error`, `resolved`; event: `badge`,
  `text`). `meta` = `cwd`, `gitBranch`, `model`, `context_tokens/pct`,
  per-lane counts. Same robustness rule as `resume.py`/`status.py`
  (never raises; bad lines counted, skipped).
- `claudiu/status.py` — add `window_title(pty_tail)` (last OSC `0;`/`2;`
  title) and `parse_permission(pty_tail, patterns)` →
  `{prompt, options:[{key,label}]}` for the Yes/No buttons.
- Routes: `GET /api/conversation` (turns + meta + title + permission),
  cached by (mtime,size). Input keeps flowing over the existing
  `WS /ws/<id>` — no new input route.

### Frontend (per pane, all controlled)

Stacked frames, each stable in size (resize of the browser never reflows
the conversation text; only the frame boxes flex):

- **Header row** — working-directory frame, window-title box (from OSC),
  model + context/tokens, session state (working / waiting / ready).
- **Conversation frame** — scrollable, native scrollbar reflecting
  size/position, PageUp/PageDown, collapsible tool output, lane
  checkboxes (**thinking · tools · events · subagents**, matching
  SESSIONPUBLISHER) + a search box. A **jump-to-latest** button that is
  only ever a button (never auto-shown mid-scroll ambiguity: shown iff not
  at bottom).
- **Thinking/status strip** — the current live state as a controlled line
  (working…, waiting for you, ready), plus the latest thinking preview.
- **Command panel (bottom)** — a composer textarea → stdin; when a
  permission prompt is detected, its options render as buttons; a
  **Show terminal** toggle (escape hatch) and quick actions (Esc/interrupt,
  clear).

### V1 scope (Fabio, 2026-08-31)

In: conversation frame + lane checkboxes + search, working-dir frame,
window-title box, model + tokens/cost per turn, state/thinking strip,
composer, **permission Yes/No buttons**, jump-to-latest button, hidden
terminal + escape hatch, polled ~1 s.

Deferred: todos panel, files-changed affordance, subagent deep view,
token-streaming, and full menu reimplementation (Option 3 — revisit after
watching real surface-change frequency).

## Testing

Backend `parse_conversation`, `window_title`, `parse_permission` unit-
tested against synthetic transcripts and pty tails (kinds, ordering,
tool result pairing, bad lines, OSC forms, numbered options). Endpoint
shape test. Frontend verified live in Chrome. Docs guards updated for the
new config keys and route.

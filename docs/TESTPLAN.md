# ClaudIU — manual & fidelity test plan

The conversation view **displays** a session and, unlike a passive
transcript viewer, **sends input** to a live agent. A dropped or
mis-rendered turn misleads a decision; a wrongly-issued keystroke can
**approve a destructive action**. So accuracy here matters more than in a
read-only tool. This plan pairs automated coverage with hands-on cases —
some need a human (interactive prompts, menus). Record pass/fail and the
date/version next to each.

## Ground truth & how to check

Three sources, checked against each other:

1. **The transcript** — `~/.claude/projects/<slug>/<session-id>.jsonl`
   (the session id is in the tab's `/api/conversation` payload). This is
   the authority for the conversation.
2. **The raw terminal** — the **▤ Terminal** toggle shows exactly what
   Claude Code drew. Use it to confirm a permission prompt's real options.
3. **The audit log** — `~/.claudiu/logs/claudiu-*.log`, logger
   `claudiu.audit`: one `stdin session=… len=… ctrl=… data=…` line per
   keystroke/text ever sent. This is the record of **what was issued**.

Automated backing (run `python -m pytest -q`): `test_conversation.py`
(parsing, tool pairing, ordering, no-empty-turns, **fidelity accounting**),
`test_audit.py` (every stdin logged), `test_status.py` (state, title,
permission-text detection), `test_app.py` (endpoints).

## A. Conversation accuracy (nothing dropped, nothing invented)

Run a normal session for a few turns, then verify:

- [ ] Every prompt **you** typed appears once as a `you` turn, verbatim.
- [ ] Every assistant reply matches the transcript's `text` blocks.
- [ ] Every tool call shows with its target, and its result is paired
      under it (expand it) — count tool calls in the view vs `tool_use`
      records in the transcript; they must match.
- [ ] Thinking blocks present (collapsed) when the transcript has them.
- [ ] **Fidelity chip**: the header shows **no** "⚠ N unrecognized
      record(s)". If it does, a Claude Code version introduced a record
      type the parser doesn't know — note the types (hover the chip) and
      report; the view may be incomplete until `_KNOWN_IGNORED` /
      rendering is updated.
- [ ] Nothing from the raw terminal (▤ Terminal) is **missing** from the
      conversation view except the live input line, menus, and spinners
      (those are intentionally terminal-only).

## B. Permission prompts — the safety-critical path

Trigger each and, **before clicking**, compare the buttons to the real
prompt in ▤ Terminal. The button labels and numbers must match exactly.

- [ ] **Write** a file (default/manual mode → "Do you want to create …?"):
      3 options. Buttons match. Click **No** → not created. Repeat, click
      **Yes** → created. Confirm the audit log shows the digit you clicked.
- [ ] **Edit** an existing file ("Do you want to make this edit?").
- [ ] **Bash** command prompt ("Do you want to proceed?").
- [ ] A prompt with a **very long** option (the "…accept edits… for this
      session (shift+tab)" one): the long option still renders and maps to
      the right key.
- [ ] **Mid-prompt redraw**: while the prompt is up, resize the window or
      let a spinner tick. The buttons must **not** change key→label
      mapping. (Stability: buttons only appear once the parse repeats.)
- [ ] **Fail-safe**: if the buttons ever don't appear while the tab light
      is on "waiting" (accent pulse), the view must show **"⚠ Claude is
      asking for confirmation. Open the terminal to answer"** with an
      Open-terminal button — never a guessed option.
- [ ] **Re-verify on click**: (hard to force) clicking an option must send
      that option's number only when it still maps to the same label.
- [ ] After answering via a button, the session proceeds exactly as if you
      had pressed the number in the terminal.

> Report any case where a button's label/number disagrees with the
> terminal, or where a click sent the wrong answer. That is a stop-ship bug.

## C. Input integrity

- [ ] Composer: type a multi-line message (Shift+Enter for newlines),
      send. It arrives verbatim (check the transcript / terminal). No
      dropped or doubled characters.
- [ ] Composer **Enter** sends; **Shift+Enter** inserts a newline.
- [ ] **Esc** button interrupts a running turn (audit log shows `\e`).
- [ ] Snippets bar still sends its text.
- [ ] Every send appears in the audit log with the right length.

## D. Escape hatch & menus (terminal-only surfaces)

- [ ] `/` then a command name → autocomplete menu shows in ▤ Terminal.
- [ ] `/model` selector works in the terminal; toggle back to conversation.
- [ ] Plan mode (shift+tab cycle) and `@`-file picker work in the terminal.
- [ ] The **▤ Terminal / ▤ Conversation** toggle works from **both**
      views (regression: it used to vanish in terminal mode).

## E. Stability, view controls, resilience

- [ ] Resize the browser: the conversation does **not** reflow or jump;
      only the frames flex.
- [ ] Lane checkboxes hide/show thinking / tools / events / subagents.
- [ ] Search filters turns; PageUp/PageDown scroll; **↓ latest** appears
      only when scrolled up and returns to the bottom.
- [ ] Theme button cycles system / light / dark; remembered on reload.
- [ ] Reload the page mid-session: the conversation re-renders complete and
      the session keeps running.

## F. Concurrency / multiple tabs

- [ ] Two sessions: switching tabs shows each one's own conversation; a
      background tab's light/gauge still update; only the visible tab's
      conversation is polled.

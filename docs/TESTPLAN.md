# acp-cockpit — manual test plan

The automated suite (`python -m pytest tests/ -q`, plus the opt-in contract
tier against the real adapter) proves the engine, the server and the web
View against a scripted agent. What it cannot prove is the product against
a **real agent on a real account**: whether the adapter installed today
still says what the fixtures say, whether the account panel reads what this
account's rate limits look like, whether a long session still feels right.
This plan is the human half. Run it before a release and after any adapter
upgrade; record the date, the adapter version (`npm ls -g
@agentclientprotocol/claude-agent-acp`) and pass/fail next to each item.

A permission dialog here grants a real agent the right to change real
files. Every "nothing dropped" claim below is checked against the session
record, which is the ground truth.

## Ground truth and how to read it

Three sources, checked against each other:

1. **The session record** — `~/.acp-cockpit/records/<session>.jsonl`. Every
   protocol frame verbatim (`dir: in|out`), the adapter's stderr (`dir:
   err`) and every client action (`dir: client`: `spawn`, `prompt`,
   `permission`, `elicitation`, `fs_decision`, `set_mode`,
   `set_config_option`, `cancel`). The `{}` button on a special row shows
   the frame number (`raw_ref`) that indexes into it.
2. **The page** — what the View rendered. The five lane switches decide what
   is on it; the record decides what is true.
3. **The agent's own transcript** — for Claude Code,
   `~/.claude/projects/<slug>/<agent session id>.jsonl`. The agent session id
   is in the tab tooltip and in `GET /api/sessions`.

## A. Nothing lost (the core guarantee)

Run a session of several turns with at least one tool call, one edit, one
approval and one `/context`. Then:

- [ ] Every `session/update` frame in the record with a `sessionUpdate` kind
      the client knows (`agent_message_chunk`, `agent_thought_chunk`,
      `tool_call`, `tool_call_update`, `plan`, `available_commands_update`,
      `current_mode_update`, `config_option_update`, `session_info_update`,
      `usage_update`, `user_message_chunk`) has a visible counterpart: a row,
      a tool row update, the plan panel, the palette, the strip.
- [ ] Every frame with a kind the client does NOT know is on the page as an
      `unrecognized` row (harness lane) **and** the drift chip counts it.
      Adapter kinds outside the schema that the registry names
      (`subagent_spawned`, `subagent_state_update`, `async_task_*`) are
      `vendor_update` rows in their lane, not drift.
- [ ] The **drift** chip is empty for a whole session against the pinned
      adapter version. If it is not, the registry is behind: that is the
      sentinel working, and a release task.
- [ ] Adapter stderr lines in the record (`dir: err`) equal the count in
      the **log** chip.
- [ ] No frame arrives after the tab is closed without landing in the record
      (`session/update` after `closed` is still written; the record closes
      when the adapter process has exited).

## B. Approvals and questions (the safety surface)

- [ ] A tool that needs permission opens the dialog with the agent's **own**
      options, one-shot first, standing grants last and dashed; the digits
      1–9 answer; `Esc` does nothing; clicking outside does nothing.
- [ ] Answer **Allow once**: the record has `action: permission, source:
      user, option: <id>`; the tool runs; the file changes.
- [ ] Answer **Reject**: the agent reports the refusal; nothing changed.
- [ ] A tool call naming a path **outside** the project directory shows the
      red boundary warning with that path; a tool call naming only a URL
      (WebFetch, curl) shows **no** warning.
- [ ] Let a permission sit unanswered past the timeout (start the server with
      a short one for this: `make_app(permission_timeout=...)` in a scratch
      script, or wait the hour): the dialog closes by itself, the record says
      `source: failsafe`, the events lane says *auto-rejected*.
- [ ] Cancel a turn (`Esc` or Stop) while the agent has asked a question:
      whatever the agent does, the dialog is either answered or withdrawn —
      never left open with the turn ended.
- [ ] AskUserQuestion: a form with radios / checkboxes / an **Other** box per
      question; **Answer** writes *you answered: …* into the events lane and
      the agent continues with that answer; **Skip** writes *question
      skipped* and the agent continues without one.
- [ ] Plan mode: `ExitPlanMode` arrives as an approval with the agent's
      options; after *manually approve edits* the strip says the new mode
      (the profile re-asserts it — `permission_mode_followups`).

## C. File access through the client

- [ ] The agent reads a file inside the project: an `fs_request … ✓` row;
      the content the agent quotes matches the file.
- [ ] The agent reads a **range** (a large file with an offset): the record's
      `fs/read_text_file` has `line`/`limit` and the reply holds only that
      slice.
- [ ] The agent asks for a file **outside** the project: `✗ blocked` row, the
      agent reports the refusal, nothing read.
- [ ] The agent asks to read a binary file: the reply is a JSON-RPC error,
      the agent reports it, the turn ends (nothing hangs).

## D. Sessions, tabs, reconnect

- [ ] Reload the page mid-turn: the tab comes back, the conversation is
      replayed once (no duplicate rows), the turn finishes.
- [ ] Put the laptop to sleep for a few minutes, wake it: the strip says
      *reconnecting*, then the state it was in; nothing duplicated.
- [ ] Stop the server while a tab is open: the tab says the server refused
      or the session is gone, and asks for a reload; no retry storm.
- [ ] Two tabs: each keeps its own scroll position and follow state when you
      switch; approvals from the inactive tab pop up labelled with that tab.
- [ ] **Find resumable sessions** lists what the agent knows for that
      directory, newest first and dated; **Resume** replays the history and
      lands on *ready*; resuming a session already open in another tab is
      refused with a message naming the tab.
- [ ] Close a tab: the adapter process **and its CLI child** are gone
      (`tasklist`/`ps` shows neither); nothing from this session is left
      when the server exits (Ctrl+C) or is killed (`Stop-Process` — the
      Windows job object reaps the tree).

## E. Status, account, versions

- [ ] The context gauge moves during a turn; the cost appears when the agent
      reports one; the strip shows the API's canonical model id once the
      first usage update carries it.
- [ ] Rate-limit chips appear top right as the account approaches a window,
      one per window the agent reported, percentages as fractions × 100;
      hovering shows the reset time and the raw payload. No chip is invented.
- [ ] **Help → Versions** names the pinned schema, the installed adapter
      version and the latest published one; with the server started
      `--no-drift-online` it says the online check is off. When the adapter
      is behind, the **update** chip is present at the top right and opens
      Help.
- [ ] The tab tooltip names the agent and version the adapter reported at
      initialize.

## F. Archiving

- [ ] With `--archiver` (claude-session-publisher): the panel offers html,
      markdown, text, latex, pdf; the chosen formats are written to the
      chosen directory; the paths are listed in the panel and once in the
      harness lane.
- [ ] Without it: the panel says so and offers markdown only; the written
      transcript's header says it is the built-in fallback; prompts,
      answers, thinking and tool-call titles are in it.

## G. Long-session behaviour (the reasons this exists)

- [ ] A long streamed answer stays in view as it arrives; scrolled up, the
      view stays put and **↓ jump to latest** appears; selecting text inside
      a streaming answer survives the next chunk.
- [ ] Switching lanes off removes those rows entirely; switching back
      restores them; the choice survives a reload.
- [ ] After an hour of use the page has not grown sluggish (open the
      browser's task manager: memory stable between turns) and the server
      process has not grown beyond the records it holds.

## H. Before a release, in addition

- [ ] `ACP_COCKPIT_CONTRACT=1 python -m pytest tests/contract/ -q` against the
      installed adapter: PASS, zero drift.
- [ ] `python -m pip wheel . --no-deps -w /tmp/w` and start
      `python -m acp_cockpit` from a **fresh venv with only that wheel**
      installed, in a directory that is not the checkout: the page loads,
      the profiles are listed, a session starts.
- [ ] `docs/watch/` has today's report and the scheduled task's last result
      is 0 (`Get-ScheduledTaskInfo`).

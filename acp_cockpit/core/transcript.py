# SPDX-License-Identifier: Apache-2.0
"""A plain-Markdown transcript, rendered from the flight recorder.

The fallback for when claude-session-publisher is not installed: the record
already holds every frame verbatim, so a readable conversation can always be
written from it. This is deliberately simple — prompts, answers, thinking,
tool-call titles — and its own header says so. The publisher is the tool
that proves nothing was dropped; this one only promises to be honest about
being a summary.
"""
from __future__ import annotations

import json
from pathlib import Path

_HEADING = {"user": "You", "agent": "Agent", "thought": "Thinking"}


def _text_of(update: dict) -> str:
    return (update.get("content") or {}).get("text") or ""


def render_markdown(entries, title: str | None = None) -> str:
    """`entries` is what `Recorder.replay()` yields: (lineno, entry) pairs."""
    body: list[str] = []
    prompts = tools = 0
    role: str | None = None
    buffer: list[str] = []

    def flush():
        nonlocal role
        if role and "".join(buffer).strip():
            body.extend([f"### {_HEADING.get(role, role)}", "",
                         "".join(buffer).strip(), ""])
        role = None
        buffer.clear()

    def say(this_role, text):
        nonlocal role
        if this_role != role:
            flush()
            role = this_role
        buffer.append(text)

    for _, entry in entries:
        if entry.get("action") == "prompt":
            flush()
            prompts += 1
            body.extend(["### You", "",
                         str(entry.get("text", "")).strip(), ""])
            continue
        frame = entry.get("frame")
        if not isinstance(frame, dict) or \
                frame.get("method") != "session/update":
            continue
        update = (frame.get("params") or {}).get("update") or {}
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            say("agent", _text_of(update))
        elif kind == "agent_thought_chunk":
            say("thought", _text_of(update))
        elif kind == "user_message_chunk":
            say("user", _text_of(update))
        elif kind == "tool_call":
            flush()
            tools += 1
            body.extend([
                f"- **tool call** — "
                f"{update.get('title') or update.get('kind') or 'tool'}", ""])
        elif kind == "session_info_update" and not title:
            title = update.get("title") or None
    flush()

    head = [
        "# " + (title or "Session transcript"), "",
        f"*{prompts} prompt(s), {tools} tool call(s). Written by acp-cockpit's "
        "built-in fallback: prompts, answers, thinking and tool-call titles. "
        "Tool arguments and results, diffs, permissions and the raw protocol "
        "frames stay in the session's JSONL record — install "
        "claude-session-publisher for the full, fidelity-checked document.*",
        "",
    ]
    return "\n".join(head + body).rstrip() + "\n"


def safe_stem(session_id: str) -> str:
    """A filename component that cannot leave the directory it is joined to.

    `session_id` is whatever string the AGENT returned in `session/new`, or a
    `resume` id taken raw from the request body — never pattern-checked, unlike
    the `[0-9a-f]+` route regexes. Interpolated straight into the filename it
    wrote the transcript outside the directory the user picked (review
    2026-09-06). Keep it recognisable, confine it to one component.
    """
    text = str(session_id or "")
    # both separators, on every platform: the id crosses machines
    tail = text.replace("\\", "/").rsplit("/", 1)[-1]
    keep = [c for c in tail if c.isalnum() or c in "-_.@+"]
    stem = "".join(keep).strip(".").strip()
    # "..", ".", "" and an all-punctuation id all collapse to nothing
    return (stem or "session")[:96]


def write_markdown(record_path, dest_dir, session_id: str,
                   title: str | None = None, *, files) -> str:
    """Render `record_path` into `dest_dir`; returns the path written.

    `files` is a `core.ports.FileAccess`. Core does its own I/O nowhere but
    `record.py`: this function used to open both files itself, which is
    precisely the session-path I/O the layer rule is about (review
    2026-09-06). Reading through the port also keeps the promise that no
    handle is left on the live record — a Recorder opens it for APPEND and
    the first version of this never closed it.
    """
    dest = Path(dest_dir)
    files.make_dir(str(dest))
    text = files.read_text(str(record_path))
    entries = [(i, json.loads(line))
               for i, line in enumerate(text.splitlines(), 1) if line.strip()]
    target = dest / f"acp-cockpit-{safe_stem(session_id)}.md"
    files.write_text(str(target), render_markdown(entries, title))
    return str(target)

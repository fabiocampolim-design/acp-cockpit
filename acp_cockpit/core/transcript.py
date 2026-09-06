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


def write_markdown(record_path, dest_dir, session_id: str,
                   title: str | None = None) -> str:
    """Render `record_path` into `dest_dir`; returns the path written."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    # Read, never a Recorder: a Recorder opens the file for APPEND and this
    # one was never closed — a leaked handle on the live record per archive
    # (review 2026-09-06).
    with open(record_path, encoding="utf-8") as f:
        entries = [(i, json.loads(line)) for i, line in enumerate(f, 1)
                   if line.strip()]
    target = dest / f"acp-cockpit-{session_id}.md"
    target.write_text(render_markdown(entries, title), encoding="utf-8")
    return str(target)

# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""Parse a Claude Code transcript into a controlled conversation model.

The transcript (``~/.claude/projects/<slug>/<id>.jsonl``) is append-only
history with a stable schema. This turns it into a list of typed *turns*
the browser renders itself, so CLAUDIU never has to display Claude Code's
raw terminal output. See ``docs/superpowers/specs/2026-08-31-conversation-view-design.md``.

Turn ``kind`` is one of: ``human``, ``assistant``, ``thinking``, ``tool``,
``event``, ``compact``. Tool turns are paired with their result by
``tool_use_id``. Subagent (sidechain) turns are flagged, not dropped.

Robustness rule (as in ``resume.py``/``status.py``): nothing unexpected
raises; bad lines are counted and skipped.
"""
from __future__ import annotations

import json
from pathlib import Path

RESULT_MAX = 4000
INPUT_MAX = 160
TEXT_MAX = 20000  # a single assistant/thinking block; guards a runaway file
INTERRUPTED = "[Request interrupted by user"

# Tool name -> the input field worth showing as a one-line summary.
_TOOL_FIELD = {
    "Bash": "command", "Read": "file_path", "Write": "file_path",
    "Edit": "file_path", "NotebookEdit": "notebook_path", "Glob": "pattern",
    "Grep": "pattern", "Skill": "skill", "Task": "description",
    "WebFetch": "url", "WebSearch": "query", "TodoWrite": None,
}


def _clip(text, limit):
    text = "" if text is None else str(text)
    return text if len(text) <= limit else text[:limit] + "…"


def _input_summary(name: str, tool_input) -> str:
    if not isinstance(tool_input, dict):
        return ""
    field = _TOOL_FIELD.get(name, "unset")
    if field and field in tool_input:
        return _clip(str(tool_input[field]).replace("\n", " "), INPUT_MAX)
    # generic: first short string value, else the key names
    for value in tool_input.values():
        if isinstance(value, str) and value:
            return _clip(value.replace("\n", " "), INPUT_MAX)
    return _clip(", ".join(tool_input.keys()), INPUT_MAX)


def _result_text(part: dict) -> str:
    content = part.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                out.append(str(c.get("text", "")))
            elif isinstance(c, dict) and c.get("type") == "image":
                out.append("[image]")
        return "\n".join(out)
    return ""


def _is_injected(rec: dict) -> bool:
    return bool(rec.get("isMeta")) or rec.get("promptSource") == "system"


def _human_or_event(rec: dict):
    """A user record's plain-string content is either a typed human prompt
    or injected text (system-reminder, task-notification). Returns
    ('human'|'event', badge)."""
    origin = rec.get("origin")
    if isinstance(origin, dict) and origin.get("kind"):
        if origin["kind"] == "human":
            return "human", ""
        return "event", origin["kind"].replace("-", " ")
    if _is_injected(rec):
        return "event", "injected"
    return "human", ""


_EVENT_BADGE = {
    "informational": "notice", "local_command": "command",
    "away_summary": "away", "model_refusal_fallback": "refusal",
    "turn_duration": None, "scheduled_task_fire": "scheduled",
    "bridge_status": "remote", "compact_boundary": None,
}

# Top-level record types that legitimately produce no conversation turn.
# A record whose type is neither rendered (user/assistant/system) nor listed
# here is counted in meta["unaccounted"] so a future Claude Code schema
# change surfaces as a visible warning instead of a silent drop -- the whole
# point being that the view must never quietly omit part of the conversation.
_KNOWN_IGNORED = {
    "last-prompt", "mode", "permission-mode", "attachment", "ai-title",
    "file-history-snapshot", "file-history-delta", "queue-operation",
    "atis-latch", "bridge-session", "cost-state", "frame-link", "agent-name",
    "artifact-comment-monitor", "artifact-autoreact-ledger", "relocated",
    "worktree-state", "summary",
}


def parse_conversation(path, context_window: int = 0) -> dict:
    path = Path(path)
    meta = {"cwd": None, "gitBranch": None, "model": None,
            "context_tokens": None, "context_pct": None,
            "counts": {}, "bad_lines": 0, "unaccounted": {}}
    turns: list = []
    by_tool_id: dict = {}
    seq = 0
    try:
        fh = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return {"meta": meta, "turns": turns, "exists": False}
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                meta["bad_lines"] += 1
                continue
            if not isinstance(rec, dict):
                meta["bad_lines"] += 1
                continue
            if isinstance(rec.get("cwd"), str):
                meta["cwd"] = rec["cwd"]
            if isinstance(rec.get("gitBranch"), str):
                meta["gitBranch"] = rec["gitBranch"]
            ts = rec.get("timestamp")
            side = bool(rec.get("isSidechain"))
            rtype = rec.get("type")

            # fidelity accounting: flag any record type we do not handle
            if rtype not in ("assistant", "user", "system") \
                    and rtype not in _KNOWN_IGNORED:
                key = str(rtype)
                meta["unaccounted"][key] = meta["unaccounted"].get(key, 0) + 1
            elif rtype == "system":
                sub = rec.get("subtype")
                if sub not in _EVENT_BADGE:
                    key = "system:" + str(sub)
                    meta["unaccounted"][key] = meta["unaccounted"].get(key, 0) + 1

            if rtype == "assistant":
                msg = rec.get("message")
                if not isinstance(msg, dict):
                    continue
                model = msg.get("model")
                if model:
                    meta["model"] = model
                usage = msg.get("usage")
                if isinstance(usage, dict):
                    tot = sum(int(usage.get(k, 0) or 0) for k in (
                        "input_tokens", "cache_creation_input_tokens",
                        "cache_read_input_tokens"))
                    if tot:
                        meta["context_tokens"] = tot
                for part in msg.get("content", []):
                    if not isinstance(part, dict):
                        continue
                    ptype = part.get("type")
                    if ptype == "text" and part.get("text", "").strip():
                        seq += 1
                        turns.append({"seq": seq, "kind": "assistant",
                                      "ts": ts, "sub": side, "model": model,
                                      "text": _clip(part["text"], TEXT_MAX)})
                    elif ptype == "thinking" and part.get("thinking", "").strip():
                        seq += 1
                        turns.append({"seq": seq, "kind": "thinking", "ts": ts,
                                      "sub": side,
                                      "text": _clip(part["thinking"], TEXT_MAX)})
                    elif ptype == "tool_use":
                        seq += 1
                        turn = {"seq": seq, "kind": "tool", "ts": ts,
                                "sub": side, "name": part.get("name", "tool"),
                                "input_summary": _input_summary(
                                    part.get("name", ""), part.get("input")),
                                "result": None, "is_error": False,
                                "resolved": False, "result_truncated": False}
                        turns.append(turn)
                        if part.get("id"):
                            by_tool_id[part["id"]] = turn

            elif rtype == "user":
                msg = rec.get("message")
                content = msg.get("content") if isinstance(msg, dict) else None
                if isinstance(content, str):
                    if content.strip():
                        kind, badge = _human_or_event(rec)
                        interrupted = content.startswith(INTERRUPTED)
                        seq += 1
                        turns.append({"seq": seq, "kind": kind, "ts": ts,
                                      "sub": side, "badge": badge,
                                      "interrupted": interrupted,
                                      "text": _clip(content, TEXT_MAX)})
                elif isinstance(content, list):
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        if part.get("type") == "tool_result":
                            turn = by_tool_id.get(part.get("tool_use_id"))
                            if turn is not None:
                                text = _result_text(part)
                                turn["result"] = _clip(text, RESULT_MAX)
                                turn["result_truncated"] = len(text) > RESULT_MAX
                                turn["is_error"] = bool(part.get("is_error"))
                                turn["resolved"] = True
                        elif part.get("type") == "text" and \
                                part.get("text", "").strip() and \
                                not _is_injected(rec):
                            seq += 1
                            turns.append({"seq": seq, "kind": "human", "ts": ts,
                                          "sub": side, "badge": "",
                                          "interrupted": False,
                                          "text": _clip(part["text"], TEXT_MAX)})

            elif rtype == "system":
                sub = rec.get("subtype")
                if sub == "compact_boundary":
                    seq += 1
                    turns.append({"seq": seq, "kind": "compact", "ts": ts,
                                  "text": rec.get("content") or "Conversation compacted"})
                elif sub in _EVENT_BADGE and _EVENT_BADGE[sub] is not None:
                    seq += 1
                    turns.append({"seq": seq, "kind": "event", "ts": ts,
                                  "sub": side, "badge": _EVENT_BADGE[sub],
                                  "text": _clip(rec.get("content") or "", TEXT_MAX)})

    if meta["context_tokens"] and context_window > 0:
        meta["context_pct"] = round(100.0 * meta["context_tokens"]
                                    / context_window, 1)
    counts: dict = {}
    for t in turns:
        counts[t["kind"]] = counts.get(t["kind"], 0) + 1
    meta["counts"] = counts
    return {"meta": meta, "turns": turns, "exists": True}

# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""Per-session status read from the tail of Claude Code's own transcript.

Claude Code appends one JSON record per line to
``~/.claude/projects/<slug>/<session-id>.jsonl`` while a session runs.
Reading its tail gives, without parsing a single terminal byte:

* the user's last typed prompt (a ``last-prompt`` record, or the last
  ``user`` record whose content is a plain string and not injected),
* whether Claude is working or waiting for the user (the last
  ``assistant`` record's ``stop_reason``: ``end_turn`` means ready; a
  ``tool_use`` -- or a ``user`` record with no answer yet -- means busy),
* the current context size (the last assistant ``usage``: input +
  cache-creation + cache-read tokens).

Only the last ``tail_bytes`` are read, so a call costs one small read no
matter how long the session is. Same robustness rule as ``resume.py``:
nothing unexpected raises; it degrades to ``unknown``.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

PROMPT_MAX = 2000
READY_STOPS = ("end_turn", "stop_sequence", "max_tokens")
INTERRUPTED = "[Request interrupted by user"


def project_slug(cwd) -> str:
    """Claude Code's per-project directory name: every non-alphanumeric
    character of the absolute path becomes ``-``."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def transcript_path(cwd, session_id: str, claude_dir=None) -> Path:
    base = Path(claude_dir) if claude_dir is not None else Path.home() / ".claude"
    return base / "projects" / project_slug(cwd) / f"{session_id}.jsonl"


def unknown_status() -> dict:
    return {"exists": False, "state": "unknown", "last_prompt": None,
            "context_tokens": None, "context_pct": None, "mtime": None}


def _tail_lines(path: Path, tail_bytes: int) -> list:
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > tail_bytes:
            fh.seek(size - tail_bytes)
            fh.readline()  # drop the partial first line
        data = fh.read()
    return data.decode("utf-8", errors="replace").splitlines()


def _typed_prompt(rec: dict):
    """The text of a prompt the user typed, or None for anything injected."""
    if rec.get("isMeta") or rec.get("promptSource") == "system":
        return None
    msg = rec.get("message")
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return None


def _clip(text: str) -> str:
    return text if len(text) <= PROMPT_MAX else text[:PROMPT_MAX] + "…"


def read_status(path, context_window: int, tail_bytes: int = 256 * 1024) -> dict:
    path = Path(path)
    try:
        st = path.stat()
        lines = _tail_lines(path, tail_bytes)
    except OSError:
        return unknown_status()
    out = unknown_status()
    out["exists"] = True
    out["mtime"] = st.st_mtime
    state = "unknown"
    prompt = None
    fallback_prompt = None
    tokens = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        rtype = rec.get("type")
        if rtype == "last-prompt":
            if isinstance(rec.get("lastPrompt"), str) and rec["lastPrompt"].strip():
                prompt = rec["lastPrompt"].strip()
        elif rtype == "user":
            typed = _typed_prompt(rec)
            if typed is not None:
                fallback_prompt = typed
            state = "ready" if (typed or "").startswith(INTERRUPTED) else "busy"
        elif rtype == "assistant":
            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            state = "ready" if msg.get("stop_reason") in READY_STOPS else "busy"
            usage = msg.get("usage")
            if isinstance(usage, dict):
                total = 0
                for key in ("input_tokens", "cache_creation_input_tokens",
                            "cache_read_input_tokens"):
                    val = usage.get(key)
                    if isinstance(val, (int, float)):
                        total += int(val)
                tokens = total
    out["state"] = state
    text = prompt or fallback_prompt
    out["last_prompt"] = _clip(text) if text else None
    if tokens is not None:
        out["context_tokens"] = tokens
        if context_window > 0:
            out["context_pct"] = round(100.0 * tokens / context_window, 1)
    return out


def find_transcript(cwd, session_id: str, claude_dir=None):
    """The transcript for a session: the slug path, or -- should Claude Code
    ever slug a path differently -- the first ``<id>.jsonl`` under any project
    directory. None when nothing exists yet."""
    p = transcript_path(cwd, session_id, claude_dir)
    if p.is_file():
        return p
    base = p.parent.parent
    try:
        for name in os.listdir(base):
            cand = base / name / f"{session_id}.jsonl"
            if cand.is_file():
                return cand
    except OSError:
        pass
    return None

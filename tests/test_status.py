# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""Transcript-tail status: last prompt, busy/ready, context usage."""
import json
from pathlib import Path

from claudiu.status import (apply_permission, awaiting_permission,
                            find_transcript, project_slug, read_status,
                            strip_ansi, transcript_path, unknown_status)

PATTERNS = ["Do you want to proceed", "Would you like to proceed"]


def _write(path: Path, records) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in records),
                    encoding="utf-8")
    return path


def _user(text, **extra):
    rec = {"type": "user", "message": {"role": "user", "content": text}}
    rec.update(extra)
    return rec


def _tool_result():
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}


def _assistant(stop, usage=None, parts=("text",)):
    return {"type": "assistant", "message": {
        "role": "assistant", "stop_reason": stop,
        "content": [{"type": p} for p in parts],
        "usage": usage or {"input_tokens": 10, "cache_creation_input_tokens": 20,
                           "cache_read_input_tokens": 70, "output_tokens": 5}}}


def test_slug_matches_claude_code_layout():
    assert (project_slug(r"D:\work\a-project")
            == "D--work-a-project")
    assert project_slug("/srv/x/.local/proj") == "-srv-x--local-proj"


def test_transcript_path_under_claude_dir(tmp_path):
    p = transcript_path(r"C:\proj\a", "abc-123", claude_dir=tmp_path)
    assert p == tmp_path / "projects" / "C--proj-a" / "abc-123.jsonl"


def test_find_transcript_falls_back_to_any_project_dir(tmp_path):
    assert find_transcript(r"C:\proj\a", "id1", claude_dir=tmp_path) is None
    other = tmp_path / "projects" / "elsewhere"
    other.mkdir(parents=True)
    f = _write(other / "id1.jsonl", [_user("x")])
    assert find_transcript(r"C:\proj\a", "id1", claude_dir=tmp_path) == f


def test_missing_file_is_unknown(tmp_path):
    st = read_status(tmp_path / "nope.jsonl", context_window=1000)
    assert st == unknown_status()
    assert st["state"] == "unknown" and st["exists"] is False


def test_ready_after_end_turn_with_context(tmp_path):
    f = _write(tmp_path / "s.jsonl", [
        _user("hello there"),
        _assistant("tool_use", parts=("tool_use",)),
        _tool_result(),
        _assistant("end_turn", usage={"input_tokens": 100,
                                      "cache_creation_input_tokens": 400,
                                      "cache_read_input_tokens": 1500}),
        {"type": "attachment"},
        {"type": "last-prompt", "lastPrompt": "hello there"},
    ])
    st = read_status(f, context_window=4000)
    assert st["exists"] is True
    assert st["state"] == "ready"
    assert st["last_prompt"] == "hello there"
    assert st["context_tokens"] == 2000
    assert st["context_pct"] == 50.0


def test_busy_after_prompt_and_after_tool_use(tmp_path):
    f = _write(tmp_path / "a.jsonl", [_assistant("end_turn"), _user("go")])
    assert read_status(f, context_window=1000)["state"] == "busy"
    f = _write(tmp_path / "b.jsonl", [_user("go"), _assistant("tool_use")])
    assert read_status(f, context_window=1000)["state"] == "busy"
    f = _write(tmp_path / "c.jsonl", [_assistant("tool_use"), _tool_result()])
    assert read_status(f, context_window=1000)["state"] == "busy"


def test_interrupted_turn_is_ready(tmp_path):
    f = _write(tmp_path / "s.jsonl", [
        _user("do it"), _assistant("tool_use"),
        _user("[Request interrupted by user for tool use]")])
    assert read_status(f, context_window=1000)["state"] == "ready"


def test_last_prompt_falls_back_to_typed_user_text(tmp_path):
    f = _write(tmp_path / "s.jsonl", [
        _user("first question"),
        _user("<system-reminder>injected</system-reminder>", isMeta=True),
        _user("<task-notification>x</task-notification>", promptSource="system"),
        _tool_result(),
        _assistant("end_turn"),
    ])
    assert read_status(f, context_window=1000)["last_prompt"] == "first question"


def test_long_prompt_is_truncated_but_marked(tmp_path):
    f = _write(tmp_path / "s.jsonl", [_user("x" * 5000), _assistant("end_turn")])
    st = read_status(f, context_window=1000)
    assert len(st["last_prompt"]) <= 2001 and st["last_prompt"].endswith("…")


def test_only_tail_is_read_and_partial_first_line_survives(tmp_path):
    recs = [_user("early prompt " + str(i)) for i in range(300)]
    recs += [_assistant("end_turn", usage={"input_tokens": 1,
                                           "cache_creation_input_tokens": 1,
                                           "cache_read_input_tokens": 1})]
    f = _write(tmp_path / "s.jsonl", recs)
    st = read_status(f, context_window=300, tail_bytes=2048)
    assert st["state"] == "ready" and st["context_tokens"] == 3
    assert st["context_pct"] == 1.0
    assert st["last_prompt"].startswith("early prompt")  # a complete line


def test_bad_lines_never_raise(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text('{"type": "user", "message": 5}\nnot json\n[1,2]\n'
                 + json.dumps(_assistant("end_turn")) + "\n", encoding="utf-8")
    st = read_status(f, context_window=1000)
    assert st["state"] == "ready" and st["last_prompt"] is None


def test_strip_ansi_removes_escape_codes():
    assert strip_ansi("\x1b[38;2;1;2;3mhi\x1b[0m \x1b[2Kthere") == "hi there"


def test_awaiting_permission_matches_stripped_and_caseless():
    tail = "\x1b[1mDo you want to PROCEED?\x1b[0m\n 1. Yes\n 2. No"
    assert awaiting_permission(tail, PATTERNS) is True
    assert awaiting_permission("just running tests...", PATTERNS) is False
    assert awaiting_permission("", PATTERNS) is False
    assert awaiting_permission("Do you want to proceed", []) is False


def test_apply_permission_only_upgrades_busy():
    busy = {"state": "busy", "last_prompt": "x"}
    up = apply_permission(busy, "Do you want to proceed?", PATTERNS)
    assert up["state"] == "waiting"
    assert busy["state"] == "busy"  # original untouched (may be a cache entry)
    ready = {"state": "ready"}
    assert apply_permission(ready, "Do you want to proceed?", PATTERNS) is ready
    assert apply_permission(dict(busy), "nothing here", PATTERNS)["state"] == "busy"

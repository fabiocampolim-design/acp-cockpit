# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""Parsing a transcript into the controlled conversation model."""
import json

from claudiu.conversation import parse_conversation
from claudiu.status import parse_permission, window_title


def _write(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records),
                    encoding="utf-8")
    return path


def _asst(*parts, model="claude-x", usage=None):
    return {"type": "assistant", "cwd": r"C:\proj", "gitBranch": "main",
            "message": {"model": model, "content": list(parts),
                        "usage": usage or {}}}


def test_missing_file_is_marked_absent(tmp_path):
    d = parse_conversation(tmp_path / "nope.jsonl", 1000)
    assert d["exists"] is False and d["turns"] == []


def test_human_assistant_thinking_and_tool_pairing(tmp_path):
    f = _write(tmp_path / "s.jsonl", [
        {"type": "user", "message": {"content": "do the thing"}},
        _asst({"type": "thinking", "thinking": "let me think"},
              {"type": "text", "text": "on it"},
              {"type": "tool_use", "id": "t1", "name": "Bash",
               "input": {"command": "ls -la"}},
              usage={"input_tokens": 100, "cache_read_input_tokens": 900}),
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "file1\nfile2", "is_error": False}]}},
    ])
    d = parse_conversation(f, 2000)
    kinds = [t["kind"] for t in d["turns"]]
    assert kinds == ["human", "thinking", "assistant", "tool"]
    tool = d["turns"][3]
    assert tool["name"] == "Bash" and tool["input_summary"] == "ls -la"
    assert tool["resolved"] is True and tool["result"] == "file1\nfile2"
    assert tool["is_error"] is False
    assert d["meta"]["model"] == "claude-x"
    assert d["meta"]["cwd"] == r"C:\proj" and d["meta"]["gitBranch"] == "main"
    assert d["meta"]["context_tokens"] == 1000
    assert d["meta"]["context_pct"] == 50.0
    assert d["meta"]["counts"]["tool"] == 1


def test_tool_error_and_unresolved(tmp_path):
    f = _write(tmp_path / "s.jsonl", [
        _asst({"type": "tool_use", "id": "t1", "name": "Read",
               "input": {"file_path": "/x"}}),
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "boom", "is_error": True}]}},
        _asst({"type": "tool_use", "id": "t2", "name": "Grep",
               "input": {"pattern": "foo"}}),  # never resolved
    ])
    d = parse_conversation(f, 0)
    tools = [t for t in d["turns"] if t["kind"] == "tool"]
    assert tools[0]["is_error"] is True and tools[0]["resolved"] is True
    assert tools[1]["resolved"] is False and tools[1]["result"] is None
    assert tools[1]["input_summary"] == "foo"
    assert d["meta"]["context_pct"] is None  # no window given


def test_injected_user_text_is_event_not_human(tmp_path):
    f = _write(tmp_path / "s.jsonl", [
        {"type": "user", "isMeta": True,
         "message": {"content": "<system-reminder>hi</system-reminder>"}},
        {"type": "user", "promptSource": "system",
         "message": {"content": "<task-notification>done</task-notification>"}},
        {"type": "user", "origin": {"kind": "human"},
         "message": {"content": "real prompt"}},
    ])
    d = parse_conversation(f, 0)
    kinds = [t["kind"] for t in d["turns"]]
    assert kinds == ["event", "event", "human"]
    assert d["turns"][2]["text"] == "real prompt"


def test_interrupt_and_compact_and_bad_lines(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text(
        json.dumps({"type": "user", "message": {
            "content": "[Request interrupted by user]"}}) + "\n"
        + "not json\n" + "[1,2,3]\n"
        + json.dumps({"type": "system", "subtype": "compact_boundary",
                      "content": "Conversation compacted"}) + "\n",
        encoding="utf-8")
    d = parse_conversation(f, 0)
    assert d["meta"]["bad_lines"] == 2
    assert d["turns"][0]["kind"] == "human" and d["turns"][0]["interrupted"]
    assert d["turns"][1]["kind"] == "compact"


def test_long_result_is_truncated_and_flagged(tmp_path):
    f = _write(tmp_path / "s.jsonl", [
        _asst({"type": "tool_use", "id": "t1", "name": "Bash",
               "input": {"command": "cat big"}}),
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "x" * 9000}]}},
    ])
    d = parse_conversation(f, 0)
    tool = d["turns"][0]
    assert tool["result_truncated"] is True
    assert tool["result"].endswith("…") and len(tool["result"]) <= 4001


def test_fidelity_accounts_for_every_record_type(tmp_path):
    # a spread of real record types: rendered, known-ignored, and two the
    # parser has never seen. Nothing rendered should be silently dropped;
    # only the genuinely-unknown types land in meta["unaccounted"].
    f = _write(tmp_path / "s.jsonl", [
        {"type": "user", "message": {"content": "hi"}},
        _asst({"type": "text", "text": "hello"}),
        {"type": "system", "subtype": "turn_duration", "durationMs": 5},
        {"type": "last-prompt", "lastPrompt": "hi"},
        {"type": "attachment"},
        {"type": "file-history-snapshot"},
        {"type": "ai-title", "aiTitle": "t"},
        {"type": "cost-state"},
        {"type": "brand-new-2027"},                       # unknown top-level
        {"type": "system", "subtype": "brand-new-sub"},   # unknown subtype
    ])
    d = parse_conversation(f, 0)
    assert d["meta"]["unaccounted"] == {"brand-new-2027": 1,
                                        "system:brand-new-sub": 1}
    # the known-ignored records did not become turns, and the real ones did
    assert [t["kind"] for t in d["turns"]] == ["human", "assistant"]


def test_no_turn_text_is_empty(tmp_path):
    # a defence against rendering blank turns from whitespace-only content
    f = _write(tmp_path / "s.jsonl", [
        {"type": "user", "message": {"content": "   "}},
        _asst({"type": "text", "text": ""},
              {"type": "thinking", "thinking": "  "},
              {"type": "text", "text": "real"}),
    ])
    d = parse_conversation(f, 0)
    assert [t["kind"] for t in d["turns"]] == ["assistant"]
    assert all(t.get("text", "x").strip() for t in d["turns"])


def test_window_title_takes_the_last_osc(tmp_path):
    assert window_title("\x1b]0;first\x07 mid \x1b]2;second\x1b\\") == "second"
    assert window_title("no title here") is None


def test_parse_permission_reads_numbered_options():
    tail = ("\x1b[1mDo you want to proceed?\x1b[0m\r\n"
            " \u276f 1. Yes\r\n   2. No, tell Claude what to do\r\n")
    perm = parse_permission(tail, ["Do you want to proceed"])
    assert perm["prompt"] == "Do you want to proceed?"
    assert perm["options"] == [
        {"key": "1", "label": "Yes"},
        {"key": "2", "label": "No, tell Claude what to do"}]
    assert parse_permission("just working", ["Do you want to proceed"]) is None
    # a matching prompt with no options is not actionable -> None
    assert parse_permission("Do you want to proceed", ["Do you want to proceed"]) is None

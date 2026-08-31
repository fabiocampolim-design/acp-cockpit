import pytest
from claudiu.core.acp import StateError
from tests.helpers import make_session, FakeFiles
from tests.test_acp_handshake import do_handshake, feed, sent_frames

PERM_FRAME = {"jsonrpc": "2.0", "id": 44,
              "method": "session/request_permission", "params": {
                  "sessionId": "acp-123",
                  "toolCall": {"toolCallId": "t1", "title": "Write file"},
                  "options": [
                      {"optionId": "allow", "name": "Allow",
                       "kind": "allow_once"},
                      {"optionId": "rej", "name": "Reject",
                       "kind": "reject_once"}]}}


def test_permission_roundtrip_user_allow(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, PERM_FRAME)
    req = [e for e in sink.events if e.kind == "permission_request"][0]
    assert req.data["options"][0]["kind"] == "allow_once"
    assert session.pending_permissions() == [44]
    session.answer_permission(44, "allow")
    reply = [f for f in sent_frames(proc) if f.get("id") == 44][0]
    assert reply["result"]["outcome"] == {"outcome": "selected",
                                          "optionId": "allow"}
    resolved = [e for e in sink.events if e.kind == "permission_resolved"][0]
    assert resolved.data["source"] == "user"
    assert session.pending_permissions() == []


def test_permission_failsafe_prefers_reject(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, PERM_FRAME)
    session.fail_safe_reject(44)
    reply = [f for f in sent_frames(proc) if f.get("id") == 44][0]
    assert reply["result"]["outcome"]["optionId"] == "rej"
    resolved = [e for e in sink.events if e.kind == "permission_resolved"][0]
    assert resolved.data["source"] == "failsafe"


def test_fs_read_inside_boundary_served(tmp_path):
    files = FakeFiles()
    inside = str(tmp_path / "a.txt")
    files.store[inside] = "content"
    session, proc, sink = make_session(tmp_path, files=files)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "id": 50, "method": "fs/read_text_file",
                   "params": {"sessionId": "acp-123", "path": inside}})
    reply = [f for f in sent_frames(proc) if f.get("id") == 50][0]
    assert reply["result"] == {"content": "content"}
    ev = [e for e in sink.events if e.kind == "fs_request"][0]
    assert ev.data["allowed"] is True and ev.data["op"] == "read"


def test_fs_write_outside_boundary_refused(tmp_path):
    files = FakeFiles()
    session, proc, sink = make_session(tmp_path, files=files)
    do_handshake(session, proc)
    outside = str(tmp_path.parent / "evil.txt")
    feed(session, {"jsonrpc": "2.0", "id": 51, "method": "fs/write_text_file",
                   "params": {"sessionId": "acp-123", "path": outside,
                              "content": "x"}})
    reply = [f for f in sent_frames(proc) if f.get("id") == 51][0]
    assert "error" in reply
    assert files.store == {}
    ev = [e for e in sink.events if e.kind == "fs_request"][0]
    assert ev.data["allowed"] is False


def test_cancel_sends_notification_and_turn_ends_cancelled(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    session.prompt("go")
    turn = sent_frames(proc)[2]
    session.cancel()
    note = sent_frames(proc)[3]
    assert note == {"jsonrpc": "2.0", "method": "session/cancel",
                    "params": {"sessionId": "acp-123"}}
    feed(session, {"jsonrpc": "2.0", "id": turn["id"],
                   "result": {"stopReason": "cancelled"}})
    ended = [e for e in sink.events if e.kind == "turn_ended"][0]
    assert ended.data["stop_reason"] == "cancelled"
    assert session.state == "ready"


def test_set_mode(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    session.set_mode("acceptEdits")
    frame = sent_frames(proc)[2]
    assert frame["method"] == "session/set_mode"
    assert frame["params"] == {"sessionId": "acp-123",
                               "modeId": "acceptEdits"}
    feed(session, {"jsonrpc": "2.0", "id": frame["id"], "result": {}})
    mode_events = [e for e in sink.events if e.kind == "mode"]
    assert mode_events[-1].data["current"] == "acceptEdits"


def test_unknown_request_still_gets_32601(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "id": 60,
                   "method": "_vendor/surprise", "params": {}})
    reply = [f for f in sent_frames(proc) if f.get("id") == 60][0]
    assert reply["error"]["code"] == -32601


def test_answer_unknown_permission_raises(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    with pytest.raises(StateError):
        session.answer_permission(999, "allow")


def test_load_reaches_ready(tmp_path):
    session, proc, sink = make_session(tmp_path)
    session.load("acp-old", cwd="C:\\work\\proj")
    init = sent_frames(proc)[0]
    assert init["method"] == "initialize"
    feed(session, {"jsonrpc": "2.0", "id": init["id"],
                   "result": {"protocolVersion": 1,
                              "agentCapabilities": {"loadSession": True}}})
    load = sent_frames(proc)[1]
    assert load["method"] == "session/load"
    assert load["params"]["sessionId"] == "acp-old"
    feed(session, {"jsonrpc": "2.0", "id": load["id"], "result": None})
    assert session.state == "ready"
    assert session.acp_session_id == "acp-old"

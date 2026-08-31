# SPDX-License-Identifier: Apache-2.0
import json
import pytest
from claudiu.core.acp import StateError
from tests.helpers import make_session


def sent_frames(proc):
    return [json.loads(x) for x in proc.sent]


def feed(session, frame):
    session.on_line(json.dumps(frame))


def do_handshake(session, proc):
    session.start(cwd="C:\\work\\proj")
    init = sent_frames(proc)[0]
    assert init["method"] == "initialize"
    assert init["params"]["protocolVersion"] == 1
    assert init["params"]["clientCapabilities"]["fs"]["readTextFile"] is True
    assert "terminal" not in init["params"]["clientCapabilities"]
    feed(session, {"jsonrpc": "2.0", "id": init["id"], "result": {
        "protocolVersion": 1,
        "agentCapabilities": {"loadSession": True}}})
    new = sent_frames(proc)[1]
    assert new["method"] == "session/new"
    assert new["params"]["cwd"] == "C:\\work\\proj"
    feed(session, {"jsonrpc": "2.0", "id": new["id"], "result": {
        "sessionId": "acp-123",
        "modes": {"currentModeId": "default", "availableModes": [
            {"id": "default", "name": "Default"}]}}})


def test_handshake_reaches_ready(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    assert session.state == "ready"
    assert session.acp_session_id == "acp-123"
    assert "mode" in sink.kinds()
    states = [e.data["state"] for e in sink.events if e.kind == "session_state"]
    assert states[-1] == "ready"


def test_version_mismatch_fails_closed(tmp_path):
    session, proc, sink = make_session(tmp_path)
    session.start(cwd="C:\\w")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"],
                   "result": {"protocolVersion": 99}})
    assert session.state == "failed"
    assert proc.killed
    assert any(e.kind == "anomaly" and "version" in e.data["detail"]
               for e in sink.events)


def test_prompt_turn_streams_and_ends(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    session.prompt("hello")
    p = sent_frames(proc)[2]
    assert p["method"] == "session/prompt"
    assert p["params"] == {"sessionId": "acp-123",
                           "prompt": [{"type": "text", "text": "hello"}]}
    assert session.state == "turn"
    feed(session, {"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": "acp-123", "update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "hi "}}}})
    feed(session, {"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": "acp-123", "update": {
            "sessionUpdate": "agent_thought_chunk",
            "content": {"type": "text", "text": "thinking"}}}})
    feed(session, {"jsonrpc": "2.0", "id": p["id"],
                   "result": {"stopReason": "end_turn"}})
    chunks = [e for e in sink.events if e.kind == "message_chunk"]
    assert chunks[0].data == {"role": "agent", "text": "hi "}
    assert chunks[1].data == {"role": "thought", "text": "thinking"}
    assert sink.kinds()[-1] == "turn_ended" or \
        sink.kinds()[-2] == "turn_ended"   # session_state(ready) follows
    assert session.state == "ready"


def test_prompt_rejected_unless_ready(tmp_path):
    session, proc, sink = make_session(tmp_path)
    with pytest.raises(StateError):
        session.prompt("too early")


def test_unknown_update_kind_becomes_unrecognized_plus_drift(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": "acp-123", "update": {"sessionUpdate": "hologram"}}})
    assert "unrecognized" in sink.kinds()
    assert "drift" in sink.kinds()


def test_update_for_foreign_session_is_anomaly(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": "someone-else", "update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "leak?"}}}})
    assert not any(e.kind == "message_chunk" and e.data["role"] == "agent"
                   for e in sink.events)
    assert any(e.kind == "anomaly" and
               e.data["category"] == "unknown-session" for e in sink.events)


def test_everything_is_recorded_raw(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    entries = [e for _, e in session.recorder.replay()]
    dirs = [e["dir"] for e in entries]
    assert "out" in dirs and "in" in dirs
    outs = [e["frame"]["method"] for e in entries
            if e["dir"] == "out" and "method" in e["frame"]]
    assert outs[:2] == ["initialize", "session/new"]

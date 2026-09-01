# SPDX-License-Identifier: Apache-2.0
"""Engine behaviour driven by Fabio's first live test (2026-08-31 20:41)."""
from tests.helpers import make_session
from tests.test_acp_handshake import do_handshake, feed, sent_frames


def test_models_in_session_new_become_model_event(tmp_path):
    session, proc, sink = make_session(tmp_path)
    session.start(cwd="C:\\work\\proj")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"],
                   "result": {"protocolVersion": 1, "agentCapabilities": {}}})
    new = sent_frames(proc)[1]
    feed(session, {"jsonrpc": "2.0", "id": new["id"], "result": {
        "sessionId": "acp-123",
        "models": {"currentModelId": "sonnet", "availableModels": [
            {"modelId": "default", "name": "Default"},
            {"modelId": "sonnet", "name": "Sonnet"}]}}})
    ev = [e for e in sink.events if e.kind == "model"][0]
    assert ev.data["current"] == "sonnet"
    assert [m["modelId"] for m in ev.data["available"]] == ["default", "sonnet"]


def test_set_model_roundtrip(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    session.set_model("sonnet")
    frame = sent_frames(proc)[2]
    assert frame["method"] == "session/set_model"
    assert frame["params"] == {"sessionId": "acp-123", "modelId": "sonnet"}
    feed(session, {"jsonrpc": "2.0", "id": frame["id"], "result": {}})
    assert [e for e in sink.events if e.kind == "model"][-1].data["current"] \
        == "sonnet"
    actions = [e for _, e in session.recorder.replay()
               if e.get("action") == "set_model"]
    assert actions and actions[0]["model"] == "sonnet"


def test_stderr_is_recorded_and_is_not_an_anomaly(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    session.on_stderr("<local-command-stdout>## Context Usage")
    ev = sink.events[-1]
    assert ev.kind == "stderr"
    assert ev.data["line"].startswith("<local-command-stdout>")
    assert "anomaly" not in sink.kinds()
    recorded = [e for _, e in session.recorder.replay() if e.get("dir") == "err"]
    assert recorded and recorded[0]["line"].startswith("<local-command")


def test_permission_request_flags_paths_outside_boundary(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    outside = str(tmp_path.parent / "elsewhere" / "TESTE")
    inside = str(tmp_path / "ok.txt")
    feed(session, {"jsonrpc": "2.0", "id": 70,
                   "method": "session/request_permission", "params": {
                       "sessionId": "acp-123",
                       "toolCall": {"toolCallId": "t9", "kind": "execute",
                                    "title": f"`printf hi > \"{outside}\" "
                                             f"&& cat \"{inside}\"`"},
                       "options": [{"optionId": "a", "name": "Allow",
                                    "kind": "allow_once"}]}})
    ev = [e for e in sink.events if e.kind == "permission_request"][0]
    assert ev.data["outside_boundary"] == [outside]


def test_updates_arriving_before_session_id_are_buffered_not_dropped(tmp_path):
    session, proc, sink = make_session(tmp_path)
    session.start(cwd="C:\\work\\proj")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"],
                   "result": {"protocolVersion": 1, "agentCapabilities": {}}})
    # adapter announces commands BEFORE answering session/new
    feed(session, {"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": "acp-123", "update": {
            "sessionUpdate": "available_commands_update",
            "availableCommands": [{"name": "context"}]}}})
    assert "commands" not in sink.kinds()          # held, not guessed
    new = sent_frames(proc)[1]
    feed(session, {"jsonrpc": "2.0", "id": new["id"],
                   "result": {"sessionId": "acp-123"}})
    assert "commands" in sink.kinds()              # replayed once id known
    assert not any(e.kind == "anomaly" for e in sink.events)

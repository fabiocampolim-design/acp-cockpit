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


def test_prompt_error_ends_the_turn_visibly(tmp_path):
    # 2026-09-01: the adapter answered session/prompt with a JSON-RPC error
    # (its bundled CLI refused by the API). The turn must END — separator,
    # composer back — and the message must be readable, not a dict repr.
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    session.prompt("hi")
    turn = sent_frames(proc)[2]
    msg = ("Internal error: API Error: 400 Claude Code 2.1.44 does not "
           "support this model; version 2.1.251 or newer is required.")
    feed(session, {"jsonrpc": "2.0", "id": turn["id"],
                   "error": {"code": -32603, "message": msg}})
    ended = [e for e in sink.events if e.kind == "turn_ended"][0]
    assert ended.data["stop_reason"] == "error"
    assert ended.data["error"] == {"code": -32603, "message": msg}
    anomaly = [e for e in sink.events if e.kind == "anomaly"][0]
    assert anomaly.data["category"] == "turn-error"
    assert anomaly.data["detail"] == msg
    assert session.state == "ready"


def test_config_options_in_session_new_become_a_config_option_event(tmp_path):
    # claude-agent-acp 0.73 advertises mode/model/effort/agent as
    # configOptions in the session/new RESULT (no `models`, no update).
    session, proc, sink = make_session(tmp_path)
    session.start(cwd="C:/work/proj")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"],
                   "result": {"protocolVersion": 1, "agentCapabilities": {}}})
    new = sent_frames(proc)[1]
    opts = [{"id": "model", "name": "Model", "type": "select",
             "currentValue": "opus",
             "options": [{"value": "opus", "name": "Opus"},
                         {"value": "sonnet", "name": "Sonnet"}]},
            {"id": "effort", "name": "Effort", "type": "select",
             "currentValue": "default",
             "options": [{"value": "default", "name": "Default"}]}]
    feed(session, {"jsonrpc": "2.0", "id": new["id"], "result": {
        "sessionId": "acp-123", "configOptions": opts}})
    ev = [e for e in sink.events if e.kind == "config_option"]
    assert len(ev) == 1 and ev[0].data["options"] == opts
    assert "model" not in sink.kinds()          # nothing invented
    assert session.state == "ready"


def test_frames_after_close_are_recorded_until_the_adapter_exits(tmp_path):
    # The adapter keeps talking for a moment after the kill (2026-09-01:
    # usage/session_info updates hit a closed record file -> ValueError in
    # the server log). Record them; close the record when the process ends.
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    session.close()
    assert proc.killed and session.state == "closed"
    feed(session, {"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": "acp-123", "update": {"sessionUpdate": "usage_update",
                                           "used": 1, "size": 2}}})
    late = [e for _, e in session.recorder.replay()
            if (e.get("frame") or {}).get("params", {}).get("update", {})
            .get("sessionUpdate") == "usage_update"]
    assert late, "frame after close() must still be recorded"
    session.on_exit(0)
    assert session.recorder.append({"dir": "client", "action": "x"}) is None


def test_client_asks_for_subagent_transcripts(tmp_path):
    # Without this capability the adapter strips subagent text and thinking
    # from what it forwards, so a "subagents" lane would have nothing to show.
    session, proc, sink = make_session(tmp_path)
    session.start(cwd="C:\\work\\proj")
    caps = sent_frames(proc)[0]["params"]["clientCapabilities"]
    assert caps["_meta"]["subagent-transcript"] is True


def test_subagent_text_carries_the_tool_call_it_belongs_to(tmp_path):
    # Subagent messages are stamped with the Task tool call that owns them;
    # the View needs that to file them under the subagent, not the main agent.
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": "acp-123",
        "update": {"sessionUpdate": "agent_message_chunk",
                   "content": {"type": "text", "text": "subagent says hi"},
                   "_meta": {"claudeCode": {"parentToolUseId": "t-task"}}}}})
    ev = [e for e in sink.events if e.kind == "message_chunk"][-1]
    assert ev.data["text"] == "subagent says hi"
    assert ev.data["parent_tool_call_id"] == "t-task"


def test_main_agent_text_has_no_parent_tool_call(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": "acp-123",
        "update": {"sessionUpdate": "agent_message_chunk",
                   "content": {"type": "text", "text": "the answer"}}}})
    ev = [e for e in sink.events if e.kind == "message_chunk"][-1]
    assert ev.data["parent_tool_call_id"] is None

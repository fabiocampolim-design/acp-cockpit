# SPDX-License-Identifier: Apache-2.0
"""Protocol coverage the 2026-09-05 review found missing: every schema field
the client is asked to honour, every message it used to drop without a word.
"""
from tests.helpers import make_session, FakeFiles
from tests.test_acp_handshake import do_handshake, feed, sent_frames
from tests.test_acp_sessions import update


# ---- fs/read_text_file honours `line` and `limit` (schema fields) ----------

def test_fs_read_honours_line_and_limit(tmp_path):
    files = FakeFiles()
    path = str(tmp_path / "big.txt")
    files.store[path] = "l1\nl2\nl3\nl4\nl5\n"
    session, proc, sink = make_session(tmp_path, files=files)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "id": 50, "method": "fs/read_text_file",
                   "params": {"sessionId": "acp-123", "path": path,
                              "line": 2, "limit": 2}})
    reply = [f for f in sent_frames(proc) if f.get("id") == 50][0]
    assert reply["result"] == {"content": "l2\nl3\n"}


def test_fs_read_without_line_or_limit_is_the_whole_file(tmp_path):
    files = FakeFiles()
    path = str(tmp_path / "a.txt")
    files.store[path] = "x\ny\n"
    session, proc, sink = make_session(tmp_path, files=files)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "id": 51, "method": "fs/read_text_file",
                   "params": {"sessionId": "acp-123", "path": path,
                              "line": None, "limit": None}})
    reply = [f for f in sent_frames(proc) if f.get("id") == 51][0]
    assert reply["result"] == {"content": "x\ny\n"}


# ---- an unreadable file answers an error instead of hanging the agent -----

class BinaryFiles(FakeFiles):
    def read_text(self, path):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "not text")


def test_fs_read_of_a_binary_file_answers_a_jsonrpc_error(tmp_path):
    session, proc, sink = make_session(tmp_path, files=BinaryFiles())
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "id": 52, "method": "fs/read_text_file",
                   "params": {"sessionId": "acp-123",
                              "path": str(tmp_path / "img.png")}})
    reply = [f for f in sent_frames(proc) if f.get("id") == 52][0]
    assert reply["error"]["code"] == -32603
    assert "not text" in reply["error"]["message"]


# ---- a non-text content block is surfaced, never reduced to "" -----------

def test_non_text_message_content_becomes_unrecognized_not_an_empty_row(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, update("agent_message_chunk",
                         content={"type": "image", "mimeType": "image/png",
                                  "data": "iVBORw0KGgo="}))
    kinds = sink.kinds()
    assert "message_chunk" not in kinds, "an image became an empty text row"
    ev = [e for e in sink.events if e.kind == "unrecognized"][0]
    assert "image" in ev.data["why"]
    assert ev.data["frame"]["content"]["type"] == "image"


# ---- notifications other than session/update are not silently ignored ----

def test_elicitation_complete_is_surfaced(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "method": "elicitation/complete",
                   "params": {"elicitationId": "e-1"}})
    ev = [e for e in sink.events if e.kind == "unrecognized"][0]
    assert "elicitation/complete" in ev.data["why"]


def test_agent_cancel_request_resolves_a_pending_permission(tmp_path):
    # `$/cancel_request` from the agent: it no longer wants the answer. The
    # dialog closes and the record says the AGENT withdrew it.
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "id": 44,
                   "method": "session/request_permission", "params": {
                       "sessionId": "acp-123",
                       "toolCall": {"toolCallId": "t1", "title": "Write"},
                       "options": [{"optionId": "a", "name": "Allow",
                                    "kind": "allow_once"}]}})
    feed(session, {"jsonrpc": "2.0", "method": "$/cancel_request",
                   "params": {"requestId": 44}})
    reply = [f for f in sent_frames(proc) if f.get("id") == 44][0]
    assert reply["result"]["outcome"] == {"outcome": "cancelled"}
    resolved = [e for e in sink.events if e.kind == "permission_resolved"][0]
    assert resolved.data["source"] == "agent"
    assert session.pending_permissions() == []


def test_agent_cancel_request_cancels_a_pending_elicitation(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "id": 77, "method": "elicitation/create",
                   "params": {"sessionId": "acp-123", "mode": "form",
                              "message": "Which?",
                              "requestedSchema": {"type": "object",
                                                  "properties": {}}}})
    feed(session, {"jsonrpc": "2.0", "method": "$/cancel_request",
                   "params": {"requestId": 77}})
    reply = [f for f in sent_frames(proc) if f.get("id") == 77][0]
    assert reply["result"] == {"action": "cancel"}
    resolved = [e for e in sink.events if e.kind == "elicitation_resolved"][0]
    assert resolved.data["action"] == "cancel"
    assert resolved.data["source"] == "agent"
    assert session.pending_elicitations() == []


# ---- an unsupported request is an anomaly, not only a quiet -32601 --------

def test_unadvertised_terminal_request_is_an_anomaly(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "id": 61, "method": "terminal/create",
                   "params": {"sessionId": "acp-123", "command": "ls"}})
    reply = [f for f in sent_frames(proc) if f.get("id") == 61][0]
    assert reply["error"]["code"] == -32601
    ev = [e for e in sink.events if e.kind == "anomaly"][0]
    assert ev.data["category"] == "unsupported-request"
    assert "terminal/create" in ev.data["detail"]


# ---- initialize: agentInfo is kept, authMethods are not ignored -----------

def _init(session, proc, result):
    session.start(cwd="C:\\work\\proj")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"], "result": result})


def test_agent_info_rides_on_the_ready_state(tmp_path):
    session, proc, sink = make_session(tmp_path)
    _init(session, proc, {"protocolVersion": 1, "agentCapabilities": {},
                          "agentInfo": {"name": "claude-agent-acp",
                                        "version": "0.75.0"}})
    new = sent_frames(proc)[1]
    feed(session, {"jsonrpc": "2.0", "id": new["id"],
                   "result": {"sessionId": "acp-123"}})
    ready = [e for e in sink.events if e.kind == "session_state"
             and e.data["state"] == "ready"][0]
    assert ready.data["agent_info"] == {"name": "claude-agent-acp",
                                        "version": "0.75.0"}


def test_an_agent_that_wants_authentication_is_said_so(tmp_path):
    # This client does not implement `authenticate`; an agent that advertises
    # auth methods gets a visible anomaly instead of a bare session/new error.
    session, proc, sink = make_session(tmp_path)
    _init(session, proc, {"protocolVersion": 1, "agentCapabilities": {},
                          "authMethods": [{"id": "oauth", "name": "Log in"}]})
    ev = [e for e in sink.events if e.kind == "anomaly"][0]
    assert ev.data["category"] == "authentication-unsupported"
    assert "oauth" in ev.data["detail"]


# ---- vendor update kinds: known, rendered as themselves, never "unknown" --

def test_a_known_vendor_update_kind_is_its_own_event(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, update("subagent_spawned", subagentSessionId="sub-1",
                         toolCallId="t-task"))
    kinds = sink.kinds()
    assert "unrecognized" not in kinds
    ev = [e for e in sink.events if e.kind == "vendor_update"][0]
    assert ev.data["kind"] == "subagent_spawned"
    assert ev.data["update"]["subagentSessionId"] == "sub-1"


def test_a_truly_unknown_update_kind_is_still_unrecognized(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, update("hologram_chunk"))
    assert "unrecognized" in sink.kinds()


# ---- `_auth/status_update`: the adapter says which account it runs as -----
# Shape captured from claude-agent-acp 0.75.1 on 2026-09-05 (values redacted:
# the real frame carried the account e-mail).
AUTH_STATUS = {"authStatus": {"kind": "account", "label": "Claude Pro",
                              "account": {"plan": "pro",
                                          "email": "someone@example.com",
                                          "organization": "Someone's Organization"}}}


def test_auth_status_update_is_its_own_event_not_drift(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "method": "_auth/status_update",
                   "params": AUTH_STATUS})
    kinds = sink.kinds()
    assert "drift" not in kinds and "unrecognized" not in kinds
    ev = [e for e in sink.events if e.kind == "auth_status"][0]
    assert ev.data["label"] == "Claude Pro"
    assert ev.data["account"]["email"] == "someone@example.com"

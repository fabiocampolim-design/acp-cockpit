# SPDX-License-Identifier: Apache-2.0
"""Newer update kinds, config options, resume and session listing."""
from tests.helpers import make_session
from tests.test_acp_handshake import do_handshake, feed, sent_frames


def update(kind, **fields):
    return {"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": "acp-123", "update": {"sessionUpdate": kind, **fields}}}


def test_usage_session_info_and_config_option_updates(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, update("usage_update", used=59300, size=1000000,
                         cost={"amount": 0.42, "currency": "USD"}))
    feed(session, update("session_info_update", title="Fix the widget"))
    feed(session, update("config_option_update", configOptions=[
        {"id": "effort", "name": "Effort", "type": "select",
         "currentValue": "high",
         "options": [{"value": "low", "name": "Low"},
                     {"value": "high", "name": "High"}]}]))
    usage = [e for e in sink.events if e.kind == "usage"][0]
    assert usage.data == {"used": 59300, "size": 1000000,
                          "cost": {"amount": 0.42, "currency": "USD"}}
    info = [e for e in sink.events if e.kind == "session_info"][0]
    assert info.data["title"] == "Fix the widget"
    cfg = [e for e in sink.events if e.kind == "config_option"][0]
    assert cfg.data["options"][0]["id"] == "effort"
    assert "unrecognized" not in sink.kinds()


def test_set_config_option_roundtrip(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    session.set_config_option("effort", "low")
    frame = sent_frames(proc)[2]
    assert frame["method"] == "session/set_config_option"
    assert frame["params"] == {"sessionId": "acp-123", "configId": "effort",
                               "value": "low"}
    feed(session, {"jsonrpc": "2.0", "id": frame["id"], "result": {
        "configOptions": [{"id": "effort", "name": "Effort",
                           "type": "select", "currentValue": "low",
                           "options": []}]}})
    cfg = [e for e in sink.events if e.kind == "config_option"][-1]
    assert cfg.data["options"][0]["currentValue"] == "low"


def test_load_prefers_session_load_for_history_when_advertised(tmp_path):
    # session/resume attaches WITHOUT the previous messages (spec); a browser
    # client keeps no history of its own, so session/load wins when offered.
    session, proc, sink = make_session(tmp_path)
    session.load("acp-old", cwd="C:\\work\\proj")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"], "result": {
        "protocolVersion": 1,
        "agentCapabilities": {"loadSession": True,
                              "sessionCapabilities": {"resume": {}}}}})
    req = sent_frames(proc)[1]
    assert req["method"] == "session/load"
    assert req["params"]["sessionId"] == "acp-old"
    feed(session, {"jsonrpc": "2.0", "id": req["id"], "result": {
        "modes": {"currentModeId": "plan", "availableModes": []}}})
    assert session.state == "ready"
    assert [e for e in sink.events if e.kind == "mode"][-1].data["current"] \
        == "plan"


def test_probe_sessions_lists_without_creating(tmp_path):
    session, proc, sink = make_session(tmp_path)
    got = []
    session.probe_sessions("C:\\work\\proj", lambda sessions, err:
                           got.append((sessions, err)))
    init = sent_frames(proc)[0]
    assert init["method"] == "initialize"
    feed(session, {"jsonrpc": "2.0", "id": init["id"],
                   "result": {"protocolVersion": 1, "agentCapabilities": {
                       "sessionCapabilities": {"list": {}}}}})
    lst = sent_frames(proc)[1]
    assert lst["method"] == "session/list"
    assert lst["params"] == {"cwd": "C:\\work\\proj"}
    feed(session, {"jsonrpc": "2.0", "id": lst["id"], "result": {
        "sessions": [{"sessionId": "old-1", "cwd": "C:\\work\\proj",
                      "title": "Old work"}]}})
    assert got == [([{"sessionId": "old-1", "cwd": "C:\\work\\proj",
                      "title": "Old work"}], None)]
    assert session.state == "starting"          # never became a session
    assert all(f["method"] != "session/new" for f in sent_frames(proc))


def test_load_falls_back_to_session_resume_without_load_support(tmp_path):
    session, proc, sink = make_session(tmp_path)
    session.load("acp-old", cwd="C:\\work\\proj")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"], "result": {
        "protocolVersion": 1,
        "agentCapabilities": {"sessionCapabilities": {"resume": {}}}}})
    req = sent_frames(proc)[1]
    assert req["method"] == "session/resume"
    assert req["params"]["sessionId"] == "acp-old"


def test_load_fails_closed_when_neither_method_is_offered(tmp_path):
    session, proc, sink = make_session(tmp_path)
    session.load("acp-old", cwd="C:\\work\\proj")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"], "result": {
        "protocolVersion": 1, "agentCapabilities": {}}})
    assert session.state == "failed" and proc.killed



def test_session_load_carries_the_profile_client_options(tmp_path):
    # The adapter forwards `_meta` from session/load and session/resume into
    # the same createSession path as session/new: a resumed session must
    # think out loud exactly like a fresh one.
    session, proc, sink = make_session(tmp_path)
    session.load("acp-old", cwd="C:\\work\\proj")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"], "result": {
        "protocolVersion": 1, "agentCapabilities": {"loadSession": True}}})
    load = sent_frames(proc)[1]
    assert load["method"] == "session/load"
    assert load["params"]["_meta"]["claudeCode"]["options"]["thinking"] == \
        {"type": "adaptive", "display": "summarized"}


def test_session_resume_carries_the_profile_client_options(tmp_path):
    session, proc, sink = make_session(tmp_path)
    session.load("acp-old", cwd="C:\\work\\proj")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"], "result": {
        "protocolVersion": 1,
        "agentCapabilities": {"sessionCapabilities": {"resume": {}}}}})
    resume = sent_frames(proc)[1]
    assert resume["method"] == "session/resume"
    assert resume["params"]["_meta"]["claudeCode"]["options"]["thinking"] == \
        {"type": "adaptive", "display": "summarized"}

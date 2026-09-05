# SPDX-License-Identifier: Apache-2.0
"""Form elicitation: the agent asks the user a structured question.

The Claude adapter disables its AskUserQuestion tool unless the client
advertises `elicitation.form`, and renders the tool's questions as an ACP
form elicitation when it is advertised (claude-agent-acp 0.73).
"""
import pytest
from acp_cockpit.core.acp import StateError
from tests.helpers import make_session
from tests.test_acp_handshake import do_handshake, feed, sent_frames

SCHEMA = {
    "type": "object",
    "properties": {
        "question_0": {
            "type": "string", "title": "Colour",
            "oneOf": [{"const": "Red", "title": "Red"},
                      {"const": "Blue", "title": "Blue",
                       "description": "the cold one"}]},
        "question_0_custom": {
            "type": "string", "title": "Other",
            "description": "Type your own answer instead."},
    },
}


def elicitation_frame(request_id=77, **overrides):
    params = {"mode": "form", "sessionId": "acp-123", "toolCallId": "t-ask",
              "message": "Which colour?", "requestedSchema": SCHEMA}
    params.update(overrides)
    return {"jsonrpc": "2.0", "id": request_id,
            "method": "elicitation/create", "params": params}


def test_client_advertises_form_elicitation(tmp_path):
    # Without this capability the adapter never loads AskUserQuestion at all.
    session, proc, sink = make_session(tmp_path)
    session.start(cwd="C:\\work\\proj")
    caps = sent_frames(proc)[0]["params"]["clientCapabilities"]
    assert caps["elicitation"] == {"form": {}}
    assert "url" not in caps["elicitation"]      # not built; not claimed


def test_form_elicitation_becomes_an_event(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, elicitation_frame())
    ev = [e for e in sink.events if e.kind == "elicitation_request"][0]
    assert ev.data["request"] == 77
    assert ev.data["message"] == "Which colour?"
    assert ev.data["tool_call_id"] == "t-ask"
    assert ev.data["schema"]["properties"]["question_0"]["oneOf"][0]["const"] \
        == "Red"
    assert session.pending_elicitations() == [77]
    assert not [f for f in sent_frames(proc) if f.get("id") == 77]


def test_accepting_sends_the_content_the_user_chose(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, elicitation_frame())
    session.answer_elicitation(77, "accept", {"question_0": "Blue"})
    reply = [f for f in sent_frames(proc) if f.get("id") == 77][0]
    assert reply["result"] == {"action": "accept",
                               "content": {"question_0": "Blue"}}
    resolved = [e for e in sink.events if e.kind == "elicitation_resolved"][0]
    assert resolved.data == {"request": 77, "action": "accept",
                             "content": {"question_0": "Blue"},
                             "source": "user"}
    assert session.pending_elicitations() == []
    recorded = [e for _, e in session.recorder.replay()
                if e.get("action") == "elicitation"]
    assert recorded and recorded[0]["content"] == {"question_0": "Blue"}


def test_declining_sends_no_content(tmp_path):
    # Decline is "the user skipped": the adapter answers the tool with empty
    # answers and the turn continues. Content would be a lie.
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, elicitation_frame())
    session.answer_elicitation(77, "decline")
    reply = [f for f in sent_frames(proc) if f.get("id") == 77][0]
    assert reply["result"] == {"action": "decline"}


def test_fail_safe_declines_rather_than_cancelling_the_turn(tmp_path):
    # An unanswered question must not abort the agent's work: decline lets
    # the turn continue, cancel kills the tool call.
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, elicitation_frame())
    session.fail_safe_decline_elicitation(77)
    reply = [f for f in sent_frames(proc) if f.get("id") == 77][0]
    assert reply["result"] == {"action": "decline"}
    resolved = [e for e in sink.events if e.kind == "elicitation_resolved"][0]
    assert resolved.data["source"] == "failsafe"
    assert resolved.data["content"] is None      # nothing was answered
    assert session.pending_elicitations() == []


def test_url_mode_is_cancelled_and_surfaced(tmp_path):
    # URL elicitation is not advertised and not built; an agent that sends
    # one anyway gets an honest "cancelled" and the user sees why.
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, elicitation_frame(request_id=78, mode="url",
                                    url="https://example.invalid/auth",
                                    elicitationId="e-1"))
    reply = [f for f in sent_frames(proc) if f.get("id") == 78][0]
    assert reply["result"] == {"action": "cancel"}
    assert session.pending_elicitations() == []
    anomaly = [e for e in sink.events if e.kind == "anomaly"][-1]
    assert anomaly.data["category"] == "unsupported-elicitation-mode"
    assert "url" in anomaly.data["detail"]


def test_answering_an_unknown_elicitation_raises(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    with pytest.raises(StateError):
        session.answer_elicitation(999, "accept", {})

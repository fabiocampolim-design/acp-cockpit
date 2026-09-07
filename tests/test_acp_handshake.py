# SPDX-License-Identifier: Apache-2.0
import json
import pytest
from acp_cockpit.core.acp import StateError
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


def test_session_new_without_a_session_id_fails_instead_of_wedging(tmp_path):
    """`result["sessionId"]` was the only bracket deref among `.get`
    neighbours. A result missing the key raised inside the JSON-RPC callback:
    no session_state event, so `evict` never armed, the entry never left the
    manager and the adapter tree ran until the server died (2026-09-06)."""
    session, proc, sink = make_session(tmp_path)
    session.start(cwd="C:\\w")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"], "result": {
        "protocolVersion": 1, "agentCapabilities": {"loadSession": True}}})
    new = sent_frames(proc)[1]
    feed(session, {"jsonrpc": "2.0", "id": new["id"],
                   "result": {"modes": {"currentModeId": "default"}}})
    assert session.state == "failed", session.state
    states = [e.data["state"] for e in sink.events if e.kind == "session_state"]
    assert states and states[-1] == "failed"


def test_string_config_choices_do_not_wedge_the_session(tmp_path):
    """`_ordered_options` guarded `isinstance(opt, dict)` but not the elements
    of its `options` list, so a bare-string choice list crashed `sorted()` and
    left the session in "starting" for ever (review 2026-09-06)."""
    # the shipped profile already orders `model`, so this is the real path
    session, proc, sink = make_session(tmp_path)
    assert session.profile.config_option_order.get("model")
    session.start(cwd="C:\\w")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"], "result": {
        "protocolVersion": 1, "agentCapabilities": {"loadSession": True}}})
    new = sent_frames(proc)[1]
    feed(session, {"jsonrpc": "2.0", "id": new["id"], "result": {
        "sessionId": "acp-123",
        "configOptions": [{"id": "model", "currentValue": "opus",
                           "options": ["opus", "fable"]}]}})
    assert session.state == "ready", session.state


def test_a_null_capability_means_the_agent_does_not_offer_it(tmp_path):
    """The schema says `SessionCapabilities.resume` omitted OR null both mean
    unsupported. `"resume" in caps` was true for an explicit null, so the
    client sent session/resume, got -32601 back and killed the session with a
    raw adapter error instead of the accurate message (review 2026-09-06)."""
    session, proc, sink = make_session(tmp_path)
    session.load("acp-old", cwd="C:\\w")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"], "result": {
        "protocolVersion": 1,
        "agentCapabilities": {"sessionCapabilities": {"resume": None}}}})
    assert session.state == "failed"
    assert not any(f.get("method") == "session/resume"
                   for f in sent_frames(proc))
    detail = [e.data["detail"] for e in sink.events
              if e.kind == "session_state" and e.data["state"] == "failed"]
    assert detail and "session/resume" in detail[0]


def test_a_null_list_capability_is_not_a_list_capability(tmp_path):
    session, proc, sink = make_session(tmp_path)
    seen = {}
    session.probe_sessions("C:\\w",
                           lambda s, e: seen.update(sessions=s, error=e))
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"], "result": {
        "protocolVersion": 1,
        "agentCapabilities": {"sessionCapabilities": {"list": None}}}})
    assert seen["error"] == {"message": "agent cannot list sessions"}
    assert not any(f.get("method") == "session/list"
                   for f in sent_frames(proc))


def test_a_boolean_config_option_carries_its_type_discriminator(tmp_path):
    """vendor/acp/schema.json: SetSessionConfigOptionRequest anyOf[0] requires
    ["type","value"] with type const "boolean"; anyOf[1] is the default when
    `type` is absent and constrains `value` to a STRING id. A bare boolean
    matched neither, so the agent could not deserialize it and the checkbox
    snapped back (review 2026-09-06)."""
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    session.set_config_option("web_search", True)
    frame = [f for f in sent_frames(proc)
             if f.get("method") == "session/set_config_option"][-1]
    assert frame["params"]["value"] is True
    assert frame["params"]["type"] == "boolean"
    # a string value id stays the default variant: no discriminator
    session.set_config_option("model", "opus")
    frame = [f for f in sent_frames(proc)
             if f.get("method") == "session/set_config_option"][-1]
    assert frame["params"]["value"] == "opus"
    assert "type" not in frame["params"]


def test_an_adapter_that_dies_mid_turn_still_ends_the_turn(tmp_path):
    """No client request had a timeout and `_pending` was never failed when
    the transport died, so an adapter killed mid-turn never invoked
    `_on_turn_end`: no turn_ended was emitted and a View that reattached
    replayed a turn that opened and never closed (review 2026-09-06)."""
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    session.prompt("go")
    assert session.state == "turn"
    session.on_exit(137)                       # OOM-killed, say
    ended = [e for e in sink.events if e.kind == "turn_ended"]
    assert ended, [e.kind for e in sink.events]
    assert ended[0].data["stop_reason"] == "error"


def test_early_updates_are_surfaced_even_when_the_session_never_opens(tmp_path):
    """Updates that arrive before the session/new result are held and replayed
    — "never drop, never guess". On the failure branch they were simply
    dropped, and the buffer had no bound at all, so an agent that streams
    before answering could grow it without limit (review 2026-09-06)."""
    session, proc, sink = make_session(tmp_path)
    session.start(cwd="C:\\w")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"], "result": {
        "protocolVersion": 1, "agentCapabilities": {"loadSession": True}}})
    new = sent_frames(proc)[1]
    feed(session, {"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": "acp-1", "update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "said before it opened"}}}})
    feed(session, {"jsonrpc": "2.0", "id": new["id"],
                   "error": {"code": -32000, "message": "no"}})
    assert session.state == "failed"
    text = " ".join(str(e.data) for e in sink.events)
    assert "said before it opened" in text, [e.kind for e in sink.events]


def test_the_early_update_buffer_is_bounded(tmp_path):
    session, proc, sink = make_session(tmp_path)
    session.start(cwd="C:\\w")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"], "result": {
        "protocolVersion": 1, "agentCapabilities": {"loadSession": True}}})
    for i in range(session.EARLY_UPDATE_CAP + 50):
        feed(session, {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "acp-1", "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": f"chunk {i}"}}}})
    assert len(session._early_updates) <= session.EARLY_UPDATE_CAP
    assert any(e.kind == "anomaly" and "early" in str(e.data).lower()
               for e in sink.events)


def test_the_client_flags_drift_in_its_own_outbound_frames(tmp_path):
    """The sentinel has always had an outbound direction and it was never
    called: only `on_line` checked frames, so a client sending a method the
    pinned registry does not know said nothing (review 2026-09-06)."""
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    before = len([e for e in sink.events if e.kind == "drift"])
    session._conn.request("session/invented", {}, lambda r, e: None)
    session._flush()
    drift = [e for e in sink.events if e.kind == "drift"][before:]
    assert drift, [e.kind for e in sink.events]
    assert any("session/invented" in f for f in drift[0].data["flags"])


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
    # the user's own prompt leads the turn (review 2026-09-06)
    assert chunks[0].data["role"] == "user"
    chunks = chunks[1:]
    assert chunks[0].data == {"role": "agent", "text": "hi ",
                             "parent_tool_call_id": None}
    assert chunks[1].data == {"role": "thought", "text": "thinking",
                             "parent_tool_call_id": None}
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


MINIMAL_PROFILE = ('id = "bare"\nname = "Bare"\ncommand = ["bare"]\n'
                   'install_hint = "get bare"\nenv_scrub = []\n')


def test_session_new_carries_the_profile_client_options(tmp_path):
    # claude-agent-acp merges `_meta.claudeCode.options` into the SDK call,
    # which is the only way to ask for summarized thinking over ACP.
    session, proc, sink = make_session(tmp_path)
    session.start(cwd="C:\\work\\proj")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"],
                   "result": {"protocolVersion": 1, "agentCapabilities": {}}})
    new = sent_frames(proc)[1]
    assert new["params"]["_meta"]["claudeCode"]["options"]["thinking"] == \
        {"type": "adaptive", "display": "summarized"}


def test_session_new_omits_meta_without_client_options(tmp_path):
    from pathlib import Path
    from acp_cockpit.core.profiles import load_profile
    bare = tmp_path / "bare.toml"
    bare.write_text(MINIMAL_PROFILE, encoding="utf-8")
    session, proc, sink = make_session(tmp_path,
                                       profile=load_profile(Path(bare)))
    session.start(cwd="C:\\work\\proj")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"],
                   "result": {"protocolVersion": 1, "agentCapabilities": {}}})
    assert "_meta" not in sent_frames(proc)[1]["params"]

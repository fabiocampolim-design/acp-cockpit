import json
import pytest
from claudiu.core.events import KINDS, make_event, to_wire

def test_kinds_cover_spec_surface():
    for k in ("session_state", "message_chunk", "tool_call", "tool_call_update",
              "plan", "commands", "mode", "permission_request",
              "permission_resolved", "fs_request", "turn_ended", "anomaly",
              "drift", "unrecognized"):
        assert k in KINDS

def test_make_event_valid():
    e = make_event("plan", "s1", 3, {"entries": []}, raw_ref=17)
    assert (e.kind, e.session, e.seq, e.raw_ref) == ("plan", "s1", 3, 17)
    assert e.ts.endswith("+00:00") or e.ts.endswith("Z")

def test_make_event_unknown_kind_raises():
    with pytest.raises(ValueError):
        make_event("bogus", "s1", 0, {})

def test_to_wire_roundtrip():
    e = make_event("anomaly", "s1", 0, {"category": "malformed", "detail": "x"})
    d = json.loads(to_wire(e))
    assert d["kind"] == "anomaly" and d["data"]["category"] == "malformed"
    assert "\n" not in to_wire(e)

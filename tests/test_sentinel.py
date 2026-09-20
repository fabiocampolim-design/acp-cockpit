# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path
from acp_cockpit.core.sentinel import Sentinel

REG = json.loads(Path("acp_cockpit/vendor/acp/registry.json").read_text())


def test_known_traffic_is_clean():
    s = Sentinel(REG)
    assert s.check_frame("in", {"jsonrpc": "2.0", "method": "session/update",
        "params": {"sessionId": "x", "update":
                   {"sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "hi"}}}}) == []
    assert s.check_frame("out", {"jsonrpc": "2.0", "id": 1,
        "method": "initialize", "params": {}}) == []


def test_unknown_method_and_kind_flagged():
    s = Sentinel(REG)
    assert any("unknown-from-agent-method" in f for f in
               s.check_frame("in", {"jsonrpc": "2.0", "id": 5,
                                    "method": "session/brand_new_thing",
                                    "params": {}}))
    flags = s.check_frame("in", {"jsonrpc": "2.0", "method": "session/update",
        "params": {"sessionId": "x",
                   "update": {"sessionUpdate": "hologram_chunk"}}})
    assert any("unknown-update-kind" in f for f in flags)


def test_unknown_root_key_flagged():
    s = Sentinel(REG)
    flags = s.check_frame("in", {"jsonrpc": "2.0", "id": 1, "result": {},
                                 "novelty": True})
    assert any("unknown-root-key:novelty" in f for f in flags)


def test_version_compare():
    s = Sentinel(REG)
    assert s.compare_versions("v1.0.0", "v1.0.0", "1.2.3", "1.2.3") == []
    flags = s.compare_versions("v1.0.0", "v1.4.0", "1.2.3", "1.9.9")
    assert len(flags) == 2 and any("schema" in f for f in flags)


def test_an_unresolvable_installed_version_is_flagged_unknown_not_silently_current():
    # /api/drift's own npm ls -g lookup can fail the same way the daily watch
    # script's did (2026-09-16): adapter comes back None while latest_adapter
    # is known. Silence here means the UI's drift chip stays hidden and its
    # Help text says "Nothing is behind" -- false, not "confirmed current".
    s = Sentinel(REG)
    flags = s.compare_versions("v1.0.0", "v1.0.0", None, "1.9.9")
    assert flags and any("unknown" in f for f in flags)
    assert not any("behind" in f for f in flags)      # not knowing != behind


def test_an_unresolvable_latest_schema_is_flagged_unknown_not_silently_current():
    # The adapter side of this exact bug was fixed 2026-09-16; the schema
    # side never got the same treatment (hostile Fable 5 review, 2026-09-19):
    # a failed GitHub releases lookup returns latest_schema=None, which read
    # as falsy and produced no flag at all -- "nothing is behind" is false,
    # not "confirmed pinned == latest".
    s = Sentinel(REG)
    flags = s.compare_versions("v1.0.0", None, "1.2.3", "1.2.3")
    assert flags and any("schema-unknown" in f for f in flags)
    assert not any("schema-behind" in f for f in flags)


def test_vendor_update_kinds_the_adapter_is_known_to_send_are_not_drift():
    # claude-agent-acp 0.73/0.75 can emit these outside the pinned schema
    # (read from its dist, review 2026-09-05); known is not drift.
    s = Sentinel(REG)
    for kind in ("subagent_spawned", "subagent_state_update",
                 "async_task_spawned", "async_task_state_update",
                 "async_task_progress"):
        flags = s.check_frame("in", {"jsonrpc": "2.0", "method": "session/update",
            "params": {"sessionId": "x", "update": {"sessionUpdate": kind}}})
        assert flags == [], (kind, flags)


def test_protocol_level_and_auth_methods_are_known():
    s = Sentinel(REG)
    assert s.check_frame("in", {"jsonrpc": "2.0", "method": "$/cancel_request",
                                "params": {"requestId": 1}}) == []
    for method in ("authenticate", "logout", "$/cancel_request"):
        assert s.check_frame("out", {"jsonrpc": "2.0", "id": 2,
                                     "method": method, "params": {}}) == []


def test_vendor_notifications_the_adapter_is_known_to_send_are_not_drift():
    s = Sentinel(REG)
    assert s.check_frame("in", {"jsonrpc": "2.0", "method": "_auth/status_update",
                                "params": {"authStatus": {}}}) == []


def test_the_registry_maps_each_vendor_notification_to_its_event():
    # {method: {event, field}} - the engine reads the mapping, it names
    # nothing itself (review 2026-09-06). Every event named must exist.
    from acp_cockpit.core.events import KINDS
    s = Sentinel.load_default()
    assert s.vendor_notifications["_auth/status_update"] == {
        "event": "auth_status", "field": "authStatus"}
    assert all(v["event"] in KINDS for v in s.vendor_notifications.values())


def test_a_non_dict_update_is_flagged_not_crashed():
    """`(params.get("update") or {}).get("sessionUpdate")` assumed `update`,
    when present, is always a dict. An adapter sending `"update": "x"` raised
    AttributeError inside check_frame, which on_line never caught: the frame
    was recorded but never fed, so a permission request shaped this way hung
    forever with no fail-safe armed (hostile Fable 5 review, 2026-09-19)."""
    s = Sentinel(REG)
    flags = s.check_frame("in", {"jsonrpc": "2.0", "method": "session/update",
        "params": {"sessionId": "x", "update": "not-an-object"}})
    assert any("malformed-update" in f for f in flags)


def test_a_non_dict_permission_option_is_flagged_not_crashed():
    """`opt.get("kind")` assumed every element of `options` is a dict. An
    adapter sending `"options": ["allow_once"]` raised AttributeError the
    same way as the update case above (hostile Fable 5 review, 2026-09-19)."""
    s = Sentinel(REG)
    flags = s.check_frame("in", {"jsonrpc": "2.0",
        "method": "session/request_permission",
        "params": {"sessionId": "x", "options": ["allow_once"]}})
    assert any("malformed-permission-option" in f for f in flags)


def test_non_dict_params_is_flagged_not_crashed():
    s = Sentinel(REG)
    flags = s.check_frame("in", {"jsonrpc": "2.0", "method": "session/update",
        "params": "not-an-object"})
    assert any("malformed-params" in f for f in flags)


def test_the_clients_own_frames_are_checked_and_its_vendor_request_is_known():
    """The outbound direction was dead in production — `check_frame` was only
    ever called with "in" — and `_known_out` omitted
    `vendor_to_agent_requests`, so switching it on would have flagged the
    client's own `session/set_model` as drift (review 2026-09-06)."""
    s = Sentinel.load_default()
    assert s.check_frame("out", {"jsonrpc": "2.0", "id": 1,
                                 "method": "session/set_model",
                                 "params": {}}) == []
    assert s.check_frame("out", {"jsonrpc": "2.0", "id": 2,
                                 "method": "session/prompt",
                                 "params": {}}) == []
    flags = s.check_frame("out", {"jsonrpc": "2.0", "id": 3,
                                  "method": "session/invented", "params": {}})
    assert flags == ["unknown-to-agent-method:session/invented"]


def test_compaction_kinds_the_0_79_0_adapter_emits_are_known():
    # claude-agent-acp 0.79.0 runs a context-compaction lifecycle and emits
    # `sessionUpdate: "compaction_update"` (20 sites) and
    # `"compaction_summary_chunk"` (dist/context-compaction.js:133/158/192/256,
    # read from the INSTALLED adapter after the 2026-09-20 upgrade). Neither
    # is in the pinned schema-v1.23.0, so before they were registered every
    # compaction produced an `unrecognized` row and a drift chip on a frame
    # the client understands perfectly well (AGENTS.md: a kind the installed
    # adapter emits outside the schema goes in vendor_update_kinds).
    s = Sentinel(REG)
    for kind in ("compaction_update", "compaction_summary_chunk"):
        flags = s.check_frame("in", {"jsonrpc": "2.0", "method": "session/update",
            "params": {"sessionId": "x", "update": {"sessionUpdate": kind}}})
        assert flags == [], (kind, flags)

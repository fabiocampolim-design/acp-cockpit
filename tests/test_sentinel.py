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

import json
from pathlib import Path
from claudiu.core.sentinel import Sentinel

REG = json.loads(Path("vendor/acp/registry.json").read_text())


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

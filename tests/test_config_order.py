# SPDX-License-Identifier: Apache-2.0
"""The order the agent's config choices are offered in is profile DATA.

claude-agent-acp 0.73 sends the models as default, sonnet, fable, opus,
haiku — the order they were added in. A reader choosing one wants them by
capability (Fabio, 2026-09-04). The engine reorders; it never invents,
drops or renames a choice.
"""
import json
from pathlib import Path

from acp_cockpit.core.profiles import ProfileError, load_profile
from tests.helpers import make_session

REAL_MODELS = [                      # captured from ~/.claudiu/records
    {"value": "default", "name": "Default (recommended)"},
    {"value": "sonnet", "name": "Sonnet"},
    {"value": "claude-fable-5-1[1m]", "name": "Fable"},
    {"value": "opus", "name": "Opus"},
    {"value": "haiku", "name": "Haiku"},
]


def _session_new(session, proc, options):
    session.start("/tmp")
    session.on_line(json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "result": {"protocolVersion": 1, "agentCapabilities": {}}}))
    session.on_line(json.dumps({
        "jsonrpc": "2.0", "id": 2,
        "result": {"sessionId": "s", "configOptions": options}}))


def _emitted(sink, config_id="model"):
    for e in sink.events:
        if e.kind == "config_option":
            for opt in e.data["options"]:
                if opt["id"] == config_id:
                    return opt["options"]
    raise AssertionError("no config_option event for " + config_id)


def test_the_shipped_profile_orders_models_by_capability(tmp_path):
    session, proc, sink = make_session(tmp_path)
    _session_new(session, proc, [{"id": "model", "type": "select",
                                  "currentValue": "opus",
                                  "options": REAL_MODELS}])
    assert [o["name"] for o in _emitted(sink)] == [
        "Default (recommended)", "Fable", "Opus", "Sonnet", "Haiku"]


def test_a_versioned_id_is_matched_by_its_family_name(tmp_path):
    # `fable` must keep matching when the version moves on.
    session, proc, sink = make_session(tmp_path)
    models = [dict(m) for m in REAL_MODELS]
    models[2] = {"value": "claude-fable-9-9[4m]", "name": "Fable"}
    _session_new(session, proc, [{"id": "model", "type": "select",
                                  "currentValue": "opus",
                                  "options": models}])
    assert [o["name"] for o in _emitted(sink)][1] == "Fable"


def test_nothing_is_dropped_renamed_or_invented(tmp_path):
    session, proc, sink = make_session(tmp_path)
    _session_new(session, proc, [{"id": "model", "type": "select",
                                  "currentValue": "opus",
                                  "options": REAL_MODELS}])
    assert sorted(json.dumps(o, sort_keys=True) for o in _emitted(sink)) == \
        sorted(json.dumps(o, sort_keys=True) for o in REAL_MODELS)


def test_an_unknown_model_keeps_its_place_after_the_known_ones(tmp_path):
    session, proc, sink = make_session(tmp_path)
    models = REAL_MODELS + [{"value": "brand-new", "name": "Brand New"},
                            {"value": "newer-still", "name": "Newer Still"}]
    _session_new(session, proc, [{"id": "model", "type": "select",
                                  "currentValue": "opus",
                                  "options": models}])
    assert [o["name"] for o in _emitted(sink)][-2:] == ["Brand New",
                                                        "Newer Still"]


def test_a_config_the_profile_says_nothing_about_is_untouched(tmp_path):
    session, proc, sink = make_session(tmp_path)
    effort = [{"value": v, "name": v.title()}
              for v in ("default", "low", "medium", "high", "xhigh", "max")]
    _session_new(session, proc, [{"id": "effort", "type": "select",
                                  "currentValue": "default",
                                  "options": effort}])
    assert _emitted(sink, "effort") == effort


def test_the_order_survives_a_config_option_update(tmp_path):
    session, proc, sink = make_session(tmp_path)
    _session_new(session, proc, [])
    session.on_line(json.dumps({
        "jsonrpc": "2.0", "method": "session/update",
        "params": {"sessionId": "s", "update": {
            "sessionUpdate": "config_option_update",
            "configOptions": [{"id": "model", "type": "select",
                               "currentValue": "opus",
                               "options": REAL_MODELS}]}}}))
    assert [o["name"] for o in _emitted(sink)][:3] == [
        "Default (recommended)", "Fable", "Opus"]


def test_a_malformed_order_is_refused_at_load(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text('id = "x"\nname = "X"\ncommand = ["x"]\n'
                 'install_hint = "n/a"\nenv_scrub = []\n'
                 '[config_option_order]\nmodel = "opus"\n', encoding="utf-8")
    try:
        load_profile(p)
    except ProfileError as exc:
        assert "config_option_order" in str(exc)
    else:
        raise AssertionError("a string instead of a list was accepted")


def test_the_shipped_claude_profile_declares_the_order():
    prof = load_profile(Path("agents/claude.toml"))
    assert prof.config_option_order["model"] == [
        "default", "fable", "opus", "sonnet", "haiku"]

# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
import json

import pytest

from claudiu import config


def test_defaults_when_file_missing(tmp_path):
    cfg, warnings = config.load_config(tmp_path / "nope.json")
    assert cfg["port"] == 8642
    assert cfg["claude_command"] == ["claude"]
    assert warnings == []


def test_file_overrides_and_nested_merge(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"port": 9000, "theme": {"background": "#000000"}}))
    cfg, warnings = config.load_config(p)
    assert cfg["port"] == 9000
    assert cfg["theme"]["background"] == "#000000"
    assert cfg["theme"]["foreground"] == config.DEFAULTS["theme"]["foreground"]
    assert warnings == []


def test_unknown_key_warned_not_dropped(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"tpyo": 1}))
    cfg, warnings = config.load_config(p)
    assert cfg["tpyo"] == 1
    assert any("tpyo" in w for w in warnings)


def test_utf8_bom_is_tolerated(tmp_path):
    # Windows editors (Notepad, PowerShell's Set-Content -Encoding utf8)
    # write a UTF-8 BOM; strict utf-8 decoding rejects it as invalid JSON.
    p = tmp_path / "c.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"port": 9100}).encode("utf-8"))
    cfg, warnings = config.load_config(p)
    assert cfg["port"] == 9100
    assert warnings == []


def test_invalid_json_is_config_error(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{not json")
    with pytest.raises(config.ConfigError):
        config.load_config(p)


def test_bad_port_is_config_error(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"port": "eight"}))
    with pytest.raises(config.ConfigError):
        config.load_config(p)


def test_string_command_normalized(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"claude_command": "claude"}))
    cfg, _ = config.load_config(p)
    assert cfg["claude_command"] == ["claude"]


def test_snippet_and_project_validation(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"snippets": [{"name": "hi", "text": "hello"}],
                             "projects": [{"name": "x", "path": "C:/x"}]}))
    cfg, _ = config.load_config(p)
    assert cfg["snippets"][0]["send"] is False
    assert cfg["projects"][0]["args"] == []
    p.write_text(json.dumps({"snippets": [{"name": "broken"}]}))
    with pytest.raises(config.ConfigError):
        config.load_config(p)


def test_env_var_overrides_path(tmp_path, monkeypatch):
    p = tmp_path / "elsewhere.json"
    monkeypatch.setenv(config.ENV_VAR, str(p))
    assert config.config_path() == p


def test_ensure_config_file(tmp_path):
    p = tmp_path / "sub" / "config.json"
    assert config.ensure_config_file(p) is True
    assert json.loads(p.read_text())["port"] == 8642
    assert config.ensure_config_file(p) is False


def test_non_dict_theme_or_shortcuts_is_config_error(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"theme": "oops"}))
    with pytest.raises(config.ConfigError):
        config.load_config(p)
    p.write_text(json.dumps({"shortcuts": 3}))
    with pytest.raises(config.ConfigError):
        config.load_config(p)

# SPDX-License-Identifier: Apache-2.0
import pytest
from pathlib import Path
from claudiu.core.profiles import AgentProfile, ProfileError, load_profile, load_profiles


def test_claude_profile_loads():
    p = load_profile(Path("agents/claude.toml"))
    assert p.id == "claude"
    assert p.command[0] == "claude-code-acp"
    assert "CLAUDECODE" in p.env_scrub
    assert any("CLAUDE_CODE_" in s for s in p.env_scrub)
    assert p.install_hint.startswith("npm install")
    assert any(c["id"] == "shell-escapes-boundary" for c in p.caveats)
    assert "session/set_model" in p.extensions


def test_missing_field_is_a_profile_error(tmp_path):
    bad = tmp_path / "x.toml"
    bad.write_text('id = "x"\nname = "X"\n', encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(bad)


def test_load_profiles_indexes_by_id(tmp_path):
    (tmp_path / "a.toml").write_text(
        'id = "a"\nname = "A"\ncommand = ["a-cmd"]\n'
        'install_hint = "get a"\nenv_scrub = []\n', encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    profs = load_profiles(tmp_path)
    assert set(profs) == {"a"} and isinstance(profs["a"], AgentProfile)


def test_claude_profile_resolves_the_installed_claude_cli():
    # The adapter bundles its own Claude CLI; the API refused it for a new
    # model on 2026-09-01 ("version 2.1.251 or newer is required"). The
    # profile points the adapter at the user's `claude` when one is on PATH.
    p = load_profile(Path("agents/claude.toml"))
    assert p.env_resolve == {"CLAUDE_CODE_EXECUTABLE": "claude"}


MINIMAL = ('id = "a"\nname = "A"\ncommand = ["a-cmd"]\n'
           'install_hint = "get a"\nenv_scrub = []\n')


def test_env_resolve_defaults_empty(tmp_path):
    f = tmp_path / "a.toml"
    f.write_text(MINIMAL, encoding="utf-8")
    assert load_profile(f).env_resolve == {}


def test_env_resolve_values_must_be_command_names(tmp_path):
    f = tmp_path / "a.toml"
    f.write_text(MINIMAL + "[env_resolve]\nX = 1\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(f)

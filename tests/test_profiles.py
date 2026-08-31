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
    assert any(c["id"] == "model-picker" for c in p.caveats)


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

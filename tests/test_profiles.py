# SPDX-License-Identifier: Apache-2.0
import pytest
from pathlib import Path
from claudiu.core.profiles import AgentProfile, ProfileError, load_profile, load_profiles


def test_claude_profile_loads():
    p = load_profile(Path("agents/claude.toml"))
    assert p.id == "claude"
    assert p.command[0] == "claude-agent-acp"
    assert p.npm_package == "@agentclientprotocol/claude-agent-acp"
    assert "CLAUDECODE" in p.env_scrub
    assert any("CLAUDE_CODE_" in s for s in p.env_scrub)
    assert p.install_hint.startswith("npm install")
    assert any(c["id"] == "shell-escapes-boundary" for c in p.caveats)
    assert "_claude/rateLimit" in p.extensions


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


def test_claude_profile_declares_plan_exit_followups():
    p = load_profile(Path("agents/claude.toml"))
    by_option = {f["option_id"]: f["mode"] for f in p.permission_mode_followups}
    assert by_option["exit-plan-default"] == "default"
    assert by_option["exit-plan-auto"] == "auto"


def test_permission_mode_followups_are_validated(tmp_path):
    f = tmp_path / "a.toml"
    f.write_text(MINIMAL + "[[permission_mode_followups]]\noption_id = 1\n",
                 encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(f)



def test_claude_profile_asks_for_summarized_thinking():
    # The API offers "summarized" or "omitted" for recent models, never raw
    # thinking text. The adapter merges `client_options` into the SDK call
    # (`_meta.claudeCode.options`), so the profile is where the ask lives.
    p = load_profile(Path("agents/claude.toml"))
    assert p.client_options["thinking"] == {"type": "adaptive",
                                            "display": "summarized"}


def test_client_options_default_to_nothing(tmp_path):
    f = tmp_path / "a.toml"
    f.write_text(MINIMAL, encoding="utf-8")
    assert load_profile(f).client_options == {}


def test_client_options_must_be_a_table(tmp_path):
    # Passthrough, so the contents are the agent's business — but the shape
    # is ours: a list would produce an `_meta` the agent cannot read.
    f = tmp_path / "a.toml"
    f.write_text(MINIMAL + 'client_options = ["thinking"]\n', encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(f)


def test_thinking_caveat_describes_summaries_not_redaction():
    # The client now asks for summarized thinking; the old caveat promised
    # empty markers, which would be a lie in the launcher.
    p = load_profile(Path("agents/claude.toml"))
    ids = [c["id"] for c in p.caveats]
    assert "thinking-redacted" not in ids
    text = next(c["text"] for c in p.caveats if c["id"] == "thinking-summary")
    assert "summar" in text.lower()


def test_ask_user_question_caveat_is_retired():
    # The tool works now (the client advertises form elicitation), so the
    # "not loaded" caveat would be a lie. What remains true is that an
    # option's `preview` has no slot in ACP's EnumOption and is not shown.
    p = load_profile(Path("agents/claude.toml"))
    ids = [c["id"] for c in p.caveats]
    assert "no-ask-user-question" not in ids
    text = next(c["text"] for c in p.caveats
                if c["id"] == "ask-question-preview")
    assert "preview" in text.lower()

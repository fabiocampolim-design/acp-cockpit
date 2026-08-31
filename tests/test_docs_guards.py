# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""The suite guards the docs (GITHUBIFY rule 15)."""
import re
from pathlib import Path

from claudiu import VERSION
from claudiu.app import ROUTES
from claudiu.cli import build_parser
from claudiu.config import DEFAULTS

ROOT = Path(__file__).resolve().parents[1]
MANUAL = (ROOT / "docs" / "USER_MANUAL.md").read_text(encoding="utf-8")
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_every_config_key_documented():
    for key in DEFAULTS:
        assert f"`{key}`" in MANUAL, f"config key {key} missing from manual"
        assert f"`{key}`" in AGENTS, f"config key {key} missing from AGENTS.md"


def test_every_shortcut_action_documented():
    for action in DEFAULTS["shortcuts"]:
        assert f"`{action}`" in MANUAL, f"shortcut {action} missing from manual"


def test_every_route_documented():
    for route in ROUTES:
        assert route in MANUAL, f"route {route} missing from manual"
        assert route in AGENTS, f"route {route} missing from AGENTS.md"


def test_every_cli_flag_documented():
    for action in build_parser()._actions:
        for opt in action.option_strings:
            if opt in ("-h",):
                continue
            assert f"`{opt}`" in MANUAL, f"flag {opt} missing from manual"
            assert f"`{opt}`" in AGENTS, f"flag {opt} missing from AGENTS.md"


def test_manual_has_limitations_section():
    assert "## Known limitations" in MANUAL


def test_readme_states_true_check_count(request):
    m = re.search(r"(\d+)-check test suite", README)
    assert m, "README must state the '<N>-check test suite'"
    total = len(request.session.items)
    assert int(m.group(1)) == total, (
        f"README says {m.group(1)} checks, suite has {total}")


def test_version_consistent_with_pyproject():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{VERSION}"' in pyproject


def test_changelog_covers_current_version():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert VERSION in changelog

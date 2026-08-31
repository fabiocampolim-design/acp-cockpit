# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""The suite guards the docs (publication-playbook rule 15)."""
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
    # tests/test_e2e.py is skipped at collection (pytest.importorskip) when
    # playwright is not importable -- CI's `test` job installs `.[test]`
    # only, so that module never becomes a session item there. Counting it
    # here would make the guard's total depend on which matrix cell ran it,
    # so it is excluded from the count and called out separately in the
    # README sentence instead.
    m = re.search(r"(\d+) checks.*?plus one Playwright end-to-end check",
                  " ".join(README.split()))
    assert m, ("README must state '<N> checks ... plus one Playwright "
               "end-to-end check'")
    total = sum(1 for item in request.session.items
                if not item.nodeid.split("::", 1)[0].endswith("test_e2e.py"))
    assert int(m.group(1)) == total, (
        f"README says {m.group(1)} checks, suite has {total} (excl. e2e)")


def test_version_consistent_with_pyproject():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{VERSION}"' in pyproject


def test_changelog_covers_current_version():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert VERSION in changelog


def test_citation_version_matches():
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    m = re.search(r'version:\s*"([^"]+)"', citation)
    assert m, "CITATION.cff must have a version: \"x.y.z\" line"
    assert m.group(1) == VERSION
    assert "license: Apache-2.0" in citation


def test_manual_html_is_built_and_complete():
    html = (ROOT / "docs" / "USER_MANUAL.html").read_text(encoding="utf-8")
    assert "Known limitations" in html
    m = re.search(r"^#\s+(.+)$", MANUAL, re.MULTILINE)
    assert m, "USER_MANUAL.md must have an H1"
    assert m.group(1).strip() in html


DOC_FILES = (
    [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "CHANGELOG.md"]
    + list((ROOT / "docs").glob("**/*.md"))
)


def test_no_personal_paths_in_tracked_docs():
    for path in DOC_FILES:
        text = path.read_text(encoding="utf-8")
        assert "C:\\Users" not in text, f"personal path in {path}"
        assert "C:/Users" not in text, f"personal path in {path}"


def test_no_internal_nomenclature():
    banned = "GITHUB" + "IFY"  # split so this guard doesn't trip on itself
    code_files = list((ROOT / "claudiu").glob("*.py")) + [
        p for p in (ROOT / "tests").glob("*.py") if p.name != "test_docs_guards.py"
    ]
    for path in DOC_FILES + code_files:
        text = path.read_text(encoding="utf-8")
        assert banned not in text, f"internal nomenclature in {path}"

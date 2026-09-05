# SPDX-License-Identifier: Apache-2.0
"""Rule-15 docs guard: the shipped docs stay real and current."""
from pathlib import Path

MANUAL = Path("docs/USER_MANUAL.md").read_text(encoding="utf-8")
AGENTS = Path("AGENTS.md").read_text(encoding="utf-8")
README = Path("README.md").read_text(encoding="utf-8")


# Concepts of the archived v0.1 terminal mirror. None may appear in ANY
# shipped document: docs/TESTPLAN.md described that product in full for a
# week after the pivot while only the manual was checked (review 2026-09-05).
V01_CONCEPTS = ("xterm.js", "pseudo-terminal", "/api/conversation",
                "claudiu.audit", "test_conversation.py", "Terminado")

SHIPPED_DOCS = ("README.md", "AGENTS.md", "CONTRIBUTING.md", "NOTICE",
                "docs/USER_MANUAL.md", "docs/TESTPLAN.md", "docs/DESIGN.md",
                "docs/UI-PROTOCOL.md", "acp_cockpit/agents/PROFILE-SCHEMA.md")


def _docs():
    return {d: Path(d).read_text(encoding="utf-8") for d in SHIPPED_DOCS}


def test_user_manual_matches_the_product():
    assert "Agent Client Protocol" in MANUAL
    assert "python -m acp_cockpit" in MANUAL
    # every CLI flag the parser exposes is in the manual (rule 15)
    import acp_cockpit.__main__ as m
    import re
    flags = re.findall(r'ap\.add_argument\("(--[a-z-]+)"', Path(m.__file__)
                       .read_text(encoding="utf-8"))
    assert len(flags) >= 8, flags
    for flag in flags:
        assert flag in MANUAL, f"CLI flag undocumented: {flag}"


def test_no_shipped_doc_describes_the_archived_product():
    for name, text in _docs().items():
        if name == "docs/DESIGN.md":
            continue            # the design account names what was rejected
        for gone in V01_CONCEPTS:
            assert gone not in text, f"stale v0.1 concept in {name}: {gone}"


def test_the_manual_has_no_duplicate_sections():
    import re
    heads = re.findall(r"^## (.+)$", MANUAL, re.M)
    dupes = {h for h in heads if heads.count(h) > 1}
    assert not dupes, f"duplicate manual sections: {dupes}"


def test_the_project_is_named_acp_cockpit_and_the_screen_name_is_only_that():
    # Fabio, 2026-09-05: ClaudIU only for what the screen shows. A document
    # that means the repository says acp-cockpit; the old developer commands
    # and the "working name" wording are gone.
    docs = _docs()
    for name in ("README.md", "AGENTS.md", "CONTRIBUTING.md", "NOTICE"):
        assert "acp-cockpit" in docs[name], f"{name} never names the project"
    for name, text in docs.items():
        assert "pyflakes claudiu" not in text, f"{name}: stale package name"
        assert "working name" not in text, f"{name}: 'working name' is over"
        assert "ClaudIU 0." not in text, f"{name}: the project has no ClaudIU version"
    assert docs["NOTICE"].startswith("acp-cockpit")
    assert docs["CONTRIBUTING.md"].startswith("# Contributing to acp-cockpit")
    # where ClaudIU still appears, the line is about the name on screen
    for name, text in docs.items():
        for line in text.splitlines():
            if "ClaudIU" in line and name != "docs/DESIGN.md":
                low = line.lower()
                assert any(w in low for w in ("name", "shows", "calls itself",
                                                "screen", "shipped as")), \
                    f"{name}: ClaudIU used for the project, not the screen name: {line!r}"


def test_docs_name_the_packaged_paths_not_the_old_top_level_ones():
    docs = _docs()
    for name, text in docs.items():
        for old in ("`agents/claude.toml`", "`agents/PROFILE-SCHEMA.md`",
                    "`vendor/acp/", "`agents/local-*.toml`"):
            assert old not in text, f"{name}: pre-packaging path {old}"


def test_the_testplan_covers_the_current_safety_surface():
    plan = Path("docs/TESTPLAN.md").read_text(encoding="utf-8")
    for must in ("session record", "raw_ref", "drift", "vendor_update",
                 "auto-rejected", "withdrawn", "job object", "Versions",
                 "fresh venv"):
        assert must in plan, f"TESTPLAN.md does not cover {must!r}"


def test_agents_md_states_the_layer_rules():
    assert "stdlib only" in AGENTS
    assert "UI-PROTOCOL.md" in AGENTS
    assert "git add -A" in AGENTS   # the prohibition is written down


def count_checks() -> int:
    """Every `def test_*` under tests/, minus the opt-in contract tier, read
    from the source. The guard used to run `pytest --collect-only` and
    compare: a CI job without Playwright collected 36 fewer tests than the
    laptop and the guard was red on every CI run from the first push
    (review 2026-09-05). A static count is the same on every machine.
    The suite uses no parametrize, and the guard says so, so the count
    stays a count of functions."""
    import re
    total = 0
    for path in sorted(Path("tests").rglob("test_*.py")):
        if "contract" in path.parts:
            continue                       # documented separately, opt-in
        src = path.read_text(encoding="utf-8")
        assert "@pytest.mark.param" + "etrize" not in src,             f"{path}: parametrize would make the static count wrong"
        total += len(re.findall(r"^\s*def test_\w+\(", src, re.M))
    return total


def test_readme_check_count_is_current():
    import re
    m = re.search(r"Verified by (\d+) checks", README)
    assert m, "README lost its check-count line"
    counted = count_checks()
    assert int(m.group(1)) == counted, (
        f"README says {m.group(1)} checks; tests/ defines {counted} "
        f"(plus the opt-in contract tier) — update README")


def test_profile_schema_documents_every_field():
    # A profile knob nobody documented is a knob nobody can use: the schema
    # doc is the contract for adding an agent without touching core/.
    import dataclasses
    from acp_cockpit.core.profiles import AgentProfile
    schema = Path("acp_cockpit/agents/PROFILE-SCHEMA.md").read_text(encoding="utf-8")
    for f in dataclasses.fields(AgentProfile):
        assert f"`{f.name}`" in schema, \
            f"profile field {f.name} missing from agents/PROFILE-SCHEMA.md"

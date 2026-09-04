# SPDX-License-Identifier: Apache-2.0
"""Rule-15 docs guard: the shipped docs stay real and current."""
from pathlib import Path

MANUAL = Path("docs/USER_MANUAL.md").read_text(encoding="utf-8")
AGENTS = Path("AGENTS.md").read_text(encoding="utf-8")
README = Path("README.md").read_text(encoding="utf-8")


def test_user_manual_matches_the_product():
    # 0.2 is an ACP client; the manual must not describe the archived
    # terminal-mirror app.
    assert "Agent Client Protocol" in MANUAL
    assert "python -m claudiu" in MANUAL
    for gone in ("xterm.js", "pseudo-terminal"):
        assert gone not in MANUAL, f"stale v0.1 concept in manual: {gone}"
    for flag in ("--port", "--profiles", "--records", "--no-drift-online"):
        assert flag in MANUAL, f"CLI flag undocumented: {flag}"


def test_agents_md_states_the_layer_rules():
    assert "stdlib only" in AGENTS
    assert "UI-PROTOCOL.md" in AGENTS
    assert "git add -A" in AGENTS   # the prohibition is written down


def test_readme_check_count_is_current():
    # "Verified by N checks" must match the FULL suite (this test included).
    import re
    m = re.search(r"Verified by (\d+) checks", README)
    assert m, "README lost its check-count line"
    import subprocess
    import sys
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
        capture_output=True, text=True, timeout=120).stdout
    m2 = re.search(r"(\d+) tests collected", out)
    assert m2, f"could not count tests: {out[-200:]}"
    collected = int(m2.group(1))
    # the opt-in contract test is counted in collection but documented
    # separately in the README
    assert int(m.group(1)) == collected - 1, (
        f"README says {m.group(1)} checks; suite collects {collected} "
        f"(minus 1 opt-in contract test) — update README")


def test_profile_schema_documents_every_field():
    # A profile knob nobody documented is a knob nobody can use: the schema
    # doc is the contract for adding an agent without touching core/.
    import dataclasses
    from claudiu.core.profiles import AgentProfile
    schema = Path("agents/PROFILE-SCHEMA.md").read_text(encoding="utf-8")
    for f in dataclasses.fields(AgentProfile):
        assert f"`{f.name}`" in schema, \
            f"profile field {f.name} missing from agents/PROFILE-SCHEMA.md"

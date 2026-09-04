# SPDX-License-Identifier: Apache-2.0
"""The version and the citation are one fact, stated in three files."""
import re
import tomllib
from pathlib import Path

import claudiu

CITATION = Path("CITATION.cff").read_text(encoding="utf-8")


def test_version():
    assert claudiu.__version__.startswith("0.3.0")


def test_pyproject_and_citation_state_the_same_version():
    # A CITATION.cff left at an old version cites software nobody can get:
    # it went stale through 0.2.0 unnoticed because nothing checked it.
    pyproject = tomllib.loads(
        Path("pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == claudiu.__version__
    m = re.search(r'^version:\s*"([^"]+)"', CITATION, re.M)
    assert m, "CITATION.cff has no version"
    assert m.group(1) == claudiu.__version__


def test_citation_describes_the_current_product():
    # 0.2 is an ACP client; the citation must not still advertise the
    # archived v0.1 terminal mirror.
    assert "Agent Client Protocol" in CITATION
    for gone in ("xterm.js", "pseudo-terminal"):
        assert gone not in CITATION, f"stale v0.1 concept in CITATION.cff: {gone}"

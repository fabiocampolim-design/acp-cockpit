# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""Licence and disclaimer guards (GITHUBIFY rule 17)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_license_clauses_present():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND" in text
    assert "Limitation of Liability" in text


def test_readme_disclaimer_present():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    licence_pos = readme.find("## Licence")
    assert licence_pos != -1, "README needs a '## Licence' section"
    tail = readme[licence_pos:]
    assert "### Disclaimer" in tail
    assert re.search(r"without warrant", tail, re.IGNORECASE)
    assert re.search(r"liable", tail, re.IGNORECASE)
    assert "not affiliated" in tail


def test_spdx_headers_everywhere():
    sources = list((ROOT / "claudiu").glob("*.py"))
    sources += list((ROOT / "tests").glob("*.py"))
    sources += [ROOT / "claudiu" / "static" / n
                for n in ("app.js", "ui.js", "keys.js")]
    assert len(sources) >= 10
    for src in sources:
        head = src.read_text(encoding="utf-8")[:300]
        assert "SPDX-License-Identifier: Apache-2.0" in head, src.name

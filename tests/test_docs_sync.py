# SPDX-License-Identifier: Apache-2.0
import re
from pathlib import Path
from acp_cockpit.core.events import KINDS

DOC = Path("docs/UI-PROTOCOL.md").read_text(encoding="utf-8")


def test_every_event_kind_documented():
    for kind in KINDS:
        assert f"`{kind}`" in DOC, f"event kind {kind} missing from UI-PROTOCOL.md"


def test_every_ws_command_documented():
    # ws.py handles seven: set_model and set_config_option were missing from
    # this list, so a drift between the two could pass unnoticed (hostile
    # Fable 5 review, 2026-09-19 -- they happened to already be documented,
    # but nothing was checking that).
    for cmd in ("prompt", "cancel", "set_mode", "set_model",
                "set_config_option", "permission", "elicitation"):
        assert f'"cmd": "{cmd}"' in DOC


def test_every_rest_route_documented():
    for route in ("/api/profiles", "/api/sessions", "/api/drift",
                  "/api/dirs", "/api/settings", "/ws/sessions/", "/archive"):
        assert route in DOC


def test_every_drift_flag_shape_documented():
    """`app.js` branches on these exact substrings (`checkVersions`,
    `describeVersions`). None of them appeared in the doc that is supposed
    to be the sole contract the View consumes (hostile Fable 5 review,
    2026-09-19)."""
    section = DOC.split("### `GET /api/drift`")[1].split("## 3.")[0]
    for flag in ("adapter-behind", "schema-behind", "adapter-unknown",
                "schema-unknown", "drift-check-failed"):
        assert flag in section, f"{flag} missing from the /api/drift doc"
    assert "adapter_installed_reason" in section


# --- what the adapter discards: one fact, five files ------------------------
#
# The first version of this check (2026-09-20) matched the literal phrase
# "0.73 through X" and compared nothing else. An adversarial review (Fable
# 5.1, rules/14) showed it green on four of five realistic drifts -- a
# reworded range, an en-dash range, a range not starting at 0.73, and a
# stale re-check DATE all passed -- and found that while it was being
# written `docs/UI-PROTOCOL.md` still said "0.73-0.75.1". So: no phrase
# matching. Every SENTENCE that claims the adapter discards / drops /
# does not forward something is scanned, and every adapter version and
# every date in it must be one of the facts the shipped profile states.

_ADAPTER_CLAIM = re.compile(
    r"discard|drops?\b|dropped|never send|neither|"
    r"(?:do|does) not forward|nor forwards", re.I)
# adapter releases only: 0.16.2 (the deprecated Zed package) upward. This
# keeps the product's own 0.5.1 and the pty mirror's 0.1 out of the scan.
_VERSION = re.compile(r"\b0\.(\d+)(?:\.(\d+))?\b")
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_CLAIM_FILES = ["README.md", "docs/USER_MANUAL.md", "docs/UI-PROTOCOL.md",
                "docs/DESIGN.md", "acp_cockpit/ui/web/style.css",
                "acp_cockpit/ui/web/app.js", "acp_cockpit/ui/web/index.html"]
# CHANGELOG.md, docs/watch/ and docs/TESTPLAN.md are dated records of what
# was true on a day: they MUST keep their old versions, so they are not
# scanned. docs/DESIGN.md's ACPUPSTREAM sentence is scanned but says
# nothing about discarding, so its "re-checked against 0.75.1 on
# 2026-09-05" (six of seven findings, still only checked that far) stays
# honest instead of being swept up by a blanket re-stamp.


def _sentences(text):
    return re.split(r"(?<=[.!?])\s+", " ".join(text.split()))


def _adapter_versions(sentence):
    out = set()
    for m in _VERSION.finditer(sentence):
        if int(m.group(1)) >= 16:          # 0.16.2 and up are the adapter's
            out.add(m.group(0))
    return out


def test_what_the_adapter_discards_says_one_version_and_one_date():
    """The shipped profile is the source of truth -- it is the copy the user
    reads in the launcher -- and every other file that makes the same claim
    must name the same adapter version and the same re-check date."""
    profile = Path("acp_cockpit/agents/claude.toml").read_text(encoding="utf-8")
    caveat = [s for s in _sentences(profile)
              if "promptSuggestions" in s and _ADAPTER_CLAIM.search(s)]
    assert len(caveat) == 1, "the profile's prompt-suggestion caveat moved"
    versions = _adapter_versions(caveat[0])
    dates = set(_DATE.findall(caveat[0]))
    assert len(dates) == 1, f"the profile caveat needs one date, got {dates}"
    current, date = max(versions, key=lambda v: tuple(map(int, v.split(".")))), \
        dates.pop()
    # the lower bound of the range is a historical fact and stays
    allowed = versions | {"0.73", "0.73.0"}

    wrong = []
    for name in _CLAIM_FILES:
        for sentence in _sentences(Path(name).read_text(encoding="utf-8")):
            if not _ADAPTER_CLAIM.search(sentence):
                continue
            seen = _adapter_versions(sentence)
            if not seen:
                continue
            for bad in sorted(seen - allowed):
                wrong.append(f"{name}: names adapter {bad}, not {current}"
                             f" -- {sentence[:90]}")
            for bad in sorted(set(_DATE.findall(sentence)) - {date}):
                wrong.append(f"{name}: re-checked {bad}, not {date}"
                             f" -- {sentence[:90]}")
    assert not wrong, ("the adapter-discards claim disagrees with the shipped "
                       "profile:\n  " + "\n  ".join(wrong))

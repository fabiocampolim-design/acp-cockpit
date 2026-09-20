# SPDX-License-Identifier: Apache-2.0
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


def test_the_adapter_version_range_agrees_everywhere():
    """The prompt-suggestion caveat names a version range in three places:
    README, the user manual and the shipped profile that carries it into the
    UI. `8a1c9df` re-verified the range and updated the two documents but not
    the profile, which went on telling the user "0.73 through 0.75.1" while
    the docs said 0.79.0 -- the kind of drift only a check catches (found on
    the 0.79.0 upgrade, 2026-09-20)."""
    import re

    sources = [Path("README.md"), Path("docs/USER_MANUAL.md")]
    sources += sorted(Path("acp_cockpit/agents").glob("*.toml"))
    found = {}
    for path in sources:
        text = " ".join(path.read_text(encoding="utf-8").split())
        for match in re.finditer(r"0\.73 through (?:at least )?(\d+\.\d+\.\d+)",
                                 text):
            found.setdefault(match.group(1), []).append(path.as_posix())
    assert found, "no adapter version range found -- has the wording changed?"
    assert len(found) == 1, (
        "the adapter caveat names different upper versions: "
        + "; ".join(f"{v} in {', '.join(w)}" for v, w in sorted(found.items())))

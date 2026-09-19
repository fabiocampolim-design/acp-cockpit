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

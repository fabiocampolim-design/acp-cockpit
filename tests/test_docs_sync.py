from pathlib import Path
from claudiu.core.events import KINDS

DOC = Path("docs/UI-PROTOCOL.md").read_text(encoding="utf-8")


def test_every_event_kind_documented():
    for kind in KINDS:
        assert f"`{kind}`" in DOC, f"event kind {kind} missing from UI-PROTOCOL.md"


def test_every_ws_command_documented():
    for cmd in ("prompt", "cancel", "set_mode", "permission"):
        assert f'"cmd": "{cmd}"' in DOC


def test_every_rest_route_documented():
    for route in ("/api/profiles", "/api/sessions", "/api/drift",
                  "/ws/sessions/"):
        assert route in DOC

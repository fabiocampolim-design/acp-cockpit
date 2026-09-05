# SPDX-License-Identifier: Apache-2.0
"""The name this client shows in its own interface.

The project, the package and the documentation are `acp-cockpit`. What the
running client *calls itself* on screen is a separate, configurable thing —
shipped as `ClaudIU`, changeable to whatever the person running it wants,
without touching a line of code.

Resolution order, first hit wins:

1. `ACP_COCKPIT_UINAME` in the environment;
2. `ACP_COCKPIT_UINAME` in the config file (`--ui-name-file`, else
   `uiname.toml` beside the package, else `~/.acp-cockpit/uiname.toml`);
3. the built-in default.

The result is trimmed to `MAX_LEN` characters, because it goes in a browser
tab, a heading and a dialog title, and a long name overflows all three.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

KEY = "ACP_COCKPIT_UINAME"
DEFAULT = "ClaudIU"
MAX_LEN = 15
ELLIPSIS = "…"

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _candidates(explicit=None):
    if explicit:
        yield Path(explicit)
        return
    yield _PACKAGE_ROOT / "uiname.toml"
    yield Path.home() / ".acp-cockpit" / "uiname.toml"


def _from_file(explicit=None) -> str | None:
    for path in _candidates(explicit):
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue          # unreadable or malformed: fall through, never fail
        value = raw.get(KEY)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def truncate(name: str, max_len: int = MAX_LEN) -> str:
    """Fit a name in the boxes it has to sit in.

    A name longer than the limit keeps its first `max_len - 1` characters
    and gains an ellipsis, so it is visibly cut rather than silently wrong.
    """
    name = " ".join(name.split())          # no newlines in a <title>
    if len(name) <= max_len:
        return name
    return name[:max_len - 1].rstrip() + ELLIPSIS


def ui_name(explicit_file=None, env=None) -> str:
    """The name to show, already fitted. Never raises: a broken config file
    or a blank value falls back to the default rather than leaving the
    interface nameless."""
    env = os.environ if env is None else env
    value = env.get(KEY)
    if not (isinstance(value, str) and value.strip()):
        value = _from_file(explicit_file)
    if not (isinstance(value, str) and value.strip()):
        value = DEFAULT
    return truncate(value.strip())

# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""One human-editable JSON config file with env-var path override."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

ENV_VAR = "CLAUDIU_CONFIG"

DEFAULTS: dict = {
    "port": 8642,
    "claude_command": ["claude"],
    "replay_chunks": 2000,
    "scrollback_lines": 10000,
    "font_size": 16,
    "font_family": "Consolas, 'Cascadia Mono', monospace",
    "theme": {
        "background": "#14161a", "foreground": "#c9c4b8",
        "cursor": "#c9c4b8", "selectionBackground": "#3a3f4b",
        "black": "#14161a", "red": "#c8746e", "green": "#8aa87a",
        "yellow": "#c2a86c", "blue": "#7a93b8", "magenta": "#a884a8",
        "cyan": "#7aa8a0", "white": "#c9c4b8",
        "brightBlack": "#565e6a", "brightRed": "#d99790",
        "brightGreen": "#a5bf97", "brightYellow": "#d4bf8e",
        "brightBlue": "#9cb2d1", "brightMagenta": "#c0a2c0",
        "brightCyan": "#9cc2bb", "brightWhite": "#e0dbd0",
    },
    "shortcuts": {
        "tab_1": "Alt+1", "tab_2": "Alt+2", "tab_3": "Alt+3",
        "tab_4": "Alt+4", "tab_5": "Alt+5", "tab_6": "Alt+6",
        "tab_7": "Alt+7", "tab_8": "Alt+8", "tab_9": "Alt+9",
        "tab_prev": "Alt+ArrowLeft", "tab_next": "Alt+ArrowRight",
        "new_session": "Alt+t", "close_tab": "Alt+w",
        "font_bigger": "Alt+=", "font_smaller": "Alt+-", "font_reset": "Alt+0",
        "search": "Ctrl+Shift+f", "snippet_palette": "Ctrl+k",
    },
    "projects": [],
    "snippets": [],
}


class ConfigError(Exception):
    """Human-readable configuration problem."""


def config_path() -> Path:
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env)
    return Path.home() / ".claudiu" / "config.json"


def ensure_config_file(path: Path) -> bool:
    path = Path(path)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(DEFAULTS, indent=2), encoding="utf-8")
    return True


def _merge(base: dict, override: dict, prefix: str, warnings: list) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if key not in base:
            warnings.append(f"unknown config key: {prefix}{key} (kept as-is)")
            out[key] = value
        elif isinstance(base[key], dict) and isinstance(value, dict):
            out[key] = _merge(base[key], value, f"{prefix}{key}.", warnings)
        else:
            out[key] = value
    return out


def _validate(cfg: dict) -> None:
    if not isinstance(cfg["port"], int) or not 1 <= cfg["port"] <= 65535:
        raise ConfigError("port must be an integer between 1 and 65535")
    if isinstance(cfg["claude_command"], str):
        cfg["claude_command"] = [cfg["claude_command"]]
    if (not isinstance(cfg["claude_command"], list) or not cfg["claude_command"]
            or not all(isinstance(p, str) for p in cfg["claude_command"])):
        raise ConfigError("claude_command must be a non-empty list of strings")
    for key in ("replay_chunks", "scrollback_lines", "font_size"):
        if not isinstance(cfg[key], int) or cfg[key] <= 0:
            raise ConfigError(f"{key} must be a positive integer")
    for key in ("theme", "shortcuts"):
        if not isinstance(cfg[key], dict):
            raise ConfigError(f"{key} must be an object (JSON dict)")
    for i, proj in enumerate(cfg["projects"]):
        if not isinstance(proj, dict) or "name" not in proj or "path" not in proj:
            raise ConfigError(f"projects[{i}] needs 'name' and 'path'")
        proj.setdefault("args", [])
    for i, snip in enumerate(cfg["snippets"]):
        if not isinstance(snip, dict) or "name" not in snip or "text" not in snip:
            raise ConfigError(f"snippets[{i}] needs 'name' and 'text'")
        snip.setdefault("send", False)


def load_config(path=None) -> tuple[dict, list]:
    path = Path(path) if path is not None else config_path()
    warnings: list = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"{path} must contain a JSON object")
        cfg = _merge(DEFAULTS, data, "", warnings)
    else:
        cfg = copy.deepcopy(DEFAULTS)
    _validate(cfg)
    return cfg, warnings

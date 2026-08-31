# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""Recently launched folders, remembered across restarts and browsers.

A small JSON list next to the config file (``~/.claudiu/recent.json``),
newest first. The launcher offers it in the "any folder" box so a folder
you have opened before is one click away even when it has no Claude Code
history yet (so the resume scanner would not list it).

Same robustness rule as the rest of the app: a missing or corrupt file
reads as an empty list and never raises.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def recent_path(config_dir) -> Path:
    return Path(config_dir) / "recent.json"


def load_recent(config_dir) -> list:
    path = recent_path(config_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            out.append({"path": item["path"],
                        "name": item.get("name") or Path(item["path"]).name,
                        "last": item.get("last", 0),
                        "count": item.get("count", 1)})
    return out


def add_recent(config_dir, path: str, name=None, cap: int = 15) -> list:
    """Record a launch. Moves an existing entry to the front, bumps its
    count, and trims to ``cap``. Returns the new list."""
    resolved = str(Path(path).resolve())
    items = [i for i in load_recent(config_dir)
             if str(Path(i["path"]).resolve()) != resolved]
    prev = next((i for i in load_recent(config_dir)
                 if str(Path(i["path"]).resolve()) == resolved), None)
    items.insert(0, {"path": path,
                     "name": name or Path(path).name or path,
                     "last": time.time(),
                     "count": (prev["count"] + 1) if prev else 1})
    items = items[:max(1, cap)]
    write_recent(config_dir, items)
    return items


def write_recent(config_dir, items: list) -> None:
    path = recent_path(config_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, indent=2), encoding="utf-8")
    except OSError:
        pass  # a launcher convenience must never break launching

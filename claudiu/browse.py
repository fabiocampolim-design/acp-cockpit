# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""Filesystem browsing for the launcher's "any folder" picker.

Only directories are listed (you launch ``claude`` in a directory), and
only enough to navigate: a level's sub-directories plus its parent. On
Windows an empty path lists the drive roots. Everything is read-only
except :func:`make_dir`, which backs the launcher's "New folder" button.

Robustness: an unreadable directory yields an empty listing with an
``error`` note, never an exception.
"""
from __future__ import annotations

import os
import string
from pathlib import Path


def _drives() -> list:
    out = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if os.path.isdir(root):
            out.append({"name": root, "path": root})
    return out


def list_dirs(path=None) -> dict:
    """Sub-directories of ``path`` (plus its parent), for the picker.

    ``path`` None/empty -> drive roots on Windows, ``/`` elsewhere. The
    result is ``{path, parent, dirs, error}`` where ``dirs`` is a list of
    ``{name, path}`` sorted case-insensitively and ``parent`` is None at a
    top level.
    """
    if not path:
        if os.name == "nt":
            return {"path": "", "parent": None, "dirs": _drives(), "error": None}
        path = "/"
    p = Path(path)
    try:
        p = p.resolve()
    except OSError:
        return {"path": str(path), "parent": None, "dirs": [], "error": "bad path"}
    if not p.is_dir():
        return {"path": str(p), "parent": None, "dirs": [],
                "error": "not a directory"}
    if p.parent != p:
        parent = str(p.parent)          # ordinary directory
    elif os.name == "nt":
        parent = ""                     # drive root -> step back to drive list
    else:
        parent = None                   # POSIX root -> nowhere above
    dirs, error = [], None
    try:
        for entry in os.scandir(p):
            try:
                if entry.is_dir() and not entry.name.startswith("."):
                    dirs.append({"name": entry.name, "path": entry.path})
            except OSError:
                continue  # a single unstatable entry must not drop the rest
    except OSError:
        error = "permission denied"
    dirs.sort(key=lambda d: d["name"].lower())
    return {"path": str(p), "parent": parent, "dirs": dirs, "error": error}


def make_dir(parent: str, name: str) -> dict:
    """Create ``name`` under ``parent`` (one level). Returns ``{path}`` on
    success or ``{error}``. Refuses a name with path separators."""
    name = (name or "").strip()
    if not name or any(sep in name for sep in ("/", "\\")) or name in (".", ".."):
        return {"error": "invalid folder name"}
    base = Path(parent)
    if not base.is_dir():
        return {"error": "parent folder does not exist"}
    target = base / name
    try:
        target.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        return {"error": "a folder with that name already exists"}
    except OSError as exc:
        return {"error": f"could not create folder: {exc}"}
    return {"path": str(target.resolve())}

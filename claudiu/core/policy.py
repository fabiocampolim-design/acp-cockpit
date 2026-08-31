# SPDX-License-Identifier: Apache-2.0
"""Per-session path boundary for agent-initiated fs access."""
from __future__ import annotations

import os
from pathlib import Path


def _norm(p: Path) -> str:
    return os.path.normcase(str(p))


class PathPolicy:
    def __init__(self, root: Path):
        self._root = Path(root).resolve()
        self._grants: list[Path] = []

    def grant(self, path: Path) -> None:
        self._grants.append(Path(path).resolve())

    def _inside(self, target: str, base: Path) -> bool:
        b = _norm(base)
        return target == b or target.startswith(b + os.sep)

    def allowed(self, path: str) -> bool:
        if not os.path.isabs(path):
            return False
        target = _norm(Path(path).resolve())
        return any(self._inside(target, base)
                   for base in (self._root, *self._grants))

    def describe(self) -> dict:
        return {"root": str(self._root),
                "grants": [str(g) for g in self._grants]}

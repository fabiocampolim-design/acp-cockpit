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

    def _inside(self, target: str, base: Path) -> bool:
        b = _norm(base)
        return target == b or target.startswith(b + os.sep)

    def allowed(self, path: str) -> bool:
        if not os.path.isabs(path):
            return False
        target = _norm(Path(path).resolve())
        return self._inside(target, self._root)

    def describe(self) -> dict:
        return {"root": str(self._root)}

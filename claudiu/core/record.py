"""Append-only JSONL flight recorder. Raw frames verbatim, before interpretation."""
from __future__ import annotations

import io
import json
from pathlib import Path

from .events import now_iso


class Recorder:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lineno = 0
        if self._path.exists():
            with io.open(self._path, "r", encoding="utf-8") as f:
                self._lineno = sum(1 for _ in f)
        self._fh = io.open(self._path, "a", encoding="utf-8")

    def append(self, entry: dict) -> int:
        entry = {"t": now_iso(), **entry}
        self._fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._fh.flush()
        self._lineno += 1
        return self._lineno

    def replay(self):
        with io.open(self._path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                yield i, json.loads(line)

    def close(self) -> None:
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

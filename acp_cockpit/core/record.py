# SPDX-License-Identifier: Apache-2.0
"""Append-only JSONL flight recorder. Raw frames verbatim, before interpretation."""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

from .events import now_iso


def prune(directory, keep_days: int) -> list[str]:
    """Delete `*.jsonl` records last modified more than `keep_days` days ago.

    Records hold the full conversation, and nothing used to remove them
    (7.9 MB in a week of daily use — audit 2026-09-04). `keep_days <= 0`
    keeps everything, which is the default: deleting a transcript is the
    owner's decision, so the policy exists, is documented and is opt-in.
    Returns the names removed.
    """
    directory = Path(directory)
    if keep_days <= 0 or not directory.is_dir():
        return []
    cutoff = time.time() - keep_days * 86400
    removed = []
    for path in sorted(directory.glob("*.jsonl")):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed.append(path.name)
        except OSError:
            continue                 # in use, or not ours to delete
    return removed


class Recorder:
    def __init__(self, path: Path, ephemeral: bool = False):
        """`ephemeral`: the file is removed on close. For the throwaway
        adapter that answers `session/list` — nine probe records out of fifty
        files in the records directory said nothing anyone would read
        (review 2026-09-05). A real session is never ephemeral."""
        self._path = Path(path)
        self._ephemeral = ephemeral
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lineno = 0
        if self._path.exists():
            with io.open(self._path, "r", encoding="utf-8") as f:
                self._lineno = sum(1 for _ in f)
        self._fh = io.open(self._path, "a", encoding="utf-8")

    def append(self, entry: dict) -> int | None:
        if self._fh.closed:
            return None          # after close(): nothing left to write to
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
        if self._ephemeral:
            try:
                self._path.unlink()
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

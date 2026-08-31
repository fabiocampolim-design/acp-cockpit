# SPDX-License-Identifier: Apache-2.0
"""Typed engine events — the only thing the View ever renders."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

KINDS = frozenset({
    "session_state",       # {"state": "starting"|"ready"|"turn"|"failed"|"closed", "detail": str}
    "message_chunk",       # {"role": "agent"|"user"|"thought", "text": str}
    "tool_call",           # raw ACP toolCall passthrough
    "tool_call_update",
    "plan",
    "commands",            # {"commands": [...]}
    "mode",                # {"current": str|None, "available": [...]}
    "permission_request",  # {"request": int, "tool_call": dict, "options": [...]}
    "permission_resolved", # {"request": int, "option": str|None, "source": "user"|"failsafe"}
    "fs_request",          # {"op": "read"|"write", "path": str, "allowed": bool}
    "turn_ended",          # {"stop_reason": str}
    "anomaly",             # {"category": str, "detail": str}
    "drift",               # {"flags": [str]}
    "unrecognized",        # {"why": str, "frame": dict}
})


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class Event:
    kind: str
    session: str
    seq: int
    ts: str
    data: dict
    raw_ref: int | None = None


def make_event(kind: str, session: str, seq: int, data: dict,
               raw_ref: int | None = None) -> Event:
    if kind not in KINDS:
        raise ValueError(f"unknown event kind: {kind!r}")
    return Event(kind, session, seq, now_iso(), dict(data), raw_ref)


def to_wire(event: Event) -> str:
    return json.dumps({
        "kind": event.kind, "session": event.session, "seq": event.seq,
        "ts": event.ts, "data": event.data, "raw_ref": event.raw_ref,
    }, ensure_ascii=False)

# SPDX-License-Identifier: Apache-2.0
"""WebSocket bridge: EventSink -> browser, browser commands -> AcpSession."""
from __future__ import annotations

import json

import tornado.websocket

from ..core.events import now_iso, to_wire
from .auth import COOKIE_NAME, origin_ok


class BufferedSink:
    """What a browser sees when it attaches or comes back after a drop.

    Bounded. A pinned server runs for days, and every event of every session
    used to be kept for the life of the process and re-sent in full on every
    attach (audit 2026-09-04). The JSONL record is the lossless copy; this
    buffer is only the convenience that lets a late or returning browser
    catch up, so it keeps the most recent `cap` events and SAYS SO when a
    client asks for a range it no longer holds.
    """

    CAP = 2000

    def __init__(self, sid: str | None = None, cap: int | None = None):
        self.sid = sid
        self.cap = cap or self.CAP
        self._buffer: list[tuple[int, str]] = []
        self._dropped_through = 0        # highest seq no longer retained
        self._handlers: list = []

    def emit(self, event) -> None:
        wire = to_wire(event)
        self._buffer.append((event.seq, wire))
        while len(self._buffer) > self.cap:
            seq, _ = self._buffer.pop(0)
            self._dropped_through = seq
        for h in list(self._handlers):
            try:
                h.write_message(wire)
            except tornado.websocket.WebSocketClosedError:
                self._handlers.remove(h)

    def attach(self, handler, after: int = 0) -> None:
        """Replay what this client has not seen. `after` is the last `seq` it
        already holds, so a reconnecting View gets the gap and not a second
        copy of the conversation."""
        if self._dropped_through > after:
            handler.write_message(to_wire_truncated(
                self.sid, after + 1, self._dropped_through))
        for seq, wire in self._buffer:
            if seq > after:
                handler.write_message(wire)
        self._handlers.append(handler)

    def detach(self, handler) -> None:
        if handler in self._handlers:
            self._handlers.remove(handler)


def to_wire_truncated(sid, first: int, last: int) -> str:
    """`seq` is set to the last dropped event, so the client's cursor lands
    exactly where the replay resumes."""
    return json.dumps({"kind": "replay_truncated", "session": sid,
                       "seq": last, "ts": now_iso(),
                       "data": {"from_seq": first, "to_seq": last},
                       "raw_ref": None})


def to_wire_error(detail: str) -> str:
    return json.dumps({"kind": "anomaly", "session": None, "seq": -1,
                       "ts": None, "data": {"category": "command-error",
                                            "detail": detail},
                       "raw_ref": None})


class SessionWS(tornado.websocket.WebSocketHandler):
    def initialize(self, manager, auth):
        self._manager = manager
        self._auth = auth
        self._entry = None

    def check_origin(self, origin: str) -> bool:
        # A WebSocket has no CORS preflight to fall back on, so this check
        # is the whole defence: our own origin, port included (see
        # `auth.origin_ok`).
        return origin_ok(origin, self.request.host)

    def open(self, sid):
        if not self._auth.verify(self.get_cookie(COOKIE_NAME)):
            self.close(4403, "auth")
            return
        self._entry = self._manager.get(sid)
        if self._entry is None:
            self.close(4404, "no such session")
            return
        try:
            after = int(self.get_query_argument("after", "0"))
        except ValueError:
            after = 0
        self._entry.sink.attach(self, after=max(0, after))

    def on_message(self, message):
        if self._entry is None:
            return
        session = self._entry.session
        try:
            msg = json.loads(message)
            cmd = msg.get("cmd")
            if cmd == "prompt":
                session.prompt(msg["text"])
            elif cmd == "cancel":
                session.cancel()
            elif cmd == "set_mode":
                session.set_mode(msg["mode"])
            elif cmd == "set_model":
                session.set_model(msg["model"])
            elif cmd == "set_config_option":
                session.set_config_option(msg["config"], msg["value"])
            elif cmd == "permission":
                session.answer_permission(msg["request"], msg["option"])
            elif cmd == "elicitation":
                session.answer_elicitation(msg["request"], msg["action"],
                                           msg.get("content"))
            else:
                self.write_message(to_wire_error(f"unknown cmd {cmd!r}"))
        except Exception as exc:  # surfaced, never silent
            self.write_message(to_wire_error(str(exc)))

    def on_close(self):
        if self._entry is not None:
            self._entry.sink.detach(self)

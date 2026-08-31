"""ACP client session state machine. Sans-I/O: lines in, lines out via ports."""
from __future__ import annotations

import json

from .events import make_event
from .protocol import JsonRpcConn

_UPDATE_TO_EVENT = {
    "agent_message_chunk": ("message_chunk", "agent"),
    "agent_thought_chunk": ("message_chunk", "thought"),
    "user_message_chunk": ("message_chunk", "user"),
}


class StateError(Exception):
    pass


class AcpSession:
    PROTOCOL_VERSION = 1
    DEFAULT_CAPS = {"fs": {"readTextFile": True, "writeTextFile": True}}

    def __init__(self, sid, profile, proc, sink, recorder, sentinel, policy,
                 files, client_capabilities=None):
        self.sid = sid
        self.profile = profile
        self.proc = proc
        self.sink = sink
        self.recorder = recorder
        self.sentinel = sentinel
        self.policy = policy
        self.files = files
        self.caps = client_capabilities or dict(self.DEFAULT_CAPS)
        self.state = "starting"
        self.acp_session_id = None
        self._seq = 0
        self._turn_id = None
        self._last_raw_ref = None
        self._pending_perms: dict = {}
        self._conn = JsonRpcConn(self._on_request, self._on_notify,
                                 self._on_anomaly)

    # ---- plumbing -------------------------------------------------------
    def _emit(self, kind, data, raw_ref=None):
        self._seq += 1
        self.sink.emit(make_event(kind, self.sid, self._seq, data, raw_ref))

    def _set_state(self, state, detail=""):
        self.state = state
        self._emit("session_state", {"state": state, "detail": detail})

    def _flush(self):
        for line in self._conn.take_outgoing():
            self.recorder.append({"dir": "out", "frame": json.loads(line)})
            self.proc.send_line(line)

    def on_line(self, line: str) -> None:
        try:
            frame = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            frame = None
        if isinstance(frame, dict):
            raw_ref = self.recorder.append({"dir": "in", "frame": frame})
            flags = self.sentinel.check_frame("in", frame)
            if flags:
                self._emit("drift", {"flags": flags}, raw_ref)
        else:
            raw_ref = self.recorder.append({"dir": "in", "raw": line})
        self._last_raw_ref = raw_ref
        self._conn.feed(line)
        self._flush()

    def _on_anomaly(self, category, detail, raw):
        self._emit("anomaly", {"category": category, "detail": str(detail)},
                   self._last_raw_ref)

    # ---- lifecycle ------------------------------------------------------
    def start(self, cwd: str) -> None:
        self._cwd = cwd
        self._conn.request("initialize", {
            "protocolVersion": self.PROTOCOL_VERSION,
            "clientCapabilities": self.caps,
        }, self._on_initialized)
        self._flush()

    def _on_initialized(self, result, error):
        if error or not result:
            return self._fail(f"initialize failed: {error}")
        version = result.get("protocolVersion")
        if version != self.PROTOCOL_VERSION:
            self._emit("anomaly", {"category": "version-mismatch",
                       "detail": f"agent speaks protocol version {version}, "
                                 f"client speaks {self.PROTOCOL_VERSION}"})
            return self._fail("protocol version mismatch")
        self.agent_capabilities = result.get("agentCapabilities") or {}
        self._conn.request("session/new",
                           {"cwd": self._cwd, "mcpServers": []},
                           self._on_session_new)
        self._flush()

    def _on_session_new(self, result, error):
        if error or not result:
            return self._fail(f"session/new failed: {error}")
        self.acp_session_id = result["sessionId"]
        modes = result.get("modes") or {}
        if modes:
            self._emit("mode", {"current": modes.get("currentModeId"),
                                "available": modes.get("availableModes", [])})
        self._set_state("ready")

    def _fail(self, detail: str):
        self._set_state("failed", detail)
        self.proc.kill()

    def close(self) -> None:
        if self.state not in ("failed", "closed"):
            self._set_state("closed")
        self.proc.kill()
        self.recorder.close()

    def on_exit(self, code) -> None:
        if self.state in ("closed", "failed"):
            return
        detail = f"adapter exited with code {code}"
        recoverable = self.state == "turn"
        self._emit("anomaly", {"category": "adapter-exit", "detail": detail})
        self._set_state("failed", "recoverable: " + detail if recoverable
                        else detail)

    # ---- user actions ---------------------------------------------------
    def prompt(self, text: str) -> None:
        if self.state != "ready":
            raise StateError(f"cannot prompt in state {self.state!r}")
        self.recorder.append({"dir": "client", "action": "prompt",
                              "text": text})
        self._set_state("turn")
        self._turn_id = self._conn.request("session/prompt", {
            "sessionId": self.acp_session_id,
            "prompt": [{"type": "text", "text": text}],
        }, self._on_turn_end)
        self._flush()

    def _on_turn_end(self, result, error):
        self._turn_id = None
        if error:
            self._emit("anomaly", {"category": "turn-error",
                                   "detail": str(error)})
            self._set_state("ready")
            return
        self._emit("turn_ended",
                   {"stop_reason": (result or {}).get("stopReason")})
        self._set_state("ready")

    # ---- agent -> client ------------------------------------------------
    def _on_notify(self, method, params):
        if method != "session/update":
            return  # tolerated per spec; sentinel already flagged unknowns
        if params.get("sessionId") != self.acp_session_id:
            self._emit("anomaly", {
                "category": "unknown-session",
                "detail": f"update for session {params.get('sessionId')!r}, "
                          f"ours is {self.acp_session_id!r}"},
                self._last_raw_ref)
            return
        update = params.get("update") or {}
        kind = update.get("sessionUpdate")
        ref = self._last_raw_ref
        if kind in _UPDATE_TO_EVENT:
            event_kind, role = _UPDATE_TO_EVENT[kind]
            text = (update.get("content") or {}).get("text", "")
            self._emit(event_kind, {"role": role, "text": text}, ref)
        elif kind in ("tool_call", "tool_call_update"):
            self._emit(kind, update, ref)
        elif kind == "plan":
            self._emit("plan", {"entries": update.get("entries", [])}, ref)
        elif kind == "available_commands_update":
            self._emit("commands",
                       {"commands": update.get("availableCommands", [])}, ref)
        elif kind == "current_mode_update":
            self._emit("mode", {"current": update.get("currentModeId"),
                                "available": []}, ref)
        else:
            self._emit("unrecognized",
                       {"why": f"unknown update kind {kind!r}",
                        "frame": update}, ref)

    def _on_request(self, msg_id, method, params):
        self._conn.error(msg_id, -32601, f"unsupported method: {method}")
        self._flush()

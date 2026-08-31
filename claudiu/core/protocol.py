# SPDX-License-Identifier: Apache-2.0
"""Sans-I/O newline-delimited JSON-RPC 2.0. Knows JSON-RPC, not ACP."""
from __future__ import annotations

import json


class JsonRpcConn:
    def __init__(self, on_request, on_notification, on_anomaly):
        self._on_request = on_request
        self._on_notification = on_notification
        self._on_anomaly = on_anomaly
        self._next_id = 0
        self._pending = {}
        self._out: list[str] = []

    def _send(self, frame: dict) -> None:
        self._out.append(json.dumps(frame, ensure_ascii=False))

    def request(self, method: str, params: dict, on_result) -> int:
        self._next_id += 1
        self._pending[self._next_id] = on_result
        self._send({"jsonrpc": "2.0", "id": self._next_id,
                    "method": method, "params": params})
        return self._next_id

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def respond(self, msg_id, result) -> None:
        self._send({"jsonrpc": "2.0", "id": msg_id, "result": result})

    def error(self, msg_id, code: int, message: str) -> None:
        self._send({"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": code, "message": message}})

    def feed(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            self._on_anomaly("malformed", "line is not JSON", line)
            return
        if not isinstance(frame, dict):
            self._on_anomaly("malformed", "frame is not an object", frame)
            return
        if "method" in frame:
            params = frame.get("params") or {}
            if "id" in frame:
                self._on_request(frame["id"], frame["method"], params)
            else:
                self._on_notification(frame["method"], params)
        elif "id" in frame:
            cb = self._pending.pop(frame["id"], None)
            if cb is None:
                self._on_anomaly("unmatched-id",
                                 f"response for unknown id {frame['id']}", frame)
            else:
                cb(frame.get("result"), frame.get("error"))
        else:
            self._on_anomaly("malformed", "neither method nor id", frame)

    def take_outgoing(self) -> list[str]:
        out, self._out = self._out, []
        return out

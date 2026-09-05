# SPDX-License-Identifier: Apache-2.0
"""Drift sentinel: compares live traffic against the pinned ACP registry."""
from __future__ import annotations

import json
from pathlib import Path

_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "vendor" / "acp" / "registry.json"


class Sentinel:
    def __init__(self, registry: dict):
        self._r = registry
        self._known_in = set(registry["from_agent_requests"]) | \
            set(registry["from_agent_notifications"])
        self._known_out = set(registry["to_agent_requests"]) | \
            set(registry["to_agent_notifications"])
        self._root = set(registry["root_keys"])
        # Schema kinds plus the kinds a known adapter emits outside the schema
        # (claude-agent-acp's subagent/async-task updates, read from its dist
        # 2026-09-05): known is not drift; the engine renders them as
        # `vendor_update` rather than `unrecognized`.
        self._kinds = set(registry["update_kinds"])
        self.vendor_kinds = frozenset(registry.get("vendor_update_kinds", []))
        self._kinds |= self.vendor_kinds
        self._stops = set(registry["stop_reasons"])
        self._perms = set(registry["permission_kinds"])

    @classmethod
    def load_default(cls) -> "Sentinel":
        return cls(json.loads(_REGISTRY_PATH.read_text(encoding="utf-8")))

    def check_frame(self, direction: str, frame: dict) -> list[str]:
        flags: list[str] = []
        for key in frame:
            if key not in self._root:
                flags.append(f"unknown-root-key:{key}")
        method = frame.get("method")
        if method is not None:
            known = self._known_in if direction == "in" else self._known_out
            side = "from-agent" if direction == "in" else "to-agent"
            if method not in known:
                flags.append(f"unknown-{side}-method:{method}")
        params = frame.get("params") or {}
        if method == "session/update":
            kind = (params.get("update") or {}).get("sessionUpdate")
            if kind not in self._kinds:
                flags.append(f"unknown-update-kind:{kind}")
        if method == "session/request_permission":
            for opt in params.get("options") or []:
                if opt.get("kind") not in self._perms:
                    flags.append(f"unknown-permission-kind:{opt.get('kind')}")
        result = frame.get("result")
        if isinstance(result, dict) and "stopReason" in result:
            if result["stopReason"] not in self._stops:
                flags.append(f"unknown-stop-reason:{result['stopReason']}")
        return flags

    def compare_versions(self, pinned_schema, latest_schema,
                         adapter, latest_adapter) -> list[str]:
        flags = []
        if latest_schema and latest_schema != pinned_schema:
            flags.append(f"schema-behind:pinned={pinned_schema},latest={latest_schema}")
        if latest_adapter and adapter and latest_adapter != adapter:
            flags.append(f"adapter-behind:installed={adapter},latest={latest_adapter}")
        return flags

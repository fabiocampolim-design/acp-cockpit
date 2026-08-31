# CLAUDIU-ACP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build CLAUDIU-ACP — a Windows-native browser client for AI coding agents over the Agent Client Protocol, with Claude Code (via `claude-code-acp`) as the first configured agent.

**Architecture:** Four one-way layers: `ui/web` (vanilla-JS View) → `server/` (Tornado Controller implementing ports) → `core/` (pure-stdlib sans-I/O Model: JSON-RPC framing, ACP state machine, flight recorder, drift sentinel, path policy) → `agents/*.toml` (agent profiles as data). Losslessness by recording every raw frame before interpretation; drift by checking every frame against a hand-curated registry pinned to a vendored ACP schema release.

**Tech Stack:** Python ≥ 3.11 stdlib + Tornado (only shipped dep). Dev/test: pytest, pyflakes, playwright. User-installed external: node + `@zed-industries/claude-code-acp`.

**Spec:** `docs/superpowers/specs/2026-08-31-claudiu-acp-design.md` (approved). Research: `docs/superpowers/specs/2026-08-31-acp-research.md`.

## Global Constraints

- Python floor **3.11** (`tomllib`); local interpreters: Bash `python` = 3.13 (has playwright — run tests here), PowerShell `python` = 3.14.
- Shipped runtime deps: **stdlib + `tornado` only**. No JS dependencies, no build step, no external resources in the UI.
- `core/` **never imports tornado** and does no real I/O except `record.py` writing its own files; everything else goes through `core/ports.py`.
- Commits: author `Fabio Campolim <250239356+fabiocampolim-design@users.noreply.github.com>` (repo has no local override — the conformance checker verifies). Never `git add -A` — always add explicit paths.
- Codename `claudiu` never ships as the public name (renamed at publication; not this plan's concern).
- Server binds **127.0.0.1 only**; default port **0** (OS-assigned, printed) — never a habit port (KEEP rules/08).
- Every task: run `python -m pyflakes <changed .py files>` before commit; it must be clean.
- Run tests from repo root with Bash `python -m pytest`. The v0.1 suite disappears in Task 1; the count grows from 0.
- ACP field names in this plan were verified live against `claude-code-acp` on 2026-08-31 (see research doc); the contract tier (Task 17) re-verifies them against the real adapter.

## File Structure (end state)

```
agents/claude.toml            # first agent profile (data)
agents/PROFILE-SCHEMA.md      # profile format doc
claudiu/__init__.py           # version
claudiu/__main__.py           # CLI: parse args, start server, print token URL
claudiu/core/__init__.py
claudiu/core/events.py        # Event dataclass + KINDS + wire format
claudiu/core/protocol.py      # JsonRpcConn (sans-I/O ndjson JSON-RPC 2.0)
claudiu/core/record.py        # Recorder (append-only JSONL, replay)
claudiu/core/sentinel.py      # Sentinel (registry checks, version compare)
claudiu/core/policy.py        # PathPolicy (session path boundary)
claudiu/core/profiles.py      # AgentProfile loader (tomllib)
claudiu/core/ports.py         # AgentProcess / EventSink / FileAccess protocols
claudiu/core/acp.py           # AcpSession state machine
claudiu/server/__init__.py
claudiu/server/auth.py        # TokenAuth
claudiu/server/procs.py       # SubprocessAgentProcess
claudiu/server/app.py         # make_app, REST handlers, SessionManager
claudiu/server/ws.py          # WS handler + BufferedSink (EventSink impl)
claudiu/ui/web/index.html
claudiu/ui/web/app.js
claudiu/ui/web/style.css
vendor/acp/schema.json        # pinned ACP schema release (data)
vendor/acp/VERSION            # its release tag
vendor/acp/registry.json      # hand-curated runtime registry
tools/check_schema_drift.py   # dev-time: diff schema.json vs registry.json
tests/...                     # per task below; tests/fake_adapter.py + fixtures/
docs/UI-PROTOCOL.md           # the View seam (deliverable)
```

---

### Task 1: Archive v0.1 (KEEP rule 20) and scaffold the new layout

**Files:**
- Create: `archive/claudiu-v0.1/` (clone with own `.git`; gitignored)
- Modify: `.gitignore` (add `archive/`), `pyproject.toml` (rewrite)
- Delete (git rm): `claudiu/` (all 24 files incl. `static/`), `tests/` (all 15), `run_claudiu.bat`
- Create: `claudiu/__init__.py`, `claudiu/core/__init__.py`, `claudiu/server/__init__.py`, `tests/test_wiring.py`

**Interfaces:**
- Produces: importable empty package `claudiu` with `claudiu.__version__ = "0.2.0.dev0"`; `pyproject.toml` with `[project] requires-python = ">=3.11"`, dependency `tornado`.

- [ ] **Step 1: Preconditions** — `git status --porcelain` must be empty; note `git rev-parse --short HEAD`.

- [ ] **Step 2: Archive with own history**

```bash
git clone --no-hardlinks . archive/claudiu-v0.1
printf '\narchive/\n' >> .gitignore
```

- [ ] **Step 3: Remove the v0.1 app from master**

```bash
git rm -r -q claudiu tests run_claudiu.bat
```
(Keep: `docs/`, `README.md`, `CHANGELOG.md`, `LICENSE`, `NOTICE`, `CITATION.cff`, `AGENTS.md`, `.github/`, `.gitattributes`, `.gitignore`, `pyproject.toml`.)

- [ ] **Step 4: New skeleton** — create dirs/files:

`claudiu/__init__.py`:
```python
"""CLAUDIU — browser client for AI coding agents over ACP."""
__version__ = "0.2.0.dev0"
```
`claudiu/core/__init__.py` and `claudiu/server/__init__.py`: empty.

Rewrite `pyproject.toml`:
```toml
[project]
name = "claudiu"
version = "0.2.0.dev0"
description = "Browser client for AI coding agents over the Agent Client Protocol"
requires-python = ">=3.11"
dependencies = ["tornado>=6.4"]

[project.optional-dependencies]
dev = ["pytest", "pyflakes", "playwright"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["claudiu*"]
```

- [ ] **Step 5: Wiring test** — `tests/test_wiring.py`:

```python
import claudiu

def test_version():
    assert claudiu.__version__.startswith("0.2.0")
```

- [ ] **Step 6: Run** — `python -m pytest tests/ -q` → 1 passed. `python -c "import claudiu.core, claudiu.server"` → OK. Verify `git status` does not list `archive/`.

- [ ] **Step 7: Commit**

```bash
git add .gitignore pyproject.toml claudiu tests
git commit -m "refactor!: archive v0.1 app (KEEP rule 20), scaffold ACP client layout"
```

---

### Task 2: core/events.py — typed engine events

**Files:**
- Create: `claudiu/core/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Produces: `Event` frozen dataclass `(kind: str, session: str, seq: int, ts: str, data: dict, raw_ref: int | None = None)`; `KINDS: frozenset[str]`; `make_event(kind, session, seq, data, raw_ref=None) -> Event` (raises `ValueError` on unknown kind); `to_wire(event) -> str` (one-line JSON with keys kind/session/seq/ts/data/raw_ref); `now_iso() -> str`.

- [ ] **Step 1: Failing tests** — `tests/test_events.py`:

```python
import json
import pytest
from claudiu.core.events import KINDS, make_event, to_wire

def test_kinds_cover_spec_surface():
    for k in ("session_state", "message_chunk", "tool_call", "tool_call_update",
              "plan", "commands", "mode", "permission_request",
              "permission_resolved", "fs_request", "turn_ended", "anomaly",
              "drift", "unrecognized"):
        assert k in KINDS

def test_make_event_valid():
    e = make_event("plan", "s1", 3, {"entries": []}, raw_ref=17)
    assert (e.kind, e.session, e.seq, e.raw_ref) == ("plan", "s1", 3, 17)
    assert e.ts.endswith("+00:00") or e.ts.endswith("Z")

def test_make_event_unknown_kind_raises():
    with pytest.raises(ValueError):
        make_event("bogus", "s1", 0, {})

def test_to_wire_roundtrip():
    e = make_event("anomaly", "s1", 0, {"category": "malformed", "detail": "x"})
    d = json.loads(to_wire(e))
    assert d["kind"] == "anomaly" and d["data"]["category"] == "malformed"
    assert "\n" not in to_wire(e)
```

- [ ] **Step 2: Run to fail** — `python -m pytest tests/test_events.py -q` → ImportError.

- [ ] **Step 3: Implement** — `claudiu/core/events.py`:

```python
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
```

- [ ] **Step 4: Run to pass** — `python -m pytest tests/test_events.py -q` → 4 passed. Pyflakes clean.

- [ ] **Step 5: Commit** — `git add claudiu/core/events.py tests/test_events.py && git commit -m "feat(core): typed engine events"`

---

### Task 3: core/protocol.py — sans-I/O ndjson JSON-RPC 2.0

**Files:**
- Create: `claudiu/core/protocol.py`
- Test: `tests/test_protocol.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `JsonRpcConn(on_request, on_notification, on_anomaly)` where `on_request(msg_id, method, params: dict)`, `on_notification(method, params: dict)`, `on_anomaly(category: str, detail: str, raw: str | dict)`. Methods: `request(method, params, on_result) -> int` (`on_result(result, error)`, either may be None), `notify(method, params)`, `respond(msg_id, result)`, `error(msg_id, code: int, message: str)`, `feed(line: str)`, `take_outgoing() -> list[str]` (each item one JSON line, no trailing newline).

- [ ] **Step 1: Failing tests** — `tests/test_protocol.py`:

```python
import json
from claudiu.core.protocol import JsonRpcConn


def make_conn(log):
    return JsonRpcConn(
        on_request=lambda i, m, p: log.append(("req", i, m, p)),
        on_notification=lambda m, p: log.append(("note", m, p)),
        on_anomaly=lambda c, d, r: log.append(("anomaly", c)),
    )


def test_request_response_matching():
    log, results = [], []
    conn = make_conn(log)
    rid = conn.request("initialize", {"protocolVersion": 1},
                       lambda res, err: results.append((res, err)))
    out = conn.take_outgoing()
    frame = json.loads(out[0])
    assert frame == {"jsonrpc": "2.0", "id": rid, "method": "initialize",
                     "params": {"protocolVersion": 1}}
    conn.feed(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {"ok": 1}}))
    assert results == [({"ok": 1}, None)]


def test_error_response_delivered():
    log, results = [], []
    conn = make_conn(log)
    rid = conn.request("session/new", {}, lambda r, e: results.append((r, e)))
    conn.feed(json.dumps({"jsonrpc": "2.0", "id": rid,
                          "error": {"code": -32603, "message": "boom"}}))
    assert results[0][0] is None and results[0][1]["code"] == -32603


def test_incoming_request_and_notification_dispatch():
    log = []
    conn = make_conn(log)
    conn.feed(json.dumps({"jsonrpc": "2.0", "id": 9,
                          "method": "session/request_permission",
                          "params": {"x": 1}}))
    conn.feed(json.dumps({"jsonrpc": "2.0", "method": "session/update",
                          "params": {"y": 2}}))
    assert log[0] == ("req", 9, "session/request_permission", {"x": 1})
    assert log[1] == ("note", "session/update", {"y": 2})


def test_respond_and_error_frames():
    conn = make_conn([])
    conn.respond(9, {"outcome": {"outcome": "cancelled"}})
    conn.error(10, -32601, "unsupported")
    a, b = (json.loads(x) for x in conn.take_outgoing())
    assert a["id"] == 9 and "result" in a
    assert b["error"]["code"] == -32601


def test_malformed_and_unmatched_are_anomalies_not_crashes():
    log = []
    conn = make_conn(log)
    conn.feed("this is not json")
    conn.feed(json.dumps({"jsonrpc": "2.0", "id": 777, "result": {}}))
    conn.feed(json.dumps([1, 2, 3]))
    cats = [x[1] for x in log if x[0] == "anomaly"]
    assert cats == ["malformed", "unmatched-id", "malformed"]
```

- [ ] **Step 2: Run to fail** → ImportError.

- [ ] **Step 3: Implement** — `claudiu/core/protocol.py`:

```python
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
```

- [ ] **Step 4: Run to pass** — 5 passed; pyflakes clean.

- [ ] **Step 5: Commit** — `git add claudiu/core/protocol.py tests/test_protocol.py && git commit -m "feat(core): sans-IO ndjson JSON-RPC connection"`

---

### Task 4: Vendored ACP schema, registry, and core/sentinel.py

**Files:**
- Create: `vendor/acp/schema.json` (downloaded), `vendor/acp/VERSION`, `vendor/acp/registry.json`, `tools/check_schema_drift.py`, `claudiu/core/sentinel.py`
- Test: `tests/test_sentinel.py`

**Interfaces:**
- Produces: `Sentinel(registry: dict)`; `Sentinel.load_default() -> Sentinel` (classmethod, reads `vendor/acp/registry.json` relative to repo/package); `check_frame(direction: str, frame: dict) -> list[str]` with `direction in ("in", "out")`, returning drift-flag strings (empty = clean); `compare_versions(pinned_schema: str, latest_schema: str | None, adapter: str | None, latest_adapter: str | None) -> list[str]`. Registry keys used by later tasks: `to_agent_requests`, `to_agent_notifications`, `from_agent_requests`, `from_agent_notifications`, `update_kinds`, `stop_reasons`, `permission_kinds`, `root_keys`, `protocol_version`.

- [ ] **Step 1: Vendor the schema (execution-time download, pinned)**

```bash
mkdir -p vendor/acp tools
curl -fsSL https://api.github.com/repos/agentclientprotocol/agent-client-protocol/releases/latest -o /tmp_release.json 2>/dev/null || true
curl -fsSL https://github.com/agentclientprotocol/agent-client-protocol/releases/latest/download/schema.json -o vendor/acp/schema.json
python - <<'EOF'
import json, urllib.request
with urllib.request.urlopen("https://api.github.com/repos/agentclientprotocol/agent-client-protocol/releases/latest") as r:
    tag = json.load(r)["tag_name"]
open("vendor/acp/VERSION", "w").write(tag + "\n")
print("pinned", tag)
EOF
```
(If the network is unavailable, stop and report — the pin is required, not optional.) Note the ACP repo's license in `NOTICE` (check the release page; the protocol repo is Apache-2.0 — verify at download time and record file+version in NOTICE).

- [ ] **Step 2: Hand-curated registry** — `vendor/acp/registry.json`:

```json
{
  "protocol_version": 1,
  "root_keys": ["jsonrpc", "id", "method", "params", "result", "error", "_meta"],
  "to_agent_requests": ["initialize", "authenticate", "session/new",
    "session/load", "session/prompt", "session/set_mode"],
  "to_agent_notifications": ["session/cancel"],
  "from_agent_requests": ["session/request_permission", "fs/read_text_file",
    "fs/write_text_file", "terminal/create", "terminal/output",
    "terminal/release", "terminal/wait_for_exit", "terminal/kill",
    "elicitation/create"],
  "from_agent_notifications": ["session/update", "elicitation/complete"],
  "update_kinds": ["user_message_chunk", "agent_message_chunk",
    "agent_thought_chunk", "tool_call", "tool_call_update", "plan",
    "available_commands_update", "current_mode_update"],
  "stop_reasons": ["end_turn", "max_tokens", "max_turn_requests",
    "refusal", "cancelled"],
  "permission_kinds": ["allow_once", "allow_always", "reject_once",
    "reject_always"]
}
```

- [ ] **Step 3: Failing tests** — `tests/test_sentinel.py`:

```python
import json
from pathlib import Path
from claudiu.core.sentinel import Sentinel

REG = json.loads(Path("vendor/acp/registry.json").read_text())


def test_known_traffic_is_clean():
    s = Sentinel(REG)
    assert s.check_frame("in", {"jsonrpc": "2.0", "method": "session/update",
        "params": {"sessionId": "x", "update":
                   {"sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "hi"}}}}) == []
    assert s.check_frame("out", {"jsonrpc": "2.0", "id": 1,
        "method": "initialize", "params": {}}) == []


def test_unknown_method_and_kind_flagged():
    s = Sentinel(REG)
    assert any("unknown-from-agent-method" in f for f in
               s.check_frame("in", {"jsonrpc": "2.0", "id": 5,
                                    "method": "session/brand_new_thing",
                                    "params": {}}))
    flags = s.check_frame("in", {"jsonrpc": "2.0", "method": "session/update",
        "params": {"sessionId": "x",
                   "update": {"sessionUpdate": "hologram_chunk"}}})
    assert any("unknown-update-kind" in f for f in flags)


def test_unknown_root_key_flagged():
    s = Sentinel(REG)
    flags = s.check_frame("in", {"jsonrpc": "2.0", "id": 1, "result": {},
                                 "novelty": True})
    assert any("unknown-root-key:novelty" in f for f in flags)


def test_version_compare():
    s = Sentinel(REG)
    assert s.compare_versions("v1.0.0", "v1.0.0", "1.2.3", "1.2.3") == []
    flags = s.compare_versions("v1.0.0", "v1.4.0", "1.2.3", "1.9.9")
    assert len(flags) == 2 and any("schema" in f for f in flags)
```

- [ ] **Step 4: Run to fail** → ImportError.

- [ ] **Step 5: Implement** — `claudiu/core/sentinel.py`:

```python
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
        self._kinds = set(registry["update_kinds"])
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
```

- [ ] **Step 6: Dev-time diff tool** — `tools/check_schema_drift.py`:

```python
"""Dev-time: walk the vendored ACP schema.json for identifiers the registry
does not know. Structure-agnostic: collects every string that looks like a
method name or enum value anywhere in the schema tree."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
schema = json.loads((ROOT / "vendor/acp/schema.json").read_text(encoding="utf-8"))
reg = json.loads((ROOT / "vendor/acp/registry.json").read_text(encoding="utf-8"))

known = set()
for key in ("to_agent_requests", "to_agent_notifications",
            "from_agent_requests", "from_agent_notifications",
            "update_kinds", "stop_reasons", "permission_kinds"):
    known |= set(reg[key])

found = set()
METHOD = re.compile(r"^(session|fs|terminal|elicitation)/[a-z_]+$")
WORD = re.compile(r"^[a-z][a-z_]+$")

def walk(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("const", "enum"):
                vals = v if isinstance(v, list) else [v]
                for x in vals:
                    if isinstance(x, str) and (METHOD.match(x) or WORD.match(x)):
                        found.add(x)
            walk(v)
    elif isinstance(node, list):
        for x in node:
            walk(x)

walk(schema)
novel = sorted(x for x in found if x not in known and
               (METHOD.match(x) or x.endswith("_chunk") or
                x.endswith("_update") or x.startswith(("allow_", "reject_"))))
if novel:
    print("SCHEMA HAS IDENTIFIERS THE REGISTRY DOES NOT KNOW:")
    for x in novel:
        print("  -", x)
    sys.exit(1)
print("registry covers all recognizable schema identifiers")
```

- [ ] **Step 7: Run everything** — `python -m pytest tests/test_sentinel.py -q` → 4 passed. `python tools/check_schema_drift.py` → run it; if it exits 1, examine the reported identifiers: add genuinely-new protocol surface to the registry (and note it — that is the sentinel doing its job on day one), rerun until clean or the remainder is demonstrably noise (then tighten the tool's filters instead of the registry). Pyflakes clean.

- [ ] **Step 8: Commit** — `git add vendor tools/check_schema_drift.py claudiu/core/sentinel.py tests/test_sentinel.py NOTICE && git commit -m "feat(core): drift sentinel with pinned ACP schema and registry"`

---

### Task 5: core/record.py — the flight recorder

**Files:**
- Create: `claudiu/core/record.py`
- Test: `tests/test_record.py`

**Interfaces:**
- Produces: `Recorder(path: Path)` — `append(entry: dict) -> int` (1-based line number, flushed each write), `replay() -> Iterator[tuple[int, dict]]`, `close()`, context-manager support. Entry shapes used by acp.py: `{"t": iso, "dir": "in"|"out", "frame": <verbatim dict>}` and `{"t": iso, "dir": "client", "action": str, ...}`.

- [ ] **Step 1: Failing tests** — `tests/test_record.py`:

```python
import json
from claudiu.core.record import Recorder


def test_append_returns_line_numbers_and_replay_roundtrips(tmp_path):
    p = tmp_path / "s1.jsonl"
    with Recorder(p) as rec:
        n1 = rec.append({"dir": "in", "frame": {"jsonrpc": "2.0", "id": 1}})
        n2 = rec.append({"dir": "client", "action": "prompt", "text": "hi"})
    assert (n1, n2) == (1, 2)
    entries = list(Recorder(p).replay())
    assert entries[0][0] == 1
    assert entries[0][1]["frame"] == {"jsonrpc": "2.0", "id": 1}
    assert entries[1][1]["action"] == "prompt"
    assert all("t" in e for _, e in entries)   # timestamps auto-added


def test_frames_stored_verbatim_including_unknown_fields(tmp_path):
    p = tmp_path / "s2.jsonl"
    weird = {"jsonrpc": "2.0", "method": "x/y", "novel_field": {"deep": [1]}}
    with Recorder(p) as rec:
        rec.append({"dir": "in", "frame": weird})
    (_, entry), = Recorder(p).replay()
    assert entry["frame"] == weird


def test_append_survives_reopen(tmp_path):
    p = tmp_path / "s3.jsonl"
    with Recorder(p) as rec:
        rec.append({"dir": "in", "frame": {}})
    with Recorder(p) as rec:
        assert rec.append({"dir": "in", "frame": {}}) == 2
```

- [ ] **Step 2: Run to fail** → ImportError.

- [ ] **Step 3: Implement** — `claudiu/core/record.py`:

```python
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
```

- [ ] **Step 4: Run to pass** — 3 passed; pyflakes clean.

- [ ] **Step 5: Commit** — `git add claudiu/core/record.py tests/test_record.py && git commit -m "feat(core): JSONL flight recorder"`

---

### Task 6: core/profiles.py + agents/claude.toml — agent profiles as data

**Files:**
- Create: `claudiu/core/profiles.py`, `agents/claude.toml`, `agents/PROFILE-SCHEMA.md`
- Test: `tests/test_profiles.py`

**Interfaces:**
- Produces: `@dataclass AgentProfile(id: str, name: str, command: list[str], install_hint: str, env_scrub: list[str], env_set: dict[str, str], caveats: list[dict], extensions: list[str])`; `load_profile(path: Path) -> AgentProfile` raising `ProfileError(msg)` on any missing/mistyped field; `load_profiles(directory: Path) -> dict[str, AgentProfile]` (key = profile id, skips non-`.toml`).

- [ ] **Step 1: Failing tests** — `tests/test_profiles.py`:

```python
import pytest
from pathlib import Path
from claudiu.core.profiles import AgentProfile, ProfileError, load_profile, load_profiles


def test_claude_profile_loads():
    p = load_profile(Path("agents/claude.toml"))
    assert p.id == "claude"
    assert p.command[0] == "claude-code-acp"
    assert "CLAUDECODE" in p.env_scrub
    assert any("CLAUDE_CODE_" in s for s in p.env_scrub)
    assert p.install_hint.startswith("npm install")
    assert any(c["id"] == "model-picker" for c in p.caveats)


def test_missing_field_is_a_profile_error(tmp_path):
    bad = tmp_path / "x.toml"
    bad.write_text('id = "x"\nname = "X"\n', encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(bad)


def test_load_profiles_indexes_by_id(tmp_path):
    (tmp_path / "a.toml").write_text(
        'id = "a"\nname = "A"\ncommand = ["a-cmd"]\n'
        'install_hint = "get a"\nenv_scrub = []\n', encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    profs = load_profiles(tmp_path)
    assert set(profs) == {"a"} and isinstance(profs["a"], AgentProfile)
```

- [ ] **Step 2: Run to fail** → ImportError.

- [ ] **Step 3: Write the profile** — `agents/claude.toml`:

```toml
# Agent profile: Claude Code over the claude-code-acp adapter.
# Everything Claude-specific lives HERE, not in the engine.
id = "claude"
name = "Claude Code"
command = ["claude-code-acp"]
install_hint = "npm install -g @zed-industries/claude-code-acp"

# Nested-session guard: the Claude SDK refuses to start when these are set.
env_scrub = ["CLAUDECODE", "CLAUDE_CODE_*"]

[env_set]

# Vendor _meta extension names the adapter is known to use (surfaced, not interpreted).
extensions = []

[[caveats]]
id = "model-picker"
text = "The interactive /model picker has no ACP equivalent; model choice follows the underlying claude configuration."

[[caveats]]
id = "terminal-unadvertised"
text = "This client does not advertise the terminal capability in v1; the agent runs commands through its own executor instead. Nothing is lost, output arrives as tool calls."
```

- [ ] **Step 4: Implement** — `claudiu/core/profiles.py`:

```python
"""Agent profiles: everything agent-specific, loaded from TOML data."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ProfileError(Exception):
    pass


@dataclass(frozen=True)
class AgentProfile:
    id: str
    name: str
    command: list[str]
    install_hint: str
    env_scrub: list[str]
    env_set: dict = field(default_factory=dict)
    caveats: list = field(default_factory=list)
    extensions: list = field(default_factory=list)


_REQUIRED = ("id", "name", "command", "install_hint", "env_scrub")


def load_profile(path: Path) -> AgentProfile:
    try:
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProfileError(f"{path}: {exc}") from exc
    for key in _REQUIRED:
        if key not in raw:
            raise ProfileError(f"{path}: missing required field {key!r}")
    if not isinstance(raw["command"], list) or not raw["command"]:
        raise ProfileError(f"{path}: 'command' must be a non-empty list")
    return AgentProfile(
        id=raw["id"], name=raw["name"], command=list(raw["command"]),
        install_hint=raw["install_hint"], env_scrub=list(raw["env_scrub"]),
        env_set=dict(raw.get("env_set", {})),
        caveats=list(raw.get("caveats", [])),
        extensions=list(raw.get("extensions", [])),
    )


def load_profiles(directory: Path) -> dict[str, AgentProfile]:
    out: dict[str, AgentProfile] = {}
    for p in sorted(Path(directory).glob("*.toml")):
        prof = load_profile(p)
        out[prof.id] = prof
    return out
```

- [ ] **Step 5: Schema doc** — `agents/PROFILE-SCHEMA.md`: document every field above (required/optional, type, meaning, one example each). Include the sentence: "The engine consumes any conforming profile; adding an agent means adding a file here, never touching `core/`."

- [ ] **Step 6: Run to pass** — 3 passed; pyflakes clean.

- [ ] **Step 7: Commit** — `git add claudiu/core/profiles.py agents tests/test_profiles.py && git commit -m "feat(core): agent profiles as TOML data, Claude profile first"`

---

### Task 7: core/policy.py — session path boundary

**Files:**
- Create: `claudiu/core/policy.py`
- Test: `tests/test_policy.py`

**Interfaces:**
- Produces: `PathPolicy(root: Path)` — `allowed(path: str) -> bool` (absolute paths only; resolves symlinks; case-insensitive on Windows; True iff inside root or a grant), `grant(path: Path)` (adds an extra allowed directory), `describe() -> dict` (root + grants as strings, for the record).

- [ ] **Step 1: Failing tests** — `tests/test_policy.py`:

```python
import os
import pytest
from claudiu.core.policy import PathPolicy


def test_inside_root_allowed(tmp_path):
    pol = PathPolicy(tmp_path)
    inner = tmp_path / "sub" / "f.txt"
    assert pol.allowed(str(inner))
    assert pol.allowed(str(tmp_path))


def test_outside_and_traversal_denied(tmp_path):
    pol = PathPolicy(tmp_path / "proj")
    assert not pol.allowed(str(tmp_path / "other" / "f.txt"))
    assert not pol.allowed(str(tmp_path / "proj" / ".." / "other" / "f.txt"))


def test_relative_paths_denied(tmp_path):
    pol = PathPolicy(tmp_path)
    assert not pol.allowed("relative/file.txt")


def test_grant_extends_boundary(tmp_path):
    pol = PathPolicy(tmp_path / "proj")
    extra = tmp_path / "shared"
    assert not pol.allowed(str(extra / "f.txt"))
    pol.grant(extra)
    assert pol.allowed(str(extra / "f.txt"))
    assert str(extra.resolve()) in pol.describe()["grants"][0]


@pytest.mark.skipif(os.name != "nt", reason="case rule is Windows-specific")
def test_windows_case_insensitive(tmp_path):
    pol = PathPolicy(tmp_path)
    assert pol.allowed(str(tmp_path).upper() + os.sep + "F.TXT")


def test_symlink_escape_denied(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    link = root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("no symlink privilege")
    assert not pol_allowed_through_link(root, link)


def pol_allowed_through_link(root, link):
    return PathPolicy(root).allowed(str(link / "f.txt"))
```

- [ ] **Step 2: Run to fail** → ImportError.

- [ ] **Step 3: Implement** — `claudiu/core/policy.py`:

```python
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
```

(`Path.resolve()` follows symlinks, so a link pointing outside the root
resolves outside it and is denied — that is the escape test.)

- [ ] **Step 4: Run to pass** — 5-6 passed (symlink test may skip); pyflakes clean.

- [ ] **Step 5: Commit** — `git add claudiu/core/policy.py tests/test_policy.py && git commit -m "feat(core): session path boundary policy"`

---

### Task 8: core/ports.py + core/acp.py — handshake and prompt turn

**Files:**
- Create: `claudiu/core/ports.py`, `claudiu/core/acp.py`, `tests/helpers.py`
- Test: `tests/test_acp_handshake.py`

**Interfaces:**
- Consumes: `JsonRpcConn`, `Event`/`make_event`, `Recorder`, `Sentinel`, `PathPolicy`, `AgentProfile`.
- Produces:
  - `ports.py`: `class AgentProcess(Protocol): def send_line(self, line: str) -> None: ...; def kill(self) -> None: ...` — `class EventSink(Protocol): def emit(self, event) -> None: ...` — `class FileAccess(Protocol): def read_text(self, path: str) -> str: ...; def write_text(self, path: str, content: str) -> None: ...`
  - `acp.py`: `class StateError(Exception)`; `AcpSession(sid: str, profile, proc, sink, recorder, sentinel, policy, files, client_capabilities=None)` with attributes `state` (one of `"starting"|"ready"|"turn"|"failed"|"closed"`), `acp_session_id: str | None`, and methods `start(cwd: str)`, `prompt(text: str)` (raises `StateError` unless ready), `on_line(line: str)` (wire from process stdout), `on_exit(code: int | None)`, `close()`. Constant `PROTOCOL_VERSION = 1`. Client capabilities default: `{"fs": {"readTextFile": True, "writeTextFile": True}}` (terminal deliberately omitted = unsupported).
  - `tests/helpers.py`: `class FakeProc` (collects `sent: list[str]`, `killed: bool`), `class SinkList` (collects events), `def make_session(tmp_path, **kw) -> tuple[AcpSession, FakeProc, SinkList]` building a session with real Recorder/Sentinel/PathPolicy over tmp_path and the claude profile.

- [ ] **Step 1: Test helpers** — `tests/helpers.py`:

```python
from pathlib import Path
from claudiu.core.acp import AcpSession
from claudiu.core.policy import PathPolicy
from claudiu.core.profiles import load_profile
from claudiu.core.record import Recorder
from claudiu.core.sentinel import Sentinel


class FakeProc:
    def __init__(self):
        self.sent: list[str] = []
        self.killed = False

    def send_line(self, line: str) -> None:
        self.sent.append(line)

    def kill(self) -> None:
        self.killed = True


class SinkList:
    def __init__(self):
        self.events = []

    def emit(self, event) -> None:
        self.events.append(event)

    def kinds(self):
        return [e.kind for e in self.events]


class FakeFiles:
    def __init__(self):
        self.store: dict[str, str] = {}

    def read_text(self, path: str) -> str:
        return self.store[path]

    def write_text(self, path: str, content: str) -> None:
        self.store[path] = content


def make_session(tmp_path, **kw):
    proc, sink = FakeProc(), SinkList()
    session = AcpSession(
        sid="s1",
        profile=load_profile(Path("agents/claude.toml")),
        proc=proc, sink=sink,
        recorder=Recorder(tmp_path / "s1.jsonl"),
        sentinel=Sentinel.load_default(),
        policy=PathPolicy(tmp_path),
        files=kw.pop("files", FakeFiles()),
        **kw)
    return session, proc, sink
```

- [ ] **Step 2: Failing tests** — `tests/test_acp_handshake.py` (frames match the live traffic recorded in the research doc):

```python
import json
import pytest
from claudiu.core.acp import StateError
from tests.helpers import make_session


def sent_frames(proc):
    return [json.loads(x) for x in proc.sent]


def feed(session, frame):
    session.on_line(json.dumps(frame))


def do_handshake(session, proc):
    session.start(cwd="C:\\work\\proj")
    init = sent_frames(proc)[0]
    assert init["method"] == "initialize"
    assert init["params"]["protocolVersion"] == 1
    assert init["params"]["clientCapabilities"]["fs"]["readTextFile"] is True
    assert "terminal" not in init["params"]["clientCapabilities"]
    feed(session, {"jsonrpc": "2.0", "id": init["id"], "result": {
        "protocolVersion": 1,
        "agentCapabilities": {"loadSession": True}}})
    new = sent_frames(proc)[1]
    assert new["method"] == "session/new"
    assert new["params"]["cwd"] == "C:\\work\\proj"
    feed(session, {"jsonrpc": "2.0", "id": new["id"], "result": {
        "sessionId": "acp-123",
        "modes": {"currentModeId": "default", "availableModes": [
            {"id": "default", "name": "Default"}]}}})


def test_handshake_reaches_ready(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    assert session.state == "ready"
    assert session.acp_session_id == "acp-123"
    assert "mode" in sink.kinds()
    states = [e.data["state"] for e in sink.events if e.kind == "session_state"]
    assert states[-1] == "ready"


def test_version_mismatch_fails_closed(tmp_path):
    session, proc, sink = make_session(tmp_path)
    session.start(cwd="C:\\w")
    init = sent_frames(proc)[0]
    feed(session, {"jsonrpc": "2.0", "id": init["id"],
                   "result": {"protocolVersion": 99}})
    assert session.state == "failed"
    assert proc.killed
    assert any(e.kind == "anomaly" and "version" in e.data["detail"]
               for e in sink.events)


def test_prompt_turn_streams_and_ends(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    session.prompt("hello")
    p = sent_frames(proc)[2]
    assert p["method"] == "session/prompt"
    assert p["params"] == {"sessionId": "acp-123",
                           "prompt": [{"type": "text", "text": "hello"}]}
    assert session.state == "turn"
    feed(session, {"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": "acp-123", "update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "hi "}}}})
    feed(session, {"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": "acp-123", "update": {
            "sessionUpdate": "agent_thought_chunk",
            "content": {"type": "text", "text": "thinking"}}}})
    feed(session, {"jsonrpc": "2.0", "id": p["id"],
                   "result": {"stopReason": "end_turn"}})
    chunks = [e for e in sink.events if e.kind == "message_chunk"]
    assert chunks[0].data == {"role": "agent", "text": "hi "}
    assert chunks[1].data == {"role": "thought", "text": "thinking"}
    assert sink.kinds()[-1] == "turn_ended"
    assert session.state == "ready"


def test_prompt_rejected_unless_ready(tmp_path):
    session, proc, sink = make_session(tmp_path)
    with pytest.raises(StateError):
        session.prompt("too early")


def test_unknown_update_kind_becomes_unrecognized_plus_drift(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": "acp-123", "update": {"sessionUpdate": "hologram"}}})
    assert "unrecognized" in sink.kinds()
    assert "drift" in sink.kinds()


def test_update_for_foreign_session_is_anomaly(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": "someone-else", "update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "leak?"}}}})
    assert not any(e.kind == "message_chunk" and e.data["role"] == "agent"
                   for e in sink.events)
    assert any(e.kind == "anomaly" and
               e.data["category"] == "unknown-session" for e in sink.events)


def test_everything_is_recorded_raw(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    entries = [e for _, e in session.recorder.replay()]
    dirs = [e["dir"] for e in entries]
    assert "out" in dirs and "in" in dirs
    outs = [e["frame"]["method"] for e in entries
            if e["dir"] == "out" and "method" in e["frame"]]
    assert outs[:2] == ["initialize", "session/new"]
```

- [ ] **Step 3: Run to fail** → ImportError.

- [ ] **Step 4: Implement** — `claudiu/core/ports.py`:

```python
"""Abstract seams between the engine and the outside world."""
from __future__ import annotations

from typing import Protocol


class AgentProcess(Protocol):
    def send_line(self, line: str) -> None: ...
    def kill(self) -> None: ...


class EventSink(Protocol):
    def emit(self, event) -> None: ...


class FileAccess(Protocol):
    def read_text(self, path: str) -> str: ...
    def write_text(self, path: str, content: str) -> None: ...
```

Then `claudiu/core/acp.py` (handshake + prompt turn; permission/fs arrive in Task 9 — leave `_on_request` raising `-32601` for everything for now):

```python
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
        raw_ref = None
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
                   getattr(self, "_last_raw_ref", None))

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
                getattr(self, "_last_raw_ref", None))
            return
        update = params.get("update") or {}
        kind = update.get("sessionUpdate")
        ref = getattr(self, "_last_raw_ref", None)
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
```

- [ ] **Step 5: Run to pass** — `python -m pytest tests/test_acp_handshake.py -q` → 6 passed; full suite green; pyflakes clean.

- [ ] **Step 6: Commit** — `git add claudiu/core/ports.py claudiu/core/acp.py tests/helpers.py tests/test_acp_handshake.py && git commit -m "feat(core): ACP session state machine — handshake and prompt turns"`

---

### Task 9: core/acp.py — permissions, fs gating, cancel, modes, resume

**Files:**
- Modify: `claudiu/core/acp.py` (replace `_on_request`; add methods)
- Test: `tests/test_acp_requests.py`

**Interfaces:**
- Produces (added to `AcpSession`): `answer_permission(request_id: int, option_id: str)` (raises `StateError` if unknown), `fail_safe_reject(request_id: int)` (auto-answer: prefers a `reject_once` option, else outcome `cancelled`; emits `permission_resolved` with `source: "failsafe"`), `pending_permissions() -> list[int]`, `cancel()` (sends `session/cancel` notification), `set_mode(mode_id: str)`, `load(acp_session_id: str, cwd: str)` (uses `session/load`, replayed updates flow as normal events, then ready).

- [ ] **Step 1: Failing tests** — `tests/test_acp_requests.py`:

```python
import json
import pytest
from tests.helpers import make_session, FakeFiles
from tests.test_acp_handshake import do_handshake, feed, sent_frames

PERM_FRAME = {"jsonrpc": "2.0", "id": 44,
              "method": "session/request_permission", "params": {
                  "sessionId": "acp-123",
                  "toolCall": {"toolCallId": "t1", "title": "Write file"},
                  "options": [
                      {"optionId": "allow", "name": "Allow",
                       "kind": "allow_once"},
                      {"optionId": "rej", "name": "Reject",
                       "kind": "reject_once"}]}}


def test_permission_roundtrip_user_allow(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, PERM_FRAME)
    req = [e for e in sink.events if e.kind == "permission_request"][0]
    assert req.data["options"][0]["kind"] == "allow_once"
    assert session.pending_permissions() == [44]
    session.answer_permission(44, "allow")
    reply = [f for f in sent_frames(proc) if f.get("id") == 44][0]
    assert reply["result"]["outcome"] == {"outcome": "selected",
                                          "optionId": "allow"}
    resolved = [e for e in sink.events if e.kind == "permission_resolved"][0]
    assert resolved.data["source"] == "user"
    assert session.pending_permissions() == []


def test_permission_failsafe_prefers_reject(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, PERM_FRAME)
    session.fail_safe_reject(44)
    reply = [f for f in sent_frames(proc) if f.get("id") == 44][0]
    assert reply["result"]["outcome"]["optionId"] == "rej"
    resolved = [e for e in sink.events if e.kind == "permission_resolved"][0]
    assert resolved.data["source"] == "failsafe"


def test_fs_read_inside_boundary_served(tmp_path):
    files = FakeFiles()
    inside = str(tmp_path / "a.txt")
    files.store[inside] = "content"
    session, proc, sink = make_session(tmp_path, files=files)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "id": 50, "method": "fs/read_text_file",
                   "params": {"sessionId": "acp-123", "path": inside}})
    reply = [f for f in sent_frames(proc) if f.get("id") == 50][0]
    assert reply["result"] == {"content": "content"}
    ev = [e for e in sink.events if e.kind == "fs_request"][0]
    assert ev.data["allowed"] is True and ev.data["op"] == "read"


def test_fs_write_outside_boundary_refused(tmp_path):
    files = FakeFiles()
    session, proc, sink = make_session(tmp_path, files=files)
    do_handshake(session, proc)
    outside = str(tmp_path.parent / "evil.txt")
    feed(session, {"jsonrpc": "2.0", "id": 51, "method": "fs/write_text_file",
                   "params": {"sessionId": "acp-123", "path": outside,
                              "content": "x"}})
    reply = [f for f in sent_frames(proc) if f.get("id") == 51][0]
    assert "error" in reply
    assert files.store == {}
    ev = [e for e in sink.events if e.kind == "fs_request"][0]
    assert ev.data["allowed"] is False


def test_cancel_sends_notification_and_turn_ends_cancelled(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    session.prompt("go")
    turn = sent_frames(proc)[2]
    session.cancel()
    note = sent_frames(proc)[3]
    assert note == {"jsonrpc": "2.0", "method": "session/cancel",
                    "params": {"sessionId": "acp-123"}}
    feed(session, {"jsonrpc": "2.0", "id": turn["id"],
                   "result": {"stopReason": "cancelled"}})
    ended = [e for e in sink.events if e.kind == "turn_ended"][0]
    assert ended.data["stop_reason"] == "cancelled"
    assert session.state == "ready"


def test_set_mode(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    session.set_mode("acceptEdits")
    frame = sent_frames(proc)[2]
    assert frame["method"] == "session/set_mode"
    assert frame["params"] == {"sessionId": "acp-123",
                               "modeId": "acceptEdits"}
    feed(session, {"jsonrpc": "2.0", "id": frame["id"], "result": {}})
    mode_events = [e for e in sink.events if e.kind == "mode"]
    assert mode_events[-1].data["current"] == "acceptEdits"


def test_unknown_request_still_gets_32601(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "id": 60,
                   "method": "_vendor/surprise", "params": {}})
    reply = [f for f in sent_frames(proc) if f.get("id") == 60][0]
    assert reply["error"]["code"] == -32601


def test_answer_unknown_permission_raises(tmp_path):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    with pytest.raises(Exception):
        session.answer_permission(999, "allow")
```

- [ ] **Step 2: Run to fail** — permission/fs/cancel tests fail (current `_on_request` answers everything -32601).

- [ ] **Step 3: Implement** — in `claudiu/core/acp.py`, replace `_on_request` and add the user-action methods:

```python
    # ---- agent -> client requests --------------------------------------
    def _on_request(self, msg_id, method, params):
        ref = getattr(self, "_last_raw_ref", None)
        if method == "session/request_permission":
            self._pending_perms = getattr(self, "_pending_perms", {})
            self._pending_perms[msg_id] = params.get("options") or []
            self._emit("permission_request", {
                "request": msg_id,
                "tool_call": params.get("toolCall") or {},
                "options": params.get("options") or []}, ref)
            return  # answered later by answer_permission / fail_safe_reject
        if method in ("fs/read_text_file", "fs/write_text_file"):
            self._handle_fs(msg_id, method, params, ref)
        else:
            self._conn.error(msg_id, -32601, f"unsupported method: {method}")
        self._flush()

    def _handle_fs(self, msg_id, method, params, ref):
        op = "read" if method == "fs/read_text_file" else "write"
        path = params.get("path", "")
        ok = self.policy.allowed(path)
        self._emit("fs_request", {"op": op, "path": path, "allowed": ok}, ref)
        self.recorder.append({"dir": "client", "action": "fs_decision",
                              "op": op, "path": path, "allowed": ok,
                              "policy": self.policy.describe()})
        if not ok:
            self._conn.error(msg_id, -32602,
                             "path outside the session boundary")
            return
        try:
            if op == "read":
                self._conn.respond(msg_id,
                                   {"content": self.files.read_text(path)})
            else:
                self.files.write_text(path, params.get("content", ""))
                self._conn.respond(msg_id, None)
        except OSError as exc:
            self._conn.error(msg_id, -32603, f"fs failure: {exc}")

    # ---- permissions ----------------------------------------------------
    def pending_permissions(self):
        return sorted(getattr(self, "_pending_perms", {}))

    def _resolve_permission(self, request_id, outcome, option_id, source):
        perms = getattr(self, "_pending_perms", {})
        if request_id not in perms:
            raise StateError(f"no pending permission {request_id}")
        del perms[request_id]
        self._conn.respond(request_id, {"outcome": outcome})
        self.recorder.append({"dir": "client", "action": "permission",
                              "request": request_id, "option": option_id,
                              "source": source})
        self._emit("permission_resolved", {"request": request_id,
                   "option": option_id, "source": source})
        self._flush()

    def answer_permission(self, request_id: int, option_id: str) -> None:
        self._resolve_permission(
            request_id, {"outcome": "selected", "optionId": option_id},
            option_id, "user")

    def fail_safe_reject(self, request_id: int) -> None:
        options = getattr(self, "_pending_perms", {}).get(request_id) or []
        reject = next((o for o in options
                       if o.get("kind") == "reject_once"), None)
        if reject is None:
            reject = next((o for o in options
                           if str(o.get("kind", "")).startswith("reject")),
                          None)
        if reject:
            self._resolve_permission(
                request_id,
                {"outcome": "selected", "optionId": reject["optionId"]},
                reject["optionId"], "failsafe")
        else:
            self._resolve_permission(
                request_id, {"outcome": "cancelled"}, None, "failsafe")

    # ---- more user actions ---------------------------------------------
    def cancel(self) -> None:
        if self.state != "turn":
            return
        self.recorder.append({"dir": "client", "action": "cancel"})
        self._conn.notify("session/cancel",
                          {"sessionId": self.acp_session_id})
        self._flush()

    def set_mode(self, mode_id: str) -> None:
        self.recorder.append({"dir": "client", "action": "set_mode",
                              "mode": mode_id})

        def done(result, error):
            if error:
                self._emit("anomaly", {"category": "set-mode-error",
                                       "detail": str(error)})
            else:
                self._emit("mode", {"current": mode_id, "available": []})
        self._conn.request("session/set_mode",
                           {"sessionId": self.acp_session_id,
                            "modeId": mode_id}, done)
        self._flush()

    def load(self, acp_session_id: str, cwd: str) -> None:
        if self.state != "starting":
            raise StateError("load only from a fresh session")
        self._cwd = cwd
        self._load_target = acp_session_id
        self._conn.request("initialize", {
            "protocolVersion": self.PROTOCOL_VERSION,
            "clientCapabilities": self.caps}, self._on_initialized_for_load)
        self._flush()

    def _on_initialized_for_load(self, result, error):
        if error or (result or {}).get("protocolVersion") != self.PROTOCOL_VERSION:
            return self._fail(f"initialize for load failed: {error}")

        def done(res, err):
            if err:
                return self._fail(f"session/load failed: {err}")
            self.acp_session_id = self._load_target
            self._set_state("ready")
        self._conn.request("session/load", {
            "sessionId": self._load_target, "cwd": self._cwd,
            "mcpServers": []}, done)
        self._flush()
```

- [ ] **Step 4: Run to pass** — `python -m pytest tests/test_acp_requests.py tests/test_acp_handshake.py -q` → all passing; full suite green; pyflakes clean.

- [ ] **Step 5: Commit** — `git add claudiu/core/acp.py tests/test_acp_requests.py && git commit -m "feat(core): permissions, fs gating, cancel, modes, session load"`

---

### Task 10: server/auth.py — token auth

**Files:**
- Create: `claudiu/server/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Produces: `TokenAuth()` — `token: str` (urlsafe, ≥ 32 bytes entropy, generated in `__init__`), `verify(presented: str | None) -> bool` (constant-time; False for None/empty). `COOKIE_NAME = "claudiu_token"`.

- [ ] **Step 1: Failing tests** — `tests/test_auth.py`:

```python
from claudiu.server.auth import TokenAuth, COOKIE_NAME


def test_token_is_long_and_unique():
    a, b = TokenAuth(), TokenAuth()
    assert len(a.token) >= 43          # token_urlsafe(32)
    assert a.token != b.token


def test_verify():
    a = TokenAuth()
    assert a.verify(a.token)
    assert not a.verify(a.token[:-1] + "x")
    assert not a.verify("")
    assert not a.verify(None)


def test_cookie_name_stable():
    assert COOKIE_NAME == "claudiu_token"
```

- [ ] **Step 2: Run to fail** → ImportError.

- [ ] **Step 3: Implement** — `claudiu/server/auth.py`:

```python
"""Per-launch bearer token; localhost is not a trust boundary."""
from __future__ import annotations

import hmac
import secrets

COOKIE_NAME = "claudiu_token"


class TokenAuth:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)

    def verify(self, presented) -> bool:
        if not presented:
            return False
        return hmac.compare_digest(self.token, str(presented))
```

- [ ] **Step 4: Run to pass**; pyflakes clean.

- [ ] **Step 5: Commit** — `git add claudiu/server/auth.py tests/test_auth.py && git commit -m "feat(server): per-launch token auth"`

---

### Task 11: server/procs.py — adapter subprocess with scrubbed env

**Files:**
- Create: `claudiu/server/procs.py`, `tests/child_lines.py`
- Test: `tests/test_procs.py`

**Interfaces:**
- Consumes: `AgentProfile` (command, env_scrub, env_set).
- Produces: `SubprocessAgentProcess(command: list[str], cwd: str, env_scrub: list[str], env_set: dict, on_line, on_stderr, on_exit)` — implements the `AgentProcess` port (`send_line`, `kill`) plus `wait(timeout)` for tests. **Threading contract (documented in the docstring): `on_line`/`on_stderr`/`on_exit` are invoked on reader threads; the server must marshal to its own loop.** `resolve_command(argv: list[str]) -> list[str]` uses `shutil.which` on `argv[0]` (finds Windows `.cmd`/`.ps1` shims) and raises `FileNotFoundError` with the profile's install hint attached by the caller.

- [ ] **Step 1: Child fixture** — `tests/child_lines.py` (a stand-in adapter):

```python
"""Test child: echoes each stdin line as {"echo": line}; reports env once."""
import json
import os
import sys

print(json.dumps({"env_has_CLAUDECODE": "CLAUDECODE" in os.environ,
                  "env_has_marker": "CLAUDE_CODE_MARKER" in os.environ,
                  "env_extra": os.environ.get("EXTRA_VAR", "")}), flush=True)
for line in sys.stdin:
    line = line.rstrip("\n")
    if line == "QUIT":
        break
    print(json.dumps({"echo": line}), flush=True)
print("bye on stderr", file=sys.stderr, flush=True)
```

- [ ] **Step 2: Failing tests** — `tests/test_procs.py`:

```python
import json
import os
import sys
import threading
import pytest
from claudiu.server.procs import SubprocessAgentProcess, resolve_command


def collectors():
    lines, errs, exits = [], [], []
    done = threading.Event()
    return lines, errs, exits, done


def spawn(tmp_path, lines, errs, exits, done, env_scrub=(), env_set=None):
    return SubprocessAgentProcess(
        command=[sys.executable, "tests/child_lines.py"],
        cwd=str(tmp_path),
        env_scrub=list(env_scrub), env_set=env_set or {},
        on_line=lines.append, on_stderr=errs.append,
        on_exit=lambda code: (exits.append(code), done.set()))


def test_line_roundtrip_and_exit(tmp_path):
    lines, errs, exits, done = collectors()
    proc = spawn(tmp_path, lines, errs, exits, done)
    proc.send_line("hello")
    proc.send_line("QUIT")
    assert done.wait(timeout=15)
    payloads = [json.loads(x) for x in lines]
    assert {"echo": "hello"} in payloads
    assert exits == [0]
    assert any("bye" in e for e in errs)


def test_env_scrubbed_and_set(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_MARKER", "1")
    lines, errs, exits, done = collectors()
    proc = spawn(tmp_path, lines, errs, exits, done,
                 env_scrub=["CLAUDECODE", "CLAUDE_CODE_*"],
                 env_set={"EXTRA_VAR": "injected"})
    proc.send_line("QUIT")
    assert done.wait(timeout=15)
    first = json.loads(lines[0])
    assert first == {"env_has_CLAUDECODE": False, "env_has_marker": False,
                     "env_extra": "injected"}


def test_kill_terminates(tmp_path):
    lines, errs, exits, done = collectors()
    proc = spawn(tmp_path, lines, errs, exits, done)
    proc.kill()
    assert done.wait(timeout=15)


def test_resolve_command_missing_raises():
    with pytest.raises(FileNotFoundError):
        resolve_command(["definitely-not-a-real-binary-xyz"])
```

- [ ] **Step 3: Run to fail** → ImportError.

- [ ] **Step 4: Implement** — `claudiu/server/procs.py`:

```python
"""Adapter subprocess: plain pipes, scrubbed env, reader threads.

Threading contract: on_line / on_stderr / on_exit fire on internal reader
threads. The server marshals them onto its IOLoop; core never sees threads.
"""
from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import threading


def resolve_command(argv: list[str]) -> list[str]:
    exe = shutil.which(argv[0])
    if exe is None:
        raise FileNotFoundError(argv[0])
    return [exe, *argv[1:]]


def build_env(env_scrub: list[str], env_set: dict) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not any(fnmatch.fnmatch(k, pat) for pat in env_scrub)}
    env.update(env_set)
    return env


class SubprocessAgentProcess:
    def __init__(self, command, cwd, env_scrub, env_set,
                 on_line, on_stderr, on_exit):
        self._proc = subprocess.Popen(
            resolve_command(command), cwd=cwd,
            env=build_env(env_scrub, env_set),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", bufsize=1)
        self._on_exit = on_exit
        self._threads = [
            threading.Thread(target=self._pump, args=(self._proc.stdout,
                                                      on_line), daemon=True),
            threading.Thread(target=self._pump, args=(self._proc.stderr,
                                                      on_stderr), daemon=True),
            threading.Thread(target=self._reap, daemon=True),
        ]
        for t in self._threads:
            t.start()

    def _pump(self, stream, callback):
        for line in stream:
            callback(line.rstrip("\n"))

    def _reap(self):
        code = self._proc.wait()
        self._on_exit(code)

    def send_line(self, line: str) -> None:
        try:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError):
            pass  # dead child; _reap reports it

    def kill(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def wait(self, timeout=None):
        return self._proc.wait(timeout=timeout)
```

- [ ] **Step 5: Run to pass** — 4 passed (Windows + POSIX both fine: no pty anywhere); pyflakes clean.

- [ ] **Step 6: Commit** — `git add claudiu/server/procs.py tests/child_lines.py tests/test_procs.py && git commit -m "feat(server): adapter subprocess with env scrub and reader threads"`

---

### Task 12: server/app.py + server/ws.py + CLI — the Tornado controller

**Files:**
- Create: `claudiu/server/app.py`, `claudiu/server/ws.py`, `claudiu/__main__.py`, `tests/fake_adapter.py`, `tests/fixtures/basic_turn.json`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: everything from Tasks 2–11.
- Produces:
  - `ws.py`: `class BufferedSink` (implements `EventSink`; `emit(event)` appends `to_wire(event)` to an in-memory list and pushes to attached WS handlers; `attach(handler)` replays the buffer then streams; `detach(handler)`), `class SessionWS(tornado.websocket.WebSocketHandler)` — client messages are JSON `{"cmd": "prompt"|"cancel"|"set_mode"|"permission", ...}` mapped to `AcpSession.prompt/cancel/set_mode/answer_permission`.
  - `app.py`: `make_app(profiles_dir: Path, records_dir: Path, auth: TokenAuth) -> tornado.web.Application`; `class SessionManager` — `create(profile_id, cwd) -> str` (spawns `SubprocessAgentProcess` from the profile, marshals its callbacks onto the IOLoop via `IOLoop.current().add_callback`, builds `AcpSession` with a real `Recorder(records_dir/sid.jsonl)`, `Sentinel.load_default()`, `PathPolicy(cwd)`, a `LocalFiles` FileAccess impl, and a `BufferedSink`), `get(sid)`, `list() -> list[dict]`, `close(sid)`, `close_all()`. Permission fail-safe: when a `permission_request` event is emitted, the manager schedules `IOLoop.call_later(config timeout, default 3600s, fail_safe_reject)` cancelled on resolution. REST routes (all token-guarded, Host/Origin-guarded, CSP header on HTML):
    - `GET /` → serves `claudiu/ui/web/index.html`; accepts `?token=` once and sets the cookie (redirects to bare `/`).
    - `GET /ui/(.*)` → static files.
    - `GET /api/profiles` → `{"profiles": [{id, name, caveats, install_ok: bool}]}` (`install_ok` = `shutil.which(command[0]) is not None`).
    - `POST /api/sessions` `{"profile": id, "cwd": path}` → `{"id": sid}`; 400 on unknown profile/missing cwd; 424 with install_hint when the adapter binary is missing.
    - `GET /api/sessions` → `{"sessions": [{id, profile, cwd, state}]}`.
    - `DELETE /api/sessions/(sid)` → closes.
    - `GET /api/drift` → `{"pinned_schema": str, "flags": [...], "online": bool}` — version-watch (spec §6): when online checks are enabled it compares the pinned schema tag and the installed adapter version against the latest published ones. CLI default **on** (`--no-drift-online` disables); `make_app` default **off** so tests never touch the network.
    - `WS /ws/sessions/(sid)`.
  - `__main__.py`: argparse (`--port` default 0, `--profiles` default `agents/`, `--records` default `~/.claudiu/records`, `--drift-online` flag); binds `127.0.0.1`, prints `http://127.0.0.1:<actual-port>/?token=<token>`; SIGINT closes all sessions cleanly.
  - `tests/fake_adapter.py`: generic scripted ACP agent for subprocess tests — reads a JSON fixture (list of rules `{"on_method": str, "respond": {...}, "notify": [frames...]}`); for each incoming request whose method matches a rule it first sends each notification in `notify` (with `params.sessionId` filled in), then the response (`respond` used as the JSON-RPC `result`, with `"$id"` placeholders substituted). Unknown methods → `-32601`.
- Test fixture `tests/fixtures/basic_turn.json` drives: initialize → session/new → prompt (2 message chunks + end_turn) → a permission request round (triggered by a prompt containing "PERMISSION").

- [ ] **Step 1: fake adapter** — `tests/fake_adapter.py`:

```python
"""Scripted stand-in ACP agent. Usage: python fake_adapter.py fixture.json"""
import json
import sys

rules = json.loads(open(sys.argv[1], encoding="utf-8").read())
SESSION = "fake-session-1"


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


pending_permission = None
for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    frame = json.loads(raw)
    if "method" not in frame:      # a response to one of OUR requests
        continue
    method, mid = frame["method"], frame.get("id")
    matched = False
    for rule in rules:
        if rule["on_method"] != method:
            continue
        if "if_prompt_contains" in rule:
            text = "".join(b.get("text", "") for b in
                           frame["params"].get("prompt", []))
            if rule["if_prompt_contains"] not in text:
                continue
        matched = True
        for note in rule.get("notify", []):
            note = json.loads(json.dumps(note).replace("$SESSION", SESSION))
            send(note)
        for req in rule.get("request", []):
            req = json.loads(json.dumps(req).replace("$SESSION", SESSION))
            send(req)
        if "respond" in rule:
            result = json.loads(
                json.dumps(rule["respond"]).replace("$SESSION", SESSION))
            send({"jsonrpc": "2.0", "id": mid, "result": result})
        break
    if not matched and mid is not None:
        send({"jsonrpc": "2.0", "id": mid,
              "error": {"code": -32601, "message": "no rule"}})
```

- [ ] **Step 2: fixture** — `tests/fixtures/basic_turn.json`:

```json
[
  {"on_method": "initialize",
   "respond": {"protocolVersion": 1, "agentCapabilities": {}}},
  {"on_method": "session/new",
   "respond": {"sessionId": "$SESSION",
               "modes": {"currentModeId": "default",
                          "availableModes": [{"id": "default",
                                              "name": "Default"}]}}},
  {"on_method": "session/prompt", "if_prompt_contains": "PERMISSION",
   "request": [{"jsonrpc": "2.0", "id": 900,
     "method": "session/request_permission",
     "params": {"sessionId": "$SESSION",
       "toolCall": {"toolCallId": "t1", "title": "Write file"},
       "options": [{"optionId": "y", "name": "Allow", "kind": "allow_once"},
                    {"optionId": "n", "name": "Reject",
                     "kind": "reject_once"}]}}],
   "respond": {"stopReason": "end_turn"}},
  {"on_method": "session/prompt",
   "notify": [
     {"jsonrpc": "2.0", "method": "session/update",
      "params": {"sessionId": "$SESSION",
        "update": {"sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "hello "}}}},
     {"jsonrpc": "2.0", "method": "session/update",
      "params": {"sessionId": "$SESSION",
        "update": {"sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "world"}}}}],
   "respond": {"stopReason": "end_turn"}}
]
```
(Order matters: the fake adapter takes the FIRST matching rule, so the `if_prompt_contains` rule precedes the generic prompt rule.)

- [ ] **Step 3: Failing tests** — `tests/test_server.py` (Tornado `AsyncHTTPTestCase` + `tornado.websocket.websocket_connect`). A test profile is written into `tmp` pointing at `[sys.executable, "tests/fake_adapter.py", "tests/fixtures/basic_turn.json"]`:

```python
import json
import sys
from pathlib import Path
import tornado.testing
import tornado.websocket
from claudiu.server.app import make_app
from claudiu.server.auth import TokenAuth

# Absolute paths: sessions spawn with cwd=<session dir>, so relative
# script paths would not resolve.
FIXTURE_PROFILE = '''
id = "fake"
name = "Fake Agent"
command = [{python!r}, {adapter!r}, {fixture!r}]
install_hint = "n/a"
env_scrub = []
'''.replace("{adapter!r}", repr(str(Path("tests/fake_adapter.py").resolve()))
).replace("{fixture!r}",
          repr(str(Path("tests/fixtures/basic_turn.json").resolve())))


class ServerTest(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp())
        profs = self.tmpdir / "agents"
        profs.mkdir()
        (profs / "fake.toml").write_text(
            FIXTURE_PROFILE.format(python=sys.executable), encoding="utf-8")
        self.auth = TokenAuth()
        return make_app(profiles_dir=profs,
                        records_dir=self.tmpdir / "records", auth=self.auth)

    def _headers(self):
        return {"Cookie": f"claudiu_token={self.auth.token}",
                "Host": f"127.0.0.1:{self.get_http_port()}"}

    def test_profiles_listed(self):
        resp = self.fetch("/api/profiles", headers=self._headers())
        assert resp.code == 200
        data = json.loads(resp.body)
        assert data["profiles"][0]["id"] == "fake"

    def test_no_token_is_403(self):
        resp = self.fetch("/api/profiles")
        assert resp.code == 403

    def test_session_lifecycle_and_ws_stream(self):
        resp = self.fetch("/api/sessions", method="POST",
                          headers=self._headers(),
                          body=json.dumps({"profile": "fake",
                                           "cwd": str(self.tmpdir)}))
        assert resp.code == 200
        sid = json.loads(resp.body)["id"]

        async def drive():
            url = (f"ws://127.0.0.1:{self.get_http_port()}"
                   f"/ws/sessions/{sid}")
            conn = await tornado.websocket.websocket_connect(
                tornado.httpclient.HTTPRequest(
                    url, headers=self._headers()))
            # wait for ready
            while True:
                ev = json.loads(await conn.read_message())
                if ev["kind"] == "session_state" and \
                        ev["data"]["state"] == "ready":
                    break
            await conn.write_message(json.dumps(
                {"cmd": "prompt", "text": "say hello"}))
            texts, ended = [], False
            while not ended:
                ev = json.loads(await conn.read_message())
                if ev["kind"] == "message_chunk":
                    texts.append(ev["data"]["text"])
                elif ev["kind"] == "turn_ended":
                    ended = True
            assert "".join(texts) == "hello world"
            conn.close()
        self.io_loop.run_sync(drive, timeout=30)

    def test_permission_roundtrip_over_ws(self):
        resp = self.fetch("/api/sessions", method="POST",
                          headers=self._headers(),
                          body=json.dumps({"profile": "fake",
                                           "cwd": str(self.tmpdir)}))
        sid = json.loads(resp.body)["id"]

        async def drive():
            url = (f"ws://127.0.0.1:{self.get_http_port()}"
                   f"/ws/sessions/{sid}")
            conn = await tornado.websocket.websocket_connect(
                tornado.httpclient.HTTPRequest(url, headers=self._headers()))
            while True:
                ev = json.loads(await conn.read_message())
                if ev["kind"] == "session_state" and \
                        ev["data"]["state"] == "ready":
                    break
            await conn.write_message(json.dumps(
                {"cmd": "prompt", "text": "do the PERMISSION thing"}))
            request_id = None
            while request_id is None:
                ev = json.loads(await conn.read_message())
                if ev["kind"] == "permission_request":
                    request_id = ev["data"]["request"]
                    assert ev["data"]["options"][0]["kind"] == "allow_once"
            await conn.write_message(json.dumps(
                {"cmd": "permission", "request": request_id,
                 "option": "y"}))
            while True:
                ev = json.loads(await conn.read_message())
                if ev["kind"] == "permission_resolved":
                    assert ev["data"]["option"] == "y"
                    break
            conn.close()
        self.io_loop.run_sync(drive, timeout=30)
```

- [ ] **Step 4: Run to fail** → ImportError.

- [ ] **Step 5: Implement** `claudiu/server/ws.py`:

```python
"""WebSocket bridge: EventSink -> browser, browser commands -> AcpSession."""
from __future__ import annotations

import json

import tornado.websocket

from ..core.events import to_wire
from .auth import COOKIE_NAME


class BufferedSink:
    def __init__(self):
        self._buffer: list[str] = []
        self._handlers: list = []

    def emit(self, event) -> None:
        wire = to_wire(event)
        self._buffer.append(wire)
        for h in list(self._handlers):
            try:
                h.write_message(wire)
            except tornado.websocket.WebSocketClosedError:
                self._handlers.remove(h)

    def attach(self, handler) -> None:
        for wire in self._buffer:
            handler.write_message(wire)
        self._handlers.append(handler)

    def detach(self, handler) -> None:
        if handler in self._handlers:
            self._handlers.remove(handler)


class SessionWS(tornado.websocket.WebSocketHandler):
    def initialize(self, manager, auth):
        self._manager = manager
        self._auth = auth
        self._entry = None

    def check_origin(self, origin: str) -> bool:
        return origin.startswith(("http://127.0.0.1:",
                                  "http://localhost:"))

    def open(self, sid):
        if not self._auth.verify(self.get_cookie(COOKIE_NAME)):
            self.close(4403, "auth")
            return
        self._entry = self._manager.get(sid)
        if self._entry is None:
            self.close(4404, "no such session")
            return
        self._entry.sink.attach(self)

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
            elif cmd == "permission":
                session.answer_permission(msg["request"], msg["option"])
            else:
                self.write_message(to_wire_error(f"unknown cmd {cmd!r}"))
        except Exception as exc:  # surfaced, never silent
            self.write_message(to_wire_error(str(exc)))

    def on_close(self):
        if self._entry is not None:
            self._entry.sink.detach(self)


def to_wire_error(detail: str) -> str:
    return json.dumps({"kind": "anomaly", "session": None, "seq": -1,
                       "ts": None, "data": {"category": "command-error",
                                            "detail": detail},
                       "raw_ref": None})
```

Then `claudiu/server/app.py`:

```python
"""Tornado controller: REST + static + session manager."""
from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

import tornado.ioloop
import tornado.web

from ..core.acp import AcpSession, StateError
from ..core.policy import PathPolicy
from ..core.profiles import load_profiles
from ..core.record import Recorder
from ..core.sentinel import Sentinel
from .auth import COOKIE_NAME
from .procs import SubprocessAgentProcess
from .ws import BufferedSink, SessionWS

UI_DIR = Path(__file__).resolve().parents[1] / "ui" / "web"
VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "acp"

CSP = ("default-src 'self'; img-src 'self' data:; "
       "style-src 'self'; script-src 'self'")


class LocalFiles:
    def read_text(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8")

    def write_text(self, path: str, content: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


@dataclass
class Entry:
    session: AcpSession
    sink: BufferedSink
    profile_id: str
    cwd: str


class SessionManager:
    def __init__(self, profiles_dir: Path, records_dir: Path,
                 permission_timeout: float = 3600.0):
        self.profiles = load_profiles(profiles_dir)
        self.records_dir = Path(records_dir)
        self.permission_timeout = permission_timeout
        self._entries: dict[str, Entry] = {}

    def create(self, profile_id: str, cwd: str) -> str:
        profile = self.profiles[profile_id]
        sid = uuid.uuid4().hex[:12]
        sink = BufferedSink()
        loop = tornado.ioloop.IOLoop.current()
        holder = {}

        def marshal(fn):
            return lambda *a: loop.add_callback(fn, *a)

        proc = SubprocessAgentProcess(
            command=profile.command, cwd=cwd,
            env_scrub=profile.env_scrub, env_set=profile.env_set,
            on_line=marshal(lambda ln: holder["s"].on_line(ln)),
            on_stderr=marshal(lambda ln: holder["s"]._emit(
                "anomaly", {"category": "stderr", "detail": ln})),
            on_exit=marshal(lambda code: holder["s"].on_exit(code)))
        session = AcpSession(
            sid=sid, profile=profile, proc=proc, sink=sink,
            recorder=Recorder(self.records_dir / f"{sid}.jsonl"),
            sentinel=Sentinel.load_default(),
            policy=PathPolicy(cwd), files=LocalFiles())
        holder["s"] = session
        self._watch_permissions(session, sink, loop)
        self._entries[sid] = Entry(session, sink, profile_id, cwd)
        session.start(cwd)
        return sid

    def _watch_permissions(self, session, sink, loop):
        timers: dict[int, object] = {}
        original_emit = sink.emit

        def emit(event):
            original_emit(event)
            if event.kind == "permission_request":
                rid = event.data["request"]
                timers[rid] = loop.call_later(
                    self.permission_timeout,
                    lambda: rid in session.pending_permissions()
                    and session.fail_safe_reject(rid))
            elif event.kind == "permission_resolved":
                t = timers.pop(event.data["request"], None)
                if t:
                    loop.remove_timeout(t)
        sink.emit = emit

    def get(self, sid):
        return self._entries.get(sid)

    def list(self):
        return [{"id": sid, "profile": e.profile_id, "cwd": e.cwd,
                 "state": e.session.state}
                for sid, e in self._entries.items()]

    def close(self, sid):
        entry = self._entries.pop(sid, None)
        if entry:
            entry.session.close()

    def close_all(self):
        for sid in list(self._entries):
            self.close(sid)


class BaseHandler(tornado.web.RequestHandler):
    def initialize(self, manager=None, auth=None):
        self.manager = manager
        self.auth = auth

    def prepare(self):
        host = self.request.host_name
        if host not in ("127.0.0.1", "localhost"):
            raise tornado.web.HTTPError(403, "bad host")
        origin = self.request.headers.get("Origin")
        if origin and not origin.startswith(("http://127.0.0.1:",
                                             "http://localhost:")):
            raise tornado.web.HTTPError(403, "bad origin")
        if not self._authed():
            raise tornado.web.HTTPError(403, "auth")

    def _authed(self):
        return self.auth.verify(self.get_cookie(COOKIE_NAME))

    def set_default_headers(self):
        self.set_header("Content-Security-Policy", CSP)
        self.set_header("X-Content-Type-Options", "nosniff")

    def write_json(self, obj):
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(obj))


class RootHandler(BaseHandler):
    def _authed(self):
        # one-time ?token= sets the cookie
        presented = self.get_query_argument("token", None)
        if presented and self.auth.verify(presented):
            self.set_cookie(COOKIE_NAME, presented, httponly=True,
                            samesite="Strict")
            return True
        return super()._authed()

    def get(self):
        if self.get_query_argument("token", None):
            return self.redirect("/")
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.write((UI_DIR / "index.html").read_bytes())


class ProfilesHandler(BaseHandler):
    def get(self):
        self.write_json({"profiles": [
            {"id": p.id, "name": p.name, "caveats": p.caveats,
             "install_ok": shutil.which(p.command[0]) is not None,
             "install_hint": p.install_hint}
            for p in self.manager.profiles.values()]})


class SessionsHandler(BaseHandler):
    def get(self):
        self.write_json({"sessions": self.manager.list()})

    def post(self):
        body = json.loads(self.request.body or b"{}")
        profile_id = body.get("profile")
        cwd = body.get("cwd")
        if profile_id not in self.manager.profiles or not cwd or \
                not Path(cwd).is_dir():
            raise tornado.web.HTTPError(400, "bad profile or cwd")
        profile = self.manager.profiles[profile_id]
        if shutil.which(profile.command[0]) is None:
            self.set_status(424)
            return self.write_json({"error": "adapter not installed",
                                    "install_hint": profile.install_hint})
        self.write_json({"id": self.manager.create(profile_id, cwd)})


class SessionHandler(BaseHandler):
    def delete(self, sid):
        self.manager.close(sid)
        self.write_json({"ok": True})


class DriftHandler(BaseHandler):
    """Spec §6: report the pinned schema and, when online checks are
    enabled, whether the pin or the installed adapter is behind."""

    async def get(self):
        pinned = (VENDOR / "VERSION").read_text(encoding="utf-8").strip()
        result = {"pinned_schema": pinned, "flags": [], "online": False}
        if self.application.settings.get("drift_online"):
            result["online"] = True
            try:
                latest = await tornado.ioloop.IOLoop.current().\
                    run_in_executor(None, _latest_versions)
                from ..core.sentinel import Sentinel
                result["flags"] = Sentinel.load_default().compare_versions(
                    pinned, latest.get("schema"),
                    latest.get("adapter_installed"),
                    latest.get("adapter_latest"))
                result["latest"] = latest
            except Exception as exc:      # network failure is data, not death
                result["flags"] = [f"drift-check-failed:{exc}"]
        self.write_json(result)


def _latest_versions() -> dict:
    """Blocking lookups, run in an executor. External systems addressed
    generically: a GitHub releases URL and the npm registry, both plain
    HTTPS JSON — no vendor SDKs."""
    import json as _json
    import subprocess as _sp
    import urllib.request as _rq
    out: dict = {}
    with _rq.urlopen("https://api.github.com/repos/agentclientprotocol/"
                     "agent-client-protocol/releases/latest",
                     timeout=10) as r:
        out["schema"] = _json.load(r).get("tag_name")
    with _rq.urlopen("https://registry.npmjs.org/@zed-industries/"
                     "claude-code-acp/latest", timeout=10) as r:
        out["adapter_latest"] = _json.load(r).get("version")
    try:
        ls = _sp.run(["npm", "ls", "-g", "@zed-industries/claude-code-acp",
                      "--json"], capture_output=True, text=True, timeout=30,
                     shell=(__import__("os").name == "nt"))
        deps = _json.loads(ls.stdout or "{}").get("dependencies", {})
        out["adapter_installed"] = deps.get(
            "@zed-industries/claude-code-acp", {}).get("version")
    except Exception:
        out["adapter_installed"] = None
    return out


def make_app(profiles_dir, records_dir, auth,
             permission_timeout: float = 3600.0, drift_online: bool = False):
    manager = SessionManager(profiles_dir, records_dir, permission_timeout)
    common = {"manager": manager, "auth": auth}
    app = tornado.web.Application([
        (r"/", RootHandler, common),
        (r"/api/profiles", ProfilesHandler, common),
        (r"/api/sessions", SessionsHandler, common),
        (r"/api/sessions/([0-9a-f]+)", SessionHandler, common),
        (r"/api/drift", DriftHandler, common),
        (r"/ws/sessions/([0-9a-f]+)", SessionWS, common),
        (r"/ui/(.*)", tornado.web.StaticFileHandler, {"path": str(UI_DIR)}),
    ], drift_online=drift_online)
    app.manager = manager
    return app
```

And `claudiu/__main__.py`:

```python
"""CLI: python -m claudiu [--port N] [--profiles DIR] [--records DIR]"""
import argparse
import signal
from pathlib import Path

import tornado.ioloop

from .server.app import make_app
from .server.auth import TokenAuth


def main():
    ap = argparse.ArgumentParser(prog="claudiu")
    ap.add_argument("--port", type=int, default=0,
                    help="port (default 0 = OS-assigned)")
    ap.add_argument("--profiles", default="agents")
    ap.add_argument("--records",
                    default=str(Path.home() / ".claudiu" / "records"))
    ap.add_argument("--no-drift-online", action="store_true",
                    help="disable the online schema/adapter version check")
    args = ap.parse_args()

    auth = TokenAuth()
    app = make_app(Path(args.profiles), Path(args.records), auth,
                   drift_online=not args.no_drift_online)
    sockets = tornado.netutil.bind_sockets(args.port, address="127.0.0.1")
    server = tornado.httpserver.HTTPServer(app)
    server.add_sockets(sockets)
    port = sockets[0].getsockname()[1]
    print(f"CLAUDIU listening: http://127.0.0.1:{port}/?token={auth.token}")

    loop = tornado.ioloop.IOLoop.current()

    def shutdown(*_):
        app.manager.close_all()
        loop.add_callback_from_signal(loop.stop)
    signal.signal(signal.SIGINT, shutdown)
    loop.start()


if __name__ == "__main__":
    main()
```
(Add the missing imports `tornado.netutil`, `tornado.httpserver`.)

Create an empty placeholder `claudiu/ui/web/index.html` (`<!-- UI lands in Task 15 -->`) so `RootHandler` works.

- [ ] **Step 6: Run to pass** — `python -m pytest tests/test_server.py -q` → 4 passed; full suite green; pyflakes clean.

- [ ] **Step 7: Commit** — `git add claudiu/server claudiu/__main__.py claudiu/ui tests/fake_adapter.py tests/fixtures tests/test_server.py && git commit -m "feat(server): Tornado controller, session manager, WS bridge, CLI"`

---

### Task 13: Security test suite

**Files:**
- Test: `tests/test_security.py`

**Interfaces:** consumes the Task 12 app; adds no new API.

- [ ] **Step 1: Write the tests** — `tests/test_security.py` (same harness pattern as `tests/test_server.py`'s `get_app`/`_headers`):

```python
import json
import sys
import tempfile
from pathlib import Path
import tornado.testing
from claudiu.server.app import make_app
from claudiu.server.auth import TokenAuth
from tests.test_server import FIXTURE_PROFILE


class SecurityTest(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        profs = self.tmpdir / "agents"
        profs.mkdir()
        (profs / "fake.toml").write_text(
            FIXTURE_PROFILE.format(python=sys.executable), encoding="utf-8")
        self.auth = TokenAuth()
        return make_app(profiles_dir=profs,
                        records_dir=self.tmpdir / "records", auth=self.auth)

    def ok_headers(self):
        return {"Cookie": f"claudiu_token={self.auth.token}"}

    def test_missing_token_403(self):
        assert self.fetch("/api/sessions").code == 403

    def test_wrong_token_403(self):
        r = self.fetch("/api/sessions",
                       headers={"Cookie": "claudiu_token=wrong"})
        assert r.code == 403

    def test_evil_host_403(self):
        r = self.fetch("/api/profiles", headers={
            **self.ok_headers(), "Host": "evil.example.com"})
        assert r.code == 403

    def test_evil_origin_403(self):
        r = self.fetch("/api/profiles", headers={
            **self.ok_headers(), "Origin": "http://evil.example.com"})
        assert r.code == 403

    def test_csp_header_present(self):
        r = self.fetch("/api/profiles", headers=self.ok_headers())
        assert "default-src 'self'" in r.headers["Content-Security-Policy"]

    def test_token_never_recorded(self):
        r = self.fetch("/api/sessions", method="POST",
                       headers=self.ok_headers(),
                       body=json.dumps({"profile": "fake",
                                        "cwd": str(self.tmpdir)}))
        assert r.code == 200
        import time
        time.sleep(1.0)   # let the handshake record
        for rec in (self.tmpdir / "records").glob("*.jsonl"):
            assert self.auth.token not in rec.read_text(encoding="utf-8")

    def test_session_ids_are_unguessable_format(self):
        r = self.fetch("/api/sessions", method="POST",
                       headers=self.ok_headers(),
                       body=json.dumps({"profile": "fake",
                                        "cwd": str(self.tmpdir)}))
        sid = json.loads(r.body)["id"]
        assert len(sid) >= 12
```
(The fs-boundary escape itself is covered at the engine level in Task 9 —
`test_fs_write_outside_boundary_refused` — and the env scrub in Task 11.)

- [ ] **Step 2: Run** — all security tests pass against the Task 12 app with **no production changes**; if any fails, the app — not the test — is wrong: fix `app.py` until green. Pyflakes clean.

- [ ] **Step 3: Commit** — `git add tests/test_security.py && git commit -m "test: security suite — auth, host/origin, CSP, token leakage"`

---

### Task 14: docs/UI-PROTOCOL.md + doc-sync test

**Files:**
- Create: `docs/UI-PROTOCOL.md`
- Test: `tests/test_docs_sync.py`

**Interfaces:** none (documentation deliverable, spec §4.1).

- [ ] **Step 1: Failing test** — `tests/test_docs_sync.py`:

```python
from pathlib import Path
from claudiu.core.events import KINDS

DOC = Path("docs/UI-PROTOCOL.md").read_text(encoding="utf-8")


def test_every_event_kind_documented():
    for kind in KINDS:
        assert f"`{kind}`" in DOC, f"event kind {kind} missing from UI-PROTOCOL.md"


def test_every_ws_command_documented():
    for cmd in ("prompt", "cancel", "set_mode", "permission"):
        assert f'"cmd": "{cmd}"' in DOC


def test_every_rest_route_documented():
    for route in ("/api/profiles", "/api/sessions", "/api/drift",
                  "/ws/sessions/"):
        assert route in DOC
```

- [ ] **Step 2: Write the doc** — `docs/UI-PROTOCOL.md`: title "UI Protocol — the View seam"; state that ANY UI (web, desktop, mobile) implementing this document is a full CLAUDIU front-end. Sections: (1) Authentication (token URL → cookie); (2) REST routes with request/response JSON examples exactly as implemented in Task 12; (3) WS endpoint and the four client commands with JSON examples (`{"cmd": "prompt", "text": "..."}` etc.); (4) a table of ALL event kinds from `events.py` with their `data` payload fields and rendering intent (one row per kind, backtick-quoted kind names — the sync test enforces coverage); (5) ordering guarantees (per-session `seq` strictly increases; buffer replay on WS attach); (6) the losslessness contract (`raw_ref` points into the session record; `unrecognized`/`drift`/`anomaly` must be surfaced by every conforming UI, never dropped).

- [ ] **Step 3: Run to pass**; commit — `git add docs/UI-PROTOCOL.md tests/test_docs_sync.py && git commit -m "docs: UI protocol — the View seam, with sync test"`

---

### Task 15: ui/web — launcher, conversation view, composer

**Files:**
- Create: `claudiu/ui/web/index.html` (replace placeholder), `claudiu/ui/web/style.css`, `claudiu/ui/web/app.js`
- Test: manual smoke (Playwright automation lands in Task 16)

**Interfaces:**
- Consumes: exactly `docs/UI-PROTOCOL.md` — nothing else. If the UI needs something the doc lacks, STOP and extend the doc + doc-sync test first (that is the MVC seam working as designed).
- Produces: DOM contract used by Task 16's e2e: `#launcher` (profile select `#profile`, cwd input `#cwd`, button `#start`), `#conversation` (event elements carry `data-kind` attributes), `#composer` (textarea `#prompt-input`, button `#send`), permission dialog `#permission` (buttons carry `data-option`), status strip `#status` with `.state` and `.drift-chip`, per-event raw toggle `.raw-toggle`.

- [ ] **Step 1: index.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CLAUDIU</title>
<link rel="stylesheet" href="/ui/style.css">
</head>
<body>
<div id="launcher">
  <h1>CLAUDIU</h1>
  <label>Agent <select id="profile"></select></label>
  <label>Project directory <input id="cwd" spellcheck="false"></label>
  <button id="start">Start session</button>
  <ul id="caveats"></ul>
</div>
<div id="workspace" hidden>
  <div id="status"><span class="state">starting</span><span class="mode"></span>
    <span class="drift-chip" hidden>drift</span>
    <span class="anomaly-chip" hidden>anomalies</span></div>
  <div id="conversation"></div>
  <div id="plan" hidden></div>
  <div id="composer">
    <textarea id="prompt-input" rows="3"
      placeholder="Prompt — Enter sends, Shift+Enter for newline"></textarea>
    <button id="send">Send</button>
    <button id="cancel" hidden>Stop</button>
    <select id="mode" hidden></select>
  </div>
</div>
<dialog id="permission">
  <h2>Approval request</h2>
  <pre id="perm-tool"></pre>
  <div id="perm-options"></div>
</dialog>
<script src="/ui/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: style.css** — dark, low-contrast default with `prefers-color-scheme: light` variant (design values carried from v0.1's approved palette in the archive — consult `archive/claudiu-v0.1/claudiu/static/` for the exact colors; re-type them, both trees are Fabio's). Layout: `#conversation` flex column, scrollable; `[data-kind="message_chunk"][data-role="thought"]` dimmed italic; `[data-kind="tool_call"]` collapsible boxes; `.drift-chip`, `.anomaly-chip` amber; `#permission` centered with visible diff-style `<pre>`; monospace only in code/raw areas.

- [ ] **Step 3: app.js** — complete, no framework:

```javascript
"use strict";
/* CLAUDIU web View. Talks ONLY the UI protocol (docs/UI-PROTOCOL.md). */

const $ = (sel) => document.querySelector(sel);
let ws = null, sid = null, turnActive = false;

async function api(path, opts = {}) {
  const resp = await fetch(path, {headers: {"Content-Type": "application/json"},
                                  ...opts});
  if (!resp.ok) throw new Error(`${path}: ${resp.status}`);
  return resp.json();
}

async function initLauncher() {
  const {profiles} = await api("/api/profiles");
  const sel = $("#profile");
  for (const p of profiles) {
    const o = document.createElement("option");
    o.value = p.id;
    o.textContent = p.name + (p.install_ok ? "" : " (adapter missing)");
    o.disabled = !p.install_ok;
    sel.append(o);
  }
  sel.onchange = () => {
    const p = profiles.find(x => x.id === sel.value);
    $("#caveats").replaceChildren(...(p ? p.caveats : []).map(c => {
      const li = document.createElement("li"); li.textContent = c.text;
      return li;
    }));
  };
  sel.onchange();
  $("#start").onclick = startSession;
}

async function startSession() {
  const body = JSON.stringify({profile: $("#profile").value,
                               cwd: $("#cwd").value.trim()});
  const {id} = await api("/api/sessions", {method: "POST", body});
  sid = id;
  $("#launcher").hidden = true;
  $("#workspace").hidden = false;
  connect();
}

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws/sessions/${sid}`);
  ws.onmessage = (m) => handleEvent(JSON.parse(m.data));
  ws.onclose = () => setState("disconnected");
}

function setState(s) {
  $("#status .state").textContent = s;
  turnActive = (s === "turn");
  $("#send").disabled = turnActive;
  $("#cancel").hidden = !turnActive;
}

const agg = {};   // role -> current <div> for chunk aggregation

function addBlock(kind, role, text) {
  const key = kind + ":" + (role || "");
  if (agg.currentKey === key && agg.node) {
    agg.node.querySelector(".text").textContent += text;
    return agg.node;
  }
  const div = document.createElement("div");
  div.dataset.kind = kind;
  if (role) div.dataset.role = role;
  const span = document.createElement("span");
  span.className = "text";
  span.textContent = text;
  div.append(span);
  $("#conversation").append(div);
  agg.currentKey = key;
  agg.node = div;
  div.scrollIntoView({block: "end"});
  return div;
}

function addRawToggle(node, ev) {
  const btn = document.createElement("button");
  btn.className = "raw-toggle";
  btn.textContent = "{}";
  btn.title = `raw frame #${ev.raw_ref ?? "-"}`;
  btn.onclick = () => {
    let pre = node.querySelector("pre.raw");
    if (pre) { pre.remove(); return; }
    pre = document.createElement("pre");
    pre.className = "raw";
    pre.textContent = JSON.stringify(ev, null, 2);
    node.append(pre);
  };
  node.append(btn);
}

function handleEvent(ev) {
  const d = ev.data;
  switch (ev.kind) {
    case "session_state":
      setState(d.state);
      break;
    case "message_chunk":
      addBlock("message_chunk", d.role, d.text);
      break;
    case "tool_call":
    case "tool_call_update": {
      agg.currentKey = null;
      const node = addBlock(ev.kind, null,
        `${d.title || d.kind || "tool"} [${d.status || ""}]`);
      addRawToggle(node, ev);
      break;
    }
    case "plan":
      $("#plan").hidden = d.entries.length === 0;
      $("#plan").replaceChildren(...d.entries.map(e => {
        const li = document.createElement("div");
        li.textContent = `${e.status || "?"} — ${e.content || ""}`;
        return li;
      }));
      break;
    case "commands":
      window._commands = d.commands;   // palette lands in Task 16
      break;
    case "mode": {
      const sel = $("#mode");
      if (d.available.length) {
        sel.hidden = false;
        sel.replaceChildren(...d.available.map(m => {
          const o = document.createElement("option");
          o.value = m.id; o.textContent = m.name || m.id;
          return o;
        }));
      }
      if (d.current) sel.value = d.current;
      $("#status .mode").textContent = d.current || "";
      break;
    }
    case "permission_request":
      showPermission(ev);
      break;
    case "permission_resolved":
      $("#permission").close();
      break;
    case "turn_ended":
      agg.currentKey = null;
      addBlock("turn_ended", null, `— turn ended (${d.stop_reason}) —`);
      break;
    case "fs_request":
      addBlock("fs_request", null,
        `agent ${d.op} ${d.path} ${d.allowed ? "✓" : "✗ blocked"}`);
      break;
    case "drift":
      $("#status .drift-chip").hidden = false;
      $("#status .drift-chip").title = d.flags.join("\n");
      break;
    case "anomaly":
      $("#status .anomaly-chip").hidden = false;
      agg.currentKey = null;
      addRawToggle(addBlock("anomaly", null,
        `⚠ ${d.category}: ${d.detail}`), ev);
      break;
    case "unrecognized":
      agg.currentKey = null;
      addRawToggle(addBlock("unrecognized", null,
        `unrecognized protocol data (${d.why})`), ev);
      break;
    default:
      agg.currentKey = null;
      addRawToggle(addBlock("unrecognized", null,
        `unknown event kind ${ev.kind}`), ev);
  }
}

function showPermission(ev) {
  $("#perm-tool").textContent =
    JSON.stringify(ev.data.tool_call, null, 2);
  const box = $("#perm-options");
  box.replaceChildren(...ev.data.options.map((o, i) => {
    const b = document.createElement("button");
    b.dataset.option = o.optionId;
    b.textContent = `${i + 1}. ${o.name} (${o.kind})`;
    b.onclick = () => send({cmd: "permission",
                            request: ev.data.request, option: o.optionId});
    return b;
  }));
  $("#permission").showModal();
}

function send(obj) { ws.send(JSON.stringify(obj)); }

function sendPrompt() {
  const text = $("#prompt-input").value.trim();
  if (!text || turnActive) return;
  addBlock("message_chunk", "user", text);
  agg.currentKey = null;
  send({cmd: "prompt", text});
  $("#prompt-input").value = "";
}

$("#send").onclick = sendPrompt;
$("#cancel").onclick = () => send({cmd: "cancel"});
$("#prompt-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendPrompt(); }
});
$("#mode").onchange = () => send({cmd: "set_mode", mode: $("#mode").value});

initLauncher();
```

- [ ] **Step 4: Manual smoke** — `python -m claudiu --profiles agents --records "$TMPDIR/rec"` in a terminal that is NOT a Claude child; open the printed token URL; if `claude-code-acp` is installed, run one real prompt; otherwise use a profile pointing at `tests/fake_adapter.py`. Verify: launcher lists agents + caveats, prompt streams, permission dialog appears and answers, drift/anomaly chips stay hidden on clean traffic, raw toggle reveals frames.

- [ ] **Step 5: Commit** — `git add claudiu/ui/web && git commit -m "feat(ui): web view — launcher, conversation, composer, permission dialog"`

---

### Task 16: ui/web interactions + Playwright e2e

**Files:**
- Modify: `claudiu/ui/web/app.js` (+ palette markup in `index.html`, styles)
- Test: `tests/test_e2e_ui.py`

**Interfaces:**
- Produces: command palette — typing `/` first in an empty composer opens `#palette` listing `window._commands` (name + description), filtered as you type; Enter/click inserts the command; commands are ONLY submitted on explicit send (the toad `/model` lesson: never auto-issue, always render the response, which arrives as ordinary events). Escape closes. Keyboard on the permission dialog: digits 1..9 select the matching option; `Escape` does nothing (explicit choice required).

- [ ] **Step 1: Failing e2e test** — `tests/test_e2e_ui.py` (skip cleanly when playwright is missing, same pattern as v0.1; server subprocess launched with the fake-adapter profile and `--records` under tmp; the token comes from parsing the printed URL):

```python
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import pytest

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def server():
    tmp = Path(tempfile.mkdtemp())
    profs = tmp / "agents"
    profs.mkdir()
    from tests.test_server import FIXTURE_PROFILE
    (profs / "fake.toml").write_text(
        FIXTURE_PROFILE.format(python=sys.executable), encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "claudiu", "--profiles", str(profs),
         "--records", str(tmp / "rec")],
        stdout=subprocess.PIPE, text=True, encoding="utf-8")
    url = None
    deadline = time.time() + 20
    while time.time() < deadline:
        line = proc.stdout.readline()
        m = re.search(r"(http://127\.0\.0\.1:\d+/\?token=\S+)", line or "")
        if m:
            url = m.group(1)
            break
    assert url, "server never printed its URL"
    yield url, tmp
    proc.terminate()


def test_full_turn_and_permission(server):
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        page.goto(url)
        page.select_option("#profile", "fake")
        page.fill("#cwd", str(tmp))
        page.click("#start")
        page.wait_for_selector("#workspace:not([hidden])")
        page.fill("#prompt-input", "say hello")
        page.click("#send")
        page.wait_for_selector('[data-kind="turn_ended"]')
        convo = page.inner_text("#conversation")
        assert "hello world" in convo
        # permission round trip
        page.fill("#prompt-input", "do the PERMISSION thing")
        page.click("#send")
        page.wait_for_selector("#permission[open]")
        page.click('#perm-options button[data-option="y"]')
        page.wait_for_selector("#permission:not([open])")


def test_permission_reject_path(server):
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        page.goto(url)
        page.select_option("#profile", "fake")
        page.fill("#cwd", str(tmp))
        page.click("#start")
        page.wait_for_selector("#workspace:not([hidden])")
        page.fill("#prompt-input", "do the PERMISSION thing")
        page.click("#send")
        page.wait_for_selector("#permission[open]")
        page.click('#perm-options button[data-option="n"]')
        page.wait_for_selector('[data-kind="turn_ended"]')
```

- [ ] **Step 2: Implement the palette + digit keys** (additions to `app.js`):

```javascript
// Command palette: '/' in an empty composer lists agent-advertised commands.
const promptEl = $("#prompt-input");
promptEl.addEventListener("input", () => {
  const v = promptEl.value;
  const pal = $("#palette");
  if (!v.startsWith("/") || !window._commands?.length) {
    if (pal) pal.hidden = true;
    return;
  }
  ensurePalette().hidden = false;
  renderPalette(v.slice(1).toLowerCase());
});

function ensurePalette() {
  let pal = $("#palette");
  if (!pal) {
    pal = document.createElement("div");
    pal.id = "palette";
    $("#composer").prepend(pal);
  }
  return pal;
}

function renderPalette(filter) {
  const pal = $("#palette");
  const cmds = window._commands.filter(c =>
    c.name.toLowerCase().includes(filter));
  pal.replaceChildren(...cmds.map(c => {
    const b = document.createElement("button");
    b.textContent = `/${c.name} — ${c.description || ""}`;
    b.onclick = () => {
      promptEl.value = `/${c.name} `;
      pal.hidden = true;
      promptEl.focus();
    };
    return b;
  }));
  if (!cmds.length) pal.hidden = true;
}

document.addEventListener("keydown", (e) => {
  const dlg = $("#permission");
  if (dlg.open && /^[1-9]$/.test(e.key)) {
    const btn = $("#perm-options").children[Number(e.key) - 1];
    if (btn) btn.click();
  }
  if (e.key === "Escape" && $("#palette") && !$("#palette").hidden) {
    $("#palette").hidden = true;
    e.preventDefault();
  }
});
$("#permission").addEventListener("cancel", (e) => e.preventDefault());
```
Add `#palette` styles (dropdown above the composer) to `style.css`.

- [ ] **Step 3: Run** — Bash `python -m pytest tests/test_e2e_ui.py -q` → 2 passed (skips under PowerShell python; that is expected and fine). Full suite green.

- [ ] **Step 4: Commit** — `git add claudiu/ui/web tests/test_e2e_ui.py && git commit -m "feat(ui): command palette, permission keyboard, e2e coverage"`

---

### Task 17: Contract tier — the real adapter

**Files:**
- Test: `tests/contract/test_real_adapter.py`, `tests/contract/__init__.py`

**Interfaces:** none new. Gate: runs only when `CLAUDIU_CONTRACT=1` AND `claude-code-acp` is on PATH; otherwise skips with a reason.

- [ ] **Step 1: Write the test**

```python
"""Contract tests against the real claude-code-acp adapter.

Run: CLAUDIU_CONTRACT=1 python -m pytest tests/contract/ -q
Costs real tokens; requires claude credentials and the adapter installed.
"""
import os
import queue
import shutil
import pytest
from claudiu.core.acp import AcpSession
from claudiu.core.policy import PathPolicy
from claudiu.core.profiles import load_profile
from claudiu.core.record import Recorder
from claudiu.core.sentinel import Sentinel
from claudiu.server.app import LocalFiles
from claudiu.server.procs import SubprocessAgentProcess
from pathlib import Path

pytestmark = pytest.mark.skipif(
    os.environ.get("CLAUDIU_CONTRACT") != "1"
    or shutil.which("claude-code-acp") is None,
    reason="contract tier: set CLAUDIU_CONTRACT=1 with adapter installed")


class QueueSink:
    def __init__(self):
        self.q = queue.Queue()

    def emit(self, event):
        self.q.put(event)


def test_real_handshake_prompt_and_drift_silence(tmp_path):
    profile = load_profile(Path("agents/claude.toml"))
    sink = QueueSink()
    holder = {}
    proc = SubprocessAgentProcess(
        command=profile.command, cwd=str(tmp_path),
        env_scrub=profile.env_scrub, env_set=profile.env_set,
        on_line=lambda ln: holder["s"].on_line(ln),
        on_stderr=lambda ln: None,
        on_exit=lambda code: None)
    session = AcpSession(
        sid="contract", profile=profile, proc=proc, sink=sink,
        recorder=Recorder(tmp_path / "contract.jsonl"),
        sentinel=Sentinel.load_default(),
        policy=PathPolicy(tmp_path), files=LocalFiles())
    holder["s"] = session
    session.start(str(tmp_path))

    seen = []   # every event, so nothing (e.g. a drift flag) is lost

    def wait_for(kind, timeout=120):
        import time
        end = time.time() + timeout
        while time.time() < end:
            try:
                ev = sink.q.get(timeout=1)
            except queue.Empty:
                continue
            seen.append(ev)
            if ev.kind == kind:
                return ev
            if ev.kind == "session_state" and ev.data["state"] == "failed":
                pytest.fail(f"session failed: {ev.data}")
        pytest.fail(f"timed out waiting for {kind}")

    ready = wait_for("session_state")
    while ready.data["state"] != "ready":
        ready = wait_for("session_state")
    session.prompt("Reply with exactly: CONTRACT-OK and nothing else.")
    ended = wait_for("turn_ended")
    assert ended.data["stop_reason"] == "end_turn"
    session.close()

    while not sink.q.empty():
        seen.append(sink.q.get())
    drift = [ev.data for ev in seen if ev.kind == "drift"]
    text = "".join(
        e["frame"]["params"]["update"]["content"]["text"]
        for _, e in Recorder(tmp_path / "contract.jsonl").replay()
        if e.get("dir") == "in"
        and e["frame"].get("method") == "session/update"
        and e["frame"]["params"]["update"].get("sessionUpdate")
        == "agent_message_chunk")
    assert "CONTRACT-OK" in text
    assert drift == [], f"REAL ADAPTER DRIFTED: {drift} — update the registry"
```

- [ ] **Step 2: Run it once for real** — `CLAUDIU_CONTRACT=1 python -m pytest tests/contract/ -q` from a shell that is not a Claude child (env scrub makes this safe anyway — that is the point of the profile). Must pass against the live adapter. If a `drift` event fires here, the registry needs a correction — fix the registry (or the field names in `acp.py` if reality disagrees with the plan), never loosen the assertion.

- [ ] **Step 3: Commit** — `git add tests/contract && git commit -m "test: contract tier against the real claude-code-acp adapter"`

---

### Task 18: Documentation, conformance, version

**Files:**
- Modify: `README.md` (rewrite), `AGENTS.md` (rewrite), `CHANGELOG.md` (append), `claudiu/__init__.py` (version `0.2.0`), `pyproject.toml` (version), `.github/workflows/*` (adjust test paths if needed)
- Test: full suite + conformance

- [ ] **Step 1: README rewrite** — sections: what it is (browser ACP client, Windows-native, agent-agnostic); quickstart (install adapter via npm, `pip install -e .`, `python -m claudiu`, open token URL); architecture diagram of the four layers; the losslessness & drift story (record files, chips, `vendor/acp/VERSION`); security model (localhost + token + path boundary + env scrub); how to add another agent (`agents/*.toml` + PROFILE-SCHEMA.md); the "Verified by N checks" line with the real count from a FULL suite run (the v0.1 lesson: this test only passes on full runs).
- [ ] **Step 2: AGENTS.md rewrite** — dev workflow (Bash python 3.13 runs everything incl. e2e; PowerShell 3.14 skips e2e; contract tier opt-in), layer rules (core imports nothing, UI reads only UI-PROTOCOL.md), never `git add -A`, KEEP/GITHUBIFY pointers.
- [ ] **Step 3: CHANGELOG** — `## 0.2.0` — the ACP pivot: summary of D1–D4 with a pointer to the two spec docs; "v0.1 archived to archive/claudiu-v0.1 (own git history)".
- [ ] **Step 4: Versions** — `claudiu/__init__.py` → `0.2.0`; `pyproject.toml` → `0.2.0`.
- [ ] **Step 5: Verify everything** —

```bash
python -m pytest tests/ -q                      # full suite, count for README
python -m pyflakes claudiu tools tests
<run the GITHUBIFY conformance checker against the repo>
python tools/check_schema_drift.py
```
All green / FAIL=0 before the commit. If conformance flags the archive or vendor dirs, fix per its guidance (vendored data needs its licence noted in NOTICE — done in Task 4).
- [ ] **Step 6: Commit** — `git add README.md AGENTS.md CHANGELOG.md claudiu/__init__.py pyproject.toml && git commit -m "docs+release: CLAUDIU 0.2.0 — the ACP client"` (plus `.github` if changed). Tag/release stays with Fabio's publication flow (GITHUBIFY phases) — not this plan.

---

## Execution notes

- Tasks 2–9 are pure-stdlib and Windows/POSIX-neutral; nothing needs WSL anywhere.
- Tasks must run in order; 15 depends on 14 (the UI consumes the documented protocol, not the code).
- The permission fail-safe timer (Task 12) defaults to 3600 s — one hour to answer, then auto-reject; configurable via `SessionManager(permission_timeout=...)`.
- If the real ACP schema (Task 4) or real adapter traffic (Task 17) contradicts a field name in this plan, the registry/`acp.py` is corrected to match REALITY, the drift test proves it, and the correction is noted in the commit message — the plan's field names came from live traffic on 2026-08-31 and are expected to hold.
- After every task: full `python -m pytest tests/ -q` — not just the task's file.

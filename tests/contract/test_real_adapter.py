"""Contract tests against the real claude-code-acp adapter.

Run: CLAUDIU_CONTRACT=1 python -m pytest tests/contract/ -q
Costs real tokens; requires claude credentials and the adapter installed.
"""
import os
import queue
import shutil
import pytest
from pathlib import Path
from claudiu.core.acp import AcpSession
from claudiu.core.policy import PathPolicy
from claudiu.core.profiles import load_profile
from claudiu.core.record import Recorder
from claudiu.core.sentinel import Sentinel
from claudiu.server.app import LocalFiles
from claudiu.server.procs import SubprocessAgentProcess

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

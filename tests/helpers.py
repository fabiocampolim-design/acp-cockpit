# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
from acp_cockpit.core.acp import AcpSession
from acp_cockpit.core.policy import PathPolicy
from acp_cockpit.core.profiles import load_profile
from acp_cockpit.core.record import Recorder
from acp_cockpit.core.sentinel import Sentinel


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
        self.dirs = None          # a set of directories, or None = the real fs

    def is_dir(self, path: str) -> bool:
        if self.dirs is not None:
            return path in self.dirs
        import os
        return os.path.isdir(path)

    def read_text(self, path: str) -> str:
        return self.store[path]

    def write_text(self, path: str, content: str) -> None:
        self.store[path] = content


def make_session(tmp_path, **kw):
    """`profile=` overrides the Claude profile — the engine's agent-specific
    behaviour is profile data, so tests must be able to vary it."""
    proc, sink = FakeProc(), SinkList()
    session = AcpSession(
        sid="s1",
        profile=kw.pop("profile", load_profile(Path("acp_cockpit/agents/claude.toml"))),
        proc=proc, sink=sink,
        recorder=Recorder(tmp_path / "s1.jsonl"),
        sentinel=kw.pop("sentinel", Sentinel.load_default()),
        policy=PathPolicy(tmp_path),
        files=kw.pop("files", FakeFiles()),
        **kw)
    return session, proc, sink

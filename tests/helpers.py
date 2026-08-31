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

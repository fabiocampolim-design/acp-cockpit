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

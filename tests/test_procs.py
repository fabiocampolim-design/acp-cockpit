import json
import sys
import threading
from pathlib import Path
import pytest
from claudiu.server.procs import SubprocessAgentProcess, resolve_command

CHILD = str(Path("tests/child_lines.py").resolve())


def collectors():
    lines, errs, exits = [], [], []
    done = threading.Event()
    return lines, errs, exits, done


def spawn(tmp_path, lines, errs, exits, done, env_scrub=(), env_set=None):
    return SubprocessAgentProcess(
        command=[sys.executable, CHILD],
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

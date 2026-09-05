# SPDX-License-Identifier: Apache-2.0
import json
import sys
import threading
from pathlib import Path
import pytest
from acp_cockpit.server.procs import SubprocessAgentProcess, resolve_command

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


# ---- env_resolve: VAR -> command name, resolved on PATH after the scrub ----
from acp_cockpit.server import procs  # noqa: E402


def test_env_resolve_points_var_at_the_command_on_path(monkeypatch):
    # An inherited value is scrubbed (CLAUDE_CODE_* is the nested-session
    # guard); the resolved one is added AFTER the scrub, so it survives.
    monkeypatch.setenv("CLAUDE_CODE_EXECUTABLE", "C:/inherited/claude.exe")
    monkeypatch.setattr(procs.shutil, "which",
                        lambda cmd: {"claude": "C:/tools/claude.exe"}.get(cmd))
    env = procs.build_env(["CLAUDE_CODE_*"], {},
                          {"CLAUDE_CODE_EXECUTABLE": "claude"})
    assert env["CLAUDE_CODE_EXECUTABLE"] == "C:/tools/claude.exe"


def test_env_set_beats_env_resolve_and_missing_command_leaves_var_unset(
        monkeypatch):
    monkeypatch.setattr(procs.shutil, "which", lambda cmd: None)
    env = procs.build_env([], {"A": "explicit"},
                          {"A": "claude", "B": "not-installed-xyz"})
    assert env["A"] == "explicit"
    assert "B" not in env
    assert procs.resolve_env({"A": "claude", "B": "not-installed-xyz"},
                             {"A": "explicit"}) == {}


def test_env_resolve_reaches_the_child_and_is_reported(tmp_path):
    import shutil
    exe = Path(sys.executable).name          # python.exe / python3 / python
    expected = shutil.which(exe)
    if expected is None:
        pytest.skip("interpreter name not resolvable on PATH")
    lines, errs, exits, done = collectors()
    proc = SubprocessAgentProcess(
        command=[sys.executable, CHILD], cwd=str(tmp_path),
        env_scrub=[], env_set={}, env_resolve={"EXTRA_VAR": exe},
        on_line=lines.append, on_stderr=errs.append,
        on_exit=lambda code: (exits.append(code), done.set()))
    proc.send_line("QUIT")
    assert done.wait(timeout=15)
    assert json.loads(lines[0])["env_extra"] == expected
    assert proc.resolved_env == {"EXTRA_VAR": expected}

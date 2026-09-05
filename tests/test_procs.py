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


# ---- the whole process TREE dies with the adapter (review 2026-09-05) ----
import os          # noqa: E402
import subprocess  # noqa: E402
import time        # noqa: E402

TREE = str(Path("tests/child_tree.py").resolve())
PARENT_DIES = str(Path("tests/parent_dies.py").resolve())


def alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV",
                              "/NH"], capture_output=True, text=True).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_dead(pid: int, timeout=15) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.2)
    return False


def test_kill_takes_the_grandchildren_too(tmp_path):
    # The adapter is a node process that starts the CLI as ITS child; killing
    # the adapter alone left the CLI running for days.
    lines, errs, exits, done = collectors()
    proc = SubprocessAgentProcess(
        command=[sys.executable, TREE], cwd=str(tmp_path),
        env_scrub=[], env_set={},
        on_line=lines.append, on_stderr=errs.append,
        on_exit=lambda code: (exits.append(code), done.set()))
    end = time.time() + 15
    while not lines and time.time() < end:
        time.sleep(0.1)
    grandchild = json.loads(lines[0])["grandchild"]
    assert alive(grandchild)
    proc.kill()
    assert done.wait(timeout=15)
    assert wait_dead(grandchild), "the grandchild survived kill()"


def test_kill_does_not_block_the_caller_even_when_the_child_resists(tmp_path):
    # kill() used to wait up to five seconds per session ON THE IOLOOP for a
    # child that ignored terminate. Escalation happens off the caller's thread.
    lines, errs, exits, done = collectors()
    proc = spawn(tmp_path, lines, errs, exits, done,
                 env_set={"IGNORE_TERM": "1"})
    end = time.time() + 15
    while not lines and time.time() < end:
        time.sleep(0.1)
    t0 = time.time()
    proc.kill()
    assert time.time() - t0 < 1.0, "kill() blocked the caller"
    assert done.wait(timeout=20), "the resisting child was never killed"


@pytest.mark.skipif(os.name != "nt", reason="Windows job object semantics")
def test_children_die_with_a_hard_killed_parent(tmp_path):
    # `Stop-Process` on the pinned server is TerminateProcess: no handler
    # runs. Only a job object with kill-on-close reaps the adapters then.
    helper = subprocess.Popen([sys.executable, PARENT_DIES],
                              stdout=subprocess.PIPE, text=True)
    child = json.loads(helper.stdout.readline())["child"]
    assert alive(child)
    helper.kill()
    helper.wait(timeout=15)
    assert wait_dead(child), "the adapter outlived its hard-killed server"


# ---- review 2026-09-05 (independent /code-review of the release range) ----

def test_finish_waits_for_the_tree_and_hard_kills_what_resists(tmp_path):
    # kill() escalates on a daemon thread; at interpreter exit that thread is
    # torn down before the grace period ends and a SIGTERM-resistant tree
    # survived. finish() is the synchronous end used on the shutdown paths.
    lines, errs, exits, done = collectors()
    proc = spawn(tmp_path, lines, errs, exits, done,
                 env_set={"IGNORE_TERM": "1"})
    end = time.time() + 15
    while not lines and time.time() < end:
        time.sleep(0.1)
    proc.kill()
    t0 = time.time()
    assert proc.finish(timeout=8) is not None, "finish() did not return an exit code"
    assert time.time() - t0 < 9
    assert done.wait(timeout=5)


def test_the_tree_guard_is_reported(tmp_path):
    # Whether the tree is protected is recorded, never assumed: a job object
    # that could not be created or attached leaves `tree_guard` False and the
    # spawn record says so.
    lines, errs, exits, done = collectors()
    proc = spawn(tmp_path, lines, errs, exits, done)
    try:
        assert isinstance(proc.tree_guard, bool)
        if os.name == "nt":
            assert proc.tree_guard is True
    finally:
        proc.kill()
        proc.finish(timeout=10)


@pytest.mark.skipif(sys.platform != "linux", reason="PR_SET_PDEATHSIG is Linux")
def test_children_die_with_a_hard_killed_parent_on_linux(tmp_path):
    helper = subprocess.Popen([sys.executable, PARENT_DIES],
                              stdout=subprocess.PIPE, text=True)
    child = json.loads(helper.stdout.readline())["child"]
    assert alive(child)
    helper.kill()                                   # SIGKILL: no handler runs
    helper.wait(timeout=15)
    assert wait_dead(child), "the adapter outlived its SIGKILLed server"

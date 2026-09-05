# SPDX-License-Identifier: Apache-2.0
"""Adapter subprocess: plain pipes, scrubbed env, reader threads.

Threading contract: on_line / on_stderr / on_exit fire on internal reader
threads. The server marshals them onto its IOLoop; core never sees threads.

The adapter is a process TREE — the node adapter starts the agent's CLI as
its own child — and the whole tree must die with the session. Terminating the
adapter alone left ten CLI processes resident for a week (review
2026-09-05). On Windows every adapter is placed in a job object with
kill-on-close, so the tree dies even when this server is killed hard
(`Stop-Process`, which runs no handler); on POSIX the adapter starts its own
process group and the group is signalled.
"""
from __future__ import annotations

import fnmatch
import os
import shutil
import signal
import subprocess
import threading

GRACE_SECONDS = 5.0     # terminate → kill escalation, off the caller's thread


def resolve_command(argv: list[str]) -> list[str]:
    exe = shutil.which(argv[0])
    if exe is None:
        raise FileNotFoundError(argv[0])
    return [exe, *argv[1:]]


def resolve_env(env_resolve: dict | None, env_set: dict | None = None) -> dict:
    """Profile `env_resolve` (VAR -> command name): VAR becomes the command's
    absolute PATH entry when one is found. An explicit `env_set` value wins;
    a command that is not installed leaves VAR unset, so the agent falls
    back to whatever it ships. Applied AFTER the scrub: the Claude profile
    uses it for CLAUDE_CODE_EXECUTABLE, which the CLAUDE_CODE_* guard would
    otherwise strip (2026-09-01: the adapter's bundled CLI was refused by
    the API for a new model; the user's `claude` was not)."""
    out = {}
    for var, cmd in (env_resolve or {}).items():
        if env_set and var in env_set:
            continue
        path = shutil.which(cmd)
        if path:
            out[var] = path
    return out


def build_env(env_scrub: list[str], env_set: dict,
              env_resolve: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not any(fnmatch.fnmatch(k, pat) for pat in env_scrub)}
    env.update(resolve_env(env_resolve, env_set))
    env.update(env_set)
    return env


# ---- Windows job object: the tree dies with the job handle -----------------

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BASIC_LIMITS(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _EXTENDED_LIMITS(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BASIC_LIMITS),
                    ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    def _job_for(proc_handle):
        """A job object holding one adapter tree; closing it kills the tree.
        Returns None (and the tree is unprotected) only if the OS refuses."""
        job = _k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _EXTENDED_LIMITS()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = _k32.SetInformationJobObject(
            job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
            ctypes.sizeof(info))
        if ok and _k32.AssignProcessToJobObject(job, proc_handle):
            return job
        _k32.CloseHandle(job)
        return None

    def _terminate_job(job):
        _k32.TerminateJobObject(job, 1)

    def _close_job(job):
        _k32.CloseHandle(job)


class SubprocessAgentProcess:
    def __init__(self, command, cwd, env_scrub, env_set,
                 on_line, on_stderr, on_exit, env_resolve=None):
        self.resolved_env = resolve_env(env_resolve, env_set)  # for the record
        popen_kwargs = {}
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True   # its own process group
        self._proc = subprocess.Popen(
            resolve_command(command), cwd=cwd,
            env=build_env(env_scrub, env_set, env_resolve),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", bufsize=1, **popen_kwargs)
        self._job = _job_for(self._proc._handle) if os.name == "nt" else None
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

    @property
    def pid(self) -> int:
        return self._proc.pid

    def _pump(self, stream, callback):
        for line in stream:
            callback(line.rstrip("\n"))

    def _reap(self):
        code = self._proc.wait()
        if self._job is not None:
            # the adapter is gone; closing the job takes any stragglers
            _close_job(self._job)
            self._job = None
        self._on_exit(code)

    def send_line(self, line: str) -> None:
        try:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError):
            pass  # dead child; _reap reports it

    def kill(self) -> None:
        """Ask the tree to stop, and make sure it does — without blocking the
        caller: the escalation from terminate to kill waits on its own
        thread, not on the IOLoop (kill() used to hold it up to five seconds
        per session)."""
        if self._proc.poll() is not None:
            return
        self._signal_tree(hard=False)
        threading.Thread(target=self._escalate, daemon=True).start()

    def _escalate(self):
        try:
            self._proc.wait(timeout=GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self._signal_tree(hard=True)

    def _signal_tree(self, hard: bool) -> None:
        try:
            if os.name == "nt":
                if self._job is not None:
                    _terminate_job(self._job)      # the whole tree at once
                else:
                    self._proc.kill()
            else:
                os.killpg(os.getpgid(self._proc.pid),
                          signal.SIGKILL if hard else signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass                                  # already gone

    def wait(self, timeout=None):
        return self._proc.wait(timeout=timeout)

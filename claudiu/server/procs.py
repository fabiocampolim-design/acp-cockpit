# SPDX-License-Identifier: Apache-2.0
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

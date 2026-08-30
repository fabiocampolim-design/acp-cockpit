# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""Claude sessions in ConPTYs: lifetime, replay buffers, metadata.

Sessions outlive websocket connections; the browser is a disposable view.
"""
from __future__ import annotations

import collections
import itertools
import logging
import time
from pathlib import Path

from terminado import NamedTermManager, TermSocket

log = logging.getLogger(__name__)


class SessionManager(NamedTermManager):
    """One named terminal per Claude session, with a capped replay buffer."""

    def __init__(self, config: dict):
        super().__init__(shell_command=list(config["claude_command"]))
        self._config = config
        self._meta: dict = {}
        self._ids = itertools.count(1)

    def create_session(self, cwd, args=(), title=None) -> dict:
        argv = list(self._config["claude_command"]) + list(args)
        sid = f"s{next(self._ids)}"
        term = self.new_terminal(shell_command=argv, cwd=str(cwd))
        term.term_name = sid
        term.read_buffer = collections.deque(
            term.read_buffer, maxlen=self._config["replay_chunks"])
        self.terminals[sid] = term
        self.start_reading(term)
        self._meta[sid] = {
            "id": sid,
            "title": title or Path(cwd).resolve().name,
            "cwd": str(cwd),
            "args": list(args),
            "created": time.time(),
        }
        log.info("session %s started: argv=%s cwd=%s", sid, argv, cwd)
        return dict(self._meta[sid])

    def list_sessions(self) -> list:
        out = []
        for sid, term in list(self.terminals.items()):
            info = dict(self._meta.get(sid, {"id": sid}))
            try:
                info["alive"] = bool(term.ptyproc.isalive())
            except Exception:  # a broken pty must not break listing
                info["alive"] = False
            out.append(info)
        out.sort(key=lambda i: i.get("created", 0))
        return out

    def rename(self, sid: str, title: str) -> None:
        self._meta[sid]["title"] = title

    async def kill_session(self, sid: str) -> None:
        if sid not in self.terminals:
            raise KeyError(sid)
        term = self.terminals[sid]
        clients = list(term.clients)
        await self.terminate(sid, force=True)
        # terminado's normal EOF path is pty_read(): on EOFError it calls
        # on_eof() (ptys_by_fd/IOLoop-handler/terminals/_meta bookkeeping
        # plus ptyproc.close(), via NamedTermManager.on_eof -> our
        # override -> TermManagerBase.on_eof) and then notifies every
        # attached client with on_pty_died(). That only runs off the
        # IOLoop's fd-read callback once it observes EOF, and on this
        # Windows/pywinpty backend (the pty is read via a loopback socket
        # serviced by a background thread) that notification measurably
        # lags past terminate() returning -- confirmed empirically. A
        # forced kill_session() bypasses pty_read() entirely, so mirror
        # both halves of its EOFError branch here ourselves, rather than
        # leaving the pty's socket pair unclosed and any attached
        # websocket client stranded with no death signal. Guard against
        # on_eof() having already won the race and done this first (rare,
        # but possible during terminate()'s internal sleeps).
        fd = getattr(term.ptyproc, "fd", None)
        if fd is not None and fd in self.ptys_by_fd:
            self.on_eof(term)
            for client in clients:
                client.on_pty_died()
        # else: on_eof() already raced ahead of us and did all of this,
        # client notifications included.
        log.info("session %s killed", sid)

    def on_eof(self, ptywclients) -> None:
        sid = getattr(ptywclients, "term_name", None)
        super().on_eof(ptywclients)
        self._meta.pop(sid, None)
        log.info("session %s ended (eof)", sid)


class ClaudiuTermSocket(TermSocket):
    """TermSocket that closes cleanly when the session id is unknown."""

    def open(self, url_component=None):
        try:
            super().open(url_component)
        except KeyError:
            log.warning("websocket for unknown session %r", url_component)
            self.close(4404, "no such session")

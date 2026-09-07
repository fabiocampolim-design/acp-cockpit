# SPDX-License-Identifier: Apache-2.0
"""What happens when things die.

Every test here is a finding of the 2026-09-06 full product review: the ways
a session, a probe or a fail-safe timer could outlive the thing it belonged
to, and the ways a live adapter tree could end up with nothing holding a
reference to it.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest
import tornado.ioloop
import tornado.testing

from acp_cockpit.server import app as app_mod
from acp_cockpit.server.app import SessionManager
from acp_cockpit.server.procs import SubprocessAgentProcess

FIXTURE = str(Path("tests/fixtures/basic_turn.json").resolve())
ADAPTER = str(Path("tests/fake_adapter.py").resolve())

PROFILE = '''
id = "fake"
name = "Fake Agent"
command = [{python!r}, {adapter!r}, {fixture!r}]
install_hint = "n/a"
env_scrub = []
'''


def _profiles(tmp: Path) -> Path:
    profs = tmp / "agents"
    profs.mkdir()
    (profs / "fake.toml").write_text(
        PROFILE.format(python=sys.executable, adapter=ADAPTER,
                       fixture=FIXTURE), encoding="utf-8")
    return profs


class RecordingProc:
    """Stands in for SubprocessAgentProcess: a spawn that really happened."""
    instances: list = []

    def __init__(self, **kw):
        self.killed = False
        self.finished = False
        self.resolved_env = {}
        self.tree_guard = True
        self.pid = 4242
        RecordingProc.instances.append(self)

    def send_line(self, line):
        pass

    def kill(self):
        self.killed = True

    def finish(self, timeout=None):
        self.finished = True


class LifecycleTest(tornado.testing.AsyncTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        RecordingProc.instances = []

    def _manager(self, **kw):
        return SessionManager(profiles_dir=_profiles(self.tmp),
                              records_dir=self.tmp / "rec", **kw)

    def test_a_spawn_that_fails_after_the_fork_kills_the_adapter(self):
        """`_spawn` forked the adapter BEFORE building the Recorder, with no
        try/except: any failure there and the entry never reached `_entries`,
        so `close_all()` could not see the live process and no reference to
        kill() survived — the ten-orphans incident, through the error path."""
        mgr = self._manager()

        def boom(*a, **kw):
            raise OSError("records dir is read-only")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(app_mod, "SubprocessAgentProcess", RecordingProc)
            mp.setattr(app_mod, "Recorder", boom)
            with pytest.raises(OSError):
                mgr.create("fake", str(self.tmp))
        assert RecordingProc.instances, "no adapter was spawned at all"
        assert RecordingProc.instances[0].killed, \
            "the adapter was forked and then abandoned"
        assert mgr.list() == []

    def test_close_all_reaches_a_probe_adapter(self):
        """The session/list probe spawned a real adapter that was never
        registered in `_entries`, so the SIGINT/SIGTERM/atexit close_all()
        guarantee did not cover it."""
        mgr = self._manager()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(app_mod, "SubprocessAgentProcess", RecordingProc)
            mgr.list_agent_sessions("fake", str(self.tmp))
            assert RecordingProc.instances, "no probe adapter was spawned"
            mgr.close_all(wait=True)
        probe = RecordingProc.instances[0]
        assert probe.killed or probe.finished, \
            "close_all left the probe adapter running"

    def test_closing_a_session_cancels_its_fail_safe_timers(self):
        """The permission/elicitation fail-safe timers (an hour by default)
        were never cancelled on close or evict: they kept the session, its
        recorder, its sink and its adapter reachable for the rest of the hour
        and then fired against a torn-down session, so the fail-safe decision
        never reached the record that exists to prove nothing was dropped."""
        mgr = self._manager()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(app_mod, "SubprocessAgentProcess", RecordingProc)
            sid = mgr.create("fake", str(self.tmp))
            entry = mgr.get(sid)
            entry.session.acp_session_id = "acp-1"
            entry.sink.emit(_permission_event(sid))
            assert mgr.pending_timers(sid), "no fail-safe timer was armed"
            mgr.close(sid)
            assert not mgr.pending_timers(sid), \
                "the fail-safe timer outlived the session"


    @tornado.testing.gen_test
    async def test_an_adapter_that_never_answers_does_not_pin_the_session(self):
        """An adapter that starts but hangs — an auth prompt on stdin, a
        wedged CLI — never ran `_on_initialized`, so the state stayed
        "starting" for ever. `evict` only ever arms from a failed or closed
        session_state, so the entry, its record and its process tree lived for
        the life of the server and closing the tab did nothing. The throwaway
        probe path already had a timer; the real one had none (2026-09-06)."""
        import asyncio
        mgr = self._manager(startup_timeout=0.05, dead_ttl=0.05)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(app_mod, "SubprocessAgentProcess", RecordingProc)
            sid = mgr.create("fake", str(self.tmp))
            assert mgr.get(sid).session.state == "starting"
            await asyncio.sleep(0.3)
            assert mgr.get(sid) is None, "the wedged session was never evicted"
        assert RecordingProc.instances[0].killed


def _permission_event(sid):
    from acp_cockpit.core.events import make_event
    return make_event("permission_request", sid, 1,
                      {"request": 44, "options": []}, None)


def test_the_process_group_is_captured_before_the_leader_is_reaped(
        tmp_path, monkeypatch):
    """`_reap` called os.killpg(self._proc.pid) on the line AFTER
    self._proc.wait() had reaped the leader, so the pid was already free for
    reuse and the SIGKILL could land on an unrelated process group (review
    2026-09-06). The target must be the pgid captured at spawn."""
    proc = SubprocessAgentProcess.__new__(SubprocessAgentProcess)
    import threading
    proc._job = None
    proc._job_lock = threading.Lock()
    proc._pgid = 1111
    exits = []
    proc._on_exit = exits.append

    class Reaped:
        pid = 1111

        def wait(self):
            Reaped.pid = 2222          # the kernel handed the pid on
            return 0

    proc._proc = Reaped()
    signalled = []
    import signal as signal_mod
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(signal_mod, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: signalled.append(pgid),
                        raising=False)
    proc._reap()
    assert exits == [0]
    assert signalled == [1111], \
        f"signalled {signalled}, i.e. a pid re-read after the reap"


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_a_real_adapter_records_its_process_group(tmp_path):
    lines = []
    proc = SubprocessAgentProcess(
        command=[sys.executable, str(Path("tests/child_lines.py").resolve())],
        cwd=str(tmp_path), env_scrub=[], env_set={},
        on_line=lines.append, on_stderr=lines.append, on_exit=lambda c: None)
    assert proc._pgid == proc.pid
    proc.kill()


class FakeLoop:
    def __init__(self):
        self.scheduled = []
        self.stopped = False

    def add_callback_from_signal(self, fn, *a):
        self.scheduled.append(lambda: fn(*a))

    def stop(self):
        self.stopped = True


class FakeManager:
    def __init__(self):
        self.closed = []

    def close_all(self, wait=False):
        self.closed.append(wait)


def test_a_signal_schedules_the_teardown_instead_of_running_it():
    """The SIGINT/SIGTERM handler ran the whole teardown inline. A signal
    handler runs between bytecodes on the main thread, so that re-entered the
    IOLoop's timeout heap and wrote to WebSockets from inside it, and blocked
    for up to the grace period PER SESSION before the loop was told to stop
    (review 2026-09-06). The handler schedules; the loop does the work."""
    from acp_cockpit.__main__ import make_shutdown
    loop, mgr = FakeLoop(), FakeManager()
    handler = make_shutdown(mgr, loop)

    handler(2, None)                     # as the signal module calls it
    assert mgr.closed == [], "the teardown ran inside the signal handler"
    assert len(loop.scheduled) == 1

    loop.scheduled[0]()
    assert mgr.closed == [True], mgr.closed
    assert loop.stopped

    # a second Ctrl+C must not queue a second teardown on top of the first
    handler(2, None)
    assert len(loop.scheduled) == 1

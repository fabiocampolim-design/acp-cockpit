# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
import copy
import sys
from pathlib import Path

import tornado.gen
from tornado.testing import AsyncTestCase, gen_test

from claudiu.config import DEFAULTS
from claudiu.sessions import SessionManager

ECHO_CMD = [sys.executable, "-u", "-c",
            "import sys\nprint('READY', flush=True)\n"
            "for line in sys.stdin:\n"
            "    print('echo:' + line.strip(), flush=True)\n"]


def make_cfg(**over):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["claude_command"] = ECHO_CMD
    cfg.update(over)
    return cfg


async def wait_for(term, text, timeout=15.0):
    for _ in range(int(timeout / 0.1)):
        if text in "".join(term.read_buffer):
            return
        await tornado.gen.sleep(0.1)
    raise AssertionError(
        f"{text!r} not seen; buffer: {''.join(term.read_buffer)!r}")


class SessionTests(AsyncTestCase):

    @gen_test(timeout=30)
    async def test_create_lists_alive_session(self):
        mgr = SessionManager(make_cfg())
        info = mgr.create_session(cwd=".", title="demo")
        assert info["id"].startswith("s")
        assert info["title"] == "demo"
        term = mgr.get_terminal(info["id"])
        await wait_for(term, "READY")
        listed = mgr.list_sessions()
        assert [s["id"] for s in listed] == [info["id"]]
        assert listed[0]["alive"] is True
        await mgr.kill_session(info["id"])

    @gen_test(timeout=30)
    async def test_create_session_stores_absolute_cwd(self):
        mgr = SessionManager(make_cfg())
        info = mgr.create_session(cwd=".")
        assert Path(info["cwd"]).is_absolute()
        await mgr.kill_session(info["id"])

    @gen_test(timeout=30)
    async def test_replay_buffer_uses_configured_cap(self):
        mgr = SessionManager(make_cfg(replay_chunks=7))
        info = mgr.create_session(cwd=".")
        term = mgr.get_terminal(info["id"])
        assert term.read_buffer.maxlen == 7
        await mgr.kill_session(info["id"])

    @gen_test(timeout=30)
    async def test_stdin_roundtrip(self):
        mgr = SessionManager(make_cfg())
        info = mgr.create_session(cwd=".")
        term = mgr.get_terminal(info["id"])
        await wait_for(term, "READY")
        # Windows ConPTY's console input layer treats CR, not LF, as the
        # "submit this line" key (POSIX ttys in canonical mode take LF).
        # A raw "\n" here sits in ConPTY's input buffer unread; real
        # keystrokes from xterm.js already send "\r" for Enter, so this
        # matches production traffic on this platform.
        term.ptyproc.write("hello\r\n")
        await wait_for(term, "echo:hello")
        await mgr.kill_session(info["id"])

    @gen_test(timeout=30)
    async def test_kill_removes_only_that_session(self):
        mgr = SessionManager(make_cfg())
        a = mgr.create_session(cwd=".")
        b = mgr.create_session(cwd=".")
        await wait_for(mgr.get_terminal(b["id"]), "READY")
        await mgr.kill_session(a["id"])
        remaining = mgr.list_sessions()
        assert [s["id"] for s in remaining] == [b["id"]]
        assert remaining[0]["alive"] is True
        await mgr.kill_session(b["id"])

    @gen_test(timeout=30)
    async def test_kill_closes_pty_and_notifies_clients(self):
        mgr = SessionManager(make_cfg())
        info = mgr.create_session(cwd=".")
        term = mgr.get_terminal(info["id"])
        await wait_for(term, "READY")

        class FakeClient:
            def __init__(self):
                self.died = False

            def on_pty_died(self):
                self.died = True

        client = FakeClient()
        term.clients.append(client)

        await mgr.kill_session(info["id"])

        assert client.died is True
        assert [s["id"] for s in mgr.list_sessions()] == []
        assert term.ptyproc.isalive() is False
        assert getattr(term.ptyproc, "closed", True) is True

    @gen_test(timeout=30)
    async def test_rename_and_unknown_ids(self):
        mgr = SessionManager(make_cfg())
        info = mgr.create_session(cwd=".")
        mgr.rename(info["id"], "renamed")
        assert mgr.list_sessions()[0]["title"] == "renamed"
        try:
            mgr.rename("nope", "x")
            raise AssertionError("expected KeyError")
        except KeyError:
            pass
        await mgr.kill_session(info["id"])


class ChildEnvTests(AsyncTestCase):
    """A session spawned by CLAUDIU is a top-level Claude session, not a
    child of whatever Claude Code session happened to launch the server.
    Inherited nesting markers make the CLI disable transcript saving."""

    def test_nested_claude_markers_are_stripped_from_child_env(self):
        import os
        from unittest import mock
        leaked = {
            "CLAUDECODE": "1",
            "CLAUDE_CODE_CHILD_SESSION": "1",
            "CLAUDE_CODE_SESSION_ID": "abc",
            "CLAUDE_PID": "123",
            "CLAUDE_CODE_MESSAGING_SOCKET": "x",
            "CLAUDE_CODE_MESSAGING_TOKEN": "y",
            "CLAUDE_CODE_BRIDGE_SESSION_ID": "z",
            "CLAUDE_CODE_ENTRYPOINT": "cli",
            "CLAUDE_CODE_EXECPATH": "p",
            # user-level configuration must survive the scrub
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "4096",
        }
        with mock.patch.dict(os.environ, leaked):
            env = SessionManager(make_cfg()).make_term_env()
        for name in leaked:
            if name == "CLAUDE_CODE_MAX_OUTPUT_TOKENS":
                assert env[name] == "4096"
            else:
                assert name not in env, f"{name} leaked into the session"


class ArgvTests(AsyncTestCase):
    """Session id and theme injection (no process is spawned here)."""

    def test_fresh_session_gets_a_uuid_and_the_theme(self):
        mgr = SessionManager(make_cfg(claude_theme="dark-ansi"))
        argv, sid = mgr.build_argv([])
        assert argv[:len(ECHO_CMD)] == ECHO_CMD
        assert argv[len(ECHO_CMD):len(ECHO_CMD) + 2] == ["--session-id", sid]
        assert len(sid) == 36
        assert argv[-2:] == ["--settings", '{"theme": "dark-ansi"}']

    def test_resume_keeps_the_given_id_and_own_settings_win(self):
        mgr = SessionManager(make_cfg(claude_theme="dark-ansi"))
        argv, sid = mgr.build_argv(["--resume", "abc", "--settings", "x.json"])
        assert sid == "abc"
        assert "--session-id" not in argv
        assert argv.count("--settings") == 1
        argv, sid = mgr.build_argv(["--session-id=zzz"])
        assert sid == "zzz" and argv.count("--session-id=zzz") == 1

    def test_continue_and_empty_theme_inject_nothing(self):
        mgr = SessionManager(make_cfg(claude_theme=""))
        argv, sid = mgr.build_argv(["--continue"])
        assert sid is None
        assert argv == ECHO_CMD + ["--continue"]
        argv, sid = mgr.build_argv(["--resume"])  # bare: interactive picker
        assert sid is None and "--session-id" not in argv

    @gen_test(timeout=30)
    async def test_status_all_reads_the_transcript_when_it_appears(self):
        import json
        import tempfile
        from claudiu.status import transcript_path
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SessionManager(make_cfg(context_window_tokens=1000),
                                 claude_dir=tmp)
            info = mgr.create_session(cwd=".", title="demo")
            sid = info["id"]
            assert info["session_id"]
            assert mgr.status_all()[sid]["state"] == "unknown"
            path = transcript_path(info["cwd"], info["session_id"], tmp)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "type": "assistant", "message": {
                    "stop_reason": "end_turn", "content": [],
                    "usage": {"input_tokens": 500}}}) + "\n"
                + json.dumps({"type": "last-prompt", "lastPrompt": "hi"}) + "\n",
                encoding="utf-8")
            st = mgr.status_all()[sid]
            assert st["state"] == "ready" and st["last_prompt"] == "hi"
            assert st["context_pct"] == 50.0
            # the located transcript must not leak into the JSON listing
            # (it did once: a WindowsPath in _meta made /api/sessions a 500)
            json.dumps(mgr.list_sessions())
            # unchanged file -> cached object
            assert mgr.status_all()[sid] is st
            await mgr.kill_session(sid)
            assert mgr.status_all() == {}

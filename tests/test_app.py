# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
import copy
import json
import os
import sys
import tempfile

import tornado.escape
import tornado.gen
import tornado.websocket
from tornado.testing import AsyncHTTPTestCase, gen_test

from claudiu.app import make_app
from claudiu.config import DEFAULTS
from claudiu.sessions import SessionManager

ECHO_CMD = [sys.executable, "-u", "-c",
            "import sys\nprint('READY', flush=True)\n"
            "for line in sys.stdin:\n"
            "    print('echo:' + line.strip(), flush=True)\n"]


class AppTests(AsyncHTTPTestCase):

    def get_app(self):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["claude_command"] = ECHO_CMD
        self.manager = SessionManager(cfg)
        self.config_dir = tempfile.mkdtemp()
        return make_app(cfg, self.manager, warnings=["w1"],
                        config_dir=self.config_dir)

    def _post(self, url, body, headers=None):
        hdrs = {"Content-Type": "application/json"}
        if headers:
            hdrs.update(headers)
        return self.fetch(url, method="POST", body=json.dumps(body),
                          headers=hdrs, raise_error=False)

    def test_sessions_lifecycle(self):
        resp = self.fetch("/api/sessions")
        assert json.loads(resp.body) == {"sessions": []}
        resp = self._post("/api/sessions", {"path": "."})
        assert resp.code == 201
        sid = json.loads(resp.body)["id"]
        resp = self.fetch("/api/sessions")
        assert json.loads(resp.body)["sessions"][0]["id"] == sid
        resp = self.fetch(f"/api/sessions/{sid}", method="PATCH",
                          body=json.dumps({"title": "mine"}),
                          headers={"Content-Type": "application/json"},
                          raise_error=False)
        assert resp.code == 200
        resp = self.fetch("/api/sessions")
        assert json.loads(resp.body)["sessions"][0]["title"] == "mine"
        resp = self.fetch(f"/api/sessions/{sid}", method="DELETE",
                          headers={"Content-Type": "application/json"},
                          raise_error=False)
        assert resp.code == 204
        resp = self.fetch("/api/sessions")
        assert json.loads(resp.body) == {"sessions": []}

    def test_bad_path_is_400_with_message(self):
        resp = self._post("/api/sessions", {"path": "Z:/does/not/exist"})
        assert resp.code == 400
        assert "error" in json.loads(resp.body)

    def test_foreign_origin_is_403(self):
        resp = self._post("/api/sessions", {"path": "."},
                          headers={"Origin": "http://evil.example"})
        assert resp.code == 403
        assert "error" in json.loads(resp.body)

    def test_foreign_host_is_403(self):
        resp = self.fetch("/api/sessions",
                          headers={"Host": "evil.example"},
                          raise_error=False)
        assert resp.code == 403
        assert "error" in json.loads(resp.body)

    def test_non_json_content_type_is_403(self):
        resp = self.fetch("/api/sessions", method="POST", body="path=.",
                          headers={"Content-Type": "text/plain"},
                          raise_error=False)
        assert resp.code == 403
        assert "error" in json.loads(resp.body)

    def test_unknown_session_is_404(self):
        resp = self.fetch("/api/sessions/nope", method="DELETE",
                          headers={"Content-Type": "application/json"},
                          raise_error=False)
        assert resp.code == 404
        assert "error" in json.loads(resp.body)

    def test_config_endpoint(self):
        body = json.loads(self.fetch("/api/config").body)
        assert body["config"]["port"] == DEFAULTS["port"]
        assert body["warnings"] == ["w1"]

    def test_status_endpoint_shape(self):
        created = json.loads(self._post("/api/sessions", {"path": "."}).body)
        resp = self.fetch("/api/status")
        assert resp.code == 200
        sessions = json.loads(resp.body)["sessions"]
        st = sessions[created["id"]]
        assert st["state"] == "unknown" and st["last_prompt"] is None
        assert set(st) >= {"exists", "state", "last_prompt",
                           "context_tokens", "context_pct"}

    def test_conversation_endpoint_shape_and_404(self):
        created = json.loads(self._post("/api/sessions", {"path": "."}).body)
        resp = self.fetch("/api/conversation?id=" + created["id"])
        assert resp.code == 200
        data = json.loads(resp.body)
        assert set(data) >= {"exists", "meta", "turns", "title", "permission"}
        assert isinstance(data["turns"], list)
        # permission options are parsed client-side now; the server sends none
        assert data["permission"] is None
        assert self.fetch("/api/conversation?id=nope").code == 404

    def test_launching_records_a_recent_folder(self):
        cwd = os.getcwd()
        assert self._post("/api/sessions", {"path": cwd}).code == 201
        recent = json.loads(self.fetch("/api/recent").body)["recent"]
        assert recent and os.path.samefile(recent[0]["path"], cwd)

    def test_dirs_endpoint_lists_subdirectories(self):
        d = tempfile.mkdtemp()
        os.mkdir(os.path.join(d, "sub"))
        resp = self.fetch("/api/dirs?path=" + tornado.escape.url_escape(d))
        assert resp.code == 200
        data = json.loads(resp.body)
        assert [x["name"] for x in data["dirs"]] == ["sub"]

    def test_mkdir_endpoint_creates_and_validates(self):
        d = tempfile.mkdtemp()
        ok = self._post("/api/mkdir", {"parent": d, "name": "made"})
        assert ok.code == 200
        assert os.path.isdir(os.path.join(d, "made"))
        bad = self._post("/api/mkdir", {"parent": d, "name": "a/b"})
        assert bad.code == 400

    def test_resume_endpoint_shape(self):
        body = json.loads(self.fetch("/api/resume").body)
        assert "projects" in body and "report" in body

    def test_index_served(self):
        resp = self.fetch("/")
        assert resp.code == 200
        assert b"CLAUDIU" in resp.body
        for asset in ("app.css", "vendor/xterm.js", "vendor/xterm.css",
                      "vendor/addon-fit.js", "vendor/addon-search.js",
                      "vendor/addon-web-links.js"):
            assert self.fetch("/" + asset).code == 200, asset

    def test_websocket_streams_output(self):
        # self.fetch() (used by _post) runs its own io_loop.run_sync per
        # call; nesting that inside a @gen_test coroutine on this
        # installed Tornado/Windows combo trips the Proactor event loop's
        # "already running" assertion. Drive the whole test body through
        # a single self.io_loop.run_sync instead (the brief's documented
        # fallback), using self.http_client.fetch directly so nothing
        # else starts a nested loop. Assertions are unchanged.
        self.io_loop.run_sync(self._websocket_streams_output, timeout=30)

    async def _websocket_streams_output(self):
        resp = await self.http_client.fetch(
            self.get_url("/api/sessions"), method="POST",
            body=json.dumps({"path": "."}),
            headers={"Content-Type": "application/json"}, raise_error=False)
        sid = json.loads(resp.body)["id"]
        url = f"ws://127.0.0.1:{self.get_http_port()}/ws/{sid}"
        ws = await tornado.websocket.websocket_connect(url)
        seen = ""
        while "READY" not in seen:
            msg = await ws.read_message()
            assert msg is not None, "websocket closed before READY"
            data = json.loads(msg)
            if data[0] == "stdout":
                seen += data[1]
        ws.close()

    def test_set_size_resizes_pty(self):
        # Same nested-run_sync constraint as test_websocket_streams_output.
        self.io_loop.run_sync(self._set_size_resizes_pty, timeout=30)

    async def _set_size_resizes_pty(self):
        resp = await self.http_client.fetch(
            self.get_url("/api/sessions"), method="POST",
            body=json.dumps({"path": "."}),
            headers={"Content-Type": "application/json"}, raise_error=False)
        sid = json.loads(resp.body)["id"]
        url = f"ws://127.0.0.1:{self.get_http_port()}/ws/{sid}"
        ws = await tornado.websocket.websocket_connect(url)
        seen = ""
        while "READY" not in seen:
            msg = await ws.read_message()
            assert msg is not None, "websocket closed before READY"
            data = json.loads(msg)
            if data[0] == "stdout":
                seen += data[1]
        ws.write_message(json.dumps(["set_size", 30, 100, 0, 0]))
        ptyproc = self.manager.get_terminal(sid).ptyproc
        winsize = None
        for _ in range(50):
            winsize = ptyproc.getwinsize()
            if winsize == (30, 100):
                break
            await tornado.gen.sleep(0.1)
        assert winsize == (30, 100)
        ws.close()

    @gen_test(timeout=30)
    async def test_websocket_unknown_session_closes_without_spawning(self):
        url = f"ws://127.0.0.1:{self.get_http_port()}/ws/nope"
        ws = await tornado.websocket.websocket_connect(url)
        msg = await ws.read_message()
        assert msg is None, "unknown session should close, not stream"
        assert ws.close_code == 4404
        assert self.manager.list_sessions() == []


class FaviconTests(AsyncHTTPTestCase):
    """Browsers request /favicon.ico on every load; without one the log
    fills with 404 warnings and the tab shows a blank icon."""

    def get_app(self):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["claude_command"] = ECHO_CMD
        return make_app(cfg, SessionManager(cfg), config_dir=tempfile.mkdtemp())

    def test_favicon_svg_served(self):
        resp = self.fetch("/favicon.svg")
        assert resp.code == 200
        assert resp.headers["Content-Type"].startswith("image/svg+xml")

    def test_favicon_ico_is_not_a_404(self):
        resp = self.fetch("/favicon.ico", follow_redirects=False,
                          raise_error=False)
        assert resp.code in (301, 302)
        assert resp.headers["Location"].endswith("/favicon.svg")

    def test_page_links_the_icon(self):
        resp = self.fetch("/")
        assert b'rel="icon"' in resp.body

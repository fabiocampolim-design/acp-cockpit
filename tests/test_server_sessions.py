# SPDX-License-Identifier: Apache-2.0
"""Server: agent session listing (probe) and resume."""
import json
import sys
import tempfile
from pathlib import Path
import tornado.httpclient
import tornado.testing
import tornado.websocket
from claudiu.server.app import make_app
from claudiu.server.auth import TokenAuth

PROFILE = '''
id = "cmds"
name = "Commands Agent"
command = [{python}, {adapter}, {fixture}]
install_hint = "n/a"
env_scrub = []
'''.replace("{adapter}", json.dumps(str(Path("tests/fake_adapter.py").resolve()))
).replace("{fixture}",
          json.dumps(str(Path("tests/fixtures/commands_turn.json").resolve())))


class SessionsTest(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        profs = self.tmpdir / "agents"
        profs.mkdir()
        (profs / "cmds.toml").write_text(
            PROFILE.replace("{python}", json.dumps(sys.executable)),
            encoding="utf-8")
        self.auth = TokenAuth()
        return make_app(profiles_dir=profs,
                        records_dir=self.tmpdir / "records", auth=self.auth)

    def _headers(self):
        return {"Cookie": f"claudiu_token={self.auth.token}"}

    def test_list_agent_sessions_via_probe(self):
        resp = self.fetch(f"/api/profiles/cmds/sessions?cwd={self.tmpdir}",
                          headers=self._headers(), request_timeout=40)
        assert resp.code == 200, resp.body
        data = json.loads(resp.body)
        assert data["sessions"][0]["sessionId"] == "old-1"
        assert data["sessions"][0]["title"] == "Old work"
        # the probe never became a live session
        live = json.loads(self.fetch("/api/sessions",
                                     headers=self._headers()).body)
        assert live["sessions"] == []

    def test_resume_reaches_ready_and_reports_title(self):
        resp = self.fetch("/api/sessions", method="POST",
                          headers=self._headers(),
                          body=json.dumps({"profile": "cmds",
                                           "cwd": str(self.tmpdir),
                                           "resume": "old-1"}))
        assert resp.code == 200
        sid = json.loads(resp.body)["id"]

        async def drive():
            url = (f"ws://127.0.0.1:{self.get_http_port()}"
                   f"/ws/sessions/{sid}")
            conn = await tornado.websocket.websocket_connect(
                tornado.httpclient.HTTPRequest(url, headers=self._headers()))
            modes = []
            while True:
                ev = json.loads(await conn.read_message())
                if ev["kind"] == "mode":
                    modes.append(ev["data"]["current"])
                if ev["kind"] == "session_state" and \
                        ev["data"]["state"] == "ready":
                    break
            assert modes[-1] == "plan"        # from session/resume's result
            conn.close()
        self.io_loop.run_sync(drive, timeout=30)
        live = json.loads(self.fetch("/api/sessions",
                                     headers=self._headers()).body)
        assert live["sessions"][0]["agent_session"] == "old-1"

    def test_new_session_carries_usage_title_and_config(self):
        resp = self.fetch("/api/sessions", method="POST",
                          headers=self._headers(),
                          body=json.dumps({"profile": "cmds",
                                           "cwd": str(self.tmpdir)}))
        sid = json.loads(resp.body)["id"]

        async def drive():
            url = (f"ws://127.0.0.1:{self.get_http_port()}"
                   f"/ws/sessions/{sid}")
            conn = await tornado.websocket.websocket_connect(
                tornado.httpclient.HTTPRequest(url, headers=self._headers()))
            seen = {}
            while True:
                ev = json.loads(await conn.read_message())
                seen[ev["kind"]] = ev["data"]
                if ev["kind"] == "session_state" and \
                        ev["data"]["state"] == "ready":
                    break
            assert seen["usage"]["used"] == 59300
            assert seen["session_info"]["title"] == "Fixture session"
            assert seen["config_option"]["options"][0]["id"] == "effort"
            await conn.write_message(json.dumps(
                {"cmd": "set_config_option", "config": "effort",
                 "value": "low"}))
            while True:
                ev = json.loads(await conn.read_message())
                if ev["kind"] == "config_option" and \
                        ev["data"]["options"][0]["currentValue"] == "low":
                    break
            conn.close()
        self.io_loop.run_sync(drive, timeout=30)
        live = json.loads(self.fetch("/api/sessions",
                                     headers=self._headers()).body)
        assert live["sessions"][0]["title"] == "Fixture session"

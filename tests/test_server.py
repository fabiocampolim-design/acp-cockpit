# SPDX-License-Identifier: Apache-2.0
import json
import sys
import tempfile
from pathlib import Path
import tornado.httpclient
import tornado.testing
import tornado.websocket
from claudiu.server.app import make_app
from claudiu.server.auth import TokenAuth

# Absolute paths: sessions spawn with cwd=<session dir>, so relative
# script paths would not resolve.
FIXTURE_PROFILE = '''
id = "fake"
name = "Fake Agent"
command = [{python!r}, {adapter}, {fixture}]
install_hint = "n/a"
env_scrub = []
'''.replace("{adapter}", json.dumps(str(Path("tests/fake_adapter.py").resolve()))
).replace("{fixture}",
          json.dumps(str(Path("tests/fixtures/basic_turn.json").resolve())))


PY_NAME = Path(sys.executable).name          # python.exe / python3 / python


class ServerTest(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        profs = self.tmpdir / "agents"
        profs.mkdir()
        (profs / "fake.toml").write_text(
            FIXTURE_PROFILE.format(python=sys.executable), encoding="utf-8")
        # same adapter, plus an env_resolve entry that resolves on PATH
        (profs / "resolving.toml").write_text(
            FIXTURE_PROFILE.format(python=sys.executable).replace(
                'id = "fake"', 'id = "resolving"')
            + "[env_resolve]\nEXTRA_VAR = " + json.dumps(PY_NAME) + "\n",
            encoding="utf-8")
        self.auth = TokenAuth()
        return make_app(profiles_dir=profs,
                        records_dir=self.tmpdir / "records", auth=self.auth)

    def _headers(self):
        return {"Cookie": f"claudiu_token={self.auth.token}"}

    def test_profiles_listed(self):
        resp = self.fetch("/api/profiles", headers=self._headers())
        assert resp.code == 200
        data = json.loads(resp.body)
        assert data["profiles"][0]["id"] == "fake"
        by_id = {p["id"]: p for p in data["profiles"]}
        assert by_id["fake"]["env_resolved"] == {}
        import shutil
        assert by_id["resolving"]["env_resolved"] == \
            {"EXTRA_VAR": shutil.which(PY_NAME)}

    def test_spawn_is_recorded_with_the_resolved_environment(self):
        import shutil
        resp = self.fetch("/api/sessions", method="POST",
                          headers=self._headers(),
                          body=json.dumps({"profile": "resolving",
                                           "cwd": str(self.tmpdir)}))
        assert resp.code == 200
        sid = json.loads(resp.body)["id"]
        self.fetch(f"/api/sessions/{sid}", method="DELETE",
                   headers=self._headers())
        first = json.loads((self.tmpdir / "records" / f"{sid}.jsonl")
                           .read_text(encoding="utf-8").splitlines()[0])
        assert first["dir"] == "client" and first["action"] == "spawn"
        assert first["command"][1:] and first["command"][0]
        assert first["env_resolved"] == {"EXTRA_VAR": shutil.which(PY_NAME)}

    def test_no_token_is_403(self):
        resp = self.fetch("/api/profiles")
        assert resp.code == 403

    def test_session_lifecycle_and_ws_stream(self):
        resp = self.fetch("/api/sessions", method="POST",
                          headers=self._headers(),
                          body=json.dumps({"profile": "fake",
                                           "cwd": str(self.tmpdir)}))
        assert resp.code == 200
        sid = json.loads(resp.body)["id"]

        async def drive():
            url = (f"ws://127.0.0.1:{self.get_http_port()}"
                   f"/ws/sessions/{sid}")
            conn = await tornado.websocket.websocket_connect(
                tornado.httpclient.HTTPRequest(url, headers=self._headers()))
            # wait for ready
            while True:
                ev = json.loads(await conn.read_message())
                if ev["kind"] == "session_state" and \
                        ev["data"]["state"] == "ready":
                    break
            await conn.write_message(json.dumps(
                {"cmd": "prompt", "text": "say hello"}))
            texts, ended = [], False
            while not ended:
                ev = json.loads(await conn.read_message())
                if ev["kind"] == "message_chunk" and \
                        ev["data"]["role"] == "agent":
                    texts.append(ev["data"]["text"])
                elif ev["kind"] == "turn_ended":
                    ended = True
            assert "".join(texts) == "hello world"
            conn.close()
        self.io_loop.run_sync(drive, timeout=30)

    def test_permission_roundtrip_over_ws(self):
        resp = self.fetch("/api/sessions", method="POST",
                          headers=self._headers(),
                          body=json.dumps({"profile": "fake",
                                           "cwd": str(self.tmpdir)}))
        sid = json.loads(resp.body)["id"]

        async def drive():
            url = (f"ws://127.0.0.1:{self.get_http_port()}"
                   f"/ws/sessions/{sid}")
            conn = await tornado.websocket.websocket_connect(
                tornado.httpclient.HTTPRequest(url, headers=self._headers()))
            while True:
                ev = json.loads(await conn.read_message())
                if ev["kind"] == "session_state" and \
                        ev["data"]["state"] == "ready":
                    break
            await conn.write_message(json.dumps(
                {"cmd": "prompt", "text": "do the PERMISSION thing"}))
            request_id = None
            while request_id is None:
                ev = json.loads(await conn.read_message())
                if ev["kind"] == "permission_request":
                    request_id = ev["data"]["request"]
                    assert ev["data"]["options"][0]["kind"] == "allow_once"
            await conn.write_message(json.dumps(
                {"cmd": "permission", "request": request_id,
                 "option": "y"}))
            while True:
                ev = json.loads(await conn.read_message())
                if ev["kind"] == "permission_resolved":
                    assert ev["data"]["option"] == "y"
                    break
            conn.close()
        self.io_loop.run_sync(drive, timeout=30)

    def test_drift_endpoint_offline(self):
        resp = self.fetch("/api/drift", headers=self._headers())
        assert resp.code == 200
        data = json.loads(resp.body)
        assert data["pinned_schema"].startswith("schema-v")
        assert data["online"] is False

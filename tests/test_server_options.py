# SPDX-License-Identifier: Apache-2.0
"""Session-creation options, the one-attachment rule, and archiving.

Everything here is about what happens BEFORE and AROUND a session: which
options it is created with, whether a second UI may attach to the same agent
session, and handing a finished conversation to the archiver.
"""
import json
import sys
import tempfile
from pathlib import Path

import tornado.testing

from claudiu.server.app import make_app
from claudiu.server.auth import TokenAuth
FIXTURE_PROFILE = """
id = "fake"
name = "Fake Agent"
command = [{python!r}, ADAPTER, FIXTURE]
install_hint = "n/a"
env_scrub = []
""".replace("ADAPTER", json.dumps(
    str(Path("tests/fake_adapter.py").resolve()))).replace(
    "FIXTURE", json.dumps(
        str(Path("tests/fixtures/commands_turn.json").resolve())))

ARCHIVER = '''# SPDX-License-Identifier: Apache-2.0
"""Stand-in for transcript_archiver.py: records its argv, prints a path."""
import json
import sys
from pathlib import Path

out = Path(sys.argv[0]).with_name("archiver-argv.json")
out.write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
print("wrote " + str(out.with_name("session.html")) + " (0.01 MB)")
'''


class OptionsTest(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        profs = self.tmpdir / "agents"
        profs.mkdir()
        (profs / "fake.toml").write_text(
            FIXTURE_PROFILE.format(python=sys.executable), encoding="utf-8")
        self.archiver = self.tmpdir / "fake_archiver.py"
        self.archiver.write_text(ARCHIVER, encoding="utf-8")
        self.auth = TokenAuth()
        return make_app(profiles_dir=profs,
                        records_dir=self.tmpdir / "records", auth=self.auth,
                        archiver=str(self.archiver))

    def _headers(self):
        return {"Cookie": f"claudiu_token={self.auth.token}"}

    def _post(self, body, expect=200):
        resp = self.fetch("/api/sessions", method="POST",
                          headers=self._headers(), body=json.dumps(body))
        assert resp.code == expect, (resp.code, resp.body)
        return json.loads(resp.body)

    # ---- session-creation options ----------------------------------------
    def test_client_options_from_the_launcher_reach_the_agent(self):
        # Thinking cannot be changed mid-session over ACP, so the choice is
        # made where the session is created and rides along in `_meta`.
        sid = self._post({"profile": "fake", "cwd": str(self.tmpdir),
                          "client_options": {"thinking": {"type": "disabled"}}
                          })["id"]
        entry = self._app.manager.get(sid)
        self.io_loop.run_sync(lambda: _until(
            self.io_loop, lambda: entry.session.state == "ready"), timeout=30)
        out = [e["frame"] for _, e in entry.session.recorder.replay()
               if e.get("dir") == "out"]
        new = [f for f in out if f.get("method") == "session/new"][0]
        assert new["params"]["_meta"]["claudeCode"]["options"]["thinking"] == \
            {"type": "disabled"}

    def test_client_options_must_be_an_object(self):
        body = json.loads(self.fetch(
            "/api/sessions", method="POST", headers=self._headers(),
            body=json.dumps({"profile": "fake", "cwd": str(self.tmpdir),
                             "client_options": ["thinking"]})).body)
        assert "client_options" in body["error"]

    # ---- one attachment per agent session ---------------------------------
    def test_a_second_ui_cannot_attach_to_the_same_agent_session(self):
        # Two adapters resuming one agent session would write the same
        # transcript file: the second attempt is refused and points at the
        # session that already holds it.
        first = self._post({"profile": "fake", "cwd": str(self.tmpdir),
                            "resume": "fake-session-1"})["id"]
        clash = self._post({"profile": "fake", "cwd": str(self.tmpdir),
                            "resume": "fake-session-1"}, expect=409)
        assert clash["session"] == first
        assert "already" in clash["error"]

    def test_the_agent_session_is_free_again_once_it_is_closed(self):
        first = self._post({"profile": "fake", "cwd": str(self.tmpdir),
                            "resume": "fake-session-1"})["id"]
        self.fetch(f"/api/sessions/{first}", method="DELETE",
                   headers=self._headers())
        again = self._post({"profile": "fake", "cwd": str(self.tmpdir),
                            "resume": "fake-session-1"})
        assert again["id"] != first

    # ---- archiving --------------------------------------------------------
    def test_archive_hands_the_agent_session_id_to_the_archiver(self):
        sid = self._post({"profile": "fake", "cwd": str(self.tmpdir)})["id"]
        entry = self._app.manager.get(sid)
        self.io_loop.run_sync(lambda: _until(
            self.io_loop, lambda: entry.session.acp_session_id is not None),
            timeout=30)
        resp = self.fetch(f"/api/sessions/{sid}/archive", method="POST",
                          headers=self._headers(), body="{}",
                          request_timeout=60)
        assert resp.code == 200, resp.body
        data = json.loads(resp.body)
        assert data["ok"] is True
        assert "session.html" in " ".join(data["output"])
        argv = json.loads((self.tmpdir / "archiver-argv.json")
                          .read_text(encoding="utf-8"))
        assert argv[0] == "fake-session-1"
        assert "--format" in argv

    def test_archive_says_so_when_no_archiver_is_configured(self):
        app = make_app(profiles_dir=self.tmpdir / "agents",
                       records_dir=self.tmpdir / "records2", auth=self.auth)
        assert app.settings.get("archiver") is None


async def _until(loop, done, tries=300):
    import asyncio
    for _ in range(tries):
        if done():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition never became true")

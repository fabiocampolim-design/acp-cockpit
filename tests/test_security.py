# SPDX-License-Identifier: Apache-2.0
import json
import sys
import tempfile
import time
from pathlib import Path
import tornado.testing
from claudiu.server.app import make_app
from claudiu.server.auth import TokenAuth
from tests.test_server import FIXTURE_PROFILE


class SecurityTest(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        profs = self.tmpdir / "agents"
        profs.mkdir()
        (profs / "fake.toml").write_text(
            FIXTURE_PROFILE.format(python=sys.executable), encoding="utf-8")
        self.auth = TokenAuth()
        return make_app(profiles_dir=profs,
                        records_dir=self.tmpdir / "records", auth=self.auth)

    def ok_headers(self):
        return {"Cookie": f"claudiu_token={self.auth.token}"}

    def test_missing_token_403(self):
        assert self.fetch("/api/sessions").code == 403
        # the folder picker lists the filesystem: token-gated like the rest
        assert self.fetch("/api/dirs?path=").code == 403

    def test_wrong_token_403(self):
        r = self.fetch("/api/sessions",
                       headers={"Cookie": "claudiu_token=wrong"})
        assert r.code == 403

    def test_evil_host_403(self):
        r = self.fetch("/api/profiles", headers={
            **self.ok_headers(), "Host": "evil.example.com"})
        assert r.code == 403

    def test_evil_origin_403(self):
        r = self.fetch("/api/profiles", headers={
            **self.ok_headers(), "Origin": "http://evil.example.com"})
        assert r.code == 403

    def test_csp_header_present(self):
        r = self.fetch("/api/profiles", headers=self.ok_headers())
        assert "default-src 'self'" in r.headers["Content-Security-Policy"]

    def test_token_never_recorded(self):
        r = self.fetch("/api/sessions", method="POST",
                       headers=self.ok_headers(),
                       body=json.dumps({"profile": "fake",
                                        "cwd": str(self.tmpdir)}))
        assert r.code == 200
        time.sleep(1.0)   # let the handshake record
        recs = list((self.tmpdir / "records").glob("*.jsonl"))
        assert recs, "no record file written"
        for rec in recs:
            assert self.auth.token not in rec.read_text(encoding="utf-8")

    def test_session_ids_are_unguessable_format(self):
        r = self.fetch("/api/sessions", method="POST",
                       headers=self.ok_headers(),
                       body=json.dumps({"profile": "fake",
                                        "cwd": str(self.tmpdir)}))
        sid = json.loads(r.body)["id"]
        assert len(sid) >= 12

# SPDX-License-Identifier: Apache-2.0
import json
import sys
import tempfile
import time
from pathlib import Path
import tornado.testing
from acp_cockpit.server.app import make_app
from acp_cockpit.server.auth import TokenAuth
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
        return {"Cookie": f"acp_cockpit_token={self.auth.token}"}

    def test_missing_token_403(self):
        assert self.fetch("/api/sessions").code == 403
        # the folder picker lists the filesystem: token-gated like the rest
        assert self.fetch("/api/dirs?path=").code == 403

    def test_wrong_token_403(self):
        r = self.fetch("/api/sessions",
                       headers={"Cookie": "acp_cockpit_token=wrong"})
        assert r.code == 403

    def test_evil_host_403(self):
        r = self.fetch("/api/profiles", headers={
            **self.ok_headers(), "Host": "evil.example.com"})
        assert r.code == 403

    def test_evil_origin_403(self):
        r = self.fetch("/api/profiles", headers={
            **self.ok_headers(), "Origin": "http://evil.example.com"})
        assert r.code == 403

    def test_another_localhost_port_is_a_foreign_origin(self):
        # Cookies are NOT port-scoped: a page served from any other port on
        # the loopback interface sends our token automatically. Accepting
        # every `http://127.0.0.1:*` origin therefore handed the API to any
        # local web page (audit 2026-09-04). The origin must equal OUR own.
        for foreign in ("http://127.0.0.1:31337", "http://localhost:31337",
                        "http://127.0.0.1", "https://127.0.0.1:%d"):
            origin = foreign % self.get_http_port() if "%d" in foreign                 else foreign
            r = self.fetch("/api/profiles", headers={
                **self.ok_headers(), "Origin": origin})
            assert r.code == 403, (origin, r.code)

    def test_our_own_origin_is_accepted(self):
        r = self.fetch("/api/profiles", headers={
            **self.ok_headers(),
            "Origin": f"http://127.0.0.1:{self.get_http_port()}"})
        assert r.code == 200

    def test_a_request_without_an_origin_still_works(self):
        # Same-origin subresource GETs and non-browser clients send no
        # Origin at all; the token is what authenticates them.
        r = self.fetch("/api/profiles", headers=self.ok_headers())
        assert r.code == 200

    def test_the_ui_files_are_token_gated_too(self):
        # /ui/* was mounted as a bare StaticFileHandler, outside the guard:
        # no token, no host/origin check, no CSP header (audit 2026-09-04).
        assert self.fetch("/ui/app.js").code == 403
        r = self.fetch("/ui/app.js", headers=self.ok_headers())
        assert r.code == 200
        assert b"session" in r.body
        assert "default-src 'self'" in r.headers["Content-Security-Policy"]

    def test_the_page_carries_the_configured_name_not_a_placeholder(self):
        # The name is substituted server-side, so a reader never watches it
        # change one request after the page arrives.
        r = self.fetch("/", headers=self.ok_headers())
        assert r.code == 200
        body = r.body.decode("utf-8")
        assert "{{UI_NAME}}" not in body, "placeholder reached the browser"
        assert "<title>ClaudIU</title>" in body

    def test_the_ui_files_are_revalidated_not_cached(self):
        # "Reload the page" is the documented recovery from half the things
        # that go wrong; it only works if the reload fetches the new file.
        r = self.fetch("/ui/app.js", headers=self.ok_headers())
        assert r.headers["Cache-Control"] == "no-cache"
        assert r.headers.get("Etag"), "no ETag: revalidation would cost a body"

    def test_the_ui_files_refuse_a_foreign_origin(self):
        r = self.fetch("/ui/app.js", headers={
            **self.ok_headers(), "Origin": "http://127.0.0.1:31337"})
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

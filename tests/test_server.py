# SPDX-License-Identifier: Apache-2.0
import json
import sys
import tempfile
from pathlib import Path
import tornado.httpclient
import tornado.testing
import tornado.websocket
from acp_cockpit.server.app import make_app
from acp_cockpit.server.auth import TokenAuth

# Absolute paths: sessions spawn with cwd=<session dir>, so relative
# script paths would not resolve.
FIXTURE_PROFILE = '''
id = "fake"
name = "Fake Agent"
command = [{python!r}, {adapter}, {fixture}]
install_hint = "n/a"
env_scrub = []

meta = {{session_options = "claudeCode.options", prompt_suggestion = "_claude/promptSuggestion.suggestion", rate_limit = "_claude/rateLimit", parent_tool_call = "claudeCode.parentToolUseId", tool_name = "claudeCode.toolName"}}
launch_choices = [{{id = "thinking", label = "Thinking", title = "what the agent is asked to do about thinking", options = [{{value = "summarized", text = "summarized - show the model's own summary", client_options = {{thinking = {{type = "adaptive", display = "summarized"}}}}}}, {{value = "omitted", text = "omitted - think, but send nothing to show", client_options = {{thinking = {{type = "adaptive", display = "omitted"}}}}}}, {{value = "off", text = "off - don't request thinking at all", client_options = {{thinking = {{type = "disabled"}}}}}}]}}]
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
        return {"Cookie": f"acp_cockpit_token={self.auth.token}"}

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

    def test_bad_cwd_is_a_json_400_the_view_can_show(self):
        resp = self.fetch("/api/sessions", method="POST",
                          headers=self._headers(),
                          body=json.dumps({"profile": "fake", "cwd": ""}))
        assert resp.code == 400
        assert "cwd" in json.loads(resp.body)["error"]

    def test_listing_rejects_an_empty_cwd(self):
        # Path("") is the server's own directory: never list for it.
        resp = self.fetch("/api/profiles/fake/sessions?cwd=",
                          headers=self._headers())
        assert resp.code == 400
        data = json.loads(resp.body)
        assert data["sessions"] == [] and "directory" in data["error"]

    def test_no_token_is_403(self):
        resp = self.fetch("/api/profiles")
        assert resp.code == 403

    # ---- /api/dirs: the launcher's folder picker (2026-09-03) ----

    def test_dirs_lists_subdirectories_with_parent_and_roots(self):
        (self.tmpdir / "beta").mkdir()
        (self.tmpdir / "alpha").mkdir()
        (self.tmpdir / ".hidden").mkdir()
        (self.tmpdir / "afile.txt").write_text("x", encoding="utf-8")
        resp = self.fetch("/api/dirs?path=" + str(self.tmpdir),
                          headers=self._headers())
        assert resp.code == 200
        data = json.loads(resp.body)
        assert data["path"] == str(self.tmpdir.resolve())
        assert data["parent"] == str(self.tmpdir.resolve().parent)
        # files excluded; plain names first, dot-dirs last; native paths
        assert [d["name"] for d in data["dirs"]] == \
            ["agents", "alpha", "beta", ".hidden"]
        assert data["dirs"][1]["path"] == str((self.tmpdir / "alpha").resolve())
        assert data["roots"] and all(Path(r).is_dir() for r in data["roots"])
        assert data["error"] is None

    def test_dirs_empty_path_is_the_home_directory(self):
        resp = self.fetch("/api/dirs?path=", headers=self._headers())
        assert resp.code == 200
        assert json.loads(resp.body)["path"] == str(Path.home().resolve())

    def test_dirs_root_has_no_parent(self):
        root = Path(self.tmpdir.resolve().anchor)
        resp = self.fetch("/api/dirs?path=" + str(root),
                          headers=self._headers())
        assert resp.code == 200
        data = json.loads(resp.body)
        assert data["parent"] is None and data["path"] == str(root)

    def test_dirs_missing_path_is_a_json_400(self):
        resp = self.fetch("/api/dirs?path=" + str(self.tmpdir / "nope"),
                          headers=self._headers())
        assert resp.code == 400
        data = json.loads(resp.body)
        assert data["dirs"] == [] and "directory" in data["error"]

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

    def test_a_reconnect_asks_only_for_what_it_missed(self):
        # R1/R2 (audit 2026-09-04): the View comes back by itself after a
        # dropped socket, passing the last seq it holds — and must not be
        # handed the conversation a second time.
        resp = self.fetch("/api/sessions", method="POST",
                          headers=self._headers(),
                          body=json.dumps({"profile": "fake",
                                           "cwd": str(self.tmpdir)}))
        sid = json.loads(resp.body)["id"]

        async def drive():
            base = (f"ws://127.0.0.1:{self.get_http_port()}"
                    f"/ws/sessions/{sid}")
            first = await tornado.websocket.websocket_connect(
                tornado.httpclient.HTTPRequest(base, headers=self._headers()))
            seen = []
            while True:
                ev = json.loads(await first.read_message())
                seen.append(ev["seq"])
                if ev["kind"] == "session_state" and \
                        ev["data"]["state"] == "ready":
                    break
            first.close()
            again = await tornado.websocket.websocket_connect(
                tornado.httpclient.HTTPRequest(
                    f"{base}?after={max(seen)}", headers=self._headers()))
            await again.write_message(json.dumps(
                {"cmd": "prompt", "text": "say hello"}))
            fresh = []
            while True:
                ev = json.loads(await again.read_message())
                fresh.append(ev["seq"])
                if ev["kind"] == "turn_ended":
                    break
            again.close()
            return seen, fresh

        seen, fresh = self.io_loop.run_sync(drive, timeout=30)
        assert seen, "nothing replayed on the first attach"
        assert min(fresh) > max(seen), (
            f"the reconnect replayed events it already had: "
            f"{fresh} after {seen}")

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
        assert data["adapter_package"] is None      # fixture declares none

    def test_elicitation_roundtrip_over_ws(self):
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
                {"cmd": "prompt", "text": "do the ASKQUESTION thing"}))
            request_id = None
            while request_id is None:
                ev = json.loads(await conn.read_message())
                if ev["kind"] == "elicitation_request":
                    request_id = ev["data"]["request"]
                    props = ev["data"]["schema"]["properties"]
                    assert props["question_0"]["oneOf"][1]["const"] == "Blue"
                    assert ev["data"]["tool_call_id"] == "t-ask"
            await conn.write_message(json.dumps(
                {"cmd": "elicitation", "request": request_id,
                 "action": "accept",
                 "content": {"question_0": "Blue",
                             "question_1": ["Ice", "Lemon"]}}))
            while True:
                ev = json.loads(await conn.read_message())
                if ev["kind"] == "elicitation_resolved":
                    assert ev["data"]["action"] == "accept"
                    assert ev["data"]["source"] == "user"
                    break
            conn.close()
        self.io_loop.run_sync(drive, timeout=30)


class ElicitationTimeoutTest(tornado.testing.AsyncHTTPTestCase):
    """An unanswered question must not hold the agent's turn forever: the
    same fail-safe timer that rejects a stale permission declines it."""

    def get_app(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        profs = self.tmpdir / "agents"
        profs.mkdir()
        (profs / "fake.toml").write_text(
            FIXTURE_PROFILE.format(python=sys.executable), encoding="utf-8")
        self.auth = TokenAuth()
        return make_app(profiles_dir=profs,
                        records_dir=self.tmpdir / "records", auth=self.auth,
                        permission_timeout=0.3)

    def _headers(self):
        return {"Cookie": f"acp_cockpit_token={self.auth.token}"}

    def test_unanswered_elicitation_declines_itself(self):
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
                {"cmd": "prompt", "text": "do the ASKQUESTION thing"}))
            while True:                      # never answered by the user
                ev = json.loads(await conn.read_message())
                if ev["kind"] == "elicitation_resolved":
                    assert ev["data"]["action"] == "decline"
                    assert ev["data"]["source"] == "failsafe"
                    break
            conn.close()
        self.io_loop.run_sync(drive, timeout=30)


class DriftCacheTest(tornado.testing.AsyncHTTPTestCase):
    """The page asks /api/drift on every load; the two HTTPS lookups and the
    `npm ls -g` subprocess behind it run once per process per hour, not once
    per reload (review 2026-09-05)."""

    def get_app(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        profs = self.tmpdir / "agents"
        profs.mkdir()
        (profs / "fake.toml").write_text(
            FIXTURE_PROFILE.format(python=sys.executable)
            + 'npm_package = "some-adapter"\n', encoding="utf-8")
        self.auth = TokenAuth()
        return make_app(profiles_dir=profs, records_dir=self.tmpdir / "records",
                        auth=self.auth, drift_online=True)

    def test_the_online_lookup_is_cached(self):
        from acp_cockpit.server import app as appmod
        calls = []

        def fake_latest(pkg):
            calls.append(pkg)
            return {"schema": "schema-v1.21.0", "adapter_latest": "9.9.9",
                    "adapter_installed": "9.9.8"}
        appmod._DRIFT_CACHE.clear()
        original = appmod._latest_versions
        appmod._latest_versions = fake_latest
        try:
            h = {"Cookie": f"acp_cockpit_token={self.auth.token}"}
            first = json.loads(self.fetch("/api/drift", headers=h).body)
            second = json.loads(self.fetch("/api/drift", headers=h).body)
        finally:
            appmod._latest_versions = original
            appmod._DRIFT_CACHE.clear()
        assert first["flags"] and first["flags"] == second["flags"]
        assert calls == ["some-adapter"], calls


class ProfilesCarryLaunchChoicesTest(ServerTest):
    def test_profiles_route_carries_the_launch_choices(self):
        # The View builds the launcher's session-creation selects from these
        # (review 2026-09-06: the thinking select was hardcoded in the page).
        resp = self.fetch("/api/profiles", headers=self._headers())
        prof = json.loads(resp.body)["profiles"][0]
        assert [c["id"] for c in prof["launch_choices"]] == ["thinking"]
        assert prof["launch_choices"][0]["options"][2]["client_options"] == {
            "thinking": {"type": "disabled"}}

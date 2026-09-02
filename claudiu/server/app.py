# SPDX-License-Identifier: Apache-2.0
"""Tornado controller: REST + static + session manager."""
from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

import tornado.concurrent
import tornado.ioloop
import tornado.web

from ..core.acp import AcpSession
from ..core.policy import PathPolicy
from ..core.profiles import load_profiles
from ..core.record import Recorder
from ..core.sentinel import Sentinel
from .auth import COOKIE_NAME
from .procs import SubprocessAgentProcess, resolve_env
from .ws import BufferedSink, SessionWS

UI_DIR = Path(__file__).resolve().parents[1] / "ui" / "web"
VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "acp"

CSP = ("default-src 'self'; img-src 'self' data:; "
       "style-src 'self'; script-src 'self'")


def native_dir(cwd: str) -> str:
    """Agents match session cwd as an exact string (the Claude adapter's
    session/list finds nothing for C:/x but everything for C:\\x), so
    always hand them the resolved native form."""
    return str(Path(cwd).resolve())


class LocalFiles:
    def read_text(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8")

    def write_text(self, path: str, content: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


@dataclass
class Entry:
    session: AcpSession
    sink: BufferedSink
    profile_id: str
    cwd: str
    title: str | None = None


class SessionManager:
    def __init__(self, profiles_dir: Path, records_dir: Path,
                 permission_timeout: float = 3600.0):
        self.profiles = load_profiles(profiles_dir)
        self.records_dir = Path(records_dir)
        self.permission_timeout = permission_timeout
        self._entries: dict[str, Entry] = {}

    def _spawn(self, profile, cwd, sid, sink):
        loop = tornado.ioloop.IOLoop.current()
        holder = {}

        def marshal(fn):
            return lambda *a: loop.add_callback(fn, *a)

        proc = SubprocessAgentProcess(
            command=profile.command, cwd=cwd,
            env_scrub=profile.env_scrub, env_set=profile.env_set,
            env_resolve=profile.env_resolve,
            on_line=marshal(lambda ln: holder["s"].on_line(ln)),
            on_stderr=marshal(lambda ln: holder["s"].on_stderr(ln)),
            on_exit=marshal(lambda code: holder["s"].on_exit(code)))
        recorder = Recorder(self.records_dir / f"{sid}.jsonl")
        # First record of every session: what was launched and which
        # runtime it was pointed at — the answer to "which CLI ran this?".
        recorder.append({"dir": "client", "action": "spawn",
                         "command": list(profile.command),
                         "env_resolved": proc.resolved_env})
        session = AcpSession(
            sid=sid, profile=profile, proc=proc, sink=sink,
            recorder=recorder,
            sentinel=Sentinel.load_default(),
            policy=PathPolicy(cwd), files=LocalFiles())
        holder["s"] = session
        return session, loop

    def create(self, profile_id: str, cwd: str, resume: str | None = None) -> str:
        profile = self.profiles[profile_id]
        sid = uuid.uuid4().hex[:12]
        sink = BufferedSink()
        session, loop = self._spawn(profile, cwd, sid, sink)
        entry = Entry(session, sink, profile_id, cwd)
        self._watch_events(entry, loop)
        self._entries[sid] = entry
        if resume:
            session.load(resume, cwd)
        else:
            session.start(cwd)
        return sid

    def list_agent_sessions(self, profile_id: str, cwd: str):
        """Spawn a throwaway adapter, `session/list`, kill it. Returns a
        Future of the sessions list (empty + reason on failure)."""
        profile = self.profiles[profile_id]
        sid = "probe-" + uuid.uuid4().hex[:8]
        sink = BufferedSink()
        session, loop = self._spawn(profile, cwd, sid, sink)
        future = tornado.concurrent.Future()

        def done(sessions, error):
            session.close()
            if not future.done():
                future.set_result({"sessions": sessions,
                                   "error": (error or {}).get("message")
                                   if error else None})
        session.probe_sessions(cwd, done)
        loop.call_later(30, lambda: not future.done() and
                        done([], {"message": "session/list timed out"}))
        return future

    def _watch_events(self, entry, loop):
        session, sink = entry.session, entry.sink
        timers: dict[int, object] = {}
        original_emit = sink.emit

        def emit(event):
            original_emit(event)
            if event.kind == "session_info" and event.data.get("title"):
                entry.title = event.data["title"]
            if event.kind == "permission_request":
                rid = event.data["request"]

                def expire(rid=rid):
                    if rid in session.pending_permissions():
                        session.fail_safe_reject(rid)
                timers[rid] = loop.call_later(self.permission_timeout,
                                              expire)
            elif event.kind == "permission_resolved":
                t = timers.pop(event.data["request"], None)
                if t:
                    loop.remove_timeout(t)
        sink.emit = emit

    def get(self, sid):
        return self._entries.get(sid)

    def list(self):
        return [{"id": sid, "profile": e.profile_id, "cwd": e.cwd,
                 "state": e.session.state, "title": e.title,
                 "agent_session": e.session.acp_session_id}
                for sid, e in self._entries.items()]

    def close(self, sid):
        entry = self._entries.pop(sid, None)
        if entry:
            entry.session.close()

    def close_all(self):
        for sid in list(self._entries):
            self.close(sid)


class BaseHandler(tornado.web.RequestHandler):
    def initialize(self, manager=None, auth=None):
        self.manager = manager
        self.auth = auth

    def prepare(self):
        host = self.request.host_name
        if host not in ("127.0.0.1", "localhost"):
            raise tornado.web.HTTPError(403, "bad host")
        origin = self.request.headers.get("Origin")
        if origin and not origin.startswith(("http://127.0.0.1:",
                                             "http://localhost:")):
            raise tornado.web.HTTPError(403, "bad origin")
        if not self._authed():
            raise tornado.web.HTTPError(403, "auth")

    def _authed(self):
        return self.auth.verify(self.get_cookie(COOKIE_NAME))

    def set_default_headers(self):
        self.set_header("Content-Security-Policy", CSP)
        self.set_header("X-Content-Type-Options", "nosniff")

    def write_json(self, obj):
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(obj))


class RootHandler(BaseHandler):
    def _authed(self):
        # one-time ?token= sets the cookie
        presented = self.get_query_argument("token", None)
        if presented and self.auth.verify(presented):
            self.set_cookie(COOKIE_NAME, presented, httponly=True,
                            samesite="Strict")
            return True
        return super()._authed()

    def get(self):
        if self.get_query_argument("token", None):
            return self.redirect("/")
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.write((UI_DIR / "index.html").read_bytes())


class ProfilesHandler(BaseHandler):
    def get(self):
        self.write_json({"profiles": [
            {"id": p.id, "name": p.name, "caveats": p.caveats,
             "install_ok": shutil.which(p.command[0]) is not None,
             "install_hint": p.install_hint,
             "env_resolved": resolve_env(p.env_resolve, p.env_set)}
            for p in self.manager.profiles.values()]})


class SessionsHandler(BaseHandler):
    def get(self):
        self.write_json({"sessions": self.manager.list()})

    def post(self):
        body = json.loads(self.request.body or b"{}")
        profile_id = body.get("profile")
        cwd = body.get("cwd")
        if profile_id not in self.manager.profiles or not cwd or \
                not Path(cwd).is_dir():
            raise tornado.web.HTTPError(400, "bad profile or cwd")
        cwd = native_dir(cwd)
        profile = self.manager.profiles[profile_id]
        if shutil.which(profile.command[0]) is None:
            self.set_status(424)
            return self.write_json({"error": "adapter not installed",
                                    "install_hint": profile.install_hint})
        self.write_json({"id": self.manager.create(
            profile_id, cwd, resume=body.get("resume") or None)})


class SessionHandler(BaseHandler):
    def delete(self, sid):
        self.manager.close(sid)
        self.write_json({"ok": True})


class ProfileSessionsHandler(BaseHandler):
    """Sessions the AGENT knows for a cwd (for resume); needs a probe."""

    async def get(self, profile_id):
        cwd = self.get_query_argument("cwd", "")
        if profile_id not in self.manager.profiles or not Path(cwd).is_dir():
            raise tornado.web.HTTPError(400, "bad profile or cwd")
        cwd = native_dir(cwd)
        profile = self.manager.profiles[profile_id]
        if shutil.which(profile.command[0]) is None:
            return self.write_json({"sessions": [],
                                    "error": "adapter not installed"})
        self.write_json(await self.manager.list_agent_sessions(profile_id, cwd))


class DriftHandler(BaseHandler):
    """Spec §6: report the pinned schema and, when online checks are
    enabled, whether the pin or the installed adapter is behind."""

    async def get(self):
        pinned = (VENDOR / "VERSION").read_text(encoding="utf-8").strip()
        # The adapter to check is named by the profile (`npm_package`), never
        # by the server: ?profile=<id>, else the first profile that has one.
        profiles = self.manager.profiles
        wanted = self.get_query_argument("profile", None)
        profile = profiles.get(wanted) if wanted else next(
            (p for p in profiles.values() if p.npm_package), None)
        package = profile.npm_package if profile else None
        result = {"pinned_schema": pinned, "flags": [], "online": False,
                  "adapter_package": package}
        if self.application.settings.get("drift_online"):
            result["online"] = True
            try:
                latest = await tornado.ioloop.IOLoop.current().\
                    run_in_executor(None, _latest_versions, package)
                result["flags"] = Sentinel.load_default().compare_versions(
                    pinned, latest.get("schema"),
                    latest.get("adapter_installed"),
                    latest.get("adapter_latest"))
                result["latest"] = latest
            except Exception as exc:      # network failure is data, not death
                result["flags"] = [f"drift-check-failed:{exc}"]
        self.write_json(result)


def _latest_versions(npm_package: str | None = None) -> dict:
    """Blocking lookups, run in an executor. External systems addressed
    generically: a GitHub releases URL and the npm registry, both plain
    HTTPS JSON — no vendor SDKs. `npm_package` comes from the profile."""
    import json as _json
    import os as _os
    import subprocess as _sp
    import urllib.request as _rq
    out: dict = {"adapter_latest": None, "adapter_installed": None}
    with _rq.urlopen("https://api.github.com/repos/agentclientprotocol/"
                     "agent-client-protocol/releases/latest",
                     timeout=10) as r:
        out["schema"] = _json.load(r).get("tag_name")
    if not npm_package:
        return out
    with _rq.urlopen(f"https://registry.npmjs.org/{npm_package}/latest",
                     timeout=10) as r:
        out["adapter_latest"] = _json.load(r).get("version")
    try:
        ls = _sp.run(["npm", "ls", "-g", npm_package, "--json"],
                     capture_output=True, text=True, timeout=30,
                     shell=(_os.name == "nt"))
        deps = _json.loads(ls.stdout or "{}").get("dependencies", {})
        out["adapter_installed"] = deps.get(npm_package, {}).get("version")
    except Exception:
        out["adapter_installed"] = None
    return out


def make_app(profiles_dir, records_dir, auth,
             permission_timeout: float = 3600.0, drift_online: bool = False):
    manager = SessionManager(profiles_dir, records_dir, permission_timeout)
    common = {"manager": manager, "auth": auth}
    app = tornado.web.Application([
        (r"/", RootHandler, common),
        (r"/api/profiles", ProfilesHandler, common),
        (r"/api/sessions", SessionsHandler, common),
        (r"/api/sessions/([0-9a-f]+)", SessionHandler, common),
        (r"/api/profiles/([A-Za-z0-9_-]+)/sessions", ProfileSessionsHandler,
         common),
        (r"/api/drift", DriftHandler, common),
        (r"/ws/sessions/([0-9a-f]+)", SessionWS, common),
        (r"/ui/(.*)", tornado.web.StaticFileHandler, {"path": str(UI_DIR)}),
    ], drift_online=drift_online)
    app.manager = manager
    return app

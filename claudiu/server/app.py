"""Tornado controller: REST + static + session manager."""
from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

import tornado.ioloop
import tornado.web

from ..core.acp import AcpSession
from ..core.policy import PathPolicy
from ..core.profiles import load_profiles
from ..core.record import Recorder
from ..core.sentinel import Sentinel
from .auth import COOKIE_NAME
from .procs import SubprocessAgentProcess
from .ws import BufferedSink, SessionWS

UI_DIR = Path(__file__).resolve().parents[1] / "ui" / "web"
VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "acp"

CSP = ("default-src 'self'; img-src 'self' data:; "
       "style-src 'self'; script-src 'self'")


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


class SessionManager:
    def __init__(self, profiles_dir: Path, records_dir: Path,
                 permission_timeout: float = 3600.0):
        self.profiles = load_profiles(profiles_dir)
        self.records_dir = Path(records_dir)
        self.permission_timeout = permission_timeout
        self._entries: dict[str, Entry] = {}

    def create(self, profile_id: str, cwd: str) -> str:
        profile = self.profiles[profile_id]
        sid = uuid.uuid4().hex[:12]
        sink = BufferedSink()
        loop = tornado.ioloop.IOLoop.current()
        holder = {}

        def marshal(fn):
            return lambda *a: loop.add_callback(fn, *a)

        proc = SubprocessAgentProcess(
            command=profile.command, cwd=cwd,
            env_scrub=profile.env_scrub, env_set=profile.env_set,
            on_line=marshal(lambda ln: holder["s"].on_line(ln)),
            on_stderr=marshal(lambda ln: holder["s"]._emit(
                "anomaly", {"category": "stderr", "detail": ln})),
            on_exit=marshal(lambda code: holder["s"].on_exit(code)))
        session = AcpSession(
            sid=sid, profile=profile, proc=proc, sink=sink,
            recorder=Recorder(self.records_dir / f"{sid}.jsonl"),
            sentinel=Sentinel.load_default(),
            policy=PathPolicy(cwd), files=LocalFiles())
        holder["s"] = session
        self._watch_permissions(session, sink, loop)
        self._entries[sid] = Entry(session, sink, profile_id, cwd)
        session.start(cwd)
        return sid

    def _watch_permissions(self, session, sink, loop):
        timers: dict[int, object] = {}
        original_emit = sink.emit

        def emit(event):
            original_emit(event)
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
                 "state": e.session.state}
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
             "install_hint": p.install_hint}
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
        profile = self.manager.profiles[profile_id]
        if shutil.which(profile.command[0]) is None:
            self.set_status(424)
            return self.write_json({"error": "adapter not installed",
                                    "install_hint": profile.install_hint})
        self.write_json({"id": self.manager.create(profile_id, cwd)})


class SessionHandler(BaseHandler):
    def delete(self, sid):
        self.manager.close(sid)
        self.write_json({"ok": True})


class DriftHandler(BaseHandler):
    """Spec §6: report the pinned schema and, when online checks are
    enabled, whether the pin or the installed adapter is behind."""

    async def get(self):
        pinned = (VENDOR / "VERSION").read_text(encoding="utf-8").strip()
        result = {"pinned_schema": pinned, "flags": [], "online": False}
        if self.application.settings.get("drift_online"):
            result["online"] = True
            try:
                latest = await tornado.ioloop.IOLoop.current().\
                    run_in_executor(None, _latest_versions)
                result["flags"] = Sentinel.load_default().compare_versions(
                    pinned, latest.get("schema"),
                    latest.get("adapter_installed"),
                    latest.get("adapter_latest"))
                result["latest"] = latest
            except Exception as exc:      # network failure is data, not death
                result["flags"] = [f"drift-check-failed:{exc}"]
        self.write_json(result)


def _latest_versions() -> dict:
    """Blocking lookups, run in an executor. External systems addressed
    generically: a GitHub releases URL and the npm registry, both plain
    HTTPS JSON — no vendor SDKs."""
    import json as _json
    import os as _os
    import subprocess as _sp
    import urllib.request as _rq
    out: dict = {}
    with _rq.urlopen("https://api.github.com/repos/agentclientprotocol/"
                     "agent-client-protocol/releases/latest",
                     timeout=10) as r:
        out["schema"] = _json.load(r).get("tag_name")
    with _rq.urlopen("https://registry.npmjs.org/@zed-industries/"
                     "claude-code-acp/latest", timeout=10) as r:
        out["adapter_latest"] = _json.load(r).get("version")
    try:
        ls = _sp.run(["npm", "ls", "-g", "@zed-industries/claude-code-acp",
                      "--json"], capture_output=True, text=True, timeout=30,
                     shell=(_os.name == "nt"))
        deps = _json.loads(ls.stdout or "{}").get("dependencies", {})
        out["adapter_installed"] = deps.get(
            "@zed-industries/claude-code-acp", {}).get("version")
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
        (r"/api/drift", DriftHandler, common),
        (r"/ws/sessions/([0-9a-f]+)", SessionWS, common),
        (r"/ui/(.*)", tornado.web.StaticFileHandler, {"path": str(UI_DIR)}),
    ], drift_online=drift_online)
    app.manager = manager
    return app

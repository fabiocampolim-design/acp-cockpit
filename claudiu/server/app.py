# SPDX-License-Identifier: Apache-2.0
"""Tornado controller: REST + static + session manager."""
from __future__ import annotations

import json
import os
import shutil
import string
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
from ..core.transcript import write_markdown
from .auth import COOKIE_NAME, origin_ok
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


class AgentSessionBusy(Exception):
    """Another live session is already attached to that agent session."""

    def __init__(self, sid: str):
        super().__init__(f"already open in session {sid}")
        self.sid = sid


@dataclass
class Entry:
    session: AcpSession
    sink: BufferedSink
    profile_id: str
    cwd: str
    title: str | None = None
    resume_of: str | None = None      # agent session this one attached to

    @property
    def agent_session(self) -> str | None:
        """The agent-side session this entry owns, known from the resume
        request before the agent confirms it."""
        return self.session.acp_session_id or self.resume_of

    @property
    def live(self) -> bool:
        return self.session.state not in ("failed", "closed")


class SessionManager:
    # Requests that wait for the user, and how each answers itself when the
    # wait runs out: {request event: (resolved event, still-pending probe,
    # fail-safe answer)}. A question nobody answers must never hold a turn
    # open forever, and the fail-safe must be the SAFE answer for its kind
    # (reject a permission; decline — not cancel — an elicitation).
    PENDING_KINDS = {
        "permission_request": ("permission_resolved",
                               "pending_permissions", "fail_safe_reject"),
        "elicitation_request": ("elicitation_resolved",
                                "pending_elicitations",
                                "fail_safe_decline_elicitation"),
    }

    def __init__(self, profiles_dir: Path, records_dir: Path,
                 permission_timeout: float = 3600.0):
        self.profiles = load_profiles(profiles_dir)
        self.records_dir = Path(records_dir)
        self.permission_timeout = permission_timeout
        self._entries: dict[str, Entry] = {}

    def _spawn(self, profile, cwd, sid, sink, client_options=None):
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
            policy=PathPolicy(cwd), files=LocalFiles(),
            client_options=client_options)
        holder["s"] = session
        return session, loop

    def holder_of(self, agent_session: str) -> str | None:
        """Which live session already owns that agent session, if any."""
        for sid, entry in self._entries.items():
            if entry.live and entry.agent_session == agent_session:
                return sid
        return None

    def create(self, profile_id: str, cwd: str, resume: str | None = None,
               client_options: dict | None = None) -> str:
        profile = self.profiles[profile_id]
        # Two adapters attached to one agent session write the same
        # transcript file. One attachment at a time, whichever UI asks.
        if resume:
            holder = self.holder_of(resume)
            if holder:
                raise AgentSessionBusy(holder)
        sid = uuid.uuid4().hex[:12]
        sink = BufferedSink(sid)
        session, loop = self._spawn(profile, cwd, sid, sink,
                                    client_options=client_options)
        entry = Entry(session, sink, profile_id, cwd, resume_of=resume)
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
        sink = BufferedSink(sid)
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
        timers: dict[tuple, object] = {}
        asked_by = {resolved: asked
                    for asked, (resolved, _, _) in self.PENDING_KINDS.items()}
        original_emit = sink.emit

        def emit(event):
            original_emit(event)
            if event.kind == "session_info" and event.data.get("title"):
                entry.title = event.data["title"]
            if event.kind in self.PENDING_KINDS:
                _, pending, fail_safe = self.PENDING_KINDS[event.kind]
                key = (event.kind, event.data["request"])

                def expire(key=key, pending=pending, fail_safe=fail_safe):
                    if key[1] in getattr(session, pending)():
                        getattr(session, fail_safe)(key[1])
                timers[key] = loop.call_later(self.permission_timeout, expire)
            elif event.kind in asked_by:
                t = timers.pop((asked_by[event.kind],
                                event.data["request"]), None)
                if t:
                    loop.remove_timeout(t)
        sink.emit = emit

    def get(self, sid):
        return self._entries.get(sid)

    def list(self):
        return [{"id": sid, "profile": e.profile_id, "cwd": e.cwd,
                 "state": e.session.state, "title": e.title,
                 "agent_session": e.agent_session}
                for sid, e in self._entries.items()]

    def close(self, sid):
        entry = self._entries.pop(sid, None)
        if entry:
            entry.session.close()

    def close_all(self):
        for sid in list(self._entries):
            self.close(sid)


class Guard:
    """Host, origin and token, applied to every route this server answers —
    the static UI included (it was mounted bare until the 2026-09-04 audit,
    so `/ui/app.js` needed no token and carried no CSP)."""

    def prepare(self):
        host = self.request.host_name
        if host not in ("127.0.0.1", "localhost"):
            raise tornado.web.HTTPError(403, "bad host")
        if not origin_ok(self.request.headers.get("Origin"),
                         self.request.host):
            raise tornado.web.HTTPError(403, "bad origin")
        if not self._authed():
            raise tornado.web.HTTPError(403, "auth")

    def _authed(self):
        return self.auth.verify(self.get_cookie(COOKIE_NAME))

    def set_default_headers(self):
        self.set_header("Content-Security-Policy", CSP)
        self.set_header("X-Content-Type-Options", "nosniff")

    def write_error(self, status_code, **kwargs):
        """Errors are JSON too: the View shows `error` verbatim."""
        exc = kwargs.get("exc_info", (None, None, None))[1]
        reason = getattr(exc, "reason", None) or self._reason
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps({"error": reason, "status": status_code}))


class GuardedStaticFileHandler(Guard, tornado.web.StaticFileHandler):
    def initialize(self, path, auth):
        super().initialize(path)
        self.auth = auth


class BaseHandler(Guard, tornado.web.RequestHandler):
    def initialize(self, manager=None, auth=None):
        self.manager = manager
        self.auth = auth

    def json_body(self):
        """The request body as an object. A malformed body is the caller's
        mistake and answers as JSON: an unguarded json.loads made Tornado
        return its HTML 500 page, which the View cannot read (2026-09-04)."""
        try:
            body = json.loads(self.request.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise tornado.web.HTTPError(400, reason=f"invalid JSON: {exc}")
        if not isinstance(body, dict):
            raise tornado.web.HTTPError(400, reason="body must be a JSON object")
        return body

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
        body = self.json_body()
        profile_id = body.get("profile")
        cwd = body.get("cwd")
        if (profile_id not in self.manager.profiles or not cwd
                or not Path(cwd).is_dir()):
            # JSON, not Tornado's HTML page: the View shows `error` verbatim.
            self.set_status(400)
            return self.write_json({"error": "bad profile or cwd: profile="
                                    f"{profile_id!r}, cwd={cwd!r} (must be "
                                    "an existing directory)"})
        client_options = body.get("client_options") or {}
        if not isinstance(client_options, dict):
            self.set_status(400)
            return self.write_json(
                {"error": "client_options must be an object of agent session "
                          "options, e.g. {\"thinking\": {\"type\": "
                          "\"disabled\"}}"})
        cwd = native_dir(cwd)
        profile = self.manager.profiles[profile_id]
        if shutil.which(profile.command[0]) is None:
            self.set_status(424)
            return self.write_json({"error": "adapter not installed",
                                    "install_hint": profile.install_hint})
        try:
            sid = self.manager.create(profile_id, cwd,
                                      resume=body.get("resume") or None,
                                      client_options=client_options)
        except AgentSessionBusy as busy:
            self.set_status(409)
            return self.write_json(
                {"error": f"that agent session is already open in another "
                          f"tab of this server ({busy.sid}); close it there "
                          f"first — two adapters would write the same "
                          f"transcript", "session": busy.sid})
        self.write_json({"id": sid})


class SessionHandler(BaseHandler):
    def delete(self, sid):
        self.manager.close(sid)
        self.write_json({"ok": True})


class ProfileSessionsHandler(BaseHandler):
    """Sessions the AGENT knows for a cwd (for resume); needs a probe."""

    async def get(self, profile_id):
        cwd = self.get_query_argument("cwd", "")
        # An empty cwd is Path("."), the SERVER's directory — never list for
        # it; the View must name a project directory (2026-09-01 live test).
        if (profile_id not in self.manager.profiles or not cwd
                or not Path(cwd).is_dir()):
            self.set_status(400)
            return self.write_json({"sessions": [], "error":
                                    "pick an existing project directory first"})
        cwd = native_dir(cwd)
        profile = self.manager.profiles[profile_id]
        if shutil.which(profile.command[0]) is None:
            return self.write_json({"sessions": [],
                                    "error": "adapter not installed"})
        self.write_json(await self.manager.list_agent_sessions(profile_id, cwd))


def list_roots() -> list[str]:
    """Filesystem roots for the picker: drive letters on Windows, "/" else."""
    if os.name == "nt":
        listdrives = getattr(os, "listdrives", None)     # 3.12+
        if listdrives is not None:
            return list(listdrives())
        return [f"{c}:\\" for c in string.ascii_uppercase
                if Path(f"{c}:\\").is_dir()]
    return ["/"]


class DirsHandler(BaseHandler):
    """The launcher's folder picker (2026-09-03): the subdirectories of
    `path` (the home directory when empty), its parent (None at a root) and
    the roots. Files are never listed. A browser page cannot learn an
    absolute path from the OS folder dialog, so the server walks the tree.
    Exposure equals what the token already grants — a session may be
    started in any directory — so this is gated exactly like the rest."""

    def get(self):
        raw = self.get_query_argument("path", "")
        path = Path(raw).expanduser() if raw else Path.home()
        reply = {"path": raw, "parent": None, "dirs": [],
                 "roots": list_roots(), "error": None}
        if not path.is_dir():
            self.set_status(400)
            reply["error"] = f"not a directory: {raw!r}"
            return self.write_json(reply)
        path = path.resolve()
        names = []
        try:
            for entry in os.scandir(path):
                try:
                    if entry.is_dir():
                        names.append(entry.name)
                except OSError:
                    continue            # unreadable entry: skip, not fail
        except OSError as e:
            self.set_status(400)
            reply["path"] = str(path)
            reply["error"] = f"cannot list directory {path}: {e.strerror}"
            return self.write_json(reply)
        # plain names first, dot-directories last, case-insensitive
        names.sort(key=lambda n: (n.startswith("."), n.casefold()))
        parent = path.parent
        reply.update(path=str(path),
                     parent=None if parent == path else str(parent),
                     dirs=[{"name": n, "path": str(path / n)} for n in names])
        self.write_json(reply)


# What the installed publisher can write, and what this server can write
# on its own when the publisher is absent.
PUBLISHER_FORMATS = ["html", "markdown", "text", "latex", "pdf"]
FALLBACK_FORMATS = ["markdown"]


def default_archive_dir() -> str:
    """Where a transcript goes unless the user says otherwise."""
    return os.environ.get("CLAUDE_ARCHIVE_DIR") or str(
        Path.home() / "claudiu-transcripts")


class ArchiveHandler(BaseHandler):
    """Save the conversation.

    GET reports what this server can do (which formats, where by default,
    whether the full publisher is available) so the View can offer exactly
    those choices. POST writes it.

    The preferred writer is the INSTALLED claude-session-publisher, named by
    `--archiver` or `CLAUDIU_ARCHIVER`; it is never copied in here (GITHUBIFY
    rule 21). Without it the server still writes a plain Markdown transcript
    from the session's own record, and says plainly that it is the simpler
    one — refusing to save anything at all was the wrong answer to a missing
    optional tool (Fabio, 2026-09-04)."""

    def get(self, sid):
        archiver = self.application.settings.get("archiver")
        entry = self.manager.get(sid)
        self.write_json({
            "publisher": bool(archiver),
            "formats": PUBLISHER_FORMATS if archiver else FALLBACK_FORMATS,
            "default_formats": ["html", "markdown"] if archiver
                               else ["markdown"],
            "default_dest": default_archive_dir(),
            "agent_session": entry.agent_session if entry else None,
            "warning": None if archiver else
                "claude-session-publisher is not configured, so ClaudIU will "
                "write a simple Markdown transcript from the session record "
                "itself: prompts, answers, thinking and tool-call titles. "
                "For the full document (HTML, PDF, LaTeX, fidelity report) "
                "start the server with --archiver <path to "
                "transcript_archiver.py> or set CLAUDIU_ARCHIVER.",
        })

    async def post(self, sid):
        body = self.json_body()          # a bad request is a 400, always
        entry = self.manager.get(sid)
        if entry is None:
            self.set_status(404)
            return self.write_json({"error": "no such session"})
        agent_session = entry.agent_session
        if not agent_session:
            self.set_status(409)
            return self.write_json({"error": "this session has no agent "
                                    "session yet — nothing to archive"})
        dest = str(body.get("dest") or "").strip() or default_archive_dir()
        formats = body.get("formats")
        if isinstance(formats, str):
            formats = [f.strip() for f in formats.split(",") if f.strip()]
        archiver = self.application.settings.get("archiver")
        allowed = PUBLISHER_FORMATS if archiver else FALLBACK_FORMATS
        if not formats:
            formats = ["html", "markdown"] if archiver else ["markdown"]
        unknown = [f for f in formats if f not in allowed]
        if unknown:
            self.set_status(400)
            return self.write_json(
                {"error": f"this server cannot write {', '.join(unknown)}; "
                          f"it offers {', '.join(allowed)}"})

        if archiver:
            result = await tornado.ioloop.IOLoop.current().run_in_executor(
                None, _run_archiver, archiver, agent_session,
                ",".join(formats), dest)
            if not result["ok"]:
                self.set_status(502)
            return self.write_json(result)

        # No publisher: write what we can, from our own record.
        record = self.manager.records_dir / f"{sid}.jsonl"
        if not record.exists():
            self.set_status(409)
            return self.write_json({"error": f"no record for {sid} to write "
                                             "a transcript from"})
        try:
            written = await tornado.ioloop.IOLoop.current().run_in_executor(
                None, write_markdown, record, dest, agent_session, entry.title)
        except OSError as exc:
            self.set_status(502)
            return self.write_json({"ok": False, "output": [],
                                    "error": f"could not write there: {exc}"})
        self.write_json({
            "ok": True, "output": [written], "fallback": True,
            "warning": "claude-session-publisher is not configured, so this "
                       "is ClaudIU's simple Markdown transcript — prompts, "
                       "answers, thinking and tool-call titles. The full "
                       "document needs --archiver.",
            "command": None, "detail": None})


def _run_archiver(archiver: str, session_id: str, fmt: str,
                  dest: str | None = None) -> dict:
    """Blocking, run in an executor. Reports what the tool actually did:
    its own `wrote <path>` lines, and its output when it fails."""
    import subprocess
    import sys as _sys
    cmd = [_sys.executable, archiver, session_id, "--format", fmt]
    if dest:
        cmd += ["--archive-dir", dest]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=900)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "output": [], "error": f"archiver failed: {exc}",
                "command": cmd}
    out = (done.stdout or "") + (done.stderr or "")
    written = [line.split("wrote ", 1)[1].split(" (")[0].strip()
               for line in out.splitlines() if line.startswith("wrote ")]
    if done.returncode != 0:
        return {"ok": False, "output": written, "command": cmd,
                "error": f"archiver exited {done.returncode}",
                "detail": out[-2000:]}
    return {"ok": True, "output": written, "command": cmd,
            "detail": out[-2000:]}


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
             permission_timeout: float = 3600.0, drift_online: bool = False,
             archiver: str | None = None):
    manager = SessionManager(profiles_dir, records_dir, permission_timeout)
    common = {"manager": manager, "auth": auth}
    app = tornado.web.Application([
        (r"/", RootHandler, common),
        (r"/api/profiles", ProfilesHandler, common),
        (r"/api/sessions", SessionsHandler, common),
        (r"/api/sessions/([0-9a-f]+)", SessionHandler, common),
        (r"/api/sessions/([0-9a-f]+)/archive", ArchiveHandler, common),
        (r"/api/profiles/([A-Za-z0-9_-]+)/sessions", ProfileSessionsHandler,
         common),
        (r"/api/dirs", DirsHandler, common),
        (r"/api/drift", DriftHandler, common),
        (r"/ws/sessions/([0-9a-f]+)", SessionWS, common),
        (r"/ui/(.*)", GuardedStaticFileHandler,
         {"path": str(UI_DIR), "auth": auth}),
    ], drift_online=drift_online, archiver=archiver)
    app.manager = manager
    return app

# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""Tornado application: REST API, terminal websockets, static frontend."""
from __future__ import annotations

import json
import logging
import urllib.parse
from pathlib import Path

import tornado.web
from tornado.ioloop import IOLoop

from claudiu.resume import scan_recent_sessions
from claudiu.sessions import ClaudiuTermSocket

log = logging.getLogger(__name__)

# Hosts the app trusts to talk to itself. Requests whose Host header (DNS
# rebinding) or whose Origin header (CSRF from a foreign page) fall outside
# this set are refused -- see APIHandler.prepare() and
# TermSocketHandler.check_origin() below.
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _api_error(status: int, detail) -> tornado.web.HTTPError:
    """Build an HTTPError whose reason is safe to put on the status line.

    `reason` becomes literal bytes in the HTTP status line; a reason built
    from user-derived text (a submitted path, a caught exception's message)
    could contain a CR/LF that breaks header flushing, or be unbounded in
    length. Strip line breaks and cap the length before it ever reaches
    HTTPError.
    """
    text = str(detail).replace("\r", " ").replace("\n", " ")
    if len(text) > 200:
        text = text[:200] + "..."
    return tornado.web.HTTPError(status, reason=text)


ROUTES = {
    "GET /api/sessions": "list live sessions",
    "POST /api/sessions": "create a session (body: path, args, title)",
    "PATCH /api/sessions/<id>": "rename a session (body: title)",
    "DELETE /api/sessions/<id>": "kill a session",
    "GET /api/config": "effective config plus load warnings",
    "GET /api/resume": "recent resumable Claude sessions",
    "GET /api/status": "per-session status: last prompt, busy/ready, context use",
    "WS /ws/<id>": "terminal stream (terminado protocol)",
}


class APIHandler(tornado.web.RequestHandler):
    def prepare(self):
        # DNS rebinding: a page served from a foreign domain that resolves
        # to 127.0.0.1 could still send Host: evil.example.
        if self.request.host_name not in ALLOWED_HOSTS:
            raise tornado.web.HTTPError(403, reason="forbidden host")
        if self.request.method not in ("GET", "HEAD", "OPTIONS"):
            # CSRF: a cross-origin <form> post can't set a custom
            # Content-Type without triggering a CORS preflight, which this
            # app never answers -- so require the JSON type real clients
            # already send instead of relying on a preflight to run.
            ctype = self.request.headers.get("Content-Type", "")
            if not ctype.startswith("application/json"):
                raise tornado.web.HTTPError(403, reason="forbidden content type")
            origin = self.request.headers.get("Origin")
            if origin is not None:
                host = urllib.parse.urlsplit(origin).hostname
                if host not in ALLOWED_HOSTS:
                    raise tornado.web.HTTPError(403, reason="forbidden origin")

    def write_error(self, status_code, **kwargs):
        reason = self._reason or "error"
        exc = kwargs.get("exc_info")
        if exc and isinstance(exc[1], tornado.web.HTTPError) and exc[1].reason:
            reason = exc[1].reason
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps({"error": reason}))

    def body_json(self) -> dict:
        try:
            data = json.loads(self.request.body or b"{}")
        except json.JSONDecodeError:
            raise tornado.web.HTTPError(400, reason="request body is not JSON")
        if not isinstance(data, dict):
            raise tornado.web.HTTPError(400, reason="request body must be an object")
        return data


class SessionsHandler(APIHandler):
    def initialize(self, manager):
        self.manager = manager

    def get(self):
        self.write({"sessions": self.manager.list_sessions()})

    def post(self):
        body = self.body_json()
        path = body.get("path")
        if not isinstance(path, str) or not Path(path).is_dir():
            raise _api_error(400, f"not an existing directory: {path!r}")
        args = body.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise tornado.web.HTTPError(400, reason="args must be a list of strings")
        try:
            info = self.manager.create_session(path, args, body.get("title"))
        except Exception as exc:  # exception wall: one bad spawn, not a dead server
            log.exception("session spawn failed")
            raise _api_error(500, f"could not start session: {exc}")
        self.set_status(201)
        self.write(info)


class SessionHandler(APIHandler):
    def initialize(self, manager):
        self.manager = manager

    def patch(self, sid):
        title = self.body_json().get("title")
        if not isinstance(title, str) or not title.strip():
            raise tornado.web.HTTPError(400, reason="title must be a non-empty string")
        try:
            self.manager.rename(sid, title.strip())
        except KeyError:
            raise tornado.web.HTTPError(404, reason=f"no session {sid!r}")
        self.write({"ok": True})

    async def delete(self, sid):
        try:
            await self.manager.kill_session(sid)
        except KeyError:
            raise tornado.web.HTTPError(404, reason=f"no session {sid!r}")
        self.set_status(204)
        self.finish()


class ConfigHandler(APIHandler):
    def initialize(self, config, warnings):
        self.config = config
        self.warnings = warnings

    def get(self):
        self.write({"config": self.config, "warnings": self.warnings})


class ResumeHandler(APIHandler):
    async def get(self):
        try:
            # scan_recent_sessions() does blocking file I/O over every
            # recent Claude Code session file; running it inline would
            # stall the IOLoop (and every other tab's websocket) for the
            # duration of the scan.
            projects, report = await IOLoop.current().run_in_executor(
                None, scan_recent_sessions)
        except Exception as exc:  # scanner must never blank the page
            log.exception("resume scan failed")
            raise _api_error(500, f"resume scan failed: {exc}")
        self.write({"projects": projects, "report": report})


class StatusHandler(APIHandler):
    def initialize(self, manager):
        self.manager = manager

    async def get(self):
        try:
            # transcript tails are small reads, but they are still file I/O
            # on every poll: keep them off the IOLoop like the resume scan
            sessions = await IOLoop.current().run_in_executor(
                None, self.manager.status_all)
        except Exception as exc:  # a broken transcript must not blank a tab
            log.exception("status read failed")
            raise _api_error(500, f"status read failed: {exc}")
        self.write({"sessions": sessions})


class TermSocketHandler(ClaudiuTermSocket):
    """ClaudiuTermSocket with the same Origin/Host checks as the REST API.

    terminado's default check_origin() only compares Origin to Host (same
    behaviour Tornado ships); it does not defend against a foreign Host
    header (DNS rebinding), so both sides are checked here explicitly.
    """

    def check_origin(self, origin):
        if self.request.host_name not in ALLOWED_HOSTS:
            return False
        host = urllib.parse.urlsplit(origin).hostname
        return host in ALLOWED_HOSTS


def make_app(config, manager, warnings=()) -> tornado.web.Application:
    static = Path(__file__).parent / "static"
    return tornado.web.Application(
        [
            (r"/api/sessions", SessionsHandler, {"manager": manager}),
            (r"/api/sessions/([A-Za-z0-9_-]+)", SessionHandler,
             {"manager": manager}),
            (r"/api/config", ConfigHandler,
             {"config": config, "warnings": list(warnings)}),
            (r"/api/resume", ResumeHandler),
            (r"/api/status", StatusHandler, {"manager": manager}),
            (r"/ws/([A-Za-z0-9_-]+)", TermSocketHandler,
             {"term_manager": manager}),
            # browsers ask for /favicon.ico unprompted; point them at the
            # SVG so the log does not fill with 404 warnings
            (r"/favicon\.ico", tornado.web.RedirectHandler,
             {"url": "/favicon.svg", "permanent": True}),
            (r"/(.*)", tornado.web.StaticFileHandler,
             {"path": str(static), "default_filename": "index.html"}),
        ],
        websocket_ping_interval=30,
    )

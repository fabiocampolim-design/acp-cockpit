# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""Tornado application: REST API, terminal websockets, static frontend."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import tornado.web

from claudiu.resume import scan_recent_sessions
from claudiu.sessions import ClaudiuTermSocket

log = logging.getLogger(__name__)

ROUTES = {
    "GET /api/sessions": "list live sessions",
    "POST /api/sessions": "create a session (body: path, args, title)",
    "PATCH /api/sessions/<id>": "rename a session (body: title)",
    "DELETE /api/sessions/<id>": "kill a session",
    "GET /api/config": "effective config plus load warnings",
    "GET /api/resume": "recent resumable Claude sessions",
    "WS /ws/<id>": "terminal stream (terminado protocol)",
}


class APIHandler(tornado.web.RequestHandler):
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
            raise tornado.web.HTTPError(
                400, reason=f"not an existing directory: {path!r}")
        args = body.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise tornado.web.HTTPError(400, reason="args must be a list of strings")
        try:
            info = self.manager.create_session(path, args, body.get("title"))
        except Exception as exc:  # exception wall: one bad spawn, not a dead server
            log.exception("session spawn failed")
            raise tornado.web.HTTPError(
                500, reason=f"could not start session: {exc}")
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
    def get(self):
        try:
            projects, report = scan_recent_sessions()
        except Exception as exc:  # scanner must never blank the page
            log.exception("resume scan failed")
            raise tornado.web.HTTPError(500, reason=f"resume scan failed: {exc}")
        self.write({"projects": projects, "report": report})


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
            (r"/ws/([A-Za-z0-9_-]+)", ClaudiuTermSocket,
             {"term_manager": manager}),
            (r"/(.*)", tornado.web.StaticFileHandler,
             {"path": str(static), "default_filename": "index.html"}),
        ],
        websocket_ping_interval=30,
    )

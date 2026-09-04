# SPDX-License-Identifier: Apache-2.0
"""ACP client session state machine. Sans-I/O: lines in, lines out via ports."""
from __future__ import annotations

import json
import re

from .events import make_event
from .protocol import JsonRpcConn

# Windows drive paths (JSON-escaped backslashes included) and POSIX paths.
_ABS_PATH = re.compile(r"[A-Za-z]:(?:\\\\|/)[^\s\"'`<>|&;]+|(?<![\w:])/[\w./-]{2,}")

_UPDATE_TO_EVENT = {
    "agent_message_chunk": ("message_chunk", "agent"),
    "agent_thought_chunk": ("message_chunk", "thought"),
    "user_message_chunk": ("message_chunk", "user"),
}


class StateError(Exception):
    pass


class AcpSession:
    PROTOCOL_VERSION = 1
    # `elicitation.form` is what makes the Claude adapter load its
    # AskUserQuestion tool at all; `url` is deliberately not claimed.
    # `subagent-transcript` asks for what a subagent said and thought:
    # without it the adapter strips subagent text out of what it forwards.
    DEFAULT_CAPS = {"fs": {"readTextFile": True, "writeTextFile": True},
                    "elicitation": {"form": {}},
                    "_meta": {"subagent-transcript": True}}

    def __init__(self, sid, profile, proc, sink, recorder, sentinel, policy,
                 files, client_capabilities=None, client_options=None):
        self.sid = sid
        self.profile = profile
        self.proc = proc
        self.sink = sink
        self.recorder = recorder
        self.sentinel = sentinel
        self.policy = policy
        self.files = files
        self.caps = client_capabilities or dict(self.DEFAULT_CAPS)
        # Session-creation options: the profile's, with whatever the user
        # chose in the launcher layered on top (thinking, above all — it can
        # only be chosen when the session is created).
        self.client_options = dict(getattr(profile, "client_options", None)
                                   or {})
        self.client_options.update(client_options or {})
        self.state = "starting"
        self.acp_session_id = None
        self._seq = 0
        self._turn_id = None
        self._last_raw_ref = None
        self._pending_perms: dict = {}
        self._pending_elicits: dict = {}
        self._early_updates: list = []
        self._exited = False
        self._close_record_on_exit = False
        self._conn = JsonRpcConn(self._on_request, self._on_notify,
                                 self._on_anomaly)

    # ---- config options -------------------------------------------------
    def _ordered_options(self, options):
        """Offer each config option's choices in the order the PROFILE asks
        for, when it asks for one. The agent sends the model list in its own
        order (default, sonnet, fable, opus, haiku for claude-agent-acp
        0.73); a reader picking a model wants them by capability. Data, not
        code: `config_option_order` in the profile."""
        wanted = getattr(self.profile, "config_option_order", None) or {}
        if not wanted or not isinstance(options, list):
            return options
        out = []
        for opt in options:
            order = wanted.get(opt.get("id")) if isinstance(opt, dict) else None
            choices = opt.get("options") if isinstance(opt, dict) else None
            if not order or not isinstance(choices, list):
                out.append(opt)
                continue

            def rank(choice, order=order):
                hay = (f"{choice.get('value', '')} {choice.get('name', '')}"
                       ).casefold()
                for i, want in enumerate(order):
                    if want.casefold() in hay:
                        return i
                return len(order)      # unmatched: after the rest, in order
            out.append({**opt, "options": sorted(choices, key=rank)})
        return out

    # ---- plumbing -------------------------------------------------------
    def _emit(self, kind, data, raw_ref=None):
        self._seq += 1
        self.sink.emit(make_event(kind, self.sid, self._seq, data, raw_ref))

    def _set_state(self, state, detail=""):
        self.state = state
        self._emit("session_state", {"state": state, "detail": detail})

    def _flush(self):
        for line in self._conn.take_outgoing():
            self.recorder.append({"dir": "out", "frame": json.loads(line)})
            self.proc.send_line(line)

    def on_line(self, line: str) -> None:
        try:
            frame = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            frame = None
        if isinstance(frame, dict):
            raw_ref = self.recorder.append({"dir": "in", "frame": frame})
            flags = self.sentinel.check_frame("in", frame)
            if flags:
                self._emit("drift", {"flags": flags}, raw_ref)
        else:
            raw_ref = self.recorder.append({"dir": "in", "raw": line})
        self._last_raw_ref = raw_ref
        self._conn.feed(line)
        self._flush()

    def _on_anomaly(self, category, detail, raw):
        self._emit("anomaly", {"category": category, "detail": str(detail)},
                   self._last_raw_ref)

    def _session_meta(self) -> dict:
        """`_meta` for a session-creating request: the profile's
        `client_options` under the key the agent reads them from. Empty when
        the profile asks for nothing, so the frame stays minimal."""
        options = self.client_options
        if not options:
            return {}
        return {"_meta": {"claudeCode": {"options": dict(options)}}}

    # ---- lifecycle ------------------------------------------------------
    def start(self, cwd: str) -> None:
        self._cwd = cwd
        self._conn.request("initialize", {
            "protocolVersion": self.PROTOCOL_VERSION,
            "clientCapabilities": self.caps,
        }, self._on_initialized)
        self._flush()

    def _on_initialized(self, result, error):
        if error or not result:
            return self._fail(f"initialize failed: {error}")
        version = result.get("protocolVersion")
        if version != self.PROTOCOL_VERSION:
            self._emit("anomaly", {"category": "version-mismatch",
                       "detail": f"agent speaks protocol version {version}, "
                                 f"client speaks {self.PROTOCOL_VERSION}"})
            return self._fail("protocol version mismatch")
        self.agent_capabilities = result.get("agentCapabilities") or {}
        self._conn.request("session/new",
                           {"cwd": self._cwd, "mcpServers": [],
                            **self._session_meta()},
                           self._on_session_new)
        self._flush()

    def _on_session_new(self, result, error):
        if error or not result:
            return self._fail(f"session/new failed: {error}")
        self.acp_session_id = result["sessionId"]
        modes = result.get("modes") or {}
        if modes:
            self._emit("mode", {"current": modes.get("currentModeId"),
                                "available": modes.get("availableModes", [])})
        models = result.get("models") or {}
        if models:
            self._emit("model", {"current": models.get("currentModelId"),
                                 "available": models.get("availableModels", [])})
        # ACP 1.x agents hand mode/model/effort/... over as configOptions in
        # the session/new result itself (claude-agent-acp 0.73); dropping
        # them here left the View without its selectors on 2026-09-01.
        cfg = result.get("configOptions")
        if cfg:
            self._emit("config_option", {"options": self._ordered_options(cfg)})
        early, self._early_updates = self._early_updates, []
        for params, ref in early:
            self._last_raw_ref = ref
            self._on_notify("session/update", params)
        self._set_state("ready")

    def on_stderr(self, line: str) -> None:
        """Adapter stderr: recorded and surfaced at low severity. Claude's
        adapter prints slash-command output here; it is not an anomaly."""
        ref = self.recorder.append({"dir": "err", "line": line})
        self._emit("stderr", {"line": line}, ref)

    def _fail(self, detail: str):
        self._set_state("failed", detail)
        self.proc.kill()

    def close(self) -> None:
        if self.state not in ("failed", "closed"):
            self._set_state("closed")
        self.proc.kill()
        # The adapter keeps talking for a moment after the kill; those frames
        # are still recorded. The record closes when the process has exited.
        if self._exited:
            self.recorder.close()
        else:
            self._close_record_on_exit = True

    def on_exit(self, code) -> None:
        self._exited = True
        if self.state in ("closed", "failed"):
            if self._close_record_on_exit:
                self.recorder.close()
            return
        detail = f"adapter exited with code {code}"
        recoverable = self.state == "turn"
        self._emit("anomaly", {"category": "adapter-exit", "detail": detail})
        self._set_state("failed", "recoverable: " + detail if recoverable
                        else detail)

    # ---- user actions ---------------------------------------------------
    def prompt(self, text: str) -> None:
        if self.state != "ready":
            raise StateError(f"cannot prompt in state {self.state!r}")
        self.recorder.append({"dir": "client", "action": "prompt",
                              "text": text})
        self._set_state("turn")
        self._turn_id = self._conn.request("session/prompt", {
            "sessionId": self.acp_session_id,
            "prompt": [{"type": "text", "text": text}],
        }, self._on_turn_end)
        self._flush()

    def _on_turn_end(self, result, error):
        self._turn_id = None
        if error:
            # The agent failed the turn (e.g. its API rejected the request).
            # Still a turn end: the view needs its separator and composer.
            err = error if isinstance(error, dict) else {"message": str(error)}
            message = str(err.get("message") or error)
            self._emit("anomaly", {"category": "turn-error",
                                   "detail": message})
            self._emit("turn_ended", {"stop_reason": "error",
                                      "error": {"code": err.get("code"),
                                                "message": message}})
            self._set_state("ready")
            return
        self._emit("turn_ended",
                   {"stop_reason": (result or {}).get("stopReason")})
        self._set_state("ready")

    # ---- agent -> client ------------------------------------------------
    def _on_notify(self, method, params):
        if method != "session/update":
            return  # tolerated per spec; sentinel already flagged unknowns
        if self.acp_session_id is None:
            # Updates can precede the session/new result; hold them and
            # replay once the id is known — never drop, never guess.
            self._early_updates.append((params, self._last_raw_ref))
            return
        if params.get("sessionId") != self.acp_session_id:
            self._emit("anomaly", {
                "category": "unknown-session",
                "detail": f"update for session {params.get('sessionId')!r}, "
                          f"ours is {self.acp_session_id!r}"},
                self._last_raw_ref)
            return
        update = params.get("update") or {}
        kind = update.get("sessionUpdate")
        ref = self._last_raw_ref
        if kind in _UPDATE_TO_EVENT:
            event_kind, role = _UPDATE_TO_EVENT[kind]
            text = (update.get("content") or {}).get("text", "")
            # Subagent text and thinking are stamped with the tool call that
            # owns them; the View files those under the subagent.
            parent = ((update.get("_meta") or {}).get("claudeCode") or {}
                      ).get("parentToolUseId")
            self._emit(event_kind, {"role": role, "text": text,
                                    "parent_tool_call_id": parent}, ref)
        elif kind in ("tool_call", "tool_call_update"):
            self._emit(kind, update, ref)
        elif kind == "plan":
            self._emit("plan", {"entries": update.get("entries", [])}, ref)
        elif kind == "available_commands_update":
            self._emit("commands",
                       {"commands": update.get("availableCommands", [])}, ref)
        elif kind == "current_mode_update":
            self._emit("mode", {"current": update.get("currentModeId"),
                                "available": []}, ref)
        elif kind == "usage_update":
            self._emit("usage", {"used": update.get("used"),
                                 "size": update.get("size"),
                                 "cost": update.get("cost")}, ref)
            # The account's rate-limit state rides on usage updates
            # (`_meta._claude/rateLimit`). It is account-wide, not session
            # state, so it travels as its own event, passed through whole.
            limits = (update.get("_meta") or {}).get("_claude/rateLimit")
            if isinstance(limits, dict):
                self._emit("rate_limit", limits, ref)
        elif kind == "session_info_update":
            self._emit("session_info", {"title": update.get("title"),
                                        "updatedAt": update.get("updatedAt")},
                       ref)
        elif kind == "config_option_update":
            self._emit("config_option", {"options": self._ordered_options(
                update.get("configOptions", []))}, ref)
        else:
            self._emit("unrecognized",
                       {"why": f"unknown update kind {kind!r}",
                        "frame": update}, ref)

    def _on_request(self, msg_id, method, params):
        ref = self._last_raw_ref
        if method == "session/request_permission":
            self._pending_perms[msg_id] = params.get("options") or []
            tool_call = params.get("toolCall") or {}
            self._emit("permission_request", {
                "request": msg_id,
                "tool_call": tool_call,
                "options": params.get("options") or [],
                "outside_boundary": self._paths_outside(tool_call)}, ref)
            return  # answered later by answer_permission / fail_safe_reject
        if method == "elicitation/create":
            self._handle_elicitation(msg_id, params, ref)
        elif method in ("fs/read_text_file", "fs/write_text_file"):
            self._handle_fs(msg_id, method, params, ref)
        else:
            self._conn.error(msg_id, -32601, f"unsupported method: {method}")
        self._flush()

    def _paths_outside(self, tool_call: dict) -> list[str]:
        """Heuristic: absolute paths mentioned anywhere in a tool call that
        fall outside the session boundary. Shell execution is agent-side and
        cannot be fenced by the client, so the user must SEE the escape."""
        text = json.dumps(tool_call, ensure_ascii=False)
        found = []
        for m in _ABS_PATH.finditer(text):
            candidate = m.group(0).replace("\\\\", "\\")
            candidate = candidate.rstrip("`'\"),;\\")   # JSON-escaped quote tail
            if candidate not in found and not self.policy.allowed(candidate):
                found.append(candidate)
        return found

    def _handle_fs(self, msg_id, method, params, ref):
        op = "read" if method == "fs/read_text_file" else "write"
        path = params.get("path", "")
        ok = self.policy.allowed(path)
        self._emit("fs_request", {"op": op, "path": path, "allowed": ok}, ref)
        self.recorder.append({"dir": "client", "action": "fs_decision",
                              "op": op, "path": path, "allowed": ok,
                              "policy": self.policy.describe()})
        if not ok:
            self._conn.error(msg_id, -32602,
                             "path outside the session boundary")
            return
        try:
            if op == "read":
                self._conn.respond(msg_id,
                                   {"content": self.files.read_text(path)})
            else:
                self.files.write_text(path, params.get("content", ""))
                self._conn.respond(msg_id, None)
        except OSError as exc:
            self._conn.error(msg_id, -32603, f"fs failure: {exc}")

    # ---- permissions ----------------------------------------------------
    def pending_permissions(self):
        return sorted(self._pending_perms)

    def _resolve_permission(self, request_id, outcome, option_id, source):
        if request_id not in self._pending_perms:
            raise StateError(f"no pending permission {request_id}")
        del self._pending_perms[request_id]
        self._conn.respond(request_id, {"outcome": outcome})
        self.recorder.append({"dir": "client", "action": "permission",
                              "request": request_id, "option": option_id,
                              "source": source})
        self._emit("permission_resolved", {"request": request_id,
                   "option": option_id, "source": source})
        self._flush()

    def answer_permission(self, request_id: int, option_id: str) -> None:
        self._resolve_permission(
            request_id, {"outcome": "selected", "optionId": option_id},
            option_id, "user")
        # Some approvals change the agent's mode without a mode update
        # (claude-agent-acp 0.73 after ExitPlanMode): the profile says which
        # answer implies which mode, and we re-assert it so the strip never
        # shows "Plan" while the agent edits.
        for rule in getattr(self.profile, "permission_mode_followups", []):
            if rule.get("option_id") == option_id:
                self.set_mode(rule["mode"])
                break

    def fail_safe_reject(self, request_id: int) -> None:
        options = self._pending_perms.get(request_id) or []
        reject = next((o for o in options
                       if o.get("kind") == "reject_once"), None)
        if reject is None:
            reject = next((o for o in options
                           if str(o.get("kind", "")).startswith("reject")),
                          None)
        if reject:
            self._resolve_permission(
                request_id,
                {"outcome": "selected", "optionId": reject["optionId"]},
                reject["optionId"], "failsafe")
        else:
            self._resolve_permission(
                request_id, {"outcome": "cancelled"}, None, "failsafe")

    # ---- elicitation (the agent asks the user a structured question) ----
    def _handle_elicitation(self, msg_id, params, ref):
        """`elicitation/create`, form mode: hand the schema to the View and
        wait. Any other mode is answered "cancel" at once — we advertise
        only `form`, and pretending otherwise would strand the agent."""
        mode = params.get("mode", "form")
        if mode != "form":
            self._emit("anomaly", {
                "category": "unsupported-elicitation-mode",
                "detail": f"agent asked for {mode!r} elicitation; this "
                          "client advertises only form"}, ref)
            self._conn.respond(msg_id, {"action": "cancel"})
            return
        self._pending_elicits[msg_id] = params
        self._emit("elicitation_request", {
            "request": msg_id,
            "message": params.get("message", ""),
            "schema": params.get("requestedSchema") or {},
            "tool_call_id": params.get("toolCallId")}, ref)
        # answered later by answer_elicitation / fail_safe_decline_elicitation

    def pending_elicitations(self):
        return sorted(self._pending_elicits)

    def _resolve_elicitation(self, request_id, action, content, source):
        if request_id not in self._pending_elicits:
            raise StateError(f"no pending elicitation {request_id}")
        del self._pending_elicits[request_id]
        result = {"action": action}
        if action == "accept":
            result["content"] = dict(content or {})
        self._conn.respond(request_id, result)
        self.recorder.append({"dir": "client", "action": "elicitation",
                              "request": request_id, "elicit_action": action,
                              "content": result.get("content"),
                              "source": source})
        # The answer travels WITH the event: a second browser tab, a reload
        # or another View has no other way to know what was answered.
        self._emit("elicitation_resolved", {"request": request_id,
                   "action": action, "content": result.get("content"),
                   "source": source})
        self._flush()

    def answer_elicitation(self, request_id: int, action: str,
                           content: dict | None = None) -> None:
        self._resolve_elicitation(request_id, action, content, "user")

    def fail_safe_decline_elicitation(self, request_id: int) -> None:
        """Unanswered questions decline, never cancel: decline lets the agent
        continue with no answer, cancel aborts its tool call."""
        self._resolve_elicitation(request_id, "decline", None, "failsafe")

    # ---- more user actions ---------------------------------------------
    def cancel(self) -> None:
        if self.state != "turn":
            return
        self.recorder.append({"dir": "client", "action": "cancel"})
        self._conn.notify("session/cancel",
                          {"sessionId": self.acp_session_id})
        self._flush()

    def set_mode(self, mode_id: str) -> None:
        self.recorder.append({"dir": "client", "action": "set_mode",
                              "mode": mode_id})

        def done(result, error):
            if error:
                self._emit("anomaly", {"category": "set-mode-error",
                                       "detail": str(error)})
            else:
                self._emit("mode", {"current": mode_id, "available": []})
        self._conn.request("session/set_mode",
                           {"sessionId": self.acp_session_id,
                            "modeId": mode_id}, done)
        self._flush()

    def set_model(self, model_id: str) -> None:
        """Vendor method `session/set_model` (claude-code-acp <= 0.16;
        claude-agent-acp 0.73 moved model choice to config options, so the
        View hides this control when a `model` config option exists).
        Recorded like every other client action."""
        self.recorder.append({"dir": "client", "action": "set_model",
                              "model": model_id})

        def done(result, error):
            if error:
                self._emit("anomaly", {"category": "set-model-error",
                                       "detail": str(error)})
            else:
                self._emit("model", {"current": model_id, "available": []})
        self._conn.request("session/set_model",
                           {"sessionId": self.acp_session_id,
                            "modelId": model_id}, done)
        self._flush()

    def set_config_option(self, config_id: str, value) -> None:
        self.recorder.append({"dir": "client", "action": "set_config_option",
                              "config": config_id, "value": value})

        def done(result, error):
            if error:
                self._emit("anomaly", {"category": "set-config-error",
                                       "detail": str(error)})
            else:
                self._emit("config_option", {"options": self._ordered_options(
                    (result or {}).get("configOptions", []))})
        self._conn.request("session/set_config_option",
                           {"sessionId": self.acp_session_id,
                            "configId": config_id, "value": value}, done)
        self._flush()

    # ---- attaching to existing agent sessions ---------------------------
    def load(self, acp_session_id: str, cwd: str) -> None:
        """Attach to an existing agent session: `session/load` (replays the
        history) when advertised, else `session/resume` (no history)."""
        if self.state != "starting":
            raise StateError("load only from a fresh session")
        self._cwd = cwd
        self._load_target = acp_session_id
        self._conn.request("initialize", {
            "protocolVersion": self.PROTOCOL_VERSION,
            "clientCapabilities": self.caps}, self._on_initialized_for_load)
        self._flush()

    def _on_initialized_for_load(self, result, error):
        if error or (result or {}).get("protocolVersion") != \
                self.PROTOCOL_VERSION:
            return self._fail(f"initialize for load failed: {error}")
        self.agent_capabilities = result.get("agentCapabilities") or {}
        caps = self.agent_capabilities.get("sessionCapabilities") or {}
        # session/load replays the conversation so far; session/resume
        # attaches WITHOUT it (spec). A browser client keeps no history of
        # its own, so history wins whenever the agent offers it.
        if self.agent_capabilities.get("loadSession"):
            method = "session/load"
        elif "resume" in caps:
            method = "session/resume"
        else:
            return self._fail("agent offers neither session/load nor "
                              "session/resume")

        def done(res, err):
            if err:
                return self._fail(f"{method} failed: {err}")
            self.acp_session_id = self._load_target
            modes = (res or {}).get("modes") or {}
            if modes:
                self._emit("mode", {"current": modes.get("currentModeId"),
                                    "available": modes.get("availableModes", [])})
            cfg = (res or {}).get("configOptions")
            if cfg:
                self._emit("config_option", {"options": self._ordered_options(cfg)})
            early, self._early_updates = self._early_updates, []
            for params, ref in early:
                self._last_raw_ref = ref
                self._on_notify("session/update", params)
            self._set_state("ready")
        self._conn.request(method, {
            "sessionId": self._load_target, "cwd": self._cwd,
            "mcpServers": [], **self._session_meta()}, done)
        self._flush()

    def probe_sessions(self, cwd: str, on_result) -> None:
        """Initialize and list the agent's sessions for `cwd` WITHOUT
        creating one. `on_result(sessions, error)`; state stays 'starting'
        so the caller closes the probe afterwards."""
        if self.state != "starting":
            raise StateError("probe only from a fresh session")
        self.recorder.append({"dir": "client", "action": "probe_sessions",
                              "cwd": cwd})

        def listed(res, err):
            if err:
                on_result([], err)
            else:
                on_result((res or {}).get("sessions", []), None)

        def initialized(res, err):
            if err or (res or {}).get("protocolVersion") != \
                    self.PROTOCOL_VERSION:
                return on_result([], err or {"message": "version mismatch"})
            caps = (res.get("agentCapabilities") or {}).get(
                "sessionCapabilities") or {}
            if "list" not in caps:
                return on_result([], {"message": "agent cannot list sessions"})
            self._conn.request("session/list", {"cwd": cwd}, listed)
            self._flush()
        self._conn.request("initialize", {
            "protocolVersion": self.PROTOCOL_VERSION,
            "clientCapabilities": self.caps}, initialized)
        self._flush()

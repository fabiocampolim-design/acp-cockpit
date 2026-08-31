# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""Scan ~/.claude/projects for recent Claude Code sessions to --resume.

Robustness rule (publication-playbook rule 14): anything unexpected is counted and
reported, never dropped silently, and never crashes the scan.
"""
from __future__ import annotations

import collections
import json
import os
from pathlib import Path


def _first_user_text(rec: dict):
    if rec.get("type") != "user":
        return None
    msg = rec.get("message")
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip()[:120] or None
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = str(part.get("text", "")).strip()
                if text:
                    return text[:120]
    return None


def _read_session_file(path: Path, max_lines: int, report: dict) -> dict:
    cwd = None
    summary = None
    with path.open(encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if i >= max_lines:
                break
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                report["bad_lines"] += 1
                continue
            if not isinstance(rec, dict):
                report["bad_lines"] += 1
                continue
            report["record_types"][str(rec.get("type"))] += 1
            if cwd is None and isinstance(rec.get("cwd"), str):
                cwd = rec["cwd"]
            if summary is None:
                summary = _first_user_text(rec)
            if cwd and summary:
                break
    return {"id": path.stem, "cwd": cwd,
            "summary": summary or "(no prompt found)",
            "mtime": path.stat().st_mtime}


def scan_recent_sessions(claude_dir=None, limit_per_project=5,
                         max_lines=200) -> tuple:
    base = (Path(claude_dir) if claude_dir is not None
            else Path.home() / ".claude" / "projects")
    report = {"project_dirs": 0, "session_files": 0,
              "unreadable_files": 0, "bad_lines": 0,
              "record_types": collections.Counter()}
    by_path: dict = {}
    if base.is_dir():
        for pdir in sorted(base.iterdir()):
            if not pdir.is_dir():
                continue
            report["project_dirs"] += 1
            for f in pdir.glob("*.jsonl"):
                report["session_files"] += 1
                try:
                    info = _read_session_file(f, max_lines, report)
                except OSError:
                    report["unreadable_files"] += 1
                    continue
                # Normalize a record's cwd so a project matches its
                # config-file path regardless of slash direction (Windows
                # session records use backslashes; config.json commonly
                # uses forward slashes) or trailing separators. resolve()
                # is safe here even when the path no longer exists -- it
                # only normalizes the string, it does not require the
                # directory to be present.
                key = (str(Path(info["cwd"]).resolve()) if info["cwd"]
                       else pdir.name)
                by_path.setdefault(key, []).append(info)
    projects = []
    for path, sessions in by_path.items():
        sessions.sort(key=lambda s: s["mtime"], reverse=True)
        # A launcher entry for a project whose directory was since moved
        # or deleted is useless (--resume would spawn `claude` nowhere
        # usable); let the frontend skip it instead of offering it.
        projects.append({"path": path, "exists": os.path.isdir(path),
                         "sessions": sessions[:limit_per_project]})
    projects.sort(key=lambda p: (p["sessions"][0]["mtime"] if p["sessions"] else 0.0), reverse=True)
    report["record_types"] = dict(report["record_types"])
    return projects, report

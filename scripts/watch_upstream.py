#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""watch_upstream.py -- the daily upstream watch for a live product.

    python scripts/watch_upstream.py --daily

This client depends on an ACP adapter that ships several times a week
(0.72 -> 0.75 in the first days of September 2026) and on a protocol schema
it pins. Once a day, from a scheduler that does not need a live session, this
script compares:

  - the adapter installed here (`npm ls -g`) with the latest on the npm
    registry, and lists the versions published since the last run;
  - the pinned ACP schema release with the latest published one;
  - the adapter repository's recent releases and open issues, and which are
    new or changed since the last run.

It writes <outdir>/YYYY-MM-DD.md (never overwriting a day's report unless
--force), keeps a snapshot in <state-dir>/snapshot.json for the delta, and
writes one audit log per run under <log-dir> -- on failure too, with the
traceback, because a scheduled task that discards its output and a script
that logs only on success together hid four days of failures once. What to
watch comes from the agent profile (`npm_package`, `upstream_repo`), never
from this file. Exit 0 ok, 1 upstream unreachable, 2 usage error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import traceback
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from acp_cockpit import __version__                       # noqa: E402
from acp_cockpit.__main__ import default_profiles_dirs    # noqa: E402
from acp_cockpit.core.profiles import load_profiles       # noqa: E402

USER_AGENT = f"acp-cockpit-watch/{__version__} (+https://github.com/fabiocampolim-design/acp-cockpit)"
SCHEMA_REPO = "agentclientprotocol/agent-client-protocol"
FIRST_SNAPSHOT_CAP = 15          # a first run lists at most this many per bucket


def _get(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def installed_version(npm_package: str) -> str | None:
    try:
        ls = subprocess.run(["npm", "ls", "-g", npm_package, "--json"],
                            capture_output=True, text=True, timeout=60,
                            shell=(os.name == "nt"))
        deps = json.loads(ls.stdout or "{}").get("dependencies", {})
        return deps.get(npm_package, {}).get("version")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None


def watch_target(profile_id: str | None = None) -> dict:
    """What to watch, read from the shipped profile and the pinned schema."""
    profiles = load_profiles(*default_profiles_dirs())
    prof = (profiles.get(profile_id) if profile_id else
            next((p for p in profiles.values() if p.npm_package), None))
    if prof is None:
        raise SystemExit("no profile with an npm_package to watch")
    pinned = (ROOT / "acp_cockpit" / "vendor" / "acp" / "VERSION").read_text(
        encoding="utf-8").strip()
    return {"profile": prof.id, "npm_package": prof.npm_package,
            "upstream_repo": prof.upstream_repo, "pinned_schema": pinned}


def fetch(target: dict) -> dict:
    npm = _get(f"https://registry.npmjs.org/{target['npm_package']}")
    times = {k: v for k, v in (npm.get("time") or {}).items()
             if k not in ("created", "modified")}
    out = {
        "adapter_latest": (npm.get("dist-tags") or {}).get("latest"),
        "adapter_versions": times,                # version -> published
        "adapter_installed": installed_version(target["npm_package"]),
        "schema_latest": _get(f"https://api.github.com/repos/{SCHEMA_REPO}"
                              "/releases/latest").get("tag_name"),
        "releases": [], "issues": [],
    }
    repo = target.get("upstream_repo")
    if repo:
        out["releases"] = [
            {"tag": r.get("tag_name"), "name": r.get("name"),
             "published": r.get("published_at"), "url": r.get("html_url")}
            for r in _get(f"https://api.github.com/repos/{repo}/releases?per_page=15")]
        out["issues"] = [
            {"number": i["number"], "title": i.get("title"),
             "updated": i.get("updated_at"), "url": i.get("html_url")}
            for i in _get(f"https://api.github.com/repos/{repo}/issues?"
                          "state=open&per_page=30&sort=updated")
            if "pull_request" not in i]           # /issues lists PRs too
    return out


def delta(now: dict, before: dict | None) -> dict:
    """What is new since the previous snapshot. With no previous snapshot,
    everything is new and each bucket is capped."""
    if not before:
        return {"first": True,
                "versions": sorted(now["adapter_versions"], key=now["adapter_versions"].get)[-FIRST_SNAPSHOT_CAP:],
                "releases": now["releases"][:FIRST_SNAPSHOT_CAP],
                "issues": now["issues"][:FIRST_SNAPSHOT_CAP]}
    old_versions = set(before.get("adapter_versions") or {})
    old_releases = {r["tag"] for r in before.get("releases") or []}
    old_issues = {i["number"]: i.get("updated") for i in before.get("issues") or []}
    return {"first": False,
            "versions": [v for v in now["adapter_versions"] if v not in old_versions],
            "releases": [r for r in now["releases"] if r["tag"] not in old_releases],
            "issues": [i for i in now["issues"]
                       if old_issues.get(i["number"]) != i.get("updated")]}


def render(today: str, target: dict, now: dict, new: dict) -> str:
    inst, latest = now["adapter_installed"], now["adapter_latest"]
    behind = inst is not None and latest is not None and inst != latest
    schema_behind = now["schema_latest"] and now["schema_latest"] != target["pinned_schema"]
    lines = [f"# Upstream watch — {today}", "",
             f"*acp-cockpit {__version__}; profile `{target['profile']}`; "
             f"written by `scripts/watch_upstream.py`.*", "",
             "## Adapter", "",
             f"- `{target['npm_package']}`: installed {inst or 'not installed'}, "
             f"latest {latest or '?'} — "
             + ("**BEHIND** — upgrade, then run the contract tier and recreate "
                "any patched copy" if behind else "up to date"),
             ]
    if now["adapter_versions"]:
        recent = sorted(now["adapter_versions"].items(), key=lambda kv: kv[1])[-5:]
        lines.append("- recent versions: " + ", ".join(
            f"{v} ({t[:10]})" for v, t in recent))
    lines += ["", "## Protocol schema", "",
              f"- pinned {target['pinned_schema']}, latest {now['schema_latest'] or '?'} — "
              + ("**BEHIND** — re-run `tools/check_schema_drift.py` against the new "
                 "schema and extend the registry" if schema_behind else "up to date"),
              ""]
    lines += ["## New since the last run" if not new["first"]
              else "## First snapshot (capped)", ""]
    if not any(new[k] for k in ("versions", "releases", "issues")):
        lines.append("- nothing new")
    for v in new["versions"]:
        lines.append(f"- adapter version {v} ({(now['adapter_versions'].get(v) or '')[:10]})")
    for r in new["releases"]:
        lines.append(f"- release {r['tag']} — {r.get('name') or ''} "
                     f"({(r.get('published') or '')[:10]}) {r.get('url') or ''}".rstrip())
    for i in new["issues"]:
        lines.append(f"- issue #{i['number']} — {i.get('title') or ''} "
                     f"(updated {(i.get('updated') or '')[:10]}) {i.get('url') or ''}".rstrip())
    lines += ["", "## Open issues (current)", ""]
    for i in now["issues"][:30]:
        lines.append(f"- #{i['number']} {i.get('title') or ''}")
    if not now["issues"]:
        lines.append("- none listed")
    lines += ["", "## For this project", "",
              "- ACPUPSTREAM's findings are true of a version: re-check them "
              "against the installed adapter before filing anything.",
              "- A new adapter version means: upgrade, `ACP_COCKPIT_CONTRACT=1 "
              "python -m pytest tests/contract/ -q`, recreate "
              "`~/.acp-cockpit/acp-patched` with `patch_dist.py`, read the "
              "drift chip in a real session.", ""]
    return "\n".join(lines)


def audit(log_dir: Path, argv, outcome: str, detail: str = "") -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = log_dir / f"watch-{stamp}.log"
    path.write_text(
        f"watch_upstream {__version__}\nargv: {argv}\npython: {sys.version.split()[0]}\n"
        f"outcome: {outcome}\n{detail}\n", encoding="utf-8")
    return path


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    ap = argparse.ArgumentParser(prog="watch_upstream",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--daily", action="store_true",
                    help="(the scheduled mode; identical to the default, named "
                         "so the task's command line says what it is)")
    ap.add_argument("--profile", default=None, help="profile id to watch "
                    "(default: the first with an npm_package)")
    ap.add_argument("--outdir", default=str(ROOT / "docs" / "watch"),
                    help="where the dated reports go (default docs/watch)")
    ap.add_argument("--state-dir",
                    default=str(Path.home() / ".acp-cockpit" / "watch"),
                    help="snapshot for the delta (default ~/.acp-cockpit/watch)")
    ap.add_argument("--log-dir", default=None,
                    help="audit logs (default <state-dir>/logs)")
    ap.add_argument("--today", default=None, help="report date YYYY-MM-DD "
                    "(default: today, UTC)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing report for the day")
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument("--version", action="version",
                    version=f"acp-cockpit {__version__}")
    args = ap.parse_args(argv)

    outdir, state = Path(args.outdir), Path(args.state_dir)
    log_dir = Path(args.log_dir) if args.log_dir else state / "logs"
    today = args.today or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    report = outdir / f"{today}.md"
    snapshot = state / "snapshot.json"
    try:
        target = watch_target(args.profile)
        now = fetch(target)
        before = None
        if snapshot.is_file():
            before = json.loads(snapshot.read_text(encoding="utf-8"))
        new = delta(now, before)
        if report.exists() and not args.force:
            note = f"{report} exists; not overwritten (--force to redo)"
        else:
            outdir.mkdir(parents=True, exist_ok=True)
            report.write_text(render(today, target, now, new), encoding="utf-8")
            note = f"wrote {report}"
        state.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(json.dumps(now, indent=1), encoding="utf-8")
        behind = (now["adapter_installed"] and now["adapter_latest"]
                  and now["adapter_installed"] != now["adapter_latest"])
        summary = (f"adapter installed {now['adapter_installed']} latest "
                   f"{now['adapter_latest']}{' BEHIND' if behind else ''}; "
                   f"schema pinned {target['pinned_schema']} latest "
                   f"{now['schema_latest']}; new: {len(new['versions'])} versions, "
                   f"{len(new['releases'])} releases, {len(new['issues'])} issues")
        audit(log_dir, argv, "ok", note + "\n" + summary)
        if not args.quiet:
            print(note)
            print(summary)
        return 0
    except Exception as exc:  # noqa: BLE001 — the log is the point
        path = audit(log_dir, argv, "FAIL", f"{exc}\n{traceback.format_exc()}")
        print(f"watch failed: {exc} (log: {path})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

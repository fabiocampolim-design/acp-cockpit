# SPDX-License-Identifier: Apache-2.0
"""npm-installed-version lookup, shared by the daily watch script
(scripts/watch_upstream.py) and the live `/api/drift` endpoint
(acp_cockpit/server/app.py). Not under `core/`: it does real subprocess and
filesystem I/O (an `npm ls -g` call, a PATH/ProgramFiles search), which
`core/`'s layer rule reserves for its own narrow carve-outs (AGENTS.md).
Kept free of a tornado dependency so the watch script -- which must still
run, and report a clean audit-log failure, in an environment where tornado
is not installed -- can import it unconditionally.

Two independent copies of this used to drift apart (a 30s vs 60s timeout, a
ProgramFiles fallback only the script had) after each was fixed for the
same silent-failure bug on its own schedule (hostile Fable 5 review,
2026-09-19)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

DEFAULT_TIMEOUT = 60.0


def npm_fallback_paths() -> list[Path]:
    """Where npm lives when it is not on PATH. A Task Scheduler run does not
    inherit an interactive shell's PATH the way a login session does; the
    Node.js MSI's own install directory is a steadier source of truth."""
    return [Path(base) / "nodejs" / "npm.cmd"
            for base in (os.environ.get("ProgramFiles"),
                         os.environ.get("ProgramFiles(x86)")) if base]


def npm_executable() -> str | None:
    """npm itself, resolved. `shell=True` was how this used to run on
    Windows, where `npm` is `npm.cmd` and CreateProcess will not start it —
    but a shell joins the argv list back into a command line and re-parses
    it, so a package name read from a profile file ended up inside a cmd.exe
    line (review 2026-09-06). Resolving the executable needs no shell."""
    which = shutil.which("npm")
    if which:
        return which
    for candidate in npm_fallback_paths():
        if candidate.is_file():
            return str(candidate)
    return None


def installed_version(npm_package: str,
                      timeout: float = DEFAULT_TIMEOUT) -> tuple[str | None, str | None]:
    """(version, reason). reason is set only when version is None -- a
    scheduled run once reported 'not installed' with no exception and no way
    to tell PATH-missing, npm-failed and bad-JSON apart (2026-09-16); this is
    the audit trail that should have existed for it."""
    npm = npm_executable()
    if not npm:
        return None, "npm not found on PATH or the standard install location"
    try:
        ls = subprocess.run([npm, "ls", "-g", npm_package, "--json"],
                            capture_output=True, text=True, timeout=timeout)
        deps = json.loads(ls.stdout or "{}").get("dependencies", {})
        version = deps.get(npm_package, {}).get("version")
        if version is None:
            detail = (ls.stderr or ls.stdout or "no dependencies listed").strip()[:300]
            return None, (f"npm ls -g exit {ls.returncode}: {detail} -- npm ran and "
                          f"returned valid JSON but the package wasn't in it; a "
                          f"possible cause is a global prefix mismatch (`npm config "
                          f"get prefix`), since a scheduled run's token can resolve a "
                          f"different one than an interactive login -- unconfirmed: "
                          f"every failure seen here so far has been a timeout instead")
        return version, None
    except subprocess.TimeoutExpired:
        return None, f"npm ls -g timed out after {timeout:g}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"npm ls -g failed to run: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"npm ls -g output was not JSON: {exc}"

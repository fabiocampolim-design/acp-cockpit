# SPDX-License-Identifier: Apache-2.0
"""acp_cockpit/npm_lookup.py: the npm-installed-version lookup, shared by
the daily watch script (scripts/watch_upstream.py) and the live /api/drift
endpoint (acp_cockpit/server/app.py). The two used to be independent copies
that drifted apart -- a 30s vs 60s timeout, a ProgramFiles fallback only one
of them had -- each fixed for the same silent-failure bug on its own
schedule (hostile Fable 5 review, 2026-09-19: "unify the two copies into
one helper"). This is that helper; these are its own tests. The two callers
get thin identity/delegation tests, not a second copy of this coverage."""
import subprocess

from acp_cockpit import npm_lookup as nl


def test_npm_not_on_path_gives_a_reason(monkeypatch):
    monkeypatch.setattr(nl.shutil, "which", lambda name: None)
    monkeypatch.setattr(nl, "npm_fallback_paths", lambda: [])
    version, reason = nl.installed_version("some-adapter")
    assert version is None and "PATH" in reason


def test_npm_executable_falls_back_to_the_programfiles_install(monkeypatch, tmp_path):
    """Task Scheduler runs outside the interactive shell's PATH; the
    standard Node.js MSI install location is a steadier source of truth."""
    monkeypatch.setattr(nl.shutil, "which", lambda name: None)
    nodejs = tmp_path / "nodejs"
    nodejs.mkdir()
    npm_cmd = nodejs / "npm.cmd"
    npm_cmd.write_text("", encoding="utf-8")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    assert nl.npm_executable() == str(npm_cmd)


def test_the_npm_lookup_never_goes_through_a_shell(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["kw"] = kw
        return subprocess.CompletedProcess(cmd, 0, "{}", "")
    monkeypatch.setattr(nl.subprocess, "run", fake_run)
    monkeypatch.setattr(nl.shutil, "which", lambda name: "C:\\npm.cmd")
    nl.installed_version("@scope/pkg & calc.exe")
    assert not seen["kw"].get("shell")
    assert "@scope/pkg & calc.exe" in seen["cmd"]


def test_npm_ls_failure_gives_a_reason(monkeypatch):
    monkeypatch.setattr(nl.shutil, "which", lambda name: "npm.cmd")

    def boom(cmd, **kw):
        raise OSError("access is denied")
    monkeypatch.setattr(nl.subprocess, "run", boom)
    version, reason = nl.installed_version("some-adapter")
    assert version is None and "access is denied" in reason


def test_npm_ls_timeout_gives_a_reason(monkeypatch):
    monkeypatch.setattr(nl.shutil, "which", lambda name: "npm.cmd")

    def timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    monkeypatch.setattr(nl.subprocess, "run", timeout)
    version, reason = nl.installed_version("some-adapter")
    assert version is None and "timed out" in reason


def test_npm_ls_bad_json_gives_a_reason(monkeypatch):
    monkeypatch.setattr(nl.shutil, "which", lambda name: "npm.cmd")

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, "not json", "")
    monkeypatch.setattr(nl.subprocess, "run", fake_run)
    version, reason = nl.installed_version("some-adapter")
    assert version is None and "JSON" in reason


def test_a_resolved_version_carries_no_reason(monkeypatch):
    monkeypatch.setattr(nl.shutil, "which", lambda name: "npm.cmd")

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(
            cmd, 0, '{"dependencies": {"some-adapter": {"version": "1.2.3"}}}', "")
    monkeypatch.setattr(nl.subprocess, "run", fake_run)
    version, reason = nl.installed_version("some-adapter")
    assert version == "1.2.3" and reason is None


def test_the_watch_script_and_the_server_use_the_same_implementation():
    """The actual point of this module: one function, not two that can
    drift apart again."""
    import scripts.watch_upstream as w
    import acp_cockpit.server.app as appmod
    assert w.installed_version is nl.installed_version
    assert w.npm_executable is nl.npm_executable
    assert appmod._installed_adapter_version is nl.installed_version
    assert w.NPM_LS_TIMEOUT == nl.DEFAULT_TIMEOUT

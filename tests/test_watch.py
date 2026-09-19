# SPDX-License-Identifier: Apache-2.0
"""The daily upstream watch (Fabio, 2026-09-05: a live project, monitored at
least once a day). Offline: the network is stubbed, the shape of what it
writes is what is tested."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("scripts").resolve()))
import watch_upstream as w  # noqa: E402

NPM = {"dist-tags": {"latest": "0.75.0"},
       "time": {"created": "2026-01-01T00:00:00Z", "modified": "2026-09-05T08:56:12Z",
                "0.73.0": "2026-09-01T20:27:00Z", "0.74.0": "2026-09-04T10:00:00Z",
                "0.75.0": "2026-09-05T08:56:12Z"}}
SCHEMA_LATEST = {"tag_name": "schema-v1.21.0", "published_at": "2026-08-20T19:43:13Z"}
RELEASES = [{"tag_name": "v0.75.0", "name": "v0.75.0", "published_at": "2026-09-05T08:55:00Z",
             "html_url": "https://github.com/x/y/releases/tag/v0.75.0"},
            {"tag_name": "v0.74.0", "name": "v0.74.0", "published_at": "2026-09-04T10:00:00Z",
             "html_url": "https://github.com/x/y/releases/tag/v0.74.0"}]
ISSUES = [{"number": 1030, "title": "system notifications are dropped", "state": "open",
           "updated_at": "2026-09-03T00:00:00Z", "html_url": "https://github.com/x/y/issues/1030"},
          {"number": 1099, "title": "a pull request", "state": "open", "pull_request": {},
           "updated_at": "2026-09-04T00:00:00Z", "html_url": "https://github.com/x/y/pull/1099"}]


def fake_get(url, timeout=30):
    if "registry.npmjs.org" in url:
        return NPM
    if "agent-client-protocol/releases/latest" in url:
        return SCHEMA_LATEST
    if url.endswith("/releases?per_page=15"):
        return RELEASES
    if "/issues?" in url:
        return ISSUES
    raise AssertionError(f"unexpected URL {url}")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_get", fake_get)
    monkeypatch.setattr(w, "installed_version", lambda pkg: ("0.73.0", None))
    return {"outdir": tmp_path / "watch", "state": tmp_path / "state",
            "logs": tmp_path / "logs"}


def run(env, *extra):
    return w.main(["--outdir", str(env["outdir"]), "--state-dir",
                   str(env["state"]), "--log-dir", str(env["logs"]),
                   "--today", "2026-09-05", *extra])


def test_a_daily_report_names_versions_releases_and_issues(env):
    assert run(env) == 0
    report = (env["outdir"] / "2026-09-05.md").read_text(encoding="utf-8")
    assert "installed 0.73.0" in report and "latest 0.75.0" in report
    assert "BEHIND" in report                        # 0.73 < 0.75, said loudly
    assert "schema-v1.21.0" in report                 # pinned == latest
    assert "v0.75.0" in report and "v0.74.0" in report
    assert "#1030" in report
    assert "#1099" not in report                      # PRs are not issues
    assert "up to date" in report.lower() or "behind" in report.lower()


def test_the_first_run_snapshots_and_the_second_reports_the_delta(env):
    run(env)
    NPM["dist-tags"]["latest"] = "0.76.0"
    NPM["time"]["0.76.0"] = "2026-09-06T01:00:00Z"
    ISSUES.append({"number": 1200, "title": "prompt suggestions never reach a client",
                   "state": "open", "updated_at": "2026-09-06T02:00:00Z",
                   "html_url": "https://github.com/x/y/issues/1200"})
    try:
        assert w.main(["--outdir", str(env["outdir"]), "--state-dir",
                       str(env["state"]), "--log-dir", str(env["logs"]),
                       "--today", "2026-09-06"]) == 0
        report = (env["outdir"] / "2026-09-06.md").read_text(encoding="utf-8")
        assert "New since the last run" in report
        assert "0.76.0" in report and "#1200" in report
        assert "#1030" not in report.split("New since the last run")[1].split("##")[0]
    finally:
        NPM["dist-tags"]["latest"] = "0.75.0"
        del NPM["time"]["0.76.0"]
        ISSUES.pop()


def test_a_second_run_on_the_same_day_does_not_overwrite_the_report(env):
    run(env)
    first = (env["outdir"] / "2026-09-05.md").read_text(encoding="utf-8")
    assert run(env) == 0
    assert (env["outdir"] / "2026-09-05.md").read_text(encoding="utf-8") == first
    assert run(env, "--force") == 0


def test_a_same_day_rerun_does_not_lose_the_delta_it_saw(env):
    """The snapshot used to be overwritten every run regardless of whether
    the report was, so anything new between two same-day runs landed in
    neither that day's report (skipped: already exists) nor the next day's
    (its delta is computed against the just-overwritten snapshot). Not
    advancing the snapshot when the report isn't (re)written means the next
    written report still sees the full delta (hostile Fable 5 review,
    2026-09-19)."""
    run(env)                                          # writes 2026-09-05.md
    NPM["dist-tags"]["latest"] = "0.76.0"
    NPM["time"]["0.76.0"] = "2026-09-05T20:00:00Z"
    try:
        assert run(env) == 0                          # same day, not --force
        report = (env["outdir"] / "2026-09-05.md").read_text(encoding="utf-8")
        assert "0.76.0" not in report                 # unchanged, as before
        # the NEXT day's run must still see 0.76.0 as new -- the unreported
        # rerun above must not have advanced the snapshot past it. Checked in
        # the delta section specifically: "recent versions" lists it either
        # way, so a bare substring check on the whole report would pass even
        # with the bug (the section a delta bug actually breaks) still there.
        assert run(env, "--today", "2026-09-06") == 0
        next_report = (env["outdir"] / "2026-09-06.md").read_text(encoding="utf-8")
        assert "New since the last run" in next_report
        new_section = next_report.split("New since the last run")[1].split("##")[0]
        assert "0.76.0" in new_section, next_report
    finally:
        NPM["dist-tags"]["latest"] = "0.75.0"
        del NPM["time"]["0.76.0"]


def test_every_run_writes_an_audit_log_including_a_failed_one(env, monkeypatch):
    run(env)
    logs = list(env["logs"].glob("watch-*.log"))
    assert len(logs) == 1 and "ok" in logs[0].read_text(encoding="utf-8")

    def down(url, timeout=30):
        raise OSError("network is down")
    monkeypatch.setattr(w, "_get", down)
    assert run(env, "--force") == 1
    logs = sorted(env["logs"].glob("watch-*.log"))
    assert len(logs) == 2
    assert "FAIL" in logs[-1].read_text(encoding="utf-8")
    assert "network is down" in logs[-1].read_text(encoding="utf-8")


def test_the_watch_reads_the_shipped_profile_for_what_to_watch():
    target = w.watch_target()
    assert target["npm_package"] == "@agentclientprotocol/claude-agent-acp"
    assert target["upstream_repo"] == "agentclientprotocol/claude-agent-acp"
    assert target["pinned_schema"].startswith("schema-v")


def test_the_scheduler_wrapper_runs_daily_and_keeps_the_output():
    # Rule 23 lessons: the task action discards stdout, so the wrapper
    # redirects to a log; the trigger is DAILY for this live project.
    ps1 = Path("scripts/register_watch_task.ps1").read_text(encoding="utf-8")
    assert "-Daily" in ps1
    assert ">>" in ps1 and "2>&1" in ps1
    assert "--daily" in ps1
    assert "Get-ScheduledTaskInfo" in ps1            # verification is part of it


def test_the_npm_lookup_never_goes_through_a_shell(monkeypatch):
    """`shell=(os.name == "nt")` handed the argv LIST to cmd.exe, which joins
    and re-parses it — so `npm_package`, a value read from a profile file, was
    interpolated into a command line. npm is resolved as an executable now
    (npm.cmd on Windows) and run directly (review 2026-09-06)."""
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["kw"] = kw
        return w.subprocess.CompletedProcess(cmd, 0, "{}", "")

    monkeypatch.setattr(w.subprocess, "run", fake_run)
    monkeypatch.setattr(w.shutil, "which", lambda name: "C:\n\npm.cmd")
    w.installed_version("@scope/pkg & calc.exe")
    assert not seen["kw"].get("shell")
    # the package is one argument, whatever it contains
    assert "@scope/pkg & calc.exe" in seen["cmd"]
    assert seen["cmd"][0] == "C:\n\npm.cmd"


def test_npm_not_on_path_gives_a_reason_not_a_silent_none(monkeypatch):
    """2026-09-16: a scheduled run reported 'installed not installed' with
    outcome 'ok' -- installed_version() swallowed whatever went wrong and left
    no way to tell PATH-missing from npm-failed from bad-JSON apart. version
    is None either way; the reason is what a human needs."""
    monkeypatch.setattr(w.shutil, "which", lambda name: None)
    monkeypatch.setattr(w, "_npm_fallback_paths", lambda: [])
    version, reason = w.installed_version("@agentclientprotocol/claude-agent-acp")
    assert version is None
    assert "PATH" in reason


def test_npm_ls_failure_gives_a_reason(monkeypatch):
    monkeypatch.setattr(w.shutil, "which", lambda name: "npm.cmd")

    def boom(cmd, **kw):
        raise OSError("access is denied")
    monkeypatch.setattr(w.subprocess, "run", boom)
    version, reason = w.installed_version("@agentclientprotocol/claude-agent-acp")
    assert version is None
    assert "access is denied" in reason


def test_npm_executable_falls_back_to_the_programfiles_install_when_path_lookup_fails(monkeypatch, tmp_path):
    """Task Scheduler runs outside the interactive shell's PATH; the standard
    Node.js MSI install location is a steadier source of truth than PATH."""
    monkeypatch.setattr(w.shutil, "which", lambda name: None)
    nodejs = tmp_path / "nodejs"
    nodejs.mkdir()
    npm_cmd = nodejs / "npm.cmd"
    npm_cmd.write_text("", encoding="utf-8")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    assert w.npm_executable() == str(npm_cmd)


def test_a_not_installed_reason_reaches_the_audit_log(env, monkeypatch):
    monkeypatch.setattr(w, "installed_version", lambda pkg: (None, "npm not found on PATH"))
    assert run(env) == 0
    logs = list(env["logs"].glob("watch-*.log"))
    assert "npm not found on PATH" in logs[0].read_text(encoding="utf-8")


def test_npm_ran_but_the_package_is_not_in_its_output_gives_a_reason(monkeypatch):
    """The likeliest real cause behind the 2026-09-16 run: npm ls -g succeeds
    (valid JSON, exit 0) but resolves a different global prefix than the one
    the package was installed under (a Task Scheduler run's S4U token can
    differ from an interactive login's) -- so the package is simply absent
    from ITS output. That is not a crash and not caught by any except above;
    it needs its own reason, which should hint at the actual cause."""
    monkeypatch.setattr(w.shutil, "which", lambda name: "npm.cmd")

    def fake_run(cmd, **kw):
        return w.subprocess.CompletedProcess(cmd, 0, "{}", "")
    monkeypatch.setattr(w.subprocess, "run", fake_run)
    version, reason = w.installed_version("@agentclientprotocol/claude-agent-acp")
    assert version is None
    assert "prefix" in reason.lower()


def test_npm_ls_timeout_gives_a_reason(monkeypatch):
    monkeypatch.setattr(w.shutil, "which", lambda name: "npm.cmd")

    def timeout(cmd, **kw):
        raise w.subprocess.TimeoutExpired(cmd, kw.get("timeout", 60))
    monkeypatch.setattr(w.subprocess, "run", timeout)
    version, reason = w.installed_version("@agentclientprotocol/claude-agent-acp")
    assert version is None
    assert "timed out" in reason


def test_npm_ls_bad_json_gives_a_reason(monkeypatch):
    monkeypatch.setattr(w.shutil, "which", lambda name: "npm.cmd")

    def fake_run(cmd, **kw):
        return w.subprocess.CompletedProcess(cmd, 0, "not json", "")
    monkeypatch.setattr(w.subprocess, "run", fake_run)
    version, reason = w.installed_version("@agentclientprotocol/claude-agent-acp")
    assert version is None
    assert "JSON" in reason


def test_an_unresolvable_latest_schema_reports_unknown_not_up_to_date(env, monkeypatch):
    """The adapter side of this got fixed on 2026-09-16; the schema side
    never did (hostile Fable 5 review, 2026-09-19): `schema_latest is None`
    made `schema_behind` falsy, which rendered as plain "up to date" --
    indistinguishable from a confirmed match."""
    def flaky_get(url, timeout=30):
        if "agent-client-protocol/releases/latest" in url:
            return {"tag_name": None}          # GitHub answered, no usable tag
        return fake_get(url, timeout)
    monkeypatch.setattr(w, "_get", flaky_get)
    assert run(env) == 0
    report = (env["outdir"] / "2026-09-05.md").read_text(encoding="utf-8")
    schema_line = report.split("## Protocol schema")[1].split("##")[0]
    assert "UNKNOWN" in schema_line
    assert "up to date" not in schema_line.lower()
    assert "BEHIND" not in schema_line


def test_an_unresolvable_install_reports_unknown_not_up_to_date(env, monkeypatch):
    """2026-09-16's real report said 'installed not installed ... up to date'
    -- False: not knowing the installed version is not the same as knowing it
    matches latest. render() must not claim a state it cannot support."""
    monkeypatch.setattr(w, "installed_version",
                        lambda pkg: (None, "npm not found on PATH"))
    assert run(env) == 0
    report = (env["outdir"] / "2026-09-05.md").read_text(encoding="utf-8")
    adapter_line = report.split("## Adapter")[1].split("##")[0]
    assert "UNKNOWN" in adapter_line
    assert "up to date" not in adapter_line.lower()
    assert "BEHIND" not in adapter_line

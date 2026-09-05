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
    monkeypatch.setattr(w, "installed_version", lambda pkg: "0.73.0")
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

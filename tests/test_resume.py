# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
import json
import os
import time
from pathlib import Path

from claudiu.resume import scan_recent_sessions


def write_session(pdir, sid, records, age=0):
    pdir.mkdir(parents=True, exist_ok=True)
    f = pdir / f"{sid}.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    if age:
        past = time.time() - age
        os.utime(f, (past, past))
    return f


def user_rec(text, cwd="C:/proj"):
    return {"type": "user", "cwd": cwd,
            "message": {"role": "user", "content": text}}


def test_missing_dir_is_empty_not_error(tmp_path):
    projects, report = scan_recent_sessions(tmp_path / "absent")
    assert projects == []
    assert report["session_files"] == 0


def test_finds_cwd_summary_and_sorts_newest_first(tmp_path):
    p = tmp_path / "C--proj"
    write_session(p, "old", [user_rec("old prompt")], age=3600)
    write_session(p, "new", [user_rec("new prompt")])
    projects, report = scan_recent_sessions(tmp_path)
    assert len(projects) == 1
    # A record's cwd is normalized (resolve()) so it matches a project's
    # config path regardless of slash direction -- see the dedicated
    # normalization test below.
    assert projects[0]["path"] == str(Path("C:/proj").resolve())
    ids = [s["id"] for s in projects[0]["sessions"]]
    assert ids == ["new", "old"]
    assert projects[0]["sessions"][0]["summary"] == "new prompt"
    assert report["session_files"] == 2


def test_content_list_form_and_limit(tmp_path):
    p = tmp_path / "C--proj"
    rec = {"type": "user", "cwd": "C:/proj", "message": {
        "role": "user",
        "content": [{"type": "text", "text": "from a list"}]}}
    for i in range(7):
        write_session(p, f"s{i}", [rec], age=i)
    projects, _ = scan_recent_sessions(tmp_path, limit_per_project=5)
    assert len(projects[0]["sessions"]) == 5
    assert projects[0]["sessions"][0]["summary"] == "from a list"


def test_bad_lines_and_unknown_types_counted_not_dropped(tmp_path):
    p = tmp_path / "C--proj"
    f = p; p.mkdir(parents=True)
    (f / "weird.jsonl").write_text(
        'not json at all\n'
        + json.dumps({"type": "worktree-state", "cwd": "C:/proj"}) + "\n"
        + json.dumps({"type": "user", "cwd": "C:/proj",
                      "message": {"role": "user", "content": "hi"}}),
        encoding="utf-8")
    projects, report = scan_recent_sessions(tmp_path)
    assert report["bad_lines"] == 1
    assert report["record_types"].get("worktree-state") == 1
    assert projects[0]["sessions"][0]["summary"] == "hi"


def test_no_user_record_still_listed(tmp_path):
    p = tmp_path / "C--mystery"
    write_session(p, "s1", [{"type": "system", "note": "x"}])
    projects, _ = scan_recent_sessions(tmp_path)
    assert projects[0]["path"] == "C--mystery"
    assert projects[0]["sessions"][0]["summary"] == "(no prompt found)"


def test_backslash_and_forward_slash_cwd_are_the_same_project(tmp_path):
    # A record's cwd (as Claude Code writes it -- backslashes on Windows)
    # must group under the same project as a config.json path written with
    # forward slashes, so the ended-tab Resume button finds it (F3).
    p = tmp_path / "C--code-app"
    write_session(p, "s1", [user_rec("hi", cwd="C:\\code\\app")])
    projects, _ = scan_recent_sessions(tmp_path)
    assert len(projects) == 1
    assert projects[0]["path"] == str(Path("C:/code/app").resolve())


def test_exists_flag_reflects_the_real_directory(tmp_path):
    p = tmp_path / "C--proj"
    write_session(p, "s1", [user_rec("hi", cwd=str(tmp_path / "C--proj"))])
    projects, _ = scan_recent_sessions(tmp_path)
    assert projects[0]["exists"] is True
    write_session(p, "s2", [user_rec("hi", cwd="Z:/does/not/exist")])
    projects, _ = scan_recent_sessions(tmp_path)
    missing = [pr for pr in projects
               if pr["path"] == str(Path("Z:/does/not/exist").resolve())][0]
    assert missing["exists"] is False


def test_zero_limit_does_not_crash(tmp_path):
    p = tmp_path / "C--proj"
    write_session(p, "s1", [user_rec("test")])
    projects, _ = scan_recent_sessions(tmp_path, limit_per_project=0)
    assert len(projects) == 1
    assert projects[0]["sessions"] == []

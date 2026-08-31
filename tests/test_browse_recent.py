# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""Launcher backend: folder picker, mkdir, and the recent-folders file."""
import json

from claudiu.browse import list_dirs, make_dir
from claudiu.recent import add_recent, load_recent


def test_list_dirs_lists_only_subdirectories(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    result = list_dirs(str(tmp_path))
    names = [d["name"] for d in result["dirs"]]
    assert names == ["a", "b"]  # sorted, no file, no dotfile
    assert result["parent"] == str(tmp_path.parent)
    assert result["error"] is None


def test_list_dirs_bad_path_reports_error_without_raising(tmp_path):
    result = list_dirs(str(tmp_path / "does-not-exist"))
    assert result["dirs"] == [] and result["error"]


def test_make_dir_creates_and_rejects_bad_names(tmp_path):
    ok = make_dir(str(tmp_path), "new-project")
    assert (tmp_path / "new-project").is_dir()
    assert ok["path"].endswith("new-project")
    assert make_dir(str(tmp_path), "new-project")["error"]  # already exists
    assert make_dir(str(tmp_path), "a/b")["error"]          # separator
    assert make_dir(str(tmp_path), "")["error"]             # empty
    assert make_dir(str(tmp_path / "nope"), "x")["error"]   # missing parent


def test_recent_roundtrip_dedupes_and_orders(tmp_path):
    assert load_recent(tmp_path) == []
    (tmp_path / "p1").mkdir()
    (tmp_path / "p2").mkdir()
    add_recent(tmp_path, str(tmp_path / "p1"), "One")
    items = add_recent(tmp_path, str(tmp_path / "p2"), "Two")
    assert [i["name"] for i in items] == ["Two", "One"]
    # re-launching p1 moves it to the front and bumps its count
    items = add_recent(tmp_path, str(tmp_path / "p1"))
    assert items[0]["path"].endswith("p1") and items[0]["count"] == 2
    assert len(items) == 2


def test_recent_respects_cap(tmp_path):
    for i in range(5):
        add_recent(tmp_path, str(tmp_path / f"p{i}"), cap=3)
    items = load_recent(tmp_path)
    assert len(items) == 3
    assert [i["path"].rsplit("p", 1)[1] for i in items] == ["4", "3", "2"]


def test_recent_tolerates_corrupt_file(tmp_path):
    (tmp_path / "recent.json").write_text("{not json", encoding="utf-8")
    assert load_recent(tmp_path) == []
    add_recent(tmp_path, str(tmp_path))
    assert isinstance(json.loads((tmp_path / "recent.json").read_text()), list)

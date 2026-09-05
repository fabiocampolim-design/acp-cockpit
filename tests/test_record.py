# SPDX-License-Identifier: Apache-2.0
import os
import time

from acp_cockpit.core.record import Recorder, prune


def test_append_returns_line_numbers_and_replay_roundtrips(tmp_path):
    p = tmp_path / "s1.jsonl"
    with Recorder(p) as rec:
        n1 = rec.append({"dir": "in", "frame": {"jsonrpc": "2.0", "id": 1}})
        n2 = rec.append({"dir": "client", "action": "prompt", "text": "hi"})
    assert (n1, n2) == (1, 2)
    entries = list(Recorder(p).replay())
    assert entries[0][0] == 1
    assert entries[0][1]["frame"] == {"jsonrpc": "2.0", "id": 1}
    assert entries[1][1]["action"] == "prompt"
    assert all("t" in e for _, e in entries)   # timestamps auto-added


def test_frames_stored_verbatim_including_unknown_fields(tmp_path):
    p = tmp_path / "s2.jsonl"
    weird = {"jsonrpc": "2.0", "method": "x/y", "novel_field": {"deep": [1]}}
    with Recorder(p) as rec:
        rec.append({"dir": "in", "frame": weird})
    (_, entry), = Recorder(p).replay()
    assert entry["frame"] == weird


def test_append_survives_reopen(tmp_path):
    p = tmp_path / "s3.jsonl"
    with Recorder(p) as rec:
        rec.append({"dir": "in", "frame": {}})
    with Recorder(p) as rec:
        assert rec.append({"dir": "in", "frame": {}}) == 2


def _aged(path, days):
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def test_prune_keeps_everything_by_default(tmp_path):
    # Records hold the whole conversation: deleting one is the owner's
    # decision, so the policy exists but is opt-in (audit 2026-09-04).
    p = tmp_path / "old.jsonl"
    p.write_text("{}\n", encoding="utf-8")
    _aged(p, 400)
    assert prune(tmp_path, 0) == []
    assert prune(tmp_path, -1) == []
    assert p.exists()


def test_prune_removes_only_what_is_older_than_the_window(tmp_path):
    old, recent = tmp_path / "old.jsonl", tmp_path / "recent.jsonl"
    for f in (old, recent):
        f.write_text("{}\n", encoding="utf-8")
    _aged(old, 40)
    _aged(recent, 3)
    assert prune(tmp_path, 30) == ["old.jsonl"]
    assert recent.exists() and not old.exists()


def test_prune_ignores_everything_that_is_not_a_record(tmp_path):
    keep = tmp_path / "notes.txt"
    keep.write_text("x", encoding="utf-8")
    _aged(keep, 400)
    assert prune(tmp_path, 1) == []
    assert keep.exists()


def test_prune_on_a_missing_directory_is_not_an_error(tmp_path):
    assert prune(tmp_path / "nope", 30) == []

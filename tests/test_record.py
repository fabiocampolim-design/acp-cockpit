# SPDX-License-Identifier: Apache-2.0
from claudiu.core.record import Recorder


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

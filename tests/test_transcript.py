# SPDX-License-Identifier: Apache-2.0
"""The built-in Markdown transcript (the archive fallback)."""
import gc
import json
import os
import warnings

from acp_cockpit.core.transcript import write_markdown


def _record(path):
    entries = [
        {"t": "2026-09-06T00:00:00+00:00", "dir": "client", "action": "prompt",
         "text": "say hello"},
        {"t": "2026-09-06T00:00:01+00:00", "dir": "in", "frame": {
            "jsonrpc": "2.0", "method": "session/update", "params": {
                "sessionId": "a", "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "hello world"}}}}},
    ]
    path.write_text("".join(json.dumps(e) + "\n" for e in entries),
                    encoding="utf-8")
    return path


def test_writing_the_transcript_leaves_no_handle_on_the_live_record(tmp_path):
    """write_markdown opened a Recorder (append mode) on the session's live
    record to replay it and never closed it — a leaked handle per archive,
    on the file the session is still writing (review 2026-09-06)."""
    record = _record(tmp_path / "s1.jsonl")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        written = write_markdown(record, tmp_path / "out", "agent-1", "T")
        gc.collect()
    leaks = [w for w in caught if issubclass(w.category, ResourceWarning)
             and "s1.jsonl" in str(w.message)]
    assert not leaks, [str(w.message) for w in leaks]
    # and the record can be moved at once (Windows refuses while a handle
    # is open)
    os.replace(record, tmp_path / "moved.jsonl")
    text = (tmp_path / "out" / os.path.basename(written)).read_text(
        encoding="utf-8")
    assert "say hello" in text and "hello world" in text

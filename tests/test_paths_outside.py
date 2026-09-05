# SPDX-License-Identifier: Apache-2.0
"""The out-of-boundary warning is the one safety control the client has for
agent-side shell execution. A warning that fires on every URL and every
`/api/...` token trains the reader to ignore it (review 2026-09-05)."""
from tests.helpers import make_session
from tests.test_acp_handshake import do_handshake, feed


def _warn(tmp_path, title):
    session, proc, sink = make_session(tmp_path)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "id": 70,
                   "method": "session/request_permission", "params": {
                       "sessionId": "acp-123",
                       "toolCall": {"toolCallId": "t9", "kind": "execute",
                                    "title": title},
                       "options": [{"optionId": "a", "name": "Allow",
                                    "kind": "allow_once"}]}})
    return [e for e in sink.events
            if e.kind == "permission_request"][0].data["outside_boundary"]


def test_urls_are_not_paths(tmp_path):
    assert _warn(tmp_path, "WebFetch https://example.com/docs/page") == []
    assert _warn(tmp_path, "curl -s http://registry.npmjs.org/x/latest") == []


def test_route_like_tokens_that_exist_nowhere_are_not_paths(tmp_path):
    # `/api/sessions` is text about an HTTP route; nothing on this machine
    # has a top-level directory called `api`.
    assert _warn(tmp_path, "GET /api/sessions returns 200") == []


def test_a_real_directory_outside_the_boundary_is_still_flagged(tmp_path):
    outside = str(tmp_path.parent / "elsewhere.txt")
    assert _warn(tmp_path, f"cat {outside}") == [outside]


def test_a_windows_drive_path_outside_is_flagged_even_if_absent(tmp_path):
    # A drive-letter path is unambiguous: nothing else looks like `Q:\x\y`.
    assert _warn(tmp_path, r"type Q:\secrets\keys.txt") == [r"Q:\secrets\keys.txt"]


# ---- review 2026-09-05 (independent /code-review of the release range) ----

def test_a_git_bash_drive_path_is_a_path_on_windows(tmp_path):
    # Claude Code's shell on Windows is Git Bash: `cat /c/Work/x/.ssh/id_rsa`
    # is a real path outside the boundary and MUST warn. The first version
    # of the URL fix asked the host whether `/c` is a directory (it is not,
    # on Windows) and dropped every such path silently.
    import os
    if os.name != "nt":
        import pytest
        pytest.skip("Git Bash drive paths are a Windows concern")
    found = _warn(tmp_path, "cat /c/Work/somebody/.ssh/id_rsa")
    assert found == ["C:\\Work\\somebody\\.ssh\\id_rsa"], found


def test_the_boundary_check_does_no_filesystem_io_in_core(tmp_path, monkeypatch):
    # core/ does no real I/O (AGENTS.md); the "does this top-level directory
    # exist" question goes through the FileAccess port, which tests control.
    from tests.helpers import make_session, FakeFiles
    from tests.test_acp_handshake import do_handshake, feed
    files = FakeFiles()
    files.dirs = {"/srv"}                    # the only top-level dir "on disk"
    session, proc, sink = make_session(tmp_path, files=files)
    do_handshake(session, proc)
    feed(session, {"jsonrpc": "2.0", "id": 71,
                   "method": "session/request_permission", "params": {
                       "sessionId": "acp-123",
                       "toolCall": {"toolCallId": "t", "kind": "execute",
                                    "title": "cat /srv/app/secret and /nope/x/y"},
                       "options": [{"optionId": "a", "name": "Allow",
                                    "kind": "allow_once"}]}})
    ev = [e for e in sink.events if e.kind == "permission_request"][0]
    assert ev.data["outside_boundary"] == ["/srv/app/secret"]

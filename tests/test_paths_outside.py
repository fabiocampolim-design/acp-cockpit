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

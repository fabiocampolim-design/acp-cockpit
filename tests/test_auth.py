# SPDX-License-Identifier: Apache-2.0
import os
import stat

import pytest
from acp_cockpit.server.auth import TokenAuth, COOKIE_NAME


def test_token_is_long_and_unique():
    a, b = TokenAuth(), TokenAuth()
    assert len(a.token) >= 43          # token_urlsafe(32)
    assert a.token != b.token


def test_verify():
    a = TokenAuth()
    assert a.verify(a.token)
    assert not a.verify(a.token[:-1] + "x")
    assert not a.verify("")
    assert not a.verify(None)


def test_cookie_name_stable():
    assert COOKIE_NAME == "acp_cockpit_token"


def test_token_file_persists_and_is_reused(tmp_path):
    f = tmp_path / "state" / "token"          # parent created on demand
    a = TokenAuth.from_file(f)
    assert f.read_text(encoding="utf-8").strip() == a.token
    b = TokenAuth.from_file(f)
    assert b.token == a.token                  # a pinned URL keeps working
    f.write_text("too-short", encoding="utf-8")
    c = TokenAuth.from_file(f)                 # untrustworthy -> replaced
    assert len(c.token) >= 43 and c.token != "too-short"
    assert f.read_text(encoding="utf-8").strip() == c.token



@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_the_token_file_is_never_readable_by_anyone_else(tmp_path):
    """The file was written with the default umask and chmod'd afterwards, so
    on a permissive umask it existed world-readable for a moment — and the
    chmod's failure was swallowed. It is created 0600 (review 2026-09-06)."""
    old = os.umask(0o000)
    try:
        path = tmp_path / "token"
        TokenAuth.from_file(path)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        os.umask(old)

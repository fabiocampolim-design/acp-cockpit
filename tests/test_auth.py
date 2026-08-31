# SPDX-License-Identifier: Apache-2.0
from claudiu.server.auth import TokenAuth, COOKIE_NAME


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
    assert COOKIE_NAME == "claudiu_token"

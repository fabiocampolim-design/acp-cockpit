# SPDX-License-Identifier: Apache-2.0
"""Bearer token; localhost is not a trust boundary. Per launch by default;
`--token-file` keeps one across launches so a pinned-port URL stays valid."""
from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path

COOKIE_NAME = "acp_cockpit_token"
MIN_TOKEN_CHARS = 32


def origin_ok(origin, host: str) -> bool:
    """Is `origin` this very server, or no browser origin at all?

    Cookies are NOT scoped by port: a page served from any other port on the
    loopback interface carries our token automatically. Accepting every
    `http://127.0.0.1:*` origin therefore handed the API to any local web
    page the user happened to visit (audit 2026-09-04). The origin must
    equal the host the browser actually connected to, port included.

    A missing Origin is not an origin failure: same-origin subresource GETs
    and non-browser clients send none, and the token authenticates those.
    """
    if not origin:
        return True
    return origin == "http://" + host


class TokenAuth:
    def __init__(self, token: str | None = None):
        self.token = token or secrets.token_urlsafe(32)

    @classmethod
    def from_file(cls, path) -> "TokenAuth":
        """Reuse the token stored at `path`; create it (owner-only where the
        OS supports modes) when missing or too short to trust."""
        path = Path(path)
        try:
            stored = path.read_text(encoding="utf-8").strip()
        except OSError:
            stored = ""
        if len(stored) >= MIN_TOKEN_CHARS:
            return cls(stored)
        auth = cls()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Created 0600, not created-then-chmod'd: under a permissive umask the
        # file existed readable by everyone for the moment in between, and the
        # chmod's own failure was swallowed (review 2026-09-06). The mode
        # argument is ignored on Windows, where the ACL is inherited.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(auth.token + "\n")
        try:
            os.chmod(path, 0o600)          # an existing file keeps its mode
        except OSError:
            pass
        return auth

    def verify(self, presented) -> bool:
        if not presented:
            return False
        return hmac.compare_digest(self.token, str(presented))

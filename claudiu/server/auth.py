# SPDX-License-Identifier: Apache-2.0
"""Bearer token; localhost is not a trust boundary. Per launch by default;
`--token-file` keeps one across launches so a pinned-port URL stays valid."""
from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path

COOKIE_NAME = "claudiu_token"
MIN_TOKEN_CHARS = 32


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
        path.write_text(auth.token + "\n", encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return auth

    def verify(self, presented) -> bool:
        if not presented:
            return False
        return hmac.compare_digest(self.token, str(presented))

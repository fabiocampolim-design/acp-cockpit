# SPDX-License-Identifier: Apache-2.0
"""Per-launch bearer token; localhost is not a trust boundary."""
from __future__ import annotations

import hmac
import secrets

COOKIE_NAME = "claudiu_token"


class TokenAuth:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)

    def verify(self, presented) -> bool:
        if not presented:
            return False
        return hmac.compare_digest(self.token, str(presented))

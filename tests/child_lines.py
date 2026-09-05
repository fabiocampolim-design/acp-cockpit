# SPDX-License-Identifier: Apache-2.0
"""Test child: echoes each stdin line as {"echo": line}; reports env once.
With IGNORE_TERM=1 it ignores SIGTERM where that is possible (POSIX), to
stand in for an adapter that does not go quietly."""
import json
import os
import signal
import sys

if os.environ.get("IGNORE_TERM") == "1" and hasattr(signal, "SIGTERM") \
        and os.name != "nt":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

print(json.dumps({"env_has_CLAUDECODE": "CLAUDECODE" in os.environ,
                  "env_has_marker": "CLAUDE_CODE_MARKER" in os.environ,
                  "env_extra": os.environ.get("EXTRA_VAR", "")}), flush=True)
for line in sys.stdin:
    line = line.rstrip("\n")
    if line == "QUIT":
        break
    print(json.dumps({"echo": line}), flush=True)
print("bye on stderr", file=sys.stderr, flush=True)

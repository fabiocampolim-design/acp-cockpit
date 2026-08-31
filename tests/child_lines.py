"""Test child: echoes each stdin line as {"echo": line}; reports env once."""
import json
import os
import sys

print(json.dumps({"env_has_CLAUDECODE": "CLAUDECODE" in os.environ,
                  "env_has_marker": "CLAUDE_CODE_MARKER" in os.environ,
                  "env_extra": os.environ.get("EXTRA_VAR", "")}), flush=True)
for line in sys.stdin:
    line = line.rstrip("\n")
    if line == "QUIT":
        break
    print(json.dumps({"echo": line}), flush=True)
print("bye on stderr", file=sys.stderr, flush=True)

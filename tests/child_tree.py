# SPDX-License-Identifier: Apache-2.0
"""Test child that has a child of its own: spawns a grandchild that depends
on nothing (no pipe to close under it), reports its PID as
{"grandchild": pid}, then idles on stdin. Killing THIS process must take the
grandchild with it (review 2026-09-05: ten orphaned adapter CLIs from the
week before were still resident)."""
import json
import subprocess
import sys

grandchild = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(600)"],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL)
print(json.dumps({"grandchild": grandchild.pid}), flush=True)
for line in sys.stdin:
    if line.strip() == "QUIT":
        break
grandchild.terminate()

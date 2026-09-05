# SPDX-License-Identifier: Apache-2.0
"""Test helper: a stand-in server that starts one adapter through
SubprocessAgentProcess, prints the adapter's PID and then idles. The test
kills THIS process hard (TerminateProcess / SIGKILL), the way a `Stop-Process`
on the pinned server does, and checks that the adapter died with it."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from acp_cockpit.server.procs import SubprocessAgentProcess  # noqa: E402

proc = SubprocessAgentProcess(
    # an adapter that reads no stdin, so a closed pipe cannot be what ends it
    command=[sys.executable, "-c", "import time; time.sleep(600)"],
    cwd=str(Path(__file__).parent), env_scrub=[], env_set={},
    on_line=lambda ln: None, on_stderr=lambda ln: None,
    on_exit=lambda code: None)
print(json.dumps({"child": proc.pid}), flush=True)
while True:
    time.sleep(1)

# tests/test_e2e.py
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""End-to-end: read the rendered page back (rule 14 - the artefact, not
the return code). Skips cleanly when playwright is not installed."""
import json
import socket
import subprocess
import sys
import time

import pytest

sync_api = pytest.importorskip("playwright.sync_api",
                               reason="playwright not installed")

ECHO = ("import sys\nprint('READY', flush=True)\n"
        "for line in sys.stdin:\n"
        "    print('echo:' + line.strip(), flush=True)\n")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_port(port, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise AssertionError(f"server did not listen on {port}")


@pytest.fixture
def server(tmp_path):
    port = free_port()
    cfg = {
        "port": port,
        "claude_command": [sys.executable, "-u", "-c", ECHO],
        "projects": [{"name": "demoproj", "path": str(tmp_path)}],
        "snippets": [{"name": "greet", "text": "hello-from-snippet",
                      "send": True}],
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "claudiu", "--config", str(cfg_file),
         "--no-browser", "--quiet", "--log-dir", str(tmp_path / "logs")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for_port(port)
        yield f"http://127.0.0.1:{port}/"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def page_has(page, text, timeout=20000):
    page.wait_for_function(
        "t => document.body.innerText.includes(t)", arg=text,
        timeout=timeout)


def test_full_roundtrip_rendered_in_browser(server):
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(server)
        # launcher auto-opens (no sessions yet); start the demo project
        page.click(".choice")
        page_has(page, "READY")
        # keystrokes reach the pty and the echo renders back
        page.keyboard.type("roundtrip")
        page.keyboard.press("Enter")
        page_has(page, "echo:roundtrip")
        # snippet bar types into the session
        page.click(".snippet")
        page_has(page, "echo:hello-from-snippet")
        # reload: session survives, scrollback replays (spec: resilience)
        page.reload()
        page_has(page, "echo:roundtrip")
        browser.close()

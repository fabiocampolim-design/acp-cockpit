# tests/test_e2e.py
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""End-to-end: read the rendered page back (rule 14 - the artefact, not
the return code). Skips cleanly when playwright is not installed."""
import json
import os
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
    # Isolate the subprocess's home so the resume scan never touches the
    # developer's real ~/.claude/projects (Path.home() follows USERPROFILE
    # on Windows, HOME elsewhere). --config/--log-dir are passed explicitly
    # so config/log locations are unaffected by this.
    env = dict(os.environ)
    env["USERPROFILE"] = str(tmp_path)
    env["HOME"] = str(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-m", "claudiu", "--config", str(cfg_file),
         "--no-browser", "--quiet", "--log-dir", str(tmp_path / "logs")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
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
        # launcher auto-opens (no sessions yet); start the demo project.
        # Scoped to #launcher-projects: the resume list appends its own
        # .choice buttons asynchronously once /api/resume resolves, and
        # an unscoped ".choice" click is ambiguous under Playwright's
        # strict mode once that happens.
        page.click("#launcher-projects .choice")
        # the controlled conversation view is the default; the raw terminal
        # (where the echo command's output shows) is behind "Show terminal"
        page.wait_for_selector(".composer-input")
        page.click(".term-toggle")
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
        page.wait_for_selector(".term-toggle")
        page.click(".term-toggle")  # reload returns to the conversation view
        page_has(page, "echo:roundtrip")
        browser.close()


def test_shortcuts_are_discoverable(server):
    """Rule of the smoke test: nobody reads the manual before pressing
    keys. The launcher, the tab tooltip and a help overlay must all reveal
    the bindings."""
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(server)
        # the auto-opened launcher already hints at the help key
        page_has(page, "Alt+H")
        page.click("#launcher-projects .choice")
        page.wait_for_selector(".tab")  # session started
        # the tab tooltip names its switch key
        assert "Alt+1" in page.get_attribute(".tab", "title")
        # the help overlay opens by key and by button, lists real bindings
        page.keyboard.press("Alt+h")
        page_has(page, "Alt+ArrowRight")
        page.keyboard.press("Escape")
        page.wait_for_selector("#help", state="hidden")
        page.click("#helpbtn")
        page.wait_for_selector("#help", state="visible")
        page_has(page, "Ctrl+Shift+F")
        page.keyboard.press("Escape")
        page.wait_for_selector("#help", state="hidden")
        # Escape must close an overlay even while the raw terminal is focused
        # (xterm.js swallows Escape unless the handler runs in capture)
        page.click(".term-toggle")
        page.keyboard.press("Alt+h")
        page.wait_for_selector("#help", state="visible")
        page.keyboard.press("Escape")
        page.wait_for_selector("#help", state="hidden")
        # and Escape closes the launcher too
        page.keyboard.press("Alt+t")
        page.wait_for_selector("#launcher", state="visible")
        page.keyboard.press("Escape")
        page.wait_for_selector("#launcher", state="hidden")
        browser.close()

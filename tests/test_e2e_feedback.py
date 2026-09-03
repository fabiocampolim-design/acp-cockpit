# SPDX-License-Identifier: Apache-2.0
"""UI behaviour driven by Fabio's first live test (2026-08-31 20:41)."""
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import pytest

pytest.importorskip("playwright.sync_api")

PROFILE = '''
id = "cmds"
name = "Commands Agent"
command = [{python}, {adapter}, {fixture}]
install_hint = "n/a"
env_scrub = []
'''.replace("{adapter}", json.dumps(str(Path("tests/fake_adapter.py").resolve()))
).replace("{fixture}",
          json.dumps(str(Path("tests/fixtures/commands_turn.json").resolve())))


@pytest.fixture(scope="module")
def server():
    tmp = Path(tempfile.mkdtemp())
    profs = tmp / "agents"
    profs.mkdir()
    (profs / "cmds.toml").write_text(
        PROFILE.replace("{python}", json.dumps(sys.executable)),
        encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "claudiu", "--profiles", str(profs),
         "--records", str(tmp / "rec"), "--no-drift-online"],
        stdout=subprocess.PIPE, text=True, encoding="utf-8")
    url = None
    deadline = time.time() + 20
    while time.time() < deadline:
        line = proc.stdout.readline()
        m = re.search(r"(http://127\.0\.0\.1:\d+/\?token=\S+)", line or "")
        if m:
            url = m.group(1)
            break
    assert url, "server never printed its URL"
    yield url, tmp
    proc.terminate()


def display_of(page, selector):
    return page.evaluate(
        f"getComputedStyle(document.querySelector('{selector}')).display")


def start(pw, url, tmp):
    page = pw.chromium.launch().new_page()
    page.goto(url)
    assert display_of(page, "#workspace") == "none"   # hidden at load
    page.select_option("#profile", "cmds")
    page.fill("#cwd", str(tmp))
    page.click("#start")
    page.wait_for_selector("#send:not([disabled])")
    return page


def test_palette_folds_back_after_selection_and_send(server):
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start(pw, url, tmp)
        page.type("#prompt-input", "/con")
        page.wait_for_selector("#palette button")
        assert display_of(page, "#palette") != "none"
        page.click("#palette button")
        assert display_of(page, "#palette") == "none"
        assert page.input_value("#prompt-input").startswith("/context")
        page.press("#prompt-input", "Enter")
        page.wait_for_selector('[data-kind="turn_ended"]')
        assert display_of(page, "#palette") == "none"


def test_model_selector_and_thinking_marker_and_stderr(server):
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start(pw, url, tmp)
        page.wait_for_selector("#model:not([hidden])")
        assert page.input_value("#model") == "default"
        # short label in the box, the description (the real identity —
        # "Default" is Opus) in the tooltip
        assert page.inner_text("#model option[value=default]").strip() == "Default"
        assert "Opus" in page.get_attribute("#model option[value=default]", "title")
        page.select_option("#model", "sonnet")
        # selector wait, not wait_for_function: the page's CSP forbids eval
        page.wait_for_selector("#status .model:text-is('sonnet')")
        page.fill("#prompt-input", "go")
        page.click("#send")
        page.wait_for_selector("#working")          # visible while the turn runs
        assert "working" in page.inner_text("#working")
        page.wait_for_selector('[data-kind="turn_ended"]')
        assert page.query_selector("#working") is None   # gone when it ends
        thought = page.inner_text(
            '[data-kind="message_chunk"][data-role="thought"]')
        assert "thinking" in thought.lower()
        # stderr: a counted chip in the strip and a drawer on click — never
        # an inline row, never an anomaly
        page.wait_for_selector("#status .stderr-chip:not([hidden])")
        assert page.inner_text("#status .stderr-chip").startswith("stderr (")
        assert page.query_selector_all('#conversation [data-kind="stderr"]') == []
        page.click("#status .stderr-chip")
        page.wait_for_selector("#stderr-drawer:not([hidden])")
        assert "Context Usage" in page.inner_text("#stderr-drawer")
        assert page.is_hidden("#status .anomaly-chip")

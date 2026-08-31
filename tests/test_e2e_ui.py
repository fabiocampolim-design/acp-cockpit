# SPDX-License-Identifier: Apache-2.0
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import pytest

pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def server():
    tmp = Path(tempfile.mkdtemp())
    profs = tmp / "agents"
    profs.mkdir()
    from tests.test_server import FIXTURE_PROFILE
    (profs / "fake.toml").write_text(
        FIXTURE_PROFILE.format(python=sys.executable), encoding="utf-8")
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


def start_fake_session(pw, url, tmp):
    page = pw.chromium.launch().new_page()
    page.goto(url)
    page.select_option("#profile", "fake")
    page.fill("#cwd", str(tmp))
    page.click("#start")
    page.wait_for_selector("#workspace:not([hidden])")
    # composer enables only once the session reaches "ready"
    page.wait_for_selector("#send:not([disabled])")
    return page


def test_full_turn_and_permission(server):
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.fill("#prompt-input", "say hello")
        page.click("#send")
        page.wait_for_selector('[data-kind="turn_ended"]')
        convo = page.inner_text("#conversation")
        assert "hello world" in convo
        # permission round trip
        page.fill("#prompt-input", "do the PERMISSION thing")
        page.click("#send")
        page.wait_for_selector("#permission[open]")
        page.click('#perm-options button[data-option="y"]')
        page.wait_for_selector("#permission", state="hidden")


def test_permission_reject_path(server):
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.fill("#prompt-input", "do the PERMISSION thing")
        page.click("#send")
        page.wait_for_selector("#permission[open]")
        page.click('#perm-options button[data-option="n"]')
        page.wait_for_selector("#permission", state="hidden")
        page.wait_for_selector('[data-kind="turn_ended"]')

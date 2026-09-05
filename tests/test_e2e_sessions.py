# SPDX-License-Identifier: Apache-2.0
"""UI: tabs, diffs, usage gauge, config options, resume, liveness."""
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import pytest

pytest.importorskip("playwright.sync_api")
from tests.test_e2e_feedback import PROFILE, display_of  # noqa: E402


@pytest.fixture(scope="module")
def server():
    import json
    tmp = Path(tempfile.mkdtemp())
    profs = tmp / "agents"
    profs.mkdir()
    (profs / "cmds.toml").write_text(
        PROFILE.replace("{python}", json.dumps(sys.executable)),
        encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "acp_cockpit", "--profiles", str(profs),
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


def new_session(page, tmp):
    page.select_option("#profile", "cmds")
    page.fill("#cwd", str(tmp))
    page.click("#start")
    page.wait_for_selector("#send:not([disabled])")


def test_tabs_two_sessions_switch_and_titles(server):
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        page.goto(url)
        page.wait_for_selector("#tab-add")
        page.click("#tab-add")
        page.wait_for_selector("#launcher:not([hidden])")
        new_session(page, tmp)
        page.wait_for_selector(".tab.active:has-text('Fixture session')")
        page.click("#tab-add")
        assert display_of(page, "#launcher") != "none"
        new_session(page, tmp)
        tabs = page.query_selector_all(".tab:not(.add)")
        assert len(tabs) == 2
        # prompt in tab 2, then switch to tab 1: its pane must be empty
        page.fill("#prompt-input", "hello two")
        page.click("#send")
        page.wait_for_selector('.pane:not([hidden]) [data-kind="turn_ended"]')
        tabs[0].click()
        page.wait_for_selector(".pane:not([hidden])", state="attached")
        visible_text = page.inner_text(".pane:not([hidden])")
        assert "hello two" not in visible_text
        tabs[1].click()
        assert "hello two" in page.inner_text(".pane:not([hidden])")
        # close tab 2 -> tab 1 becomes active
        page.click(".tab.active .close")
        assert len(page.query_selector_all(".tab:not(.add)")) == 1


def test_usage_gauge_config_options_and_diff(server):
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        page.goto(url)
        page.wait_for_selector("#tab-add")
        page.click("#tab-add")
        page.wait_for_selector("#launcher:not([hidden])")
        new_session(page, tmp)
        page.wait_for_selector("#status .usage:has-text('59.3k')")
        assert "6%" in page.inner_text("#status .usage")
        assert "0.42 USD" in page.inner_text("#status .usage")
        page.wait_for_selector("#config-options select[data-config=effort]")
        assert page.input_value("#config-options select[data-config=effort]") == "high"
        page.select_option("#config-options select[data-config=effort]", "low")
        deadline = time.time() + 10
        while time.time() < deadline and page.input_value(
                "#config-options select[data-config=effort]") != "low":
            time.sleep(0.2)
        assert page.input_value("#config-options select[data-config=effort]") == "low"
        page.fill("#prompt-input", "make a DIFF")
        page.click("#send")
        page.wait_for_selector('.pane:not([hidden]) [data-kind="turn_ended"]')
        rows = page.query_selector_all('.pane:not([hidden]) [data-kind="tool_call"]')
        assert len(rows) == 1, "tool_call + update must merge into one row"
        assert rows[0].get_attribute("data-status") == "completed"
        # results are collapsed by default (like the terminal); the toolbar
        # checkbox opens them
        assert not page.query_selector('[data-kind="tool_call"] details').get_attribute("open")
        page.check("#expand-tools")
        adds = [r.inner_text() for r in page.query_selector_all(".diff .add")]
        dels = [r.inner_text() for r in page.query_selector_all(".diff .del")]
        assert adds == ["+ B", "+ d"] and dels == ["- b"]


def test_resume_from_launcher(server):
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        page.goto(url)
        page.wait_for_selector("#tab-add")
        page.click("#tab-add")
        page.wait_for_selector("#launcher:not([hidden])")
        page.select_option("#profile", "cmds")
        page.fill("#cwd", str(tmp))
        page.click("#refresh-recent")
        page.wait_for_selector("#recent-list button[data-resume=old-1]",
                               timeout=45000)
        assert "Old work" in page.inner_text("#recent-list")
        page.click("#recent-list button[data-resume=old-1]")
        page.wait_for_selector("#send:not([disabled])")
        page.wait_for_selector("#status .mode:text-is('plan')")


def test_working_row_shows_last_activity(server):
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        page.goto(url)
        page.wait_for_selector("#tab-add")
        page.click("#tab-add")
        page.wait_for_selector("#launcher:not([hidden])")
        new_session(page, tmp)
        page.fill("#prompt-input", "go slow")
        page.click("#send")
        page.wait_for_selector("#working")
        text = page.inner_text("#working")
        assert "agent working" in text and "Stop cancels" in text
        page.wait_for_selector('.pane:not([hidden]) [data-kind="turn_ended"]')
        assert page.query_selector("#working") is None

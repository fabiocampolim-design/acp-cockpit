# SPDX-License-Identifier: Apache-2.0
import json
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
    from tests.test_server import FIXTURE_PROFILE, PY_NAME
    (profs / "fake.toml").write_text(
        FIXTURE_PROFILE.format(python=sys.executable), encoding="utf-8")
    # same adapter plus an env_resolve entry: the launcher must show it
    (profs / "resolving.toml").write_text(
        FIXTURE_PROFILE.format(python=sys.executable).replace(
            'id = "fake"', 'id = "resolving"')
        + "[env_resolve]" + chr(10) + "EXTRA_VAR = " + json.dumps(PY_NAME)
        + chr(10), encoding="utf-8")
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


def test_launcher_shows_the_resolved_runtime(server):
    # The runtime line is the user-visible half of the 2026-09-01 fix: it
    # says which CLI the adapter will be pointed at (or nothing at all).
    url, tmp = server
    import shutil
    from tests.test_server import PY_NAME
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        page.goto(url)
        page.select_option("#profile", "resolving")
        page.wait_for_selector("#caveats .runtime")
        assert page.inner_text("#caveats .runtime") == \
            f"runtime: EXTRA_VAR → {shutil.which(PY_NAME)}"
        page.select_option("#profile", "fake")
        assert page.query_selector("#caveats .runtime") is None


def test_tab_bar_stays_visible_when_the_launcher_is_taller_than_the_window(server):
    # 2026-09-03: the caveat list outgrew a short window and the flex body
    # squashed the tab bar to a sliver with the "+" pushed above the top.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        # the fixture agent has no caveats: a very short window stands in
        # for the long caveat list of a real profile
        page = pw.chromium.launch().new_page(viewport={"width": 900,
                                                       "height": 240})
        page.goto(url)
        page.wait_for_selector("#start")
        box = page.locator("#tab-add").bounding_box()
        assert box["y"] >= 0 and box["height"] >= 20, box
        # the launcher itself scrolls; the page body does not grow
        assert page.evaluate("document.body.scrollHeight <= innerHeight + 1")


def test_folder_picker_navigates_and_fills_the_directory(server):
    url, tmp = server
    sub = tmp / "proj-a"
    sub.mkdir(exist_ok=True)
    (sub / "inner").mkdir(exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        page.goto(url)
        page.fill("#cwd", str(tmp))
        page.click("#browse")
        page.wait_for_selector("#dirpick[open]")
        assert page.inner_text("#dirpick-path") == str(tmp.resolve())
        page.click('#dirpick-list button[data-name="proj-a"]')
        page.wait_for_selector('#dirpick-list button[data-name="inner"]')
        assert page.inner_text("#dirpick-path") == str(sub.resolve())
        page.click("#dirpick-up")
        page.wait_for_selector('#dirpick-list button[data-name="proj-a"]')
        page.click('#dirpick-list button[data-name="proj-a"]')
        page.wait_for_selector('#dirpick-list button[data-name="inner"]')
        page.click("#dirpick-use")
        page.wait_for_selector("#dirpick", state="hidden")
        assert page.input_value("#cwd") == str(sub.resolve())


def test_elicitation_form_asks_and_shows_the_answer(server):
    # The agent's AskUserQuestion arrives as a form elicitation: single-select
    # questions are radios, multi-select are checkboxes, and every question
    # has its own free-text "Other" box.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.fill("#prompt-input", "do the ASKQUESTION thing")
        page.click("#send")
        page.wait_for_selector("#elicitation[open]")
        assert "Please answer" in page.inner_text("#elic-message")
        page.check('#elic-form input[type="radio"][value="Blue"]')
        page.check('#elic-form input[type="checkbox"][value="Ice"]')
        page.click("#elic-submit")
        page.wait_for_selector("#elicitation", state="hidden")
        page.wait_for_selector('[data-kind="elicitation_resolved"]')
        row = page.inner_text('[data-kind="elicitation_resolved"]')
        assert "Blue" in row and "Ice" in row
        # the row names the QUESTION, not the wire field key
        assert "Colour" in row and "Extras" in row
        assert "question_0" not in row


def test_elicitation_can_be_skipped(server):
    # Skipping declines: the agent is told the user answered nothing and the
    # turn continues — it must never look like the question was answered.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.fill("#prompt-input", "do the ASKQUESTION thing")
        page.click("#send")
        page.wait_for_selector("#elicitation[open]")
        page.click("#elic-skip")
        page.wait_for_selector("#elicitation", state="hidden")
        page.wait_for_selector('[data-kind="elicitation_resolved"]')
        assert "skipped" in page.inner_text('[data-kind="elicitation_resolved"]')


def test_elicitation_free_text_answer_wins_over_the_options(server):
    # The per-question "Other" box is how the user answers in their own
    # words; it must reach the agent as that question's answer.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.fill("#prompt-input", "do the ASKQUESTION thing")
        page.click("#send")
        page.wait_for_selector("#elicitation[open]")
        page.fill('#elic-form input[data-field="question_0_custom"]',
                  "Aubergine")
        page.click("#elic-submit")
        page.wait_for_selector('[data-kind="elicitation_resolved"]')
        row = page.inner_text('[data-kind="elicitation_resolved"]')
        assert "Aubergine" in row and "question_0_custom" not in row

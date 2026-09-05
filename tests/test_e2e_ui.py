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
    # an agent that can list its own sessions, for the resume list
    (profs / "sessions.toml").write_text(
        FIXTURE_PROFILE.format(python=sys.executable)
        .replace('id = "fake"', 'id = "sessions"')
        .replace("basic_turn.json", "commands_turn.json"), encoding="utf-8")
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


def open_launcher(page, url):
    """Go to the app and show the launcher. The server keeps sessions alive
    across page loads, so a fresh page may open straight into one; "+" is
    how a user asks for a new session."""
    page.goto(url)
    page.wait_for_selector("#tab-add")
    page.click("#tab-add")
    page.wait_for_selector("#launcher:not([hidden])")
    return page


def start_fake_session(pw, url, tmp):
    page = pw.chromium.launch().new_page()
    open_launcher(page, url)
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
        page.wait_for_selector('.pane:not([hidden]) [data-kind="turn_ended"]')
        convo = page.inner_text(".pane:not([hidden])")
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
        page.wait_for_selector('.pane:not([hidden]) [data-kind="turn_ended"]')


def test_launcher_shows_the_resolved_runtime(server):
    # The runtime line is the user-visible half of the 2026-09-01 fix: it
    # says which CLI the adapter will be pointed at (or nothing at all).
    url, tmp = server
    import shutil
    from tests.test_server import PY_NAME
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        open_launcher(page, url)
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
        open_launcher(page, url)
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
        open_launcher(page, url)
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
        page.wait_for_selector('.pane:not([hidden]) [data-kind="elicitation_resolved"]')
        row = page.inner_text('.pane:not([hidden]) [data-kind="elicitation_resolved"]')
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
        page.wait_for_selector('.pane:not([hidden]) [data-kind="elicitation_resolved"]')
        assert "skipped" in page.inner_text('.pane:not([hidden]) [data-kind="elicitation_resolved"]')


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
        page.wait_for_selector('.pane:not([hidden]) [data-kind="elicitation_resolved"]')
        row = page.inner_text('.pane:not([hidden]) [data-kind="elicitation_resolved"]')
        assert "Aubergine" in row and "question_0_custom" not in row


def lanes_turn(page):
    page.fill("#prompt-input", "show me the LANES")
    page.click("#send")
    page.wait_for_selector('.pane:not([hidden]) [data-kind="turn_ended"]')


def test_lane_toggles_remove_rows_from_the_conversation(server):
    # Off means GONE from the conversation, not dimmed: Fabio asked for the
    # rows to disappear entirely.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        lanes_turn(page)
        assert page.locator('.pane:not([hidden]) [data-lane="thinking"]').count() >= 1
        assert page.locator('.pane:not([hidden]) [data-lane="subagents"]').count() >= 1
        page.click('#lanes button[data-lane-toggle="thinking"]')
        assert page.locator('.pane:not([hidden]) [data-lane="thinking"]:visible').count() == 0
        assert "weighing" not in page.inner_text(".pane:not([hidden])")
        page.click('#lanes button[data-lane-toggle="tools"]')
        assert page.locator('.pane:not([hidden]) [data-lane="tools"]:visible').count() == 0
        page.click('#lanes button[data-lane-toggle="subagents"]')
        assert page.locator('.pane:not([hidden]) [data-lane="subagents"]:visible').count() == 0
        page.click('#lanes button[data-lane-toggle="events"]')
        assert page.locator('.pane:not([hidden]) [data-lane="events"]:visible').count() == 0
        # the agent's own answer is never hidden by a lane
        assert "the plain answer" in page.inner_text(".pane:not([hidden])")
        # and the choice survives a reload (the session comes back with it)
        page.reload()
        page.wait_for_selector("#workspace:not([hidden])")
        # events are switched off at this point, so wait for the agent's own
        # text rather than the turn separator
        page.wait_for_selector('.pane:not([hidden]) [data-role="agent"]')
        assert page.locator('.pane:not([hidden]) [data-lane="thinking"]:visible').count() == 0
        page.click('#lanes button[data-lane-toggle="thinking"]')
        assert page.locator('.pane:not([hidden]) [data-lane="thinking"]:visible').count() >= 1


def test_subagent_rows_are_their_own_lane(server):
    # A tool call stamped with parentToolUseId belongs to a subagent, and
    # hiding subagents must not take the main agent's tool rows with it.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        lanes_turn(page)
        page.click('#lanes button[data-lane-toggle="subagents"]')
        assert page.locator('.pane:not([hidden]) [data-lane="subagents"]:visible').count() == 0
        assert "Read config.toml" in page.inner_text(".pane:not([hidden])")


def test_jump_to_bottom_appears_when_scrolled_away_and_follows_again(server):
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page(viewport={"width": 900,
                                                       "height": 400})
        open_launcher(page, url)
        page.select_option("#profile", "fake")
        page.fill("#cwd", str(tmp))
        page.click("#start")
        page.wait_for_selector("#send:not([disabled])")
        for _ in range(4):
            lanes_turn(page)
        pane = page.locator("#conversation")
        assert page.locator("#jump-bottom:visible").count() == 0
        page.evaluate("document.querySelector('#conversation').scrollTop = 0")
        page.wait_for_selector("#jump-bottom:visible")
        # it floats ABOVE the composer, never on top of it
        btn = page.locator("#jump-bottom").bounding_box()
        composer = page.locator("#composer").bounding_box()
        assert btn["y"] + btn["height"] <= composer["y"] + 1, (btn, composer)
        before = pane.evaluate("el => el.scrollTop")
        lanes_turn(page)
        # scrolled away: the view must NOT yank the user back down
        assert pane.evaluate("el => el.scrollTop") == before
        page.click("#jump-bottom")
        page.wait_for_selector("#jump-bottom", state="hidden")
        assert pane.evaluate(
            "el => el.scrollHeight - el.scrollTop - el.clientHeight < 4")


def test_composer_does_not_eat_a_short_window(server):
    # 2026-09-04: at 420 px tall the composer took 36 % of the height and the
    # toolbar left a dead band across the middle.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page(viewport={"width": 1200,
                                                       "height": 420})
        open_launcher(page, url)
        page.select_option("#profile", "fake")
        page.fill("#cwd", str(tmp))
        page.click("#start")
        page.wait_for_selector("#send:not([disabled])")
        composer = page.locator("#composer").bounding_box()["height"]
        assert composer <= 420 * 0.25, f"composer takes {composer}px of 420"
        # the conversation gets what the composer gives up
        convo = page.locator("#conversation").bounding_box()["height"]
        assert convo >= 420 * 0.6, f"conversation only {convo}px of 420"


def test_a_reload_gets_the_running_sessions_back(server):
    # The sessions live in the server, but the View always started at the
    # launcher: after a browser reload a running session was unreachable
    # (found 2026-09-04 while testing the lane switches).
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.fill("#prompt-input", "say hello")
        page.click("#send")
        page.wait_for_selector('.pane:not([hidden]) [data-kind="turn_ended"]')
        page.reload()
        page.wait_for_selector("#workspace:not([hidden])")
        page.wait_for_selector('.pane:not([hidden]) [data-kind="turn_ended"]')
        assert "hello world" in page.inner_text(".pane:not([hidden])")
        assert page.locator("#tabs .tab").count() >= 1


def test_launcher_sends_the_thinking_choice_with_the_session(server):
    # Thinking is a session-CREATION option (it cannot be changed later over
    # ACP), so the launcher is where it is chosen.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        open_launcher(page, url)
        page.select_option("#profile", "fake")
        page.fill("#cwd", str(tmp))
        page.select_option("#thinking", "off")
        posted = {}
        page.route("**/api/sessions", lambda route: (
            posted.update(json.loads(route.request.post_data or "{}")),
            route.continue_()))
        page.click("#start")
        page.wait_for_selector("#send:not([disabled])")
        assert posted["client_options"]["thinking"] == {"type": "disabled"}


def test_archive_opens_a_side_panel_and_falls_back_to_markdown(server):
    # The e2e server has no claude-session-publisher configured. Refusing to
    # save anything was the wrong answer to a missing optional tool (Fabio,
    # 2026-09-04): warn, offer what CAN be written, and write it. The panel
    # is beside the conversation, never a banner on top of it, and it closes.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.fill("#prompt-input", "say hello")
        page.click("#send")
        page.wait_for_selector('.pane:not([hidden]) [data-kind="turn_ended"]')

        page.click("#archive")
        page.wait_for_selector("#archive-panel:not([hidden])")
        page.wait_for_selector("#archive-formats input")
        # only what this server can actually write
        assert page.locator("#archive-formats input").count() == 1
        assert page.get_attribute("#archive-formats input", "value") == \
            "markdown"
        assert "claude-session-publisher" in \
            page.inner_text("#archive-warning")

        dest = tmp / "saved here"
        page.fill("#archive-dest", str(dest))
        page.click("#archive-run")
        page.wait_for_function(
            "() => document.querySelector('#archive-note')"
            ".textContent.startsWith('saved')", timeout=20000)
        written = list(dest.glob("*.md"))
        assert written, f"nothing written to {dest}"
        text = written[0].read_text(encoding="utf-8")
        assert "### You" in text and "say hello" in text
        assert "built-in fallback" in text

        # what you did is also in the conversation, in the harness lane
        assert "archived to" in page.inner_text(".pane:not([hidden])")

        page.click("#archive-close")
        assert page.locator("#archive-panel:not([hidden])").count() == 0


def test_the_archive_panel_does_not_cover_the_conversation(server):
    # The old note sat above the conversation and had no way to go away.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        before = page.evaluate(
            "() => document.querySelector('#conversation').clientWidth")
        page.click("#archive")
        page.wait_for_selector("#archive-panel:not([hidden])")
        boxes = page.evaluate("""() => {
          const c = document.querySelector('#conversation').getBoundingClientRect();
          const p = document.querySelector('#archive-panel').getBoundingClientRect();
          return {overlap: !(p.left >= c.right - 1 || p.right <= c.left + 1),
                  narrower: c.width < %d};
        }""" % before)
        assert not boxes["overlap"], "the panel overlaps the conversation"
        assert boxes["narrower"], "the conversation did not make room"


def test_a_dropped_socket_reconnects_without_duplicating_the_conversation(server):
    # R1 + R2 (audit 2026-09-04): the session lives in the server, so a
    # dropped socket used to leave the tab dead until someone reloaded — and
    # a naive reattach would have replayed the whole conversation again.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.fill("#prompt-input", "say hello")
        page.click("#send")
        page.wait_for_selector('.pane:not([hidden]) [data-kind="turn_ended"]')
        rows = page.locator(".pane:not([hidden]) > div").count()
        seq_before = page.evaluate(
            "() => [...sessions.values()][0].lastSeq")
        assert seq_before > 0, "the View kept no resume cursor"

        # the socket dies the way a server restart or a sleeping laptop
        # kills it: no page reload, no user action
        page.evaluate("() => [...sessions.values()][0].ws.close()")
        page.wait_for_function(
            "() => [...sessions.values()][0].ws.readyState === WebSocket.OPEN",
            timeout=20000)
        assert page.locator(".pane:not([hidden]) > div").count() == rows, \
            "the reconnect replayed the conversation a second time"

        # and the tab still works
        page.wait_for_selector("#send:not([disabled])")
        page.fill("#prompt-input", "say hello")
        page.click("#send")
        page.wait_for_function(
            "n => document.querySelectorAll("
            "'.pane:not([hidden]) [data-kind=\"turn_ended\"]').length > n",
            arg=1, timeout=20000)


def test_account_usage_panel_shows_the_windows_the_agent_reported(server):
    # Account-wide limits (5 h, 7 d, overage/credits) belong at the top
    # right, not inside one session's context gauge.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.fill("#prompt-input", "report the LIMITS")
        page.click("#send")
        page.wait_for_selector("#account:not([hidden])")
        page.wait_for_selector('#account [data-window="seven_day_overage_included"]')
        text = page.inner_text("#account")
        # One chip per window in `unifiedWindows` — the real payload reports
        # several at once and carries NO top-level utilization, so reading
        # only the top level showed one window with no number (2026-09-04).
        assert "5h" in text and "42%" in text
        assert "7d" in text and "88%" in text
        assert "7d+EC" in text and "45%" in text
        assert page.locator("#account .window").count() == 3
        assert "—" not in text, f"a window reported no number: {text}"
        # the warning windows are marked, and credits state is legible
        assert page.locator('#account [data-status="allowed_warning"]').count() == 2
        # extra credits are one word and a colour; the state is in the
        # tooltip (Fabio, 2026-09-04)
        # extra credits are ACCOUNT-wide: one badge, not one per window
        assert page.locator("#account .ec").count() == 1
        assert page.get_attribute("#account .ec", "data-ok") == "1"
        assert "extra credits in use" in page.get_attribute(
            "#account .ec", "title")


def test_a_prompt_suggestion_is_offered_and_never_sent(server):
    # An adapter that forwards them puts the prediction on the `_meta` of an
    # otherwise empty chunk. It must reach the composer only if the reader
    # asks, and it must not become a message row.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.fill("#prompt-input", "SUGGEST something")
        page.click("#send")
        page.wait_for_selector("#suggestion:not([hidden])")
        assert "add a test for add()" in page.inner_text("#suggestion")
        # the empty carrier chunk is not a row in the conversation
        rows = page.inner_text(".pane:not([hidden])")
        assert rows.count("add a test for add()") == 0, \
            "the suggestion leaked into the conversation"
        # nothing was sent, and the composer is untouched until asked
        assert page.input_value("#prompt-input") == ""
        page.click("#suggestion .take")
        assert page.input_value("#prompt-input") == "add a test for add()"
        assert page.locator("#suggestion:not([hidden])").count() == 0
        assert page.locator('.pane:not([hidden]) [data-kind="turn_ended"]') \
            .count() == 1, "accepting a suggestion started a turn"


def test_a_suggestion_can_be_dismissed(server):
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.fill("#prompt-input", "SUGGEST something")
        page.click("#send")
        page.wait_for_selector("#suggestion:not([hidden])")
        page.click("#suggestion .drop")
        assert page.locator("#suggestion:not([hidden])").count() == 0
        assert page.input_value("#prompt-input") == ""


def test_the_control_panel_waits_instead_of_shuffling(server):
    # A session announces itself in pieces; rendering each as it lands made
    # the panel shuffle for a couple of seconds (Fabio, 2026-09-04).
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        # by the time the session is ready and has its options, the
        # placeholder is gone and the real controls are there
        page.wait_for_selector("#workspace:not([data-settling='1'])")
        assert page.locator("#toolbar .controls .settling").count() == 1
        assert not page.is_visible("#toolbar .controls .settling")
        assert page.is_visible("#lanes")


def test_resumable_sessions_are_dated_and_newest_first(server):
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        open_launcher(page, url)
        page.select_option("#profile", "sessions")
        page.fill("#cwd", str(tmp))
        page.click("#refresh-recent")
        page.wait_for_selector("#recent-list li button[data-resume]")
        rows = page.locator("#recent-list li").all_inner_texts()
        assert len(rows) == 3, rows
        # newest first, and the one the agent never dated goes last rather
        # than pretending to be new
        assert "Newest work" in rows[0], rows
        assert "Old work" in rows[1], rows
        assert "No date" in rows[2] and "no date reported" in rows[2], rows
        # a date a reader can use, with the id kept in the tooltip
        assert "2026" not in rows[0], f"raw timestamp shown: {rows[0]}"
        assert "new-1" in page.get_attribute("#recent-list li", "title")


def test_many_tabs_never_push_the_account_block_off_the_screen(server):
    # Enough tabs used to scroll the whole bar, chips and all, out of sight
    # (Fabio, 2026-09-04). The strip scrolls; the right-hand block does not.
    # Layout only: tab-shaped nodes, no sessions.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        open_launcher(page, url)
        page.evaluate("""() => {
          const strip = document.querySelector('#tabstrip');
          const add = document.querySelector('#tab-add');
          for (let i = 0; i < 20; i++) {
            const b = document.createElement('button');
            b.className = 'tab';
            const l = document.createElement('span');
            l.textContent = 'claude - some-long-project-name-' + i;
            const x = document.createElement('span');
            x.className = 'close'; x.textContent = 'x';
            b.append(l, x);
            strip.insertBefore(b, add);
          }
        }""")
        box = page.evaluate("""() => {
          const tr = document.querySelector('#topright').getBoundingClientRect();
          const strip = document.querySelector('#tabstrip');
          const tabs = [...strip.querySelectorAll('.tab:not(.add)')];
          return {onScreen: tr.right <= innerWidth + 1 && tr.left >= 0,
                  scrolls: strip.scrollWidth > strip.clientWidth,
                  widest: Math.max(...tabs.map(t =>
                            t.getBoundingClientRect().width)),
                  viewport: innerWidth};
        }""")
        assert box["onScreen"], "the account/help/settings block scrolled away"
        assert box["scrolls"], "the tab strip did not take the overflow"
        assert box["widest"] < box["viewport"] / 4, \
            f"tabs did not shrink: widest {box['widest']}px"


def test_a_window_label_is_derived_from_whatever_the_agent_reports(server):
    # The agent decides which windows exist — per-model meters come and go
    # with the account. This exercises the LABELLER, not a claim about which
    # windows the adapter sends: the fixture carries only real ones.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        labels = page.evaluate(
            "() => ['five_hour', 'seven_day', 'seven_day_fable',"
            " 'seven_day_opus', 'seven_day_overage_included',"
            " 'something_new'].map(windowLabel)")
        assert labels == ["5h", "7d", "7d Fable", "7d Opus", "7d+EC",
                          "something new"], labels


def test_escape_stops_the_agent(server):
    # Esc interrupts in the terminal; it interrupts here (Fabio, 2026-09-04).
    # End to end: the key in the browser, the cancel in the session record.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.fill("#prompt-input", "SLOW please")
        page.click("#send")
        page.wait_for_selector("#cancel:not([hidden])")
        page.keyboard.press("Escape")

        deadline = time.time() + 15
        cancelled = False
        while time.time() < deadline and not cancelled:
            for rec in (tmp / "rec").glob("*.jsonl"):
                for line in rec.read_text(encoding="utf-8").splitlines():
                    entry = json.loads(line)
                    if entry.get("action") == "cancel":
                        cancelled = True
            if not cancelled:
                time.sleep(0.3)
        assert cancelled, "Escape did not reach the agent as a cancel"


def test_escape_does_not_stop_the_agent_from_inside_a_dialog(server):
    # An approval dialog owns its own Escape and refuses to be dismissed
    # unanswered; Esc there must not be read as "stop".
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.fill("#prompt-input", "PERMISSION please")
        page.click("#send")
        page.wait_for_selector("#permission[open]")
        page.keyboard.press("Escape")
        assert page.locator("#permission[open]").count() == 1
        page.click('#perm-options button[data-kind="allow_once"]')


def test_typing_anywhere_lands_in_the_composer(server):
    # "all other keys should work like in the terminal": press one with the
    # focus on the page and it types into the prompt.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.click("#conversation")
        page.evaluate("() => document.activeElement.blur()")
        page.keyboard.type("hello")
        assert page.input_value("#prompt-input") == "hello"


def test_anomalies_open_a_drawer_and_are_not_erased_by_clicking(server):
    # 2026-09-04: clicking the chip zeroed the counter and threw away the
    # details, which is exactly what the losslessness contract forbids.
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.fill("#prompt-input", "trigger an ANOMALY")
        page.click("#send")
        page.wait_for_selector(".anomaly-chip:not([hidden])")
        page.click(".anomaly-chip")
        page.wait_for_selector("#anomaly-drawer:not([hidden])")
        assert "unknown-session" in page.inner_text("#anomaly-drawer")
        assert "(1)" in page.inner_text(".anomaly-chip")
        page.click(".anomaly-chip")                      # closes, keeps them
        assert page.locator("#anomaly-drawer:visible").count() == 0
        assert "(1)" in page.inner_text(".anomaly-chip")
        page.click(".anomaly-chip")
        page.click("#anomaly-clear")                     # deliberate dismissal
        assert page.locator(".anomaly-chip:visible").count() == 0


def test_help_dialog_explains_the_view(server):
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.click("#help-button")
        page.wait_for_selector("#help[open]")
        text = page.inner_text("#help").lower()
        assert "lanes" in text and "alt" in text
        page.click("#help-close")
        page.wait_for_selector("#help", state="hidden")


def test_theme_choice_applies_and_survives_a_reload(server):
    url, tmp = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        page = start_fake_session(pw, url, tmp)
        page.click("#config-button")
        page.wait_for_selector("#config[open]")
        page.select_option("#theme", "light")
        assert page.evaluate("document.documentElement.dataset.theme") == "light"
        light = page.evaluate(
            "getComputedStyle(document.body).backgroundColor")
        page.select_option("#theme", "dark")
        assert page.evaluate(
            "getComputedStyle(document.body).backgroundColor") != light
        page.select_option("#theme", "light")
        page.click("#config-close")
        page.reload()
        page.wait_for_selector("#tab-add")
        assert page.evaluate("document.documentElement.dataset.theme") == "light"

# SPDX-License-Identifier: Apache-2.0
"""The replay buffer: bounded, resumable, and honest about what it dropped.

Before the 2026-09-04 audit it kept every event of every session for the
life of the process and re-sent all of it on every attach — so a pinned
server grew without bound and a reconnecting View received a second copy of
the whole conversation.
"""
import json
from acp_cockpit.core.events import make_event
from acp_cockpit.server.ws import BufferedSink


class Collector:
    def __init__(self):
        self.messages = []

    def write_message(self, wire):
        self.messages.append(json.loads(wire))

    def kinds(self):
        return [m["kind"] for m in self.messages]

    def seqs(self):
        return [m["seq"] for m in self.messages]


def feed(sink, n, first=1):
    for seq in range(first, first + n):
        sink.emit(make_event("stderr", "s1", seq, {"line": f"line {seq}"}))


def test_attach_replays_everything_by_default():
    sink = BufferedSink("s1")
    feed(sink, 3)
    c = Collector()
    sink.attach(c)
    assert c.seqs() == [1, 2, 3]


def test_attach_after_a_cursor_replays_only_the_gap():
    # what a reconnecting View asks for: it already holds 1 and 2.
    sink = BufferedSink("s1")
    feed(sink, 4)
    c = Collector()
    sink.attach(c, after=2)
    assert c.seqs() == [3, 4], "a reconnect must not duplicate the history"


def test_a_cursor_at_the_head_replays_nothing():
    sink = BufferedSink("s1")
    feed(sink, 3)
    c = Collector()
    sink.attach(c, after=3)
    assert c.messages == []


def test_the_buffer_is_bounded():
    sink = BufferedSink("s1", cap=10)
    feed(sink, 50)
    c = Collector()
    sink.attach(c)
    # a fresh client asked for everything and cannot have it: the last ten,
    # preceded by the notice that says so
    assert c.kinds()[0] == "replay_truncated"
    assert c.seqs()[1:] == list(range(41, 51))
    assert len(c.messages) == 11


def test_dropping_events_is_announced_not_hidden():
    # Losslessness: the JSONL record still has them, and the client is told
    # exactly which range it will not receive here.
    sink = BufferedSink("s1", cap=10)
    feed(sink, 50)
    c = Collector()
    sink.attach(c, after=5)
    assert c.kinds()[0] == "replay_truncated"
    notice = c.messages[0]
    assert notice["data"] == {"from_seq": 6, "to_seq": 40}
    assert notice["session"] == "s1"
    # the cursor lands where the replay resumes
    assert notice["seq"] == 40
    assert c.seqs()[1:] == list(range(41, 51))


def test_no_notice_when_nothing_the_client_wanted_was_dropped():
    sink = BufferedSink("s1", cap=10)
    feed(sink, 50)
    c = Collector()
    sink.attach(c, after=45)
    assert "replay_truncated" not in c.kinds()
    assert c.seqs() == [46, 47, 48, 49, 50]


def test_live_events_reach_every_attached_handler():
    sink = BufferedSink("s1", cap=10)
    a, b = Collector(), Collector()
    sink.attach(a)
    sink.attach(b)
    feed(sink, 2)
    assert a.seqs() == [1, 2] and b.seqs() == [1, 2]

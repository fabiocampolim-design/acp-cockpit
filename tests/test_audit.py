# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""Every keystroke issued to a session is logged (the 'wrongly issued' guard)."""
import logging

from claudiu.sessions import _audit_stdin


def test_audit_logs_length_control_count_and_bounded_preview(caplog):
    with caplog.at_level(logging.INFO, logger="claudiu.audit"):
        _audit_stdin("s1", "3")                    # a permission-button digit
        _audit_stdin("s2", "hello\r")              # a composer line
        _audit_stdin("s3", "\x1b")                 # Esc / interrupt
        _audit_stdin("s4", "x" * 500)              # long -> preview is bounded
    msgs = [r.getMessage() for r in caplog.records]
    assert any("session=s1 len=1 ctrl=0" in m for m in msgs)
    assert any("session=s2 len=6 ctrl=1" in m and r"\r" in m for m in msgs)
    assert any("session=s3 len=1 ctrl=1" in m and r"\e" in m for m in msgs)
    long = next(m for m in msgs if "session=s4" in m)
    assert "len=500" in long and "…" in long and len(long) < 200

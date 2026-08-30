# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
import logging

import pytest

from claudiu import VERSION
from claudiu.cli import build_parser, setup_logging


def test_parser_flags_and_defaults():
    args = build_parser().parse_args([])
    assert args.config is None
    assert args.port is None
    assert args.log_dir is None
    assert args.no_browser is False
    assert args.verbose is False
    assert args.quiet is False


def test_version_flag_exits_and_prints(capsys):
    with pytest.raises(SystemExit) as e:
        build_parser().parse_args(["--version"])
    assert e.value.code == 0
    assert VERSION in capsys.readouterr().out


def test_setup_logging_creates_audit_file(tmp_path):
    log_file = setup_logging(tmp_path / "logs", verbose=False, quiet=True)
    logging.getLogger("claudiu.test").warning("probe")
    logging.shutdown()
    assert log_file.exists()
    assert "probe" in log_file.read_text(encoding="utf-8")

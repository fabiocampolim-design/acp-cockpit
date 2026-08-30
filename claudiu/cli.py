# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""Command line entry point: args, audit log, server startup."""
from __future__ import annotations

import argparse
import logging
import platform
import sys
import time
import webbrowser
from pathlib import Path

from claudiu import VERSION
from claudiu import config as config_mod
from claudiu.app import make_app
from claudiu.sessions import SessionManager

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claudiu",
        description="Tabbed browser interface for Claude Code sessions.")
    p.add_argument("--config", default=None,
                   help="path to config.json (default: ~/.claudiu/config.json,"
                        " or $CLAUDIU_CONFIG)")
    p.add_argument("--port", type=int, default=None,
                   help="override the config port (config default: 8642)")
    p.add_argument("--log-dir", default=None,
                   help="directory for audit logs (default: <config dir>/logs)")
    p.add_argument("--no-browser", action="store_true",
                   help="do not open the browser automatically")
    p.add_argument("--verbose", action="store_true",
                   help="debug output on the console")
    p.add_argument("--quiet", action="store_true",
                   help="warnings and errors only on the console")
    p.add_argument("--version", action="version",
                   version=f"claudiu {VERSION}")
    return p


def setup_logging(log_dir, verbose: bool, quiet: bool) -> Path:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / time.strftime("claudiu-%Y%m%d-%H%M%S.log")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING if quiet
                else logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    root.addHandler(fh)
    root.addHandler(ch)
    return log_file


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg_path = (Path(args.config) if args.config
                else config_mod.config_path())
    created = config_mod.ensure_config_file(cfg_path)
    try:
        cfg, warnings = config_mod.load_config(cfg_path)
    except config_mod.ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if args.port:
        cfg["port"] = args.port
    log_dir = Path(args.log_dir) if args.log_dir else cfg_path.parent / "logs"
    log_file = setup_logging(log_dir, args.verbose, args.quiet)
    import terminado
    import tornado
    import tornado.ioloop
    log.info("claudiu %s | python %s | tornado %s | terminado %s",
             VERSION, platform.python_version(),
             tornado.version, terminado.__version__)
    log.info("argv: %s | config: %s%s", sys.argv, cfg_path,
             " (created with defaults)" if created else "")
    for w in warnings:
        log.warning("config: %s", w)
    manager = SessionManager(cfg)
    app = make_app(cfg, manager, warnings)
    app.listen(cfg["port"], address="127.0.0.1")
    url = f"http://127.0.0.1:{cfg['port']}/"
    print(f"CLAUDIU {VERSION} running at {url}  (Ctrl+C stops; log: {log_file})")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        log.info("stopped by user")
        print("stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

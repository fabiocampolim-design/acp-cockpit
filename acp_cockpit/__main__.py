# SPDX-License-Identifier: Apache-2.0
"""CLI: python -m acp_cockpit [--port N] [--profiles DIR] [--records DIR]
                          [--records-keep-days N] [--token-file F]"""
import argparse
import atexit
import os
import signal
from pathlib import Path

import tornado.httpserver
import tornado.ioloop
import tornado.netutil

from .core.record import prune
from .server.app import make_app
from .server.auth import TokenAuth


def default_records() -> Path:
    """`~/.acp-cockpit/records`, unless a `~/.claudiu` from before the
    rename is still there and holds records — in which case keep using it.
    A project changing its name is no reason to strand somebody's
    transcripts, and silently starting an empty directory beside a full one
    is the worst of both."""
    new = Path.home() / ".acp-cockpit" / "records"
    old = Path.home() / ".claudiu" / "records"
    if not new.exists() and old.is_dir() and any(old.glob("*.jsonl")):
        return old
    return new


def main():
    ap = argparse.ArgumentParser(prog="acp-cockpit")
    ap.add_argument("--port", type=int, default=0,
                    help="port (default 0 = OS-assigned)")
    ap.add_argument("--profiles", default="agents")
    ap.add_argument("--records", default=str(default_records()))
    ap.add_argument("--records-keep-days", type=int, default=0,
                    help="delete records older than N days at startup "
                         "(default 0 = keep every record for ever)")
    ap.add_argument("--no-drift-online", action="store_true",
                    help="disable the online schema/adapter version check")
    ap.add_argument("--archiver", default=os.environ.get("ACP_COCKPIT_ARCHIVER"),
                    help="path to transcript_archiver.py (claude-session-"
                         "publisher); enables Archive in the toolbar")
    ap.add_argument("--ui-name-file", default=None,
                    help="TOML file holding ACP_COCKPIT_UINAME, the name "
                         "this client shows in its own interface (default: "
                         "uiname.toml beside the package, then "
                         "~/.acp-cockpit/uiname.toml; the environment "
                         "variable of the same name wins over both)")
    ap.add_argument("--token-file", default=None,
                    help="keep the auth token in this file across launches "
                         "(with --port, the printed URL stays valid)")
    args = ap.parse_args()

    records = Path(args.records)
    gone = prune(records, args.records_keep_days)
    if gone:
        print(f"records: removed {len(gone)} older than "
              f"{args.records_keep_days} days", flush=True)
    held = sorted(records.glob("*.jsonl")) if records.is_dir() else []
    if held:
        size = sum(p.stat().st_size for p in held)
        print(f"records: {len(held)} session(s), {size / 1e6:.1f} MB in "
              f"{records} (they hold the whole conversation; "
              f"--records-keep-days prunes them)", flush=True)

    auth = (TokenAuth.from_file(args.token_file) if args.token_file
            else TokenAuth())
    app = make_app(Path(args.profiles), records, auth,
                   drift_online=not args.no_drift_online,
                   archiver=args.archiver, ui_name_file=args.ui_name_file)
    sockets = tornado.netutil.bind_sockets(args.port, address="127.0.0.1")
    server = tornado.httpserver.HTTPServer(app)
    server.add_sockets(sockets)
    port = sockets[0].getsockname()[1]
    print(f"{app.settings['ui_name']} (acp-cockpit) listening: "
          f"http://127.0.0.1:{port}/?token={auth.token}", flush=True)

    loop = tornado.ioloop.IOLoop.current()

    def shutdown(*_):
        app.manager.close_all()
        loop.add_callback_from_signal(loop.stop)
    # Ctrl+C, a polite SIGTERM (POSIX) and an ordinary interpreter exit all
    # end the adapters; a hard kill on Windows is covered by the job object
    # each adapter runs in (server/procs.py). Ten orphaned adapter CLIs from
    # the week before were still resident on 2026-09-05.
    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM") and os.name != "nt":
        signal.signal(signal.SIGTERM, shutdown)
    atexit.register(app.manager.close_all)
    loop.start()


if __name__ == "__main__":
    main()

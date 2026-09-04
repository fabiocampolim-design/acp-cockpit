# SPDX-License-Identifier: Apache-2.0
"""CLI: python -m claudiu [--port N] [--profiles DIR] [--records DIR] [--token-file F]"""
import argparse
import os
import signal
from pathlib import Path

import tornado.httpserver
import tornado.ioloop
import tornado.netutil

from .server.app import make_app
from .server.auth import TokenAuth


def main():
    ap = argparse.ArgumentParser(prog="claudiu")
    ap.add_argument("--port", type=int, default=0,
                    help="port (default 0 = OS-assigned)")
    ap.add_argument("--profiles", default="agents")
    ap.add_argument("--records",
                    default=str(Path.home() / ".claudiu" / "records"))
    ap.add_argument("--no-drift-online", action="store_true",
                    help="disable the online schema/adapter version check")
    ap.add_argument("--archiver", default=os.environ.get("CLAUDIU_ARCHIVER"),
                    help="path to transcript_archiver.py (claude-session-"
                         "publisher); enables Archive in the toolbar")
    ap.add_argument("--token-file", default=None,
                    help="keep the auth token in this file across launches "
                         "(with --port, the printed URL stays valid)")
    args = ap.parse_args()

    auth = (TokenAuth.from_file(args.token_file) if args.token_file
            else TokenAuth())
    app = make_app(Path(args.profiles), Path(args.records), auth,
                   drift_online=not args.no_drift_online,
                   archiver=args.archiver)
    sockets = tornado.netutil.bind_sockets(args.port, address="127.0.0.1")
    server = tornado.httpserver.HTTPServer(app)
    server.add_sockets(sockets)
    port = sockets[0].getsockname()[1]
    print(f"ClaudIU listening: http://127.0.0.1:{port}/?token={auth.token}",
          flush=True)

    loop = tornado.ioloop.IOLoop.current()

    def shutdown(*_):
        app.manager.close_all()
        loop.add_callback_from_signal(loop.stop)
    signal.signal(signal.SIGINT, shutdown)
    loop.start()


if __name__ == "__main__":
    main()

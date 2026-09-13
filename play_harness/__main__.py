"""Start the local play server: python -m play_harness [--port 8790]."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

os.environ.setdefault("OMP_NUM_THREADS", "2")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m play_harness",
                                 description="Play BB2025 against a trained policy in the browser.")
    ap.add_argument("--host", default="127.0.0.1",
                    help="loopback address to bind (127.0.0.1, localhost or ::1)")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--checkpoint-dir", action="append", default=None,
                    help="directory scanned for .bin checkpoints with .lineage.json sidecars "
                         "(default .play-artifacts/checkpoints; repeatable)")
    ap.add_argument("--games-dir", default=None, help="where game records are written")
    ap.add_argument("--threads", type=int, default=2, help="torch CPU threads for inference")
    args = ap.parse_args(argv)

    from . import engine as E
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        ap.error("the play server binds loopback only")
    if E.library_is_stale():
        print("Building the engine shim...", flush=True)
        E.build_library()
    E.load_library()

    import torch
    torch.set_num_threads(max(1, min(4, args.threads)))

    from . import game as G
    from .server import PlayServer

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("websockets").setLevel(logging.WARNING)
    server = PlayServer(host=args.host, port=args.port, checkpoint_dirs=args.checkpoint_dir,
                        games_dir=args.games_dir or G.GAMES_DIR)

    async def run():
        await server.start()
        print(f"Blood Bowl play harness running at {server.url}", flush=True)
        print("Open that address in a browser. Press Ctrl+C to stop.", flush=True)
        try:
            await asyncio.Future()
        finally:
            await server.close()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Run the resettable admin benchmark server."""

from __future__ import annotations

import argparse
import os
import signal
import threading
from pathlib import Path

from apps.inventory_demo import InventoryDemoServer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=Path("fixtures/inventory/inventory_v1.json"))
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    faults = [item.strip() for item in os.getenv("TRACETOTEST_FAULTS", "").split(",") if item.strip()]
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    server = InventoryDemoServer(args.fixture, faults=faults, port=args.port).start()
    print(f"Trace2Test admin listening on {server.base_url}", flush=True)
    try:
        stopped.wait()
    finally:
        server.stop()


if __name__ == "__main__":
    main()

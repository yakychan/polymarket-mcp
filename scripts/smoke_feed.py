"""Public RTDS smoke check in a temporary DB. No .env or wallet access."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from polymarket_mcp.feed import ChainlinkFeed
from polymarket_mcp.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=15)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 60:
        parser.error("--seconds must be 1..60")
    with TemporaryDirectory(prefix="polymarket-feed-smoke-") as folder:
        store = Store(Path(folder) / "feed.sqlite", 1000)
        feed = ChainlinkFeed(store, ("btc",))
        feed.start()
        try:
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                with store.transaction(write=False) as db:
                    count = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
                if count:
                    break
                time.sleep(0.2)
        finally:
            feed.close()
        with store.transaction(write=False) as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM observations ORDER BY observed DESC LIMIT 2")]
        print(json.dumps({"received": bool(rows), "observations": rows,
                          "notice": "No replay: absence of observations is not a zero price."}, indent=2))
        if not rows:
            raise SystemExit(1)


if __name__ == "__main__":
    main()

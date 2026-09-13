"""Public RTDS Chainlink TWAP collector; stores observations, never invents history."""
import asyncio
import json
import threading
import time
from decimal import Decimal

from .config import decimal
from .monitor import ProcessLock

TOPICS = {"crypto_prices_twap_thirty": 30, "crypto_prices_twap_sixty": 60}


class ChainlinkFeed:
    def __init__(self, store, assets):
        self.store, self.assets = store, assets
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = ProcessLock(str(store.path.resolve()) + ".feed.lock")

    def ingest(self, message):
        window = TOPICS.get(message.get("topic"))
        payload = message.get("payload", {})
        if not window or not isinstance(payload, dict):
            return False
        symbol = payload.get("symbol")
        if symbol not in {a + "/usd" for a in self.assets}:
            return False
        if payload.get("window_s") != window or "full_accuracy_value" not in payload:
            return False
        raw = str(payload["full_accuracy_value"])
        if not raw.lstrip("-").isdigit():
            return False
        value = decimal(raw) / Decimal(10**18)
        observed = float(decimal(payload["timestamp"]) / 1000)
        received = time.time()
        if value <= 0 or observed <= 0 or observed > received + 60:
            return False
        with self.store.transaction() as db:
            db.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?)", (symbol, window, observed, received, str(value)))
        return True

    def start(self):
        self.thread = threading.Thread(target=lambda: asyncio.run(self.run()), name="chainlink-feed", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join()

    async def run(self):
        from websockets.asyncio.client import connect
        delay = 1
        try:
            while not self.stop_event.is_set():
                if not self.lock.file and not self.lock.acquire():
                    await asyncio.sleep(1)
                    continue
                try:
                    async with connect("wss://ws-live-data.polymarket.com", open_timeout=5,
                                       close_timeout=2, ping_interval=None, max_size=1_000_000) as socket:
                        await socket.send(json.dumps({"action": "subscribe", "subscriptions": [
                            {"topic": topic, "type": "update"} for topic in TOPICS]}))
                        last_ping = 0
                        last_message = time.monotonic()
                        while not self.stop_event.is_set():
                            if time.monotonic() - last_ping >= 5:
                                await socket.send("PING")
                                last_ping = time.monotonic()
                            try:
                                data = await asyncio.wait_for(socket.recv(), timeout=1)
                                last_message = time.monotonic()
                                if data in ("PONG", "PING", ""):
                                    continue
                                message = json.loads(data)
                                if isinstance(message, dict) and self.ingest(message):
                                    delay = 1
                            except asyncio.TimeoutError:
                                if time.monotonic() - last_message > 30:
                                    raise TimeoutError("RTDS heartbeat unavailable")
                except Exception:
                    # Bounded reconnect backoff, interruptible on shutdown.
                    for _ in range(delay * 5):
                        if self.stop_event.is_set():
                            break
                        await asyncio.sleep(0.2)
                    delay = min(30, delay * 2)
        finally:
            self.lock.release()

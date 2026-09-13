"""One OS-lock owner per database/mode, released automatically on process death."""
import json
import os
from pathlib import Path
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .stops import Stops


class ProcessLock:
    def __init__(self, path):
        self.path = Path(path)
        self.file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if self.path.stat().st_size == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.file = handle
        return True

    def release(self):
        if self.file is None:
            return
        if os.name == "nt":
            import msvcrt
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.file, fcntl.LOCK_UN)
        self.file.close()
        self.file = None


class Monitor:
    def __init__(self, engine):
        self.engine = engine
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = ProcessLock(str(engine.store.path.resolve()) + "." + engine.settings.mode + ".monitor.lock")

    def start(self):
        self.thread = threading.Thread(target=self.run, name="polymarket-monitor", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join()  # IO is bounded; keep ownership until work finishes.

    def _heartbeat(self, running, error=None):
        with self.engine.store.transaction() as db:
            self.engine.store.set_state(db, self.engine.settings.mode + "_monitor", json.dumps({
                "running": running, "heartbeat": time.time(), "pid": os.getpid(),
                "interval_seconds": self.engine.settings.monitor_interval, "last_error": error}))

    def run(self):
        from .feed import ChainlinkFeed
        feed = None
        maintenance = ThreadPoolExecutor(max_workers=1, thread_name_prefix="polymarket-sync")
        pending = None
        def sync():
            errors = []
            for task in (self.engine.sync_orders, self.engine.resolve_tracked):
                try:
                    result = task()
                    if isinstance(result, dict) and result.get("errors"):
                        errors.append("RECONCILIATION_PENDING")
                except Exception as exc:
                    errors.append(type(exc).__name__)
            return errors or None
        error = None
        try:
            while not self.stop_event.is_set():
                if self.lock.file is None:
                    if not self.lock.acquire():
                        self.stop_event.wait(self.engine.settings.monitor_interval)
                        continue
                    if self.engine.settings.feed_enabled:
                        feed = ChainlinkFeed(self.engine.store, self.engine.settings.assets)
                        feed.start()
                try:
                    if pending is None or pending.done():
                        if pending:
                            error = pending.result()
                        pending = maintenance.submit(sync)
                    self._heartbeat(True, error)
                    # Slow reconciliation must not prevent unrelated armed exits.
                    Stops(self.engine).tick()
                except Exception as exc:
                    error = type(exc).__name__  # no secrets from remote errors
                self._heartbeat(True, error)
                self.stop_event.wait(self.engine.settings.monitor_interval)
        finally:
            maintenance.shutdown(wait=True)
            if feed:
                feed.close()
            if self.lock.file:
                try:
                    self._heartbeat(False)
                finally:
                    self.lock.release()

from contextlib import contextmanager
import json
import sqlite3
import time


def dumps(value):
    return json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)


class Store:
    def __init__(self, path, initial_balance):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.transaction() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS quotes (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY, quote_id TEXT UNIQUE NOT NULL,
                    mode TEXT NOT NULL, created REAL NOT NULL, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS positions (
                    token TEXT PRIMARY KEY, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL,
                    mode TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS orders_mode_created ON orders(mode, created);
                CREATE INDEX IF NOT EXISTS events_mode_seq ON events(mode, seq);
                CREATE TABLE IF NOT EXISTS stops (
                    id TEXT PRIMARY KEY, mode TEXT NOT NULL, token TEXT NOT NULL,
                    status TEXT NOT NULL, body TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS active_stop_token ON stops(mode, token)
                    WHERE status IN ('armed','triggered','waiting');
                CREATE TABLE IF NOT EXISTS observations (
                    symbol TEXT NOT NULL, window INTEGER NOT NULL, observed REAL NOT NULL,
                    received REAL NOT NULL, value TEXT NOT NULL,
                    PRIMARY KEY(symbol, window, observed)
                );
                CREATE TABLE IF NOT EXISTS forecasts (
                    id TEXT PRIMARY KEY, mode TEXT NOT NULL, created REAL NOT NULL,
                    body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS resolutions (
                    condition_id TEXT PRIMARY KEY, winner TEXT NOT NULL, observed REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id TEXT PRIMARY KEY, mode TEXT NOT NULL, created REAL NOT NULL,
                    tool TEXT NOT NULL, duration_ms REAL NOT NULL, code TEXT NOT NULL,
                    detail TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS tool_calls_mode_time ON tool_calls(mode, created);
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY, mode TEXT NOT NULL, slug TEXT NOT NULL,
                    observed REAL NOT NULL, body TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS snapshots_slug_time ON snapshots(mode, slug, observed);
                PRAGMA user_version=2;
            """)
            db.execute("INSERT OR IGNORE INTO state VALUES ('paper_cash',?)", (str(initial_balance),))
            db.execute("INSERT OR IGNORE INTO state VALUES ('paper_initial',?)", (str(initial_balance),))

    @contextmanager
    def transaction(self, write=True):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def event(db, mode, kind, body):
        cursor = db.execute("INSERT INTO events(created,mode,kind,body) VALUES (?,?,?,?)",
                            (time.time(), mode, kind, dumps(body)))
        return cursor.lastrowid

    @staticmethod
    def orders(db, mode):
        return [json.loads(r[0]) for r in db.execute("SELECT body FROM orders WHERE mode=? ORDER BY created", (mode,))]

    @staticmethod
    def save_order(db, order):
        db.execute("INSERT INTO orders VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                   (order["id"], order["quote_id"], order["mode"], order["created"], dumps(order)))

    @staticmethod
    def state(db, key):
        row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def set_state(db, key, value):
        db.execute("INSERT INTO state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    @staticmethod
    def save_stop(db, stop):
        db.execute("INSERT INTO stops VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,body=excluded.body",
                   (stop["id"], stop["mode"], stop["token"], stop["status"], dumps(stop)))

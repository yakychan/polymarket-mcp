from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
import json
import time

import pytest

from polymarket_mcp.config import Settings, TradingError, decimal
from polymarket_mcp.engine import Engine
from polymarket_mcp.market import PublicAPI, normalize_market, simulate


class FakePublic:
    def __init__(self, settings):
        self.settings = settings
        self.closed = False
        self.winner = None
        self.blocked = False
        self.price = "0.50"
        self.bid = "0.40"
        self.depth = "1000"
        self.end = time.time() + 180

    def market(self, slug):
        return {"slug": slug, "asset": slug.split("-")[0], "condition_id": "condition", "tokens": {"up": "1", "down": "2"},
                "start": time.time() - 60, "end": self.end, "active": True,
                "closed": self.closed, "accepting_orders": True}

    def now(self):
        return time.time()

    current_time = now

    tradable = PublicAPI.tradable

    def book(self, market, outcome):
        return {"asks": [{"price": self.price, "size": self.depth}],
                "bids": [{"price": self.bid, "size": self.depth}],
                "min_order_size": "5", "tick_size": "0.01", "neg_risk": False}

    def fee(self, market):
        return {"rate": "0.07", "exponent": "1"}

    def resolution(self, condition):
        return self.winner

    def geoblock(self):
        return {"blocked": self.blocked}


class FakeBroker:
    wallet = "0x1111111111111111111111111111111111111111"

    def __init__(self):
        self.submits = 0
        self.fail = False
        self.confirm = False
        self.order_id = "0xorder"
        self.available = "1000"

    def balance(self, token=None):
        return {"balance": self.available}

    def prepare(self, quote):
        return object(), self.order_id

    def submit(self, signed):
        self.submits += 1
        if self.fail:
            raise TimeoutError("sensitive upstream message")
        return {"success": True, "orderID": self.order_id, "status": "matched"}

    def reconcile(self, order_id, condition):
        return {"id": order_id, "asset_id": "1", "side": "BUY", "status": "MATCHED", "size_matched": "10"}, [
            {"id": "fill1", "size": "10", "price": "0.50", "status": "CONFIRMED" if self.confirm else "MATCHED"}]


@pytest.fixture
def engine(tmp_path):
    settings = Settings(database=tmp_path / "test.sqlite3")
    return Engine(settings, FakePublic(settings))


def quote(engine, **changes):
    args = dict(slug="btc-updown-5m-1789254000", outcome="up", side="BUY", amount="5", limit_price="0.60")
    args.update(changes)
    return engine.quote(**args)["quote_id"]


def live_engine(engine):
    settings = replace(engine.settings, mode="live", private_key="test", api_key="test", api_secret="test", api_passphrase="test")
    broker = FakeBroker()
    return Engine(settings, FakePublic(settings), broker)


def test_paper_buy_sell_and_accounting(engine):
    order = engine.execute(quote(engine), "IA decide Up")
    assert decimal(order["execution"]["shares"]) == 10
    assert decimal(order["execution"]["fee_usd"]) == Decimal("0.175")
    assert decimal(engine.portfolio()["cash_usd"]) == Decimal("994.825")
    sell = engine.execute(quote(engine, side="SELL", amount="5", limit_price="0.40"), "Cierre parcial")
    assert decimal(sell["realized_pnl_usd"]) == Decimal("-0.67150")
    assert decimal(engine.portfolio()["positions"][0]["shares"]) == 5


def test_paper_never_constructs_live_broker(engine, monkeypatch):
    import polymarket_mcp.live
    def forbidden(*args, **kwargs):
        pytest.fail("Paper intentó construir el broker real")
    monkeypatch.setattr(polymarket_mcp.live, "LiveBroker", forbidden)
    restarted = Engine(engine.settings, engine.public)
    restarted.execute(quote(restarted), "Prueba virtual")
    assert restarted.broker is None


def test_idempotency_survives_restart_and_parallel_calls(engine):
    q = quote(engine)
    second = Engine(engine.settings, engine.public)
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda e: e.execute(q, "Una sola apuesta"), [engine, second]))
    assert receipts[0] == receipts[1]
    assert len(second.history()["orders"]) == 1
    assert decimal(second.portfolio()["cash_usd"]) == Decimal("994.825")


def test_paper_win_settles_once(engine):
    engine.public.end = time.time() + 16
    engine.execute(quote(engine), "Up")
    with engine.store.transaction() as db:
        row = db.execute("SELECT body FROM positions").fetchone()
        p = json.loads(row[0]); p["market"]["end"] = time.time() - 1
        db.execute("UPDATE positions SET body=?", (json.dumps(p),))
    assert engine.settle_paper()["settlements"] == []
    engine.public.winner = "1"
    assert len(engine.settle_paper()["settlements"]) == 1
    assert engine.settle_paper()["settlements"] == []
    assert decimal(engine.portfolio()["cash_usd"]) == Decimal("1004.825")
    assert decimal(engine.portfolio()["realized_pnl_usd"]) == Decimal("4.825")


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "bad", "0", "-1", "1.001"])
def test_invalid_amounts(engine, value):
    with pytest.raises(TradingError):
        quote(engine, amount=value)


def test_fok_and_limit_price_revalidate(engine):
    q = quote(engine)
    engine.public.price = "0.70"
    with pytest.raises(TradingError, match="Liquidez"):
        engine.execute(q, "El precio cambió")
    assert engine.history()["orders"] == []


def test_minimum_and_insufficient_liquidity(engine):
    with pytest.raises(TradingError, match="mínimo"):
        quote(engine, amount="1")
    engine.public.depth = "2"
    with pytest.raises(TradingError, match="Liquidez"):
        quote(engine)


def test_limits_pause_and_no_short(engine):
    with pytest.raises(TradingError, match="MAX_BET"):
        quote(engine, amount="10")
    q = quote(engine)
    engine.pause(True)
    with pytest.raises(TradingError, match="pausadas"):
        engine.execute(q, "pausa")
    engine.pause(False)
    with pytest.raises(TradingError, match="shares virtuales"):
        engine.execute(quote(engine, side="SELL", amount="5", limit_price="0.4"), "venta sin inventario")


def test_daily_limit_persists(engine):
    engine = Engine(replace(engine.settings, daily_spend=Decimal("6")), engine.public)
    engine.execute(quote(engine), "Primera")
    restarted = Engine(engine.settings, engine.public)
    with pytest.raises(TradingError, match="DAILY"):
        restarted.execute(quote(restarted), "Segunda")


def test_expiry_and_closed_market(engine):
    q = quote(engine)
    with engine.store.transaction() as db:
        row = json.loads(db.execute("SELECT body FROM quotes WHERE id=?", (q,)).fetchone()[0])
        row["expires"] = time.time() - 1
        db.execute("UPDATE quotes SET body=? WHERE id=?", (json.dumps(row), q))
    with pytest.raises(TradingError, match="venció"):
        engine.execute(q, "Expirada")
    engine.public.closed = True
    with pytest.raises(TradingError, match="no acepta"):
        quote(engine)


def test_modes_isolated_and_quotes_cannot_cross(engine):
    q = quote(engine)
    live = live_engine(engine)
    with pytest.raises(TradingError, match="otro modo"):
        live.execute(q, "No cruzar modos")
    assert live.history()["orders"] == []
    assert live.broker.submits == 0


def test_live_timeout_no_resubmit_and_buy_block(engine):
    live = live_engine(engine)
    live.broker.fail = True
    q = quote(live)
    r = live.execute(q, "IA decide")
    assert r["status"] == "unknown"
    assert "sensitive" not in json.dumps(r)
    assert live.execute(q, "reintento") == r
    assert live.broker.submits == 1
    with pytest.raises(TradingError, match="incierta"):
        live.execute(quote(live), "No duplicar exposición")
    assert decimal(engine.portfolio()["cash_usd"]) == 1000


def test_live_match_is_not_confirmation(engine):
    live = live_engine(engine)
    r = live.execute(quote(live), "IA decide")
    assert r["status"] == "submitted" and r["execution"] is None
    live.sync_orders()
    assert live.history()["orders"][0]["status"] == "submitted"
    live.broker.confirm = True
    live.sync_orders()
    confirmed = live.history()["orders"][0]
    assert confirmed["status"] == "confirmed"
    assert confirmed["execution"]["notional_usd"] == "5.00"
    assert confirmed["execution"]["fee_usd"] is None


def test_geoblock_and_insufficient_real_balance(engine):
    live = live_engine(engine)
    live.public.blocked = True
    with pytest.raises(TradingError, match="conexión"):
        live.execute(quote(live), "No habilitado")
    live.public.blocked = False
    live.broker.available = "1"
    with pytest.raises(TradingError, match="Saldo real"):
        live.execute(quote(live), "Sin saldo")
    assert live.broker.submits == 0


def test_events_cursor(engine):
    engine.execute(quote(engine), "Decisión registrada")
    first = engine.updates()
    assert len(first["events"]) == 1
    assert first["events"][0]["body"]["reason"] == "Decisión registrada"
    assert engine.updates(first["next_cursor"])["events"] == []


def test_env_priority_and_validation(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("OPERATION_MODE=paper\nWALLET_PRIVATE_KEY=do-not-print\n")
    monkeypatch.setenv("OPERATION_MODE", "live")
    s = Settings.load(path)
    assert s.mode == "paper" and "do-not-print" not in repr(s)
    path.write_text("OPERATION_MODE=papre\n")
    with pytest.raises(TradingError):
        Settings.load(path)


def test_exact_market_scope_and_outcome_mapping():
    raw = {"slug": "btc-updown-5m-1789254000", "endDate": "2026-09-12T23:05:00Z",
           "outcomes": '["Down", "Up"]', "clobTokenIds": '["2", "1"]', "conditionId": "condition"}
    assert normalize_market(raw, ("btc",))["tokens"] == {"down": "2", "up": "1"}
    raw["slug"] = "btc-updown-15m-1789254000"
    with pytest.raises(TradingError):
        normalize_market(raw, ("btc",))


def test_resolution_requires_official_winner(engine, monkeypatch):
    api = PublicAPI(engine.settings)
    monkeypatch.setattr(api, "get", lambda *a: {"condition_id": "condition", "closed": True,
                                               "tokens": [{"token_id": "1", "price": 1, "winner": False}]})
    assert api.resolution("condition") is None


def test_depth_weighted_price_and_fees():
    book = {"asks": [{"price": "0.40", "size": "5"}, {"price": "0.50", "size": "6"}], "min_order_size": "5"}
    fill = simulate(book, "BUY", Decimal(5), Decimal("0.5"), {"rate": "0.07", "exponent": "1"})
    assert decimal(fill["shares"]) == 11
    assert decimal(fill["fee_usd"]) == Decimal("0.189")


def test_exchange_clock_handles_local_drift_and_rejects_stale_books(engine, monkeypatch):
    api = PublicAPI(engine.settings)
    server_time = time.time() + 41
    book_time = server_time
    def get(base, path, params=None):
        if path == "/time":
            return server_time
        return {"asset_id": "1", "market": "condition", "timestamp": str(book_time * 1000),
                "asks": [{"price": "0.5", "size": "10"}], "bids": []}
    monkeypatch.setattr(api, "get", get)
    assert abs(api.now() - server_time) < 1
    assert api.book(engine.public.market("slug"), "up")["asset_id"] == "1"
    book_time -= 30
    with pytest.raises(TradingError, match="desactualizado"):
        api.book(engine.public.market("slug"), "up")


def test_cash_cannot_be_overspent_by_two_processes(engine):
    settings = replace(engine.settings, initial_balance=Decimal("6"))
    with engine.store.transaction() as db:
        engine.store.set_state(db, "paper_cash", "6")
    first, second = Engine(settings, engine.public), Engine(settings, engine.public)
    quotes = [(first, quote(first)), (second, quote(second))]
    def attempt(pair):
        try:
            return pair[0].execute(pair[1], "Prueba de concurrencia")["status"]
        except TradingError:
            return "blocked"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, quotes)) == ["blocked", "simulated"]
    assert decimal(first.portfolio()["cash_usd"]) == Decimal("0.825")


def test_losing_paper_position_does_not_credit_payout(engine):
    engine.execute(quote(engine), "Up")
    engine.public.winner = "2"
    result = engine.settle_paper()["settlements"][0]
    assert result["result"] == "lost"
    assert decimal(result["payout_usd"]) == 0
    assert decimal(engine.portfolio()["cash_usd"]) == Decimal("994.825")
    assert decimal(engine.portfolio()["realized_pnl_usd"]) == Decimal("-5.175")


def test_real_order_signing_without_network(tmp_path, monkeypatch):
    """Clave pública de fixture; no usa ni lee la wallet del usuario."""
    from polymarket_mcp.live import LiveBroker
    from py_clob_client_v2 import ClobClient
    from py_clob_client_v2.clob_types import CreateOrderOptions, MarketOrderArgs
    s = Settings(mode="live", database=tmp_path / "live.sqlite", private_key="0x" + "11" * 32,
                 api_key="test", api_secret="dGVzdA==", api_passphrase="test")
    broker = LiveBroker(s)
    monkeypatch.setattr(ClobClient, "create_market_order", lambda self, args, opts:
                        self.builder.build_market_order(args, CreateOrderOptions(tick_size="0.01", neg_risk=False), version=2))
    signed, hash_ = broker.prepare({"token": "1", "amount": "5", "side": "BUY", "limit_price": "0.5", "tick_size": "0.01", "neg_risk": False})
    assert hash_.startswith("0x") and len(hash_) == 66
    assert int(signed.makerAmount) == 5_000_000

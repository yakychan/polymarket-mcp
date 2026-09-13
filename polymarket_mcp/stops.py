"""Opt-in local stop-limit exits. Never a guaranteed stop or an exchange stop order."""
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import json
import time
import uuid

from .config import TradingError, decimal
from .risk import PENDING, remaining_lots

ACTIVE = {"armed", "triggered", "waiting"}


def make_stop(order, loss_percent=None, trigger_price=None, slippage="0.03"):
    if order["side"] != "BUY" or order["status"] in ("failed", "rejected", "cancelled"):
        raise TradingError("SL requiere una compra válida de este MCP.", "INVALID_STOP")
    if (loss_percent is None) == (trigger_price is None):
        raise TradingError("Elegir loss_percent o trigger_price, exactamente uno.", "INVALID_STOP")
    tolerance = decimal(slippage)
    if not 0 <= tolerance < 1:
        raise TradingError("slippage debe estar entre 0 y 1, sin incluir 1.", "INVALID_STOP")
    if loss_percent is not None and not 0 < decimal(loss_percent) < 100:
        raise TradingError("loss_percent debe estar entre 0 y 100, sin extremos.", "INVALID_STOP")
    if trigger_price is not None and not 0 < decimal(trigger_price) < 1:
        raise TradingError("trigger_price debe estar entre 0 y 1, sin extremos.", "INVALID_STOP")
    return {"id": str(uuid.uuid4()), "mode": order["mode"], "token": order["token"],
            "source_order_id": order["id"], "market": order["market"], "outcome": order["outcome"],
            "loss_percent": str(decimal(loss_percent)) if loss_percent is not None else None,
            "trigger_price": str(decimal(trigger_price)) if trigger_price is not None else None,
            "slippage": str(tolerance), "status": "armed", "created": time.time(),
            "quote_id": None, "triggered_at": None, "attempts": 0,
            "notice": "Stop-limit local optativo. Porcentaje sobre precio medio de entrada, sin comisiones. No garantiza salida ni pérdida máxima."}


def ensure_available(db, stop):
    if db.execute("SELECT 1 FROM stops WHERE mode=? AND token=? AND status IN ('armed','triggered','waiting')",
                  (stop["mode"], stop["token"])).fetchone():
        raise TradingError("Ya hay un SL activo para este token. Cancelarlo antes de reemplazarlo.", "STOP_EXISTS")


class Stops:
    def __init__(self, engine):
        self.engine = engine
        self.store = engine.store
        self.mode = engine.settings.mode

    def create(self, order_id, loss_percent=None, trigger_price=None, slippage="0.03"):
        with self.store.transaction() as db:
            row = db.execute("SELECT body FROM orders WHERE id=? AND mode=?", (order_id, self.mode)).fetchone()
            if not row:
                raise TradingError("Compra inexistente en el modo activo.", "ORDER_NOT_FOUND")
            stop = make_stop(json.loads(row[0]), loss_percent, trigger_price, slippage)
            ensure_available(db, stop)
            self.store.save_stop(db, stop)
            self.store.event(db, self.mode, "stop_created", stop)
        return stop

    def list(self, active_only=False, limit=100, offset=0):
        if not 1 <= limit <= 200 or offset < 0:
            raise TradingError("Paginación inválida.")
        sql = "SELECT body FROM stops WHERE mode=?"
        if active_only:
            sql += " AND status IN ('armed','triggered','waiting')"
        with self.store.transaction(write=False) as db:
            return {"stops": [json.loads(r[0]) for r in db.execute(sql + " ORDER BY rowid DESC LIMIT ? OFFSET ?", (self.mode, limit, offset))]}

    def cancel(self, stop_id):
        with self.store.transaction() as db:
            stop = self._read(db, stop_id)
            if stop["status"] in ACTIVE:
                stop.update(status="cancelled", updated=time.time())
                self.store.save_stop(db, stop)
                self.store.event(db, self.mode, "stop_cancelled", stop)
        return {"stop": stop, "notice": "Desactiva futuros envíos. No revierte una venta ya reservada/enviada; consultar historial."}

    def _read(self, db, stop_id):
        row = db.execute("SELECT body FROM stops WHERE id=? AND mode=?", (stop_id, self.mode)).fetchone()
        if not row:
            raise TradingError("SL inexistente.", "STOP_NOT_FOUND")
        return json.loads(row[0])

    def _change(self, stop_id, **changes):
        with self.store.transaction() as db:
            stop = self._read(db, stop_id)
            if stop["status"] not in ACTIVE:
                return stop
            if all(stop.get(k) == v for k, v in changes.items()):
                return stop
            stop.update(changes, updated=time.time())
            self.store.save_stop(db, stop)
            self.store.event(db, self.mode, "stop_update", stop)
            return stop

    def tick(self):
        # Only the OS-lock owner calls this method. The order reservation also
        # serializes against manual sales in every other MCP process.
        with self.store.transaction(write=False) as db:
            ids = [r[0] for r in db.execute("SELECT id FROM stops WHERE mode=? AND status IN ('armed','triggered','waiting')", (self.mode,))]
        for stop_id in ids:
            try:
                self._check(stop_id)
            except TradingError as exc:
                self._change(stop_id, last_error={"code": exc.code, "message": str(exc)})
            except Exception as exc:
                # Never store remote exception text or signatures.
                self._change(stop_id, last_error={"code": "MONITOR_ERROR", "type": type(exc).__name__})

    def _check(self, stop_id):
        with self.store.transaction(write=False) as db:
            stop = self._read(db, stop_id)
            if stop["status"] not in ACTIVE:
                return
            orders = self.store.orders(db, self.mode)
            source = next(o for o in orders if o["id"] == stop["source_order_id"])
            paused = self.store.state(db, self.mode + "_paused") == "1"
            resolved = stop["market"]["condition_id"] in self.engine._resolved(db)
        # A linked exit is always checked before expiry: do not abandon an
        # unknown POST simply because the market closed.
        exit_order = next((o for o in orders if o["quote_id"] == stop.get("quote_id")), None)
        if exit_order and exit_order["status"] in PENDING:
            self._change(stop_id, status="waiting", last_error={"code": "ORDER_PENDING"})
            return
        if source["status"] in PENDING:
            self._change(stop_id, last_error={"code": "ENTRY_PENDING"})
            return
        if not source.get("execution"):
            self._change(stop_id, status="cancelled", last_error={"code": "ENTRY_NOT_FILLED"})
            return
        remaining = remaining_lots(orders, stop["token"]).get(source["id"], Decimal(0))
        if "protected_shares" not in stop:
            stop = self._change(stop_id, protected_shares=str(remaining))
        already_sold = sum((decimal(o["execution"]["shares"]) for o in orders if o.get("stop_id") == stop_id and o.get("execution")), Decimal(0))
        quantity = min(remaining, max(Decimal(0), decimal(stop["protected_shares"]) - already_sold)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if quantity <= 0:
            self._change(stop_id, status="completed", last_error=None)
            return
        now = self.engine.public.current_time()
        if resolved or now >= stop["market"]["end"] - self.engine.settings.close_buffer:
            self._change(stop_id, status="expired", last_error={"code": "MARKET_CLOSED", "message": "Terminó la ventana operable; pueden quedar shares sin vender."})
            return
        if paused:
            self._change(stop_id, last_error={"code": "TRADING_PAUSED"})
            return
        # Never exit while any other sell of this token is unresolved.
        if any(o["side"] == "SELL" and o["token"] == stop["token"] and o["status"] in PENDING for o in orders):
            self._change(stop_id, last_error={"code": "ORDER_PENDING"})
            return
        book = self.engine.public.book(stop["market"], stop["outcome"])
        if quantity < decimal(book["min_order_size"]):
            self._change(stop_id, status="dust", last_error={"code": "BELOW_MINIMUM", "remaining_shares": str(quantity)})
            return
        trigger = decimal(stop["trigger_price"]) if stop["trigger_price"] else decimal(source["execution"]["average_price"]) * (1 - decimal(stop["loss_percent"]) / 100)
        tick = decimal(book["tick_size"])
        floor = max(tick, ((trigger - decimal(stop["slippage"])) / tick).quantize(Decimal(1), rounding=ROUND_UP) * tick)
        if not book["bids"]:
            raise TradingError("No hay ofertas de compra para vender.", "INSUFFICIENT_LIQUIDITY", True)
        best = decimal(book["bids"][0]["price"])
        if not stop["triggered_at"] and best > trigger:
            return
        if not stop["triggered_at"]:
            stop = self._change(stop_id, status="triggered", triggered_at=now,
                                effective_trigger=str(trigger), min_sell_price=str(floor), last_error=None)
        if stop["status"] not in ACTIVE:
            return
        # Persist quote link before calling execute, so a crash reuses the same
        # intent. Only expired, never-submitted quotes or terminal exits can reset.
        with self.store.transaction(write=False) as db:
            row = db.execute("SELECT body FROM quotes WHERE id=?", (stop.get("quote_id"),)).fetchone()
            quote = json.loads(row[0]) if row else None
        if exit_order or not quote or quote["expires"] <= now or decimal(quote["amount"]) != quantity:
            quote = self.engine.quote(stop["market"]["slug"], stop["outcome"], "SELL", str(quantity), str(floor))
            stop = self._change(stop_id, quote_id=quote["quote_id"], status="triggered", attempts=stop["attempts"] + 1, last_error=None)
        if stop["status"] not in ACTIVE:
            return
        receipt = self.engine.execute(quote["quote_id"], "Salida automática por SL solicitado por el usuario: " + stop_id, _stop_id=stop_id)
        self._change(stop_id, status="waiting" if receipt["status"] in PENDING else "triggered",
                     last_exit_order_id=receipt["id"], last_error=None)

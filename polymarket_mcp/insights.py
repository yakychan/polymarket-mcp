from collections import Counter
from decimal import Decimal
import json
import time
import uuid

from .config import TradingError, decimal
from .store import dumps


class Insights:
    def __init__(self, engine):
        self.engine = engine
        self.store = engine.store
        self.mode = engine.settings.mode

    def observations(self, asset, window=30, since=None, limit=500):
        if asset not in self.engine.settings.assets or window not in (30, 60) or not 1 <= limit <= 1000:
            raise TradingError("Activo, ventana (30/60) o límite (1..1000) inválido.")
        since = float(decimal(since)) if since is not None else time.time() - 3600
        with self.store.transaction(write=False) as db:
            rows = db.execute("SELECT * FROM observations WHERE symbol=? AND window=? AND observed>=? ORDER BY observed LIMIT ?",
                              (asset + "/usd", window, since, limit)).fetchall()
        return {"source": "Chainlink TWAP via Polymarket RTDS", "symbol": asset + "/usd", "window_seconds": window,
                "observations": [dict(r) for r in rows], "available": bool(rows),
                "notice": "Sólo datos recibidos y persistidos localmente. RTDS no ofrece replay; puede haber huecos."}

    def context(self, slug):
        market = self.engine.public.market(slug)
        now = self.engine.public.now()
        references = []
        with self.store.transaction(write=False) as db:
            for window in (30, 60):
                symbol = market["asset"] + "/usd"
                latest = db.execute("SELECT * FROM observations WHERE symbol=? AND window=? AND observed<=? ORDER BY observed DESC LIMIT 1",
                                    (symbol, window, now)).fetchone()
                opening = db.execute("SELECT * FROM observations WHERE symbol=? AND window=? AND observed<=? AND observed>=? ORDER BY observed DESC LIMIT 1",
                                     (symbol, window, market["start"], market["start"] - 5)).fetchone()
                age = now - latest["observed"] if latest else None
                fresh = age is not None and 0 <= age <= self.engine.settings.book_age
                change = str((decimal(latest["value"]) / decimal(opening["value"]) - 1) * 100) if fresh and opening else None
                references.append({"window_seconds": window, "latest": dict(latest) if latest else None,
                                   "age_seconds": age, "fresh": fresh, "opening_observation": dict(opening) if opening else None,
                                   "change_since_open_percent": change})
        return {"market": market, "as_of": now, "references": references,
                "notice": "Referencias TWAP 30/60s. Consultar las reglas para elegir la ventana aplicable; no constituyen ganador oficial ni precio de salida del token."}

    def forecast(self, slug, outcome, probability, reason):
        probability = decimal(probability)
        if outcome not in ("up", "down") or not 0 <= probability <= 1 or not 1 <= len(reason.strip()) <= 2000:
            raise TradingError("Pronóstico inválido: probabilidad 0..1 y motivo 1..2000 caracteres.")
        market = self.engine.public.market(slug)
        now = self.engine.public.now()
        if now >= market["end"] or market["closed"]:
            raise TradingError("No se puede registrar un pronóstico después del cierre.", "MARKET_CLOSED")
        result = {"id": str(uuid.uuid4()), "market": market, "outcome": outcome,
                  "probability": str(probability), "reason": reason, "created": now}
        with self.store.transaction() as db:
            db.execute("INSERT INTO forecasts VALUES (?,?,?,?)", (result["id"], self.mode, now, dumps(result)))
            self.store.event(db, self.mode, "forecast", result)
        return result

    def metrics(self):
        with self.store.transaction(write=False) as db:
            orders = self.store.orders(db, self.mode)
            predictions = [json.loads(r[0]) for r in db.execute("SELECT body FROM forecasts WHERE mode=?", (self.mode,))]
            winners = dict(db.execute("SELECT condition_id,winner FROM resolutions"))
            calls = [dict(r) for r in db.execute("SELECT tool, COUNT(*) calls, AVG(duration_ms) mean_ms, MAX(duration_ms) max_ms, SUM(code!='OK') failures FROM tool_calls WHERE mode=? GROUP BY tool", (self.mode,))]
            recent_errors = [dict(r) for r in db.execute("SELECT id,created,tool,code,detail FROM tool_calls WHERE mode=? AND code!='OK' ORDER BY created DESC LIMIT 20", (self.mode,))]
        scores, differences = [], []
        for forecast in predictions:
            winner = winners.get(forecast["market"]["condition_id"])
            if winner:
                target = int(forecast["market"]["tokens"][forecast["outcome"]] == winner)
                scores.append((decimal(forecast["probability"]) - target) ** 2)
        for order in orders:
            if order.get("execution") and order.get("quoted_estimate"):
                delta = decimal(order["execution"]["average_price"]) - decimal(order["quoted_estimate"]["average_price"])
                differences.append(delta if order["side"] == "BUY" else -delta)
        return {"orders_by_status": dict(Counter(o["status"] for o in orders)),
                "execution_samples": len(differences),
                "mean_adverse_price_change": str(sum(differences) / len(differences)) if differences else None,
                "forecast_samples": len(predictions), "resolved_forecasts": len(scores),
                "brier_score": str(sum(scores) / len(scores)) if scores else None,
                "tool_metrics": calls, "recent_errors": recent_errors,
                "notice": "Brier: menor es mejor. Cada pronóstico cuenta; muestras del mismo mercado no son independientes. Slippage medio no ponderado. Fees live desconocidas no se imputan como ganancia."}

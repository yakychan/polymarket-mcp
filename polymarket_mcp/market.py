from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
import json
import re
import time
import math

import httpx

from .config import TradingError, decimal

CLOB = "https://clob.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
SLUG = re.compile(r"^(btc|eth|sol|xrp)-updown-5m-(\d{10})$")
ZERO = Decimal(0)


def array(value):
    return json.loads(value) if isinstance(value, str) else value


def normalize_market(raw, assets):
    match = SLUG.fullmatch(raw.get("slug", ""))
    if not match or match[1] not in assets:
        raise TradingError("Sólo se admiten mercados Up/Down de 5 minutos de los activos configurados.")
    start = int(match[2])
    end = datetime.fromisoformat(raw["endDate"].replace("Z", "+00:00")).timestamp()
    if start % 300 or abs(end - start - 300) > 1:
        raise TradingError("El horario del mercado no corresponde a un intervalo de 5 minutos.")
    outcomes, tokens = array(raw["outcomes"]), array(raw["clobTokenIds"])
    if len(outcomes) != 2 or len(tokens) != 2 or {x.lower() for x in outcomes} != {"up", "down"}:
        raise TradingError("El mercado no contiene exactamente los resultados Up y Down.")
    return {
        "slug": raw["slug"], "asset": match[1], "question": raw.get("question"),
        "condition_id": raw["conditionId"], "start": start, "end": end,
        "start_utc": datetime.fromtimestamp(start, timezone.utc).isoformat(), "end_utc": raw["endDate"],
        "tokens": {outcome.lower(): str(token) for outcome, token in zip(outcomes, tokens)},
        "active": raw.get("active") is True and raw.get("archived") is not True,
        "closed": raw.get("closed") is True,
        "accepting_orders": raw.get("acceptingOrders") is True and raw.get("enableOrderBook") is True,
        "rules": raw.get("description", ""), "resolution_source": raw.get("resolutionSource"),
        "url": "https://polymarket.com/event/" + raw["slug"],
    }


class PublicAPI:
    def __init__(self, settings):
        self.settings = settings
        self.http = httpx.Client(timeout=12, headers={"User-Agent": "polymarket-five-minute-mcp/0.1"})
        self._clock_sample = None

    def get(self, base, path, params=None):
        try:
            r = self.http.get(base + path, params=params)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as exc:
            raise TradingError(f"API pública respondió HTTP {exc.response.status_code}.", "PUBLIC_API_ERROR", exc.response.status_code in (429, 500, 502, 503, 504)) from None
        except (httpx.HTTPError, ValueError):
            raise TradingError("No se pudo obtener una respuesta válida de la API pública.", "PUBLIC_API_ERROR", True) from None

    def now(self):
        before = time.monotonic()
        server = float(decimal(self.get(CLOB, "/time")))
        if not math.isfinite(server) or server <= 0:
            raise TradingError("Reloj del exchange inválido.", "INVALID_CLOCK")
        after = time.monotonic()
        if after - before > 4:
            raise TradingError("Demasiada latencia para sincronizar el reloj del exchange; volver a consultar.")
        self._clock_sample = (server + (after - before) / 2, after)
        return self._clock_sample[0]

    def current_time(self):
        sample = self._clock_sample
        if sample is None or time.monotonic() - sample[1] > 30:
            return self.now()
        return sample[0] + time.monotonic() - sample[1]

    def market(self, slug):
        if not SLUG.fullmatch(slug):
            raise TradingError("Slug inválido: se requiere activo-updown-5m-timestamp.")
        rows = self.get(GAMMA, "/markets", {"slug": slug})
        raw = next((r for r in rows if r.get("slug") == slug), None)
        if raw is None:
            raise TradingError("No existe ese mercado de 5 minutos.")
        return normalize_market(raw, self.settings.assets)

    def discover(self, asset=None, windows=3):
        if asset and asset not in self.settings.assets:
            raise TradingError("Activo no habilitado.")
        if not 1 <= windows <= 6:
            raise TradingError("windows debe estar entre 1 y 6.")
        now = self.now()
        base = int(now) // 300 * 300
        slugs = [f"{a}-updown-5m-{base + i * 300}" for a in ([asset] if asset else self.settings.assets) for i in range(windows)]
        def fetch(slug):
            try:
                return self.market(slug), None
            except TradingError as exc:
                return None, {"slug": slug, "error": str(exc)}
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(fetch, slugs))
        return {"as_of": now, "markets": [m for m, _ in results if m and m["active"] and not m["closed"]],
                "unavailable": [e for _, e in results if e]}

    def tradable(self, market, now):
        if not market["active"] or market["closed"] or not market["accepting_orders"]:
            raise TradingError("El mercado no acepta operaciones.")
        if now < market["start"] or now >= market["end"] - self.settings.close_buffer:
            raise TradingError("El intervalo todavía no empezó o está demasiado cerca del cierre.")

    def book(self, market, outcome):
        if outcome not in market["tokens"]:
            raise TradingError("outcome debe ser up o down.")
        token = market["tokens"][outcome]
        book = self.get(CLOB, "/book", {"token_id": token})
        if book.get("asset_id") != token or book.get("market") != market["condition_id"]:
            raise TradingError("El libro recibido pertenece a otro mercado/token.")
        age = self.current_time() - float(decimal(book["timestamp"])) / 1000
        if age < -5 or age > self.settings.book_age:
            raise TradingError("El libro de órdenes está desactualizado; volver a consultar.", "STALE_BOOK", True)
        book["bids"] = sorted(book["bids"], key=lambda x: decimal(x["price"]), reverse=True)
        book["asks"] = sorted(book["asks"], key=lambda x: decimal(x["price"]))
        return book

    def fee(self, market):
        info = self.get(CLOB, "/clob-markets/" + market["condition_id"])
        if info.get("c") != market["condition_id"] or "fd" not in info:
            raise TradingError("No se pudieron verificar las comisiones actuales.")
        fd = info["fd"]
        rate, exponent = decimal(fd["r"]), decimal(fd["e"])
        if not 0 <= rate <= 1 or not 1 <= exponent <= 10:
            if rate != 0:
                raise TradingError("Esquema de comisiones no soportado; no se operó.")
        return {"rate": str(rate), "exponent": str(exponent)}

    def resolution(self, condition_id):
        raw = self.get(CLOB, "/markets/" + condition_id)
        winners = [str(t["token_id"]) for t in raw.get("tokens", []) if t.get("winner") is True]
        # Una cotización cercana a 1 NO es evidencia de resolución.
        if raw.get("condition_id") == condition_id and raw.get("closed") is True and len(winners) == 1:
            return winners[0]
        return None

    def geoblock(self):
        data = self.get("https://polymarket.com", "/api/geoblock")
        return {k: data.get(k) for k in ("blocked", "country", "region")}


def simulate(book, side, amount, limit, fee):
    """FOK sobre profundidad disponible; BUY en dólares nominales, SELL en shares."""
    remaining, gross, shares, fees = amount, ZERO, ZERO, ZERO
    fills = []
    for level in book["asks" if side == "BUY" else "bids"]:
        price, available = decimal(level["price"]), decimal(level["size"])
        if not 0 < price < 1 or available < 0:
            raise TradingError("Libro de órdenes inválido.")
        if (side == "BUY" and price > limit) or (side == "SELL" and price < limit):
            continue
        size = min(available, remaining / price if side == "BUY" else remaining).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
        if size <= 0:
            continue
        cost = size * price
        charge = size * decimal(fee["rate"]) * (price * (1 - price)) ** decimal(fee["exponent"])
        gross += cost
        shares += size
        fees += charge
        remaining -= cost if side == "BUY" else size
        fills.append({"price": str(price), "shares": str(size), "notional_usd": str(cost.quantize(Decimal("0.000001")))})
        if remaining <= Decimal("0.000001"):
            break
    if remaining > Decimal("0.000001") or shares == 0:
        raise TradingError("Liquidez insuficiente dentro del precio límite: FOK no ejecutable.", "INSUFFICIENT_LIQUIDITY", True)
    if shares < decimal(book["min_order_size"]):
        raise TradingError("La cantidad de shares no alcanza el mínimo del mercado.")
    fees = fees.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
    gross = gross.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return {"shares": str(shares), "notional_usd": str(gross), "fee_usd": str(fees),
            "total_usd": str(gross + fees if side == "BUY" else gross - fees),
            "average_price": str((gross / shares).quantize(Decimal("0.000001"))), "fills": fills}

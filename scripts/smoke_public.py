r"""Prueba opt-in con APIs públicas y una operación VIRTUAL en una base temporal.

No lee .env, no construye broker live y no deja operaciones en la cuenta paper del usuario.
Ejecutar: .venv\Scripts\python.exe scripts/smoke_public.py
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from polymarket_mcp.config import Settings
from polymarket_mcp.engine import Engine


def main():
    with TemporaryDirectory(prefix="polymarket-paper-smoke-") as folder:
        engine = Engine(Settings(database=Path(folder) / "smoke.sqlite"))
        discovery = engine.public.discover("btc", 1)
        if not discovery["markets"]:
            raise RuntimeError("No se encontró un mercado activo")
        market = discovery["markets"][0]
        snapshot = engine.snapshot(market["slug"])
        # Elección arbitraria para probar el motor; no es una estrategia.
        candidates = [o for o, book in snapshot["books"].items() if book["asks"]]
        outcome = min(candidates, key=lambda o: float(snapshot["books"][o]["asks"][0]["price"]))
        tick = snapshot["books"][outcome]["tick_size"]
        from decimal import Decimal
        limit = str(1 - Decimal(tick))
        q = engine.quote(market["slug"], outcome, "BUY", "5", limit)
        receipt = engine.execute(q["quote_id"], "Prueba técnica paper aislada; selección arbitraria, sin señal de inversión")
        assert receipt["status"] == "simulated" and engine.broker is None
        assert engine.execute(q["quote_id"], "Reintento idéntico")["id"] == receipt["id"]
        print(json.dumps({"mode": "paper", "temporary_database": True, "slug": market["slug"],
                          "execution": receipt["execution"], "cash_after": receipt["paper_cash_after_usd"],
                          "tools": "Datos reales, dinero virtual; sin usar credenciales."}, indent=2))


if __name__ == "__main__":
    main()

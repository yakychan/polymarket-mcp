"""Conservative exposure for activity recorded by this MCP (not the entire wallet)."""
from decimal import Decimal

from .config import decimal

TERMINAL = {"simulated", "confirmed", "partially_confirmed", "failed", "rejected", "cancelled"}
PENDING = {"submitting", "submitted", "unknown"}


def inventory(orders, resolved=()):
    positions = {}
    for order in sorted(orders, key=lambda o: (o["created"], o["id"])):
        token = order["token"]
        pos = positions.setdefault(token, {"token": token, "market": order["market"],
                                          "shares": Decimal(0), "cost": Decimal(0)})
        execution = order.get("execution")
        if not execution:
            continue
        shares = decimal(execution["shares"])
        if order["side"] == "BUY":
            pos["shares"] += shares
            pos["cost"] += decimal(execution["notional_usd"]) + decimal(execution.get("fee_usd") or "0")
        elif pos["shares"] > 0:
            sold = min(shares, pos["shares"])
            pos["cost"] *= (pos["shares"] - sold) / pos["shares"]
            pos["shares"] -= sold
    return {t: p for t, p in positions.items()
            if p["shares"] > 0 and p["market"]["condition_id"] not in resolved}


def exposure(orders, resolved=()):
    positions = inventory(orders, resolved)
    markets, assets, tokens = {}, {}, set(positions)
    for pos in positions.values():
        market = pos["market"]
        slug = market["slug"]
        asset = market.get("asset", slug.split("-")[0])
        markets[slug] = markets.get(slug, Decimal(0)) + pos["cost"]
        assets[asset] = assets.get(asset, Decimal(0)) + pos["cost"]
    for order in orders:
        if order["side"] != "BUY" or order["status"] not in PENDING:
            continue
        # Reserve the full debit until all fills have reached finality, even if
        # a subset of confirmed fills is already reflected above.
        slug = order["market"]["slug"]
        asset = order["market"].get("asset", slug.split("-")[0])
        reserve = decimal(order["max_debit_usd"])
        markets[slug] = markets.get(slug, Decimal(0)) + reserve
        assets[asset] = assets.get(asset, Decimal(0)) + reserve
        tokens.add(order["token"])
    return markets, assets, tokens


def remaining_lots(orders, token):
    """FIFO attribution: a stop never adopts a later buy after its lot was sold."""
    lots = {}
    for order in sorted(orders, key=lambda o: (o["created"], o["id"])):
        execution = order.get("execution")
        if order["token"] != token or not execution:
            continue
        shares = decimal(execution["shares"])
        if order["side"] == "BUY":
            lots[order["id"]] = shares
        else:
            for key in lots:
                sold = min(shares, lots[key])
                lots[key] -= sold
                shares -= sold
                if shares <= 0:
                    break
    return lots

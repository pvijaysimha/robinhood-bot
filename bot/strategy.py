"""Trend-following targets: hold an equal slice of each ETF while it trades
above its N-day simple moving average, hold none of it while below."""


def sma(closes, days):
    if len(closes) < days:
        return None
    window = closes[-days:]
    return sum(window) / days


def signal(closes, days):
    """'in', 'out', or None when there is not enough history to decide."""
    avg = sma(closes, days)
    if avg is None:
        return None
    return "in" if closes[-1] > avg else "out"


def targets(config, total_value, closes_by_symbol):
    """Dollar target per symbol. Sizes off the smaller of budget and account
    value, so deposits above the budget are never put to work."""
    symbols = config["symbols"]
    if not symbols:
        return {}, 0.0
    investable = min(config["budget_usd"], total_value) * (1 - config["cash_reserve_pct"])
    slot = investable / len(symbols)
    out = {}
    for sym in symbols:
        sig = signal(closes_by_symbol.get(sym, []), config["sma_days"])
        out[sym] = {"signal": sig, "target_usd": None if sig is None else (slot if sig == "in" else 0.0)}
    return out, slot


def propose_orders(config, account, closes_by_symbol, exits=()):
    """Turn targets into limit orders. Symbols with no signal are left alone.
    Symbols in exits (rotated out of the universe) are sold in full."""
    tgts, slot = targets(config, account["total_value"], closes_by_symbol)
    held = {p["symbol"]: p for p in account["positions"]}
    buf = config["limit_buffer_pct"]
    orders = []
    for sym in exits:
        pos = held.get(sym)
        if pos and pos["quantity"] > 0:
            limit = round(account["quotes"][sym]["bid"] * (1 - buf), 2)
            orders.append({"symbol": sym, "side": "sell", "type": "limit",
                           "quantity": pos["quantity"], "limit_price": limit,
                           "reason": "rotated out of universe: exit"})
    for sym, t in tgts.items():
        if t["target_usd"] is None:
            continue
        pos = held.get(sym, {"quantity": 0.0, "market_value": 0.0})
        quote = account["quotes"][sym]
        diff = t["target_usd"] - pos["market_value"]

        if t["target_usd"] == 0 and pos["quantity"] > 0:
            limit = round(quote["bid"] * (1 - buf), 2)
            orders.append({"symbol": sym, "side": "sell", "type": "limit",
                           "quantity": pos["quantity"], "limit_price": limit,
                           "reason": "below SMA: exit"})
            continue

        if abs(diff) < max(config["min_order_usd"], config["rebalance_band_pct"] * slot):
            continue
        if diff > 0:
            notional = min(diff, config["max_order_usd"])
            limit = round(quote["ask"] * (1 + buf), 2)
            orders.append({"symbol": sym, "side": "buy", "type": "limit",
                           "quantity": round(notional / limit, 6), "limit_price": limit,
                           "reason": "above SMA: build to target"})
        else:
            limit = round(quote["bid"] * (1 - buf), 2)
            qty = min(pos["quantity"], round(-diff / limit, 6))
            orders.append({"symbol": sym, "side": "sell", "type": "limit",
                           "quantity": qty, "limit_price": limit,
                           "reason": "over target: trim"})
    return orders, tgts

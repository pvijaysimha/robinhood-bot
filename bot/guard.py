"""Hard risk limits. Every proposed order passes through check_orders();
anything it rejects must not be placed. Orders are checked in sequence so
each approval counts against the limits for the ones after it."""

PRICE_TOLERANCE = 0.01  # cents of slack for rounding
MAX_SPREAD_PCT = 0.005  # a wider quote (often after hours) is not a fair price


def check_orders(config, account, orders, orders_placed_today, exits=(), buys_blocked=None):
    """exits: rotated-out symbols that may be sold but not bought.
    buys_blocked: None, or the reason every buy is rejected."""
    symbols = set(config["symbols"])
    sellable = symbols | set(exits)
    held = {p["symbol"]: p for p in account["positions"]}
    open_syms = {o["symbol"] for o in account.get("open_orders", [])}
    buf = config["limit_buffer_pct"]

    invested = sum(p["market_value"] for p in account["positions"])
    cash = account["cash"]
    halt_floor = config["budget_usd"] * (1 - config["max_drawdown_pct"])
    buys_halted = account["total_value"] < halt_floor
    placed = orders_placed_today

    results = []
    for o in orders:
        reasons = []
        sym = o.get("symbol")
        quote = account["quotes"].get(sym)
        qty = o.get("quantity") or 0
        limit = o.get("limit_price")

        if sym not in (sellable if o.get("side") == "sell" else symbols):
            reasons.append(f"{sym} is not in the allowed symbols")
        if o.get("type") != "limit" or not limit or limit <= 0:
            reasons.append("only limit orders with a positive limit price are allowed")
        if qty <= 0:
            reasons.append("quantity must be positive")
        if sym in open_syms:
            reasons.append(f"{sym} already has an open order")
        if placed >= config["max_orders_per_day"]:
            reasons.append(f"daily order limit reached ({config['max_orders_per_day']})")
        if quote is None:
            reasons.append(f"no quote for {sym}")
        else:
            mid = (quote["bid"] + quote["ask"]) / 2
            if mid <= 0 or (quote["ask"] - quote["bid"]) / mid > MAX_SPREAD_PCT:
                reasons.append(f"spread ${quote['bid']}-${quote['ask']} is wider than "
                               f"{MAX_SPREAD_PCT:.1%}: wait for regular hours")

        notional = qty * (limit or 0)
        if not reasons:
            if o["side"] == "buy":
                if buys_blocked:
                    reasons.append(f"buys blocked: {buys_blocked}")
                if buys_halted:
                    reasons.append(f"buys halted: account value ${account['total_value']:.2f} "
                                   f"is below the drawdown floor ${halt_floor:.2f}")
                if limit > quote["ask"] * (1 + buf) + PRICE_TOLERANCE:
                    reasons.append(f"limit ${limit} is too far above the ask ${quote['ask']}")
                if notional > config["max_order_usd"] + PRICE_TOLERANCE:
                    reasons.append(f"order ${notional:.2f} exceeds max_order_usd ${config['max_order_usd']}")
                if invested + notional > config["budget_usd"] + PRICE_TOLERANCE:
                    reasons.append(f"would put ${invested + notional:.2f} to work, over budget_usd "
                                   f"${config['budget_usd']}")
                if notional > cash + PRICE_TOLERANCE:
                    reasons.append(f"order ${notional:.2f} exceeds cash ${cash:.2f}")
            elif o["side"] == "sell":
                have = held.get(sym, {}).get("quantity", 0)
                if qty > have + 1e-9:
                    reasons.append(f"sell quantity {qty} exceeds held {have}")
                if limit < quote["bid"] * (1 - buf) - PRICE_TOLERANCE:
                    reasons.append(f"limit ${limit} is too far below the bid ${quote['bid']}")
            else:
                reasons.append(f"unknown side {o.get('side')!r}")

        approved = not reasons
        if approved:
            placed += 1
            if o["side"] == "buy":
                invested += notional
                cash -= notional
            else:
                invested -= qty * held[sym]["market_value"] / held[sym]["quantity"]
            open_syms.add(sym)
        results.append({**o, "notional_usd": round(notional, 2), "approved": approved,
                        "reasons": reasons})
    return results

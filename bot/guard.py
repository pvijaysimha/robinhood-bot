"""Hard risk limits. Every proposed order passes through check_orders();
anything it rejects must not be placed. Orders are checked in sequence so
each approval counts against the limits for the ones after it.

Robinhood takes fractional shares only on market orders. With config
"allow_fractional_market", a fractional order may be a market order (a
buy by dollar_amount, a sell by quantity), but only on weekdays between
MARKET_OPEN and MARKET_CLOSE Eastern, so it is never queued for the open,
and only while the spread check passes. Whole-share orders stay limit."""
import datetime
from zoneinfo import ZoneInfo

PRICE_TOLERANCE = 0.01  # cents of slack for rounding
MAX_SPREAD_PCT = 0.005  # a wider quote (often after hours) is not a fair price
EASTERN = ZoneInfo("America/New_York")
MARKET_OPEN = datetime.time(10, 0)    # skip the opening half hour's wide spreads
MARKET_CLOSE = datetime.time(15, 30)  # and the closing rush


def market_window_open(now):
    now = now.astimezone(EASTERN)
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def whole(qty):
    return abs(qty - round(qty)) < 1e-9


def check_orders(config, account, orders, orders_placed_today, exits=(), buys_blocked=None,
                 now=None):
    """exits: rotated-out symbols that may be sold but not bought.
    buys_blocked: None, or the reason every buy is rejected.
    now: the time to judge market orders against (default: the clock)."""
    now = now or datetime.datetime.now(EASTERN)
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
        otype = o.get("type")
        qty = o.get("quantity") or 0
        limit = o.get("limit_price")
        amount = o.get("dollar_amount") or 0

        if sym not in (sellable if o.get("side") == "sell" else symbols):
            reasons.append(f"{sym} is not in the allowed symbols")
        if otype == "limit":
            if not limit or limit <= 0:
                reasons.append("limit orders need a positive limit price")
            if qty <= 0:
                reasons.append("quantity must be positive")
            elif not whole(qty):
                reasons.append("Robinhood does not accept fractional limit orders")
        elif otype == "market":
            if not config.get("allow_fractional_market"):
                reasons.append("market orders are not allowed")
            elif o.get("side") == "buy" and (amount <= 0 or qty):
                reasons.append("a market buy must set only a positive dollar_amount")
            elif o.get("side") == "sell" and (qty <= 0 or amount):
                reasons.append("a market sell must set only a positive quantity")
            elif o.get("side") == "sell" and whole(qty):
                reasons.append("whole-share sells must be limit orders")
            if not market_window_open(now):
                reasons.append(f"market orders only on weekdays {MARKET_OPEN:%H:%M}-"
                               f"{MARKET_CLOSE:%H:%M} ET")
        else:
            reasons.append(f"unknown order type {otype!r}")
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

        if otype == "market" and o.get("side") == "buy":
            notional = amount
        else:
            notional = qty * (limit or (quote or {}).get("bid") or 0)
        if not reasons:
            if o["side"] == "buy":
                if buys_blocked:
                    reasons.append(f"buys blocked: {buys_blocked}")
                if buys_halted:
                    reasons.append(f"buys halted: account value ${account['total_value']:.2f} "
                                   f"is below the drawdown floor ${halt_floor:.2f}")
                if otype == "limit" and limit > quote["ask"] * (1 + buf) + PRICE_TOLERANCE:
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
                if otype == "limit" and limit < quote["bid"] * (1 - buf) - PRICE_TOLERANCE:
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

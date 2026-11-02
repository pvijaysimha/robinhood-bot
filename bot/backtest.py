"""Replay the strategy over daily history. Never trades.

Decisions are made on each day's close and filled at the next day's close,
with a flat cost per trade. The screen and SMA signal are the live code in
bot.screen and bot.strategy, so a variant tested here is what the bot runs.

Prices are split-adjusted closes without dividends, so every variant,
including the SPY benchmark, is measured on price return, and cash earns
nothing."""
import math

from bot.screen import correlation, screen
from bot.strategy import signal

TRADING_DAYS = 252
VOL_DAYS = 21          # the live scan's 1-month historical volatility
MAX_VOL = 0.35         # the live scan's volatility cap
WEIGHT_VOL_DAYS = 63   # ~3 months, for inverse-volatility weights


def realized_vol(closes, days):
    if len(closes) < days + 1:
        return None
    rets = [math.log(b / a) for a, b in zip(closes[-days - 1:], closes[-days:])]
    mean = sum(rets) / days
    return (sum((r - mean) ** 2 for r in rets) / (days - 1)) ** 0.5 * TRADING_DAYS ** 0.5


def pick_universe(closes, i, v, held):
    """The screen as of close i: the live scan's trend and volatility
    filters, then bot.screen ranking."""
    window = {s: c[:i + 1] for s, c in closes.items()}
    cands = []
    for sym, c in window.items():
        vol = realized_vol(c, VOL_DAYS)
        if vol is not None and vol < MAX_VOL and signal(c, v["sma_days"]) == "in":
            cands.append({"symbol": sym, "name": sym})
    rows = screen(cands, window, v["sma_days"], v["top"], held, v.get("keep_top"), v.get("themes"))
    return [r["symbol"] for r in rows if r["selected"]]


def weights(closes, i, symbols, scheme):
    if not symbols:
        return {}
    if scheme == "inverse_vol":
        inv = {s: 1 / (realized_vol(closes[s][:i + 1], WEIGHT_VOL_DAYS) or 1e9) for s in symbols}
        total = sum(inv.values())
        return {s: x / total for s, x in inv.items()}
    return {s: 1 / len(symbols) for s in symbols}


def run(dates, closes, v, cost=0.001, cash_reserve=0.05, band=0.20, start=10000.0):
    """Daily equity curve and trade count for one variant. v keys:
    symbols (fixed list) or top/keep_top/themes (screened), sma_days
    (None = always hold), weighting ("equal" or "inverse_vol")."""
    warmup = 274 if "top" in v else (v["sma_days"] or 0)
    cash, shares, universe = start, {}, list(v.get("symbols", []))
    pending, curve, trades = None, [], 0
    for i, day in enumerate(dates):
        price = {s: closes[s][i] for s in closes}
        if pending is not None:
            for sym, target in pending.items():
                have = shares.get(sym, 0.0) * price[sym]
                delta = target - have
                cash -= delta + abs(delta) * cost
                shares[sym] = shares.get(sym, 0.0) + delta / price[sym]
                trades += 1
            pending = None
        equity = cash + sum(q * price[s] for s, q in shares.items())
        curve.append((day, equity))
        if i < warmup or i == len(dates) - 1:
            continue

        held = [s for s, q in shares.items() if q * price[s] > 1e-6]
        if "top" in v and (not universe or day[:7] != dates[i - 1][:7]):
            universe = pick_universe(closes, i, v, held)
        w = weights(closes, i, universe, v.get("weighting", "equal"))
        investable = equity * (1 - cash_reserve)
        orders = {}
        for sym in set(universe) | set(held):
            have = shares.get(sym, 0.0) * price[sym]
            on = sym in w and (v["sma_days"] is None or signal(closes[sym][:i + 1], v["sma_days"]) == "in")
            target = investable * w[sym] if on else 0.0
            if target == 0 and have > 0:
                orders[sym] = 0.0
            elif target > 0 and abs(target - have) >= band * target:
                orders[sym] = target
        pending = orders or None
    return curve, trades


def stats(curve, trades=None, years=None):
    values = [e for _, e in curve]
    rets = [b / a - 1 for a, b in zip(values, values[1:])]
    n = len(rets)
    mean = sum(rets) / n
    sd = (sum((r - mean) ** 2 for r in rets) / (n - 1)) ** 0.5
    peak, max_dd = values[0], 0.0
    for x in values:
        peak = max(peak, x)
        max_dd = min(max_dd, x / peak - 1)
    cagr = (values[-1] / values[0]) ** (TRADING_DAYS / n) - 1
    out = {"cagr": cagr, "vol": sd * TRADING_DAYS ** 0.5,
           "sharpe": mean / sd * TRADING_DAYS ** 0.5 if sd else 0.0, "max_dd": max_dd,
           "calmar": cagr / -max_dd if max_dd else 0.0}
    if trades is not None and years:
        out["trades_per_year"] = trades / years
    return out


def slice_curve(curve, start, end):
    return [(d, e) for d, e in curve if start <= d <= end]


def correlation_of_curves(a, b):
    ra = [y / x - 1 for (_, x), (_, y) in zip(a, a[1:])]
    rb = [y / x - 1 for (_, x), (_, y) in zip(b, b[1:])]
    return correlation(ra, rb)

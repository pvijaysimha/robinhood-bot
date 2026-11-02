"""Rank scanner candidates into the trading universe. Never trades and
never edits config.json; `bot.cli screen` writes the picks to universe.json.

A candidate is kept when it is not a leveraged, inverse or volatility
product, has enough history, trades above its SMA and has positive 12-1
momentum (the 12-month return skipping the latest month). Survivors are
picked best momentum first, skipping any that move too closely with one
already picked, so the list is not five versions of the same fund. A held
symbol keeps its place while it ranks within keep_top, which stops funds
near the cut-off being bought and sold every month."""
import re

from bot.strategy import signal

MOMENTUM_DAYS = 252   # ~12 months of trading days
SKIP_DAYS = 21        # skip the latest ~month, which tends to reverse
CORR_DAYS = 126       # ~6 months of daily returns for the overlap check
MAX_CORR = 0.80
MIN_HISTORY = MOMENTUM_DAYS + SKIP_DAYS + 1

# Leveraged, inverse and volatility products decay or can collapse in a day,
# which a daily-close trend rule cannot protect against.
EXCLUDE = re.compile(
    r"\b(\d(\.\d+)?x|ultra(?!-short)\w*|leveraged|inverse|bear|bull|vix|(?<!low )volatility)\b"
    r"|(?<!ultra-)\bshort\b(?![- ](term|treasury|duration|maturity))",
    re.IGNORECASE)


def excluded(name):
    return bool(EXCLUDE.search(name or ""))


def momentum(closes):
    if len(closes) < MIN_HISTORY:
        return None
    return closes[-1 - SKIP_DAYS] / closes[-1 - SKIP_DAYS - MOMENTUM_DAYS] - 1


def returns(closes, days):
    window = closes[-days - 1:]
    return [b / a - 1 for a, b in zip(window, window[1:])]


def correlation(xs, ys):
    n = min(len(xs), len(ys))
    xs, ys = xs[-n:], ys[-n:]
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx * vy) ** 0.5


def screen(candidates, closes_by_symbol, sma_days, top, held=(), keep_top=None, themes=None):
    """Return every candidate with its verdict, best momentum first."""
    keep_top = max(keep_top or top, top)
    rows = []
    for c in candidates:
        sym = c["symbol"]
        closes = closes_by_symbol.get(sym, [])
        mom = momentum(closes)
        row = {**c, "momentum_12_1": None if mom is None else round(mom, 4),
               "selected": False, "kept": False, "reason": None}
        if excluded(c.get("name")):
            row["reason"] = "leveraged, inverse or volatility product"
        elif mom is None:
            row["reason"] = f"needs {MIN_HISTORY} daily closes, has {len(closes)}"
        elif signal(closes, sma_days) != "in":
            row["reason"] = f"not above its {sma_days}-day SMA"
        elif mom <= 0:
            row["reason"] = "12-1 momentum is not positive"
        rows.append(row)

    rows.sort(key=lambda r: -(r["momentum_12_1"] if r["momentum_12_1"] is not None else -1e9))
    eligible = [r for r in rows if not r["reason"]]
    picked = []
    for rank, row in enumerate(eligible):
        if row["symbol"] in held and rank < keep_top and len(picked) < top:
            row["selected"] = row["kept"] = True
            picked.append(row)
    for row in eligible:
        if row["selected"]:
            continue
        if len(picked) >= top:
            row["reason"] = f"outside the top {top}"
            continue
        theme = (themes or {}).get(row["symbol"])
        twin = next((p for p in picked if theme and (themes or {}).get(p["symbol"]) == theme), None)
        if twin:
            row["reason"] = f"same theme ({theme}) as {twin['symbol']}"
            continue
        rets = returns(closes_by_symbol[row["symbol"]], CORR_DAYS)
        for p in picked:
            corr = correlation(rets, returns(closes_by_symbol[p["symbol"]], CORR_DAYS))
            if corr is not None and corr > MAX_CORR:
                row["reason"] = f"moves with {p['symbol']} (correlation {corr:.2f})"
                break
        else:
            row["selected"] = True
            picked.append(row)
    for row in eligible:
        if row["symbol"] in held and not row["selected"]:
            row["reason"] = f"held, but fell out of the top {keep_top}"
    return rows

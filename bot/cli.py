"""Entry point.

  python3 -m bot.cli plan snapshot.json
      Run the strategy and the guard over a snapshot of the account, print
      the plan as JSON, and append it to logs/plans.jsonl. Never trades.

  python3 -m bot.cli record --symbol SPY --side buy --quantity 0.2 \
      --limit-price 512.30 --order-id <id> --state <state>
      Append a placed order to logs/orders.jsonl. The guard counts today's
      entries there toward max_orders_per_day.

  python3 -m bot.cli screen candidates.json
      Rank scanner candidates (shape: examples/candidates.example.json),
      write the picks to universe.json and append the full result to
      logs/screens.jsonl. Never trades and never edits config.json.

  python3 -m bot.cli universe
      Print which symbols the bot may trade, whether buys are blocked
      because the universe is stale, and which symbols to snapshot.
"""
import argparse
import datetime
import json
import pathlib
import sys

from bot.guard import check_orders
from bot.screen import screen as rank_candidates
from bot.strategy import propose_orders
from bot.universe import allowed_symbols, bought_symbols, exits

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.json"
ORDERS_LOG = ROOT / "logs" / "orders.jsonl"
PLANS_LOG = ROOT / "logs" / "plans.jsonl"
SCREENS_LOG = ROOT / "logs" / "screens.jsonl"
UNIVERSE = ROOT / "universe.json"


def now():
    return datetime.datetime.now().astimezone()


def append(path, entry):
    path.parent.mkdir(exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def order_log():
    if not ORDERS_LOG.exists():
        return []
    return [json.loads(l) for l in ORDERS_LOG.read_text().splitlines() if l.strip()]


def orders_placed_on(day):
    return sum(1 for e in order_log() if e["date"] == day)


def load_universe():
    return json.loads(UNIVERSE.read_text()) if UNIVERSE.exists() else None


def plan(snapshot_path):
    config = json.loads(CONFIG.read_text())
    snap = json.loads(pathlib.Path(snapshot_path).read_text())
    account, closes = snap["account"], snap["closes"]
    today = now().date().isoformat()

    symbols, buys_blocked = allowed_symbols(config, load_universe(), today)
    rotated = exits([p["symbol"] for p in account["positions"]], symbols, bought_symbols(order_log()))
    effective = {**config, "symbols": symbols}
    proposed, targets = propose_orders(effective, account, closes, rotated)
    checked = check_orders(effective, account, proposed, orders_placed_on(today), rotated, buys_blocked)
    result = {
        "date": today,
        "time": now().strftime("%H:%M:%S"),
        "mode": config["mode"],
        "may_place": config["mode"] == "live",
        "total_value": account["total_value"],
        "cash": account["cash"],
        "symbols": symbols,
        "exits": rotated,
        "buys_blocked": buys_blocked,
        "targets": targets,
        "orders": checked,
    }
    append(PLANS_LOG, result)
    print(json.dumps(result, indent=2))


def screen(candidates_path):
    config = json.loads(CONFIG.read_text())
    rules = config.get("universe", {"top": 5, "keep_while_in_top": 5})
    data = json.loads(pathlib.Path(candidates_path).read_text())
    held = data.get("held", [])
    rows = rank_candidates(data["candidates"], data["closes"], config["sma_days"],
                           rules["top"], held, rules["keep_while_in_top"])
    picks = [r for r in rows if r["selected"]]
    today = now().date().isoformat()
    previous = load_universe()
    before = previous["symbols"] if previous else []
    universe = {
        "date": today,
        "symbols": [r["symbol"] for r in picks],
        "picks": [{k: r.get(k) for k in ("symbol", "name", "momentum_12_1", "kept")} for r in picks],
    }
    UNIVERSE.write_text(json.dumps(universe, indent=2) + "\n")
    result = {
        "date": today,
        "time": now().strftime("%H:%M:%S"),
        "previous_symbols": before,
        "symbols": universe["symbols"],
        "added": [s for s in universe["symbols"] if s not in before],
        "removed": [s for s in before if s not in universe["symbols"]],
        "candidates": rows,
    }
    append(SCREENS_LOG, result)
    print(json.dumps(result, indent=2))


def universe_status():
    config = json.loads(CONFIG.read_text())
    universe = load_universe()
    today = now().date().isoformat()
    symbols, buys_blocked = allowed_symbols(config, universe, today)
    bought = bought_symbols(order_log())
    print(json.dumps({
        "source": "universe.json" if "universe" in config else "config.json",
        "date": universe["date"] if universe and "universe" in config else None,
        "symbols": symbols,
        "buys_blocked": buys_blocked,
        "snapshot_if_held": sorted(bought - set(symbols)),
    }, indent=2))


def record(args):
    append(ORDERS_LOG, {
        "date": now().date().isoformat(),
        "time": now().strftime("%H:%M:%S"),
        "symbol": args.symbol, "side": args.side, "quantity": args.quantity,
        "limit_price": args.limit_price, "order_id": args.order_id, "state": args.state,
    })


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("plan")
    sp.add_argument("snapshot")
    sc = sub.add_parser("screen")
    sc.add_argument("candidates")
    sub.add_parser("universe")
    sr = sub.add_parser("record")
    sr.add_argument("--symbol", required=True)
    sr.add_argument("--side", required=True, choices=["buy", "sell"])
    sr.add_argument("--quantity", required=True, type=float)
    sr.add_argument("--limit-price", required=True, type=float)
    sr.add_argument("--order-id", required=True)
    sr.add_argument("--state", required=True)
    args = p.parse_args(argv)
    if args.cmd == "plan":
        plan(args.snapshot)
    elif args.cmd == "screen":
        screen(args.candidates)
    elif args.cmd == "universe":
        universe_status()
    else:
        record(args)


if __name__ == "__main__":
    sys.exit(main())

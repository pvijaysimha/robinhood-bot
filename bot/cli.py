"""Entry point.

  python3 -m bot.cli plan snapshot.json
      Run the strategy and the guard over a snapshot of the account, print
      the plan as JSON, and append it to logs/plans.jsonl. Never trades.

  python3 -m bot.cli record --symbol SPY --side buy --quantity 0.2 \
      --limit-price 512.30 --order-id <id> --state <state>
      Append a placed order to logs/orders.jsonl. The guard counts today's
      entries there toward max_orders_per_day.
"""
import argparse
import datetime
import json
import pathlib
import sys

from bot.guard import check_orders
from bot.strategy import propose_orders

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.json"
ORDERS_LOG = ROOT / "logs" / "orders.jsonl"
PLANS_LOG = ROOT / "logs" / "plans.jsonl"


def now():
    return datetime.datetime.now().astimezone()


def append(path, entry):
    path.parent.mkdir(exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def orders_placed_on(day):
    if not ORDERS_LOG.exists():
        return 0
    lines = (json.loads(l) for l in ORDERS_LOG.read_text().splitlines() if l.strip())
    return sum(1 for e in lines if e["date"] == day)


def plan(snapshot_path):
    config = json.loads(CONFIG.read_text())
    snap = json.loads(pathlib.Path(snapshot_path).read_text())
    account, closes = snap["account"], snap["closes"]
    today = now().date().isoformat()

    proposed, targets = propose_orders(config, account, closes)
    checked = check_orders(config, account, proposed, orders_placed_on(today))
    result = {
        "date": today,
        "time": now().strftime("%H:%M:%S"),
        "mode": config["mode"],
        "may_place": config["mode"] == "live",
        "total_value": account["total_value"],
        "cash": account["cash"],
        "targets": targets,
        "orders": checked,
    }
    append(PLANS_LOG, result)
    print(json.dumps(result, indent=2))


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
    else:
        record(args)


if __name__ == "__main__":
    sys.exit(main())

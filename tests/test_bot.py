import unittest

from bot.guard import check_orders
from bot.strategy import propose_orders, signal

CONFIG = {
    "mode": "dry_run", "budget_usd": 500, "max_order_usd": 150, "min_order_usd": 5,
    "max_orders_per_day": 3, "max_drawdown_pct": 0.15, "cash_reserve_pct": 0.05,
    "limit_buffer_pct": 0.005, "rebalance_band_pct": 0.20, "sma_days": 5,
    "symbols": ["SPY", "QQQ", "VXUS"],
}
UP = [10, 10, 10, 10, 12]
DOWN = [10, 10, 10, 10, 8]
QUOTES = {"SPY": {"bid": 99.9, "ask": 100.0}, "QQQ": {"bid": 49.9, "ask": 50.0},
          "VXUS": {"bid": 59.9, "ask": 60.0}}


def account(cash=500.0, positions=(), total=None, open_orders=()):
    positions = list(positions)
    invested = sum(p["market_value"] for p in positions)
    return {"cash": cash, "total_value": total if total is not None else cash + invested,
            "positions": positions, "quotes": QUOTES, "open_orders": list(open_orders)}


def buy(sym="SPY", qty=1.0, limit=100.5):
    return {"symbol": sym, "side": "buy", "type": "limit", "quantity": qty, "limit_price": limit}


class StrategyTest(unittest.TestCase):
    def test_signal(self):
        self.assertEqual(signal(UP, 5), "in")
        self.assertEqual(signal(DOWN, 5), "out")
        self.assertIsNone(signal(UP[:4], 5))

    def test_buys_trending_symbols_only(self):
        orders, _ = propose_orders(CONFIG, account(), {"SPY": UP, "QQQ": DOWN, "VXUS": UP[:3]})
        self.assertEqual([(o["symbol"], o["side"]) for o in orders], [("SPY", "buy")])
        self.assertAlmostEqual(orders[0]["quantity"] * orders[0]["limit_price"], 150, delta=0.01)

    def test_exits_on_downtrend(self):
        pos = [{"symbol": "QQQ", "quantity": 2.0, "market_value": 100.0}]
        orders, _ = propose_orders(CONFIG, account(cash=400, positions=pos), {"QQQ": DOWN})
        self.assertEqual(orders, [{"symbol": "QQQ", "side": "sell", "type": "limit", "quantity": 2.0,
                                   "limit_price": 49.65, "reason": "below SMA: exit"}])

    def test_sizes_off_budget_not_bigger_account(self):
        _, targets = propose_orders(CONFIG, account(cash=5000), {"SPY": UP})
        self.assertAlmostEqual(targets["SPY"]["target_usd"], 500 * 0.95 / 3)

    def test_strategy_output_passes_guard(self):
        acct = account()
        orders, _ = propose_orders(CONFIG, acct, {"SPY": UP, "QQQ": UP, "VXUS": UP})
        self.assertTrue(all(r["approved"] for r in check_orders(CONFIG, acct, orders, 0)))


class GuardTest(unittest.TestCase):
    def check(self, orders, acct=None, placed=0):
        return check_orders(CONFIG, acct or account(), orders, placed)

    def test_rejects_market_order(self):
        r = self.check([{**buy(), "type": "market"}])[0]
        self.assertFalse(r["approved"])

    def test_rejects_unknown_symbol(self):
        self.assertFalse(self.check([buy(sym="TSLA")])[0]["approved"])

    def test_rejects_limit_far_above_ask(self):
        self.assertFalse(self.check([buy(limit=103)])[0]["approved"])

    def test_rejects_oversized_order(self):
        self.assertFalse(self.check([buy(qty=1.6)])[0]["approved"])

    def test_budget_counts_earlier_approvals(self):
        pos = [{"symbol": "QQQ", "quantity": 6.0, "market_value": 300.0}]
        acct = account(cash=400, positions=pos)
        r = self.check([buy("SPY", 1.4), buy("VXUS", 2.4, 60.3)], acct)
        self.assertEqual([x["approved"] for x in r], [True, False])
        self.assertIn("over budget_usd", r[1]["reasons"][0])

    def test_daily_order_limit(self):
        self.assertFalse(self.check([buy()], placed=3)[0]["approved"])

    def test_open_order_blocks_symbol(self):
        acct = account(open_orders=[{"symbol": "SPY"}])
        self.assertFalse(self.check([buy()], acct)[0]["approved"])

    def test_drawdown_halts_buys_not_sells(self):
        pos = [{"symbol": "SPY", "quantity": 1.0, "market_value": 100.0}]
        acct = account(cash=300, positions=pos)  # total 400 < floor 425
        sell = {"symbol": "SPY", "side": "sell", "type": "limit", "quantity": 1.0, "limit_price": 99.5}
        r = self.check([buy("QQQ", 1.0, 50.2), sell], acct)
        self.assertEqual([x["approved"] for x in r], [False, True])

    def test_cannot_sell_more_than_held(self):
        sell = {"symbol": "SPY", "side": "sell", "type": "limit", "quantity": 2.0, "limit_price": 99.5}
        pos = [{"symbol": "SPY", "quantity": 1.0, "market_value": 100.0}]
        self.assertFalse(self.check([sell], account(cash=400, positions=pos))[0]["approved"])


if __name__ == "__main__":
    unittest.main()

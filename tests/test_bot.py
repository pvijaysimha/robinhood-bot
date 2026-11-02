import datetime
import unittest

from bot.guard import EASTERN, check_orders
from bot.screen import MIN_HISTORY, excluded, screen
from bot.strategy import propose_orders, signal
from bot.universe import allowed_symbols, bought_symbols, exits

CONFIG = {
    "mode": "dry_run", "budget_usd": 500, "max_order_usd": 150, "min_order_usd": 5,
    "max_orders_per_day": 3, "max_drawdown_pct": 0.15, "cash_reserve_pct": 0.05,
    "limit_buffer_pct": 0.005, "rebalance_band_pct": 0.20, "sma_days": 5,
    "symbols": ["SPY", "QQQ", "VXUS"],
}
FRACTIONAL = {**CONFIG, "allow_fractional_market": True}
OPEN = datetime.datetime(2026, 11, 3, 11, 0, tzinfo=EASTERN)  # a Tuesday, 11:00 ET
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
        orders, _ = propose_orders(FRACTIONAL, acct, {"SPY": UP, "QQQ": UP, "VXUS": UP})
        checked = check_orders(FRACTIONAL, acct, orders, 0, now=OPEN)
        self.assertTrue(all(r["approved"] for r in checked), checked)


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
        r = self.check([buy("SPY", 1.0), buy("VXUS", 2.0, 60.3)], acct)
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


def series(growth, wiggle, n=MIN_HISTORY + 10):
    """A trending price series; wiggle picks a distinct pattern of daily noise."""
    out, price = [], 100.0
    for i in range(n):
        price *= 1 + growth + 0.01 * ((i * wiggle) % 7 - 3) / 3
        out.append(price)
    return out


class ScreenTest(unittest.TestCase):
    def test_excludes_leveraged_inverse_and_volatility(self):
        for name in ["Direxion Daily S&P 500 Bull 3x ETF", "ProShares UltraPro S&P 500 ETF",
                     "ProShares Short VIX Short-Term Futures ETF", "ProShares Short S&P500",
                     "ProShares UltraShort Gold ETF"]:
            self.assertTrue(excluded(name), name)
        for name in ["iShares Short Treasury Bond ETF", "Vanguard Short-Term Bond ETF",
                     "SPDR S&P 500 ETF Trust", "Invesco S&P 500 Low Volatility ETF",
                     "JPMorgan Ultra-Short Municipal Income ETF"]:
            self.assertFalse(excluded(name), name)

    def test_picks_best_momentum_and_skips_lookalikes(self):
        a = series(0.002, 1)
        closes = {"A": a, "A2": [x * 1.001 for x in a], "B": series(0.001, 3), "C": series(-0.001, 5)}
        cands = [{"symbol": s, "name": s} for s in closes]
        rows = {r["symbol"]: r for r in screen(cands, closes, 200, top=5)}
        self.assertTrue(rows["A"]["selected"] or rows["A2"]["selected"])
        self.assertFalse(rows["A"]["selected"] and rows["A2"]["selected"])
        self.assertTrue(rows["B"]["selected"])
        self.assertFalse(rows["C"]["selected"])

    def test_needs_history_and_respects_top(self):
        closes = {"A": series(0.002, 1), "B": series(0.001, 3), "S": series(0.003, 2)[:100]}
        rows = {r["symbol"]: r for r in screen([{"symbol": s} for s in closes], closes, 200, top=1)}
        self.assertEqual([s for s, r in rows.items() if r["selected"]], ["A"])
        self.assertIn("top 1", rows["B"]["reason"])
        self.assertIn("needs", rows["S"]["reason"])

    def test_held_symbol_keeps_its_place_within_keep_top(self):
        closes = {s: series(g, w) for s, g, w in
                  [("A", 0.004, 1), ("B", 0.0035, 2), ("C", 0.003, 3), ("D", 0.0025, 5)]}
        cands = [{"symbol": s} for s in closes]
        def picked(held, keep_top):
            return [r["symbol"] for r in screen(cands, closes, 200, 2, held, keep_top) if r["selected"]]
        self.assertEqual(picked((), 2)[:1], ["A"])
        self.assertIn("D", picked(("D",), 4))
        rows = {r["symbol"]: r for r in screen(cands, closes, 200, 2, ("D",), 3)}
        self.assertFalse(rows["D"]["selected"])
        self.assertIn("fell out of the top 3", rows["D"]["reason"])


UNIVERSE_CONFIG = {**{k: v for k, v in CONFIG.items() if k != "symbols"},
                   "universe": {"top": 5, "keep_while_in_top": 10, "max_age_days": 35}}


class UniverseTest(unittest.TestCase):
    def test_static_symbols_without_universe_block(self):
        self.assertEqual(allowed_symbols(CONFIG, None, "2026-10-30"), (["SPY", "QQQ", "VXUS"], None))

    def test_missing_universe_blocks_buys(self):
        symbols, blocked = allowed_symbols(UNIVERSE_CONFIG, None, "2026-10-30")
        self.assertEqual(symbols, [])
        self.assertIn("run the screen", blocked)

    def test_fresh_and_stale_universe(self):
        u = {"date": "2026-10-01", "symbols": ["SPY", "QQQ"]}
        self.assertEqual(allowed_symbols(UNIVERSE_CONFIG, u, "2026-11-05"), (["SPY", "QQQ"], None))
        symbols, blocked = allowed_symbols(UNIVERSE_CONFIG, u, "2026-11-06")
        self.assertEqual(symbols, ["SPY", "QQQ"])  # still managed, not treated as rotated out
        self.assertIn("36 days old", blocked)

    def test_exits_only_symbols_the_bot_bought(self):
        bought = bought_symbols([{"symbol": "VXUS", "side": "buy"}, {"symbol": "QQQ", "side": "sell"}])
        self.assertEqual(exits(["VXUS", "QQQ", "AAPL", "SPY"], ["SPY"], bought), ["VXUS"])

    def test_rotated_out_symbol_is_sold_and_guard_allows_it(self):
        cfg = {**FRACTIONAL, "symbols": ["SPY"]}
        pos = [{"symbol": "VXUS", "quantity": 1.5, "market_value": 90.0}]
        acct = account(cash=410, positions=pos)
        orders, _ = propose_orders(cfg, acct, {"SPY": UP}, exits=["VXUS"])
        self.assertEqual([(o["symbol"], o["side"]) for o in orders], [("VXUS", "sell"), ("SPY", "buy")])
        checked = check_orders(cfg, acct, orders, 0, exits=["VXUS"], now=OPEN)
        self.assertTrue(all(r["approved"] for r in checked), checked)

    def test_exit_symbol_cannot_be_bought(self):
        cfg = {**CONFIG, "symbols": ["SPY"]}
        [r] = check_orders(cfg, account(), [buy("VXUS", 1.0, 60.3)], 0, exits=["VXUS"])
        self.assertFalse(r["approved"])

    def test_buys_blocked_but_sells_allowed(self):
        pos = [{"symbol": "SPY", "quantity": 1.0, "market_value": 100.0}]
        sell = {"symbol": "SPY", "side": "sell", "type": "limit", "quantity": 1.0, "limit_price": 99.5}
        b, s = check_orders(CONFIG, account(positions=pos), [buy("QQQ", 1.0, 50.2), sell], 0,
                            buys_blocked="stale")
        self.assertFalse(b["approved"])
        self.assertIn("buys blocked: stale", b["reasons"])
        self.assertTrue(s["approved"], s)

    def test_no_symbols_proposes_nothing(self):
        orders, targets = propose_orders({**CONFIG, "symbols": []}, account(), {})
        self.assertEqual((orders, targets), ([], {}))

    def test_rejects_wide_spread(self):
        acct = {**account(), "quotes": {**QUOTES, "SPY": {"bid": 90.0, "ask": 100.0}}}
        [r] = check_orders(CONFIG, acct, [buy("SPY", 1.0, 100.5)], 0)
        self.assertFalse(r["approved"])
        self.assertIn("spread", r["reasons"][0])


MIX = {**FRACTIONAL, "symbols": ["SPY", "QQQ", "VXUS"],
       "weights": {"SPY": 0.6, "QQQ": 0.2, "VXUS": 0.2}, "trend_filter": []}


class WeightsTest(unittest.TestCase):
    def test_targets_follow_weights(self):
        _, t = propose_orders(MIX, account(), {})
        self.assertAlmostEqual(t["SPY"]["target_usd"], 500 * 0.95 * 0.6)
        self.assertAlmostEqual(t["QQQ"]["target_usd"], 500 * 0.95 * 0.2)

    def test_unfiltered_symbols_held_below_sma_and_without_history(self):
        orders, t = propose_orders(MIX, account(), {"SPY": DOWN})
        self.assertEqual({s: x["signal"] for s, x in t.items()}, {"SPY": "hold", "QQQ": "hold", "VXUS": "hold"})
        self.assertEqual(sorted(o["symbol"] for o in orders), ["QQQ", "SPY", "VXUS"])

    def test_trend_filter_applies_only_to_listed_symbols(self):
        cfg = {**MIX, "trend_filter": ["QQQ"]}
        pos = [{"symbol": "QQQ", "quantity": 2.0, "market_value": 95.0}]
        orders, t = propose_orders(cfg, account(cash=405, positions=pos), {"QQQ": DOWN})
        self.assertEqual(t["QQQ"]["target_usd"], 0.0)
        self.assertIn(("QQQ", "sell"), [(o["symbol"], o["side"]) for o in orders])

    def test_big_weight_is_built_in_capped_orders(self):
        orders, _ = propose_orders(MIX, account(), {})
        spy = next(o for o in orders if o["symbol"] == "SPY")
        self.assertEqual((spy["type"], spy["dollar_amount"]), ("market", 150))

    def test_bad_weights_rejected(self):
        for w in [{"SPY": 0.6, "QQQ": 0.2}, {"SPY": 0.7, "QQQ": 0.2, "VXUS": 0.2}]:
            with self.assertRaises(ValueError):
                propose_orders({**MIX, "weights": w}, account(), {})

    def test_mix_passes_guard(self):
        acct = account()
        orders, _ = propose_orders(MIX, acct, {})
        self.assertTrue(all(r["approved"] for r in check_orders(MIX, acct, orders, 0, now=OPEN)))


def market_buy(sym="SPY", amount=100.0):
    return {"symbol": sym, "side": "buy", "type": "market", "dollar_amount": amount}


def market_sell(sym="SPY", qty=0.5):
    return {"symbol": sym, "side": "sell", "type": "market", "quantity": qty}


class FractionalMarketTest(unittest.TestCase):
    HELD = [{"symbol": "SPY", "quantity": 1.5, "market_value": 150.0}]

    def check(self, order, config=FRACTIONAL, now=OPEN, acct=None):
        [r] = check_orders(config, acct or account(positions=self.HELD), [order], 0, now=now)
        return r

    def test_fractional_market_buy_and_sell_approved(self):
        self.assertTrue(self.check(market_buy())["approved"])
        r = self.check(market_sell())
        self.assertTrue(r["approved"], r)
        self.assertAlmostEqual(r["notional_usd"], 0.5 * 99.9, places=2)

    def test_market_orders_need_the_config_flag(self):
        self.assertIn("market orders are not allowed", self.check(market_buy(), config=CONFIG)["reasons"])

    def test_market_orders_only_inside_the_window(self):
        for when in [datetime.datetime(2026, 11, 3, 9, 45, tzinfo=EASTERN),
                     datetime.datetime(2026, 11, 3, 15, 45, tzinfo=EASTERN),
                     datetime.datetime(2026, 11, 7, 11, 0, tzinfo=EASTERN)]:  # Saturday
            r = self.check(market_buy(), now=when)
            self.assertFalse(r["approved"], when)
            self.assertIn("weekdays", r["reasons"][0])
        pacific = datetime.datetime(2026, 11, 3, 8, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-8)))
        self.assertTrue(self.check(market_buy(), now=pacific)["approved"])  # 11:00 ET

    def test_market_buy_must_be_by_dollars_and_within_caps(self):
        self.assertFalse(self.check({**market_buy(), "quantity": 0.2})["approved"])
        self.assertIn("exceeds max_order_usd", self.check(market_buy(amount=151))["reasons"][0])
        acct = account(cash=50, positions=self.HELD)
        self.assertIn("exceeds cash", self.check(market_buy(amount=60), acct=acct)["reasons"][-1])

    def test_whole_share_market_sell_rejected(self):
        self.assertIn("whole-share sells must be limit orders", self.check(market_sell(qty=1.0))["reasons"])

    def test_fractional_limit_rejected(self):
        r = self.check(buy("SPY", 0.5, 100.5))
        self.assertIn("Robinhood does not accept fractional limit orders", r["reasons"])

    def test_market_order_still_needs_a_tight_spread(self):
        acct = {**account(positions=self.HELD), "quotes": {**QUOTES, "SPY": {"bid": 90.0, "ask": 100.0}}}
        self.assertFalse(self.check(market_buy(), acct=acct)["approved"])

    def test_strategy_sells_fractional_at_market_and_whole_at_limit(self):
        for qty, otype in [(1.5, "market"), (2.0, "limit")]:
            pos = [{"symbol": "QQQ", "quantity": qty, "market_value": qty * 50}]
            orders, _ = propose_orders(FRACTIONAL, account(cash=400, positions=pos), {"QQQ": DOWN})
            [sell] = [o for o in orders if o["side"] == "sell"]
            self.assertEqual(sell["type"], otype)

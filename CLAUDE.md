# Trading runbook

This repo trades a small, capped amount through the Robinhood Agentic
Trading MCP (`robinhood-trading`). Follow these steps exactly when asked to
"run the bot", "check trades" or similar. The human approves every order.

## Rules that always apply

- Never edit `config.json`. Only the human changes `mode`, `budget_usd` or any limit.
- Never place an order the guard rejected, and never change an order's
  symbol, side, quantity or limit price after the guard checked it. If an
  order needs to change, rebuild the snapshot and run the plan again.
- Never place an order without the human's explicit "yes" for that order
  in this conversation. Silence, "looks good" to the plan as a whole, or an
  earlier session's approval does not count.
- Limit orders, except the fractional market orders the plan proposes when
  `config.json` has `allow_fractional_market` (Robinhood rejects fractional
  limit orders). No options, and no other market orders.
- Buy only symbols in the current universe (the `symbols` that
  `python3 -m bot.cli universe` prints). Sell only those, or the rotated-out
  `exits` the plan lists.
- Never edit `universe.json` by hand. Only `python3 -m bot.cli screen` writes it.
- Never estimate or invent a number. If an MCP call fails or a field is
  missing, stop and tell the human what failed.

## Steps

0. **Universe.** Run `python3 -m bot.cli universe`. If `buys_blocked` says to
   run the screen, do "Screening the universe" below first, show the human
   what was added and removed, then come back here.

1. **Snapshot.** Using the `robinhood-trading` tools, collect and write
   `snapshot.json` (shape: `examples/snapshot.example.json`), copying values
   from the tool responses:
   - `get_portfolio` → `account.total_value`, `account.cash`
   - `get_equity_positions` → `account.positions`: `symbol`, `quantity`,
     `market_value` (quantity × current price)
   - `get_equity_orders` → `account.open_orders`: every order not yet in a
     terminal state (filled, cancelled, rejected, failed, voided)
   - `get_equity_quotes` for every symbol in step 0's `symbols`, plus any
     symbol in `snapshot_if_held` that the account holds → `account.quotes`: `bid`, `ask`
   - `get_equity_historicals` (interval day, last ~300 calendar days) for
     the same symbols → `closes[symbol]`, oldest first

   If a tool has a different name, use the equivalent one and say which.

2. **Plan.** Run `python3 -m bot.cli plan snapshot.json`. It never trades.

3. **Show the plan.** Give the human a short table: each symbol's signal
   and target, then each order with side, quantity, limit price, dollar
   amount, and approved or rejected with the reasons. Call out any `exits`
   (rotated out of the universe) and any `buys_blocked` reason.

4. **Stop here if `mode` is `dry_run`.** Say what would have been placed.

5. **If `mode` is `live`**, first call `get_trade_approval_setting` for the
   account and tell the human whether Robinhood trade approvals are on. If
   they are off, say plainly that orders will execute without approval in
   the Robinhood app (the human chose this on 2026-11-02); the per-order
   "yes" below still applies. Read the setting again on every live run.
   Then, for each approved order, one at a time:
   1. Ask the human to approve that specific order. Wait for "yes". If the
      quotes in `snapshot.json` are more than 15 minutes old by then, do
      not place it: rebuild the snapshot, run the plan again and ask again.
   2. Call `review_equity_order` with exactly the planned parameters and
      `market_hours` `regular_hours`: a limit order with its quantity and
      limit price, a market buy with its `dollar_amount`, or a market sell
      with its `quantity`. If it returns any alert or warning, show it
      verbatim and do not place that order. Show its
      `market_data_disclosure` verbatim. For a market order, also check
      the review's quote: `state` `active` and `venue_last_trade_time`
      within the last 5 minutes. Otherwise the market may be closed and
      the order would queue for the open, so do not place it.
   3. Call `place_equity_order` with the same parameters and a fresh UUID
      as `ref_id` (reuse it only to retry a transport failure).
   4. Call `get_equity_orders` for that order ID to get its real state, and
      tell the human the order is waiting for their approval in the
      Robinhood app if that is what the state or `get_trade_approvals` shows.
   5. Run `python3 -m bot.cli record --symbol ... --side ... --type ...`
      with `--quantity` and `--limit-price` (limit), `--dollar-amount`
      (market buy) or `--quantity` (market sell), then `--order-id ...
      --state ...`.

6. **Commit** `logs/` and `universe.json` with a message like
   `Trading run YYYY-MM-DD` so the record survives.

## Screening the universe (when step 0 says so, or the human asks)

This picks the symbols. It never trades and never edits `config.json`. The
rules (`top`, `keep_while_in_top`, `max_age_days`) are in `config.json`'s
`universe` block, and the filters below are fixed. Do not loosen them.

1. Call `preview_scan` (not `create_scan`, so nothing is saved) with these
   filters: asset type `ETF`; expression
   `turnoverAvg(candleCount=30, candlePeriod="1d", session="regular")` >=
   `50000000`; expression `tradeAllDay.price > closeAvg(candleCount=200,
   candlePeriod="1d", session="regular")` = `True`; historical volatility
   < `0.35`. Add a `12M return` column:
   `tradeAllDay.price / close(timePeriod="1y", candlePeriod="1d", session="regular") - 1`.
2. Drop names that `bot.screen.excluded()` flags, then keep the 40 with the
   highest 12M return.
   Also add every symbol the account holds that is in the current universe
   or `snapshot_if_held`, even if the scan dropped it, so held funds are
   judged on the same terms.
3. `get_equity_historicals` (interval day, last ~420 calendar days, 10
   symbols per call) for those symbols.
4. Write `candidates.json` (shape: `examples/candidates.example.json`; `held`
   lists the held symbols from step 2) and run
   `python3 -m bot.cli screen candidates.json`. It writes `universe.json`.
5. Show the human the new universe, what was `added` and `removed`, and why
   the closest runners-up were skipped. Removed funds the bot bought are sold
   as `exits` on the next plan, each still needing the human's "yes".
6. Commit `universe.json` and `logs/screens.jsonl` with a message like
   `Screen YYYY-MM-DD`.

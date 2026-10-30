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
- Limit orders only. No options, no market orders, no symbols outside `config.json`.
- Never estimate or invent a number. If an MCP call fails or a field is
  missing, stop and tell the human what failed.

## Steps

1. **Snapshot.** Using the `robinhood-trading` tools, collect and write
   `snapshot.json` (shape: `examples/snapshot.example.json`), copying values
   from the tool responses:
   - `get_portfolio` → `account.total_value`, `account.cash`
   - `get_equity_positions` → `account.positions`: `symbol`, `quantity`,
     `market_value` (quantity × current price)
   - `get_equity_orders` → `account.open_orders`: every order not yet in a
     terminal state (filled, cancelled, rejected, failed, voided)
   - `get_equity_quotes` for every symbol in `config.json` → `account.quotes`: `bid`, `ask`
   - `get_equity_historicals` (interval day, last ~300 calendar days) for
     each symbol → `closes[symbol]`, oldest first

   If a tool has a different name, use the equivalent one and say which.

2. **Plan.** Run `python3 -m bot.cli plan snapshot.json`. It never trades.

3. **Show the plan.** Give the human a short table: each symbol's signal
   and target, then each order with side, quantity, limit price, dollar
   amount, and approved or rejected with the reasons.

4. **Stop here if `mode` is `dry_run`.** Say what would have been placed.

5. **If `mode` is `live`**, for each approved order, one at a time:
   1. Ask the human to approve that specific order. Wait for "yes".
   2. Call `review_equity_order` with exactly the planned parameters
      (limit order, the planned quantity and limit price). If it returns
      any alert or warning, show it verbatim and do not place that order.
   3. Call `place_equity_order` with the same parameters.
   4. Call `get_equity_orders` for that order ID to get its real state.
   5. Run `python3 -m bot.cli record --symbol ... --side ... --quantity ...
      --limit-price ... --order-id ... --state ...`.

6. **Commit** `logs/` with a message like `Trading run YYYY-MM-DD` so the
   record survives.

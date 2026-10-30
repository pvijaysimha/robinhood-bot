# robinhood-bot

A small, deliberately boring trading experiment for the Robinhood Agentic
Trading account. It holds a few broad ETFs while they are in an uptrend
and steps aside when they are not, with hard limits checked in code and a
human approving every order.

This is an experiment with money you can afford to lose, not an
investment plan. Most of your savings belong in plain index funds.

## Strategy

For each symbol in `config.json` (default SPY, QQQ, VXUS):

- **In** while the last close is above its 200-day simple moving average:
  target an equal slice of `budget_usd` (minus a 5% cash reserve).
- **Out** while it is below: sell the whole position.
- Trades only when a position is off target by more than 20% of its slice,
  so it does not churn. With fewer than 200 days of history it does nothing.

Trend-following like this tends to give up some return in rising markets
in exchange for sitting out part of long declines. It still loses money in
choppy markets that cross the average back and forth.

## Limits (enforced by `bot/guard.py`)

| Limit | Default |
|---|---|
| Total money put to work | `budget_usd` $500 (orders sized off the smaller of this and account value) |
| Largest single order | $150 |
| Orders per day | 3 |
| Order type | limit only, at most 0.5% past the bid/ask |
| Symbols | only those in `config.json` |
| Drawdown halt | no buys while account value is below 85% of `budget_usd` (sells still allowed) |
| Open orders | no new order for a symbol that already has one open |

Set `budget_usd` to what you deposited in the Agentic account.

**What the guard can and cannot do.** The guard is ordinary Python that
Claude runs before trading. It can't physically stop a direct
`place_equity_order` call, so the real protections are: the money in the
Agentic account is the most you can lose, and every order needs your
explicit "yes" (see `CLAUDE.md`). Read each order before approving it.

## Setup

1. In your local terminal, connect the Robinhood MCP (once):
   ```
   claude mcp add robinhood-trading --transport http https://agent.robinhood.com/mcp/trading
   ```
   Then in Claude Code run `/mcp`, choose `robinhood-trading` and sign in.
2. Clone this repo and run `claude` in it. Claude reads `CLAUDE.md`.
3. Edit `config.json`: set `budget_usd` to what is in the Agentic account.
4. Say "run the bot". In `dry_run` mode (the default) it only shows what it
   would do.
5. After a couple of weeks of dry runs that look sensible, change `mode`
   to `live` yourself. Claude will then ask before each order.

Run it at most once a day, ideally after the first hour of trading when
spreads have settled. A daily-close strategy gains nothing from more.

## Commands

```
python3 -m bot.cli plan snapshot.json   # propose and check orders, never trades
python3 -m bot.cli record ...           # log a placed order
python3 -m unittest                     # tests
```

Logs: `logs/plans.jsonl` (every plan), `logs/orders.jsonl` (every placed order).

## Judging it

After a few months, compare the account's return with simply holding SPY
over the same period. If it does not beat that after costs, stop.

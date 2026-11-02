# robinhood-bot

A small, deliberately boring trading experiment for the Robinhood Agentic
Trading account. It keeps a fixed mix of broad ETFs near its target
weights, with hard limits checked in code and a human approving every
order.

This is an experiment with money you can afford to lose, not an
investment plan. Most of your savings belong in plain index funds.

## Strategy

`config.json` sets the mix:

```json
"symbols": ["SPY", "QQQ", "SMH"],
"weights": {"SPY": 0.6, "QQQ": 0.2, "SMH": 0.2},
"trend_filter": []
```

- Each symbol targets its weight of `budget_usd` (minus a 5% cash reserve).
  Without `weights`, every symbol gets an equal slice.
- Symbols listed in `trend_filter` are held only while their last close is
  above the 200-day simple moving average, and sold in full below it.
  Without `trend_filter`, that applies to every symbol; `[]` turns it off.
- Trades only when a position is off target by more than 20% of its slice,
  so it does not churn.

**Why this mix.** A backtest over Feb 2015 to Oct 2026 (daily closes,
price return without dividends, 0.10% per trade, monthly rebalancing)
gave:

| Strategy | CAGR | Worst drop |
|---|---|---|
| SPY buy & hold | 11.9% | -34% |
| SPY 60 / QQQ 20 / SMH 20 | 16.7% | -32% |
| SPY/QQQ/VXUS, each with a 200-day SMA filter | 7.1% | -19% |
| Momentum screen of 51 ETFs, top 5 (see below) | 1.4% | -37% |

The mix's lead comes from tech and chip stocks, the winners of exactly
this period, so treat it as an upper bound, not a forecast. Chip stocks
fell about 45% in 2022. 40% of the mix is in tech and semiconductors,
which SPY already holds a lot of.

## Optional: a screened universe

Not used by default: in the backtest above it lost to SPY in every setting
tried. With a `universe` block in `config.json` instead of `symbols`, the
symbols are picked by a screen, not listed by hand:

```json
"universe": {"source": "screen", "top": 5, "keep_while_in_top": 10, "max_age_days": 35}
```

`python3 -m bot.cli screen candidates.json` ranks ETFs from a Robinhood
scan (liquid, above their 200-day SMA, moderate volatility) by 12-1
momentum: the 12-month return skipping the latest month. It drops
leveraged, inverse and volatility products, and skips any fund whose
daily returns correlate above 0.80 with one already picked. The best
`top` go into `universe.json`. A fund the account holds stays while it
ranks within `keep_while_in_top`, so funds near the cut-off are not
traded back and forth every month.

- Buys are allowed only for symbols in `universe.json`. Once it is older
  than `max_age_days`, buys are blocked until the screen runs again. Held
  funds are still managed and still exit below their SMA.
- A fund the bot bought that leaves the universe is sold in full on the
  next plan (`exits`). Holdings the bot never bought are left alone.
- Replace the block with `"symbols": [...]` to go back to a fixed list.

Momentum picks are often concentrated and volatile, and past winners can
reverse sharply. Rotating more than monthly mostly adds trading costs.

## Limits (enforced by `bot/guard.py`)

| Limit | Default |
|---|---|
| Total money put to work | `budget_usd` $500 (orders sized off the smaller of this and account value) |
| Largest single order | $150 |
| Orders per day | 3 |
| Order type | limit, at most 0.5% past the bid/ask; fractional shares as market orders (buys by dollars) only with `allow_fractional_market`, on weekdays 10:00-15:30 ET |
| Spread | no order while the quote spread is wider than 0.5% |
| Symbols | buys only in the current universe (or `symbols`); sells also for rotated-out funds the bot bought |
| Drawdown halt | no buys while account value is below 85% of `budget_usd` (sells still allowed) |
| Open orders | no new order for a symbol that already has one open |

Set `budget_usd` to what you deposited in the Agentic account.

**What the guard can and cannot do.** The guard is ordinary Python that
Claude runs before trading. It can't physically stop a direct
`place_equity_order` call, so the real protections are: the money in the
Agentic account is the most you can lose, and every order needs your
explicit "yes" (see `CLAUDE.md`). Read each order before approving it.

**Turn on trade approvals in the Robinhood app before going live.** Then
every order the bot submits also waits for your approval at the broker,
which no code or prompt can skip. In `live` mode the runbook checks this
setting and places nothing while it is off.

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
python3 -m bot.cli screen candidates.json  # pick the universe, never trades
python3 -m bot.cli universe             # show symbols and whether buys are blocked
python3 -m unittest                     # tests
```

Logs: `logs/plans.jsonl` (every plan), `logs/orders.jsonl` (every placed order),
`logs/screens.jsonl` (every screen).

## Judging it

After a few months, compare the account's return with simply holding SPY
over the same period. If it does not beat that after costs, stop.

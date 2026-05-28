# SOL Accumulation Grid Bot

A production-quality spot grid trading bot whose **primary objective is to
accumulate more SOL over time** while preserving a long-term SOL core
position. It is **not** optimized to maximize USDT profit — the headline
metric is `NET_SOL_ACCUMULATED = current_total_SOL − starting_total_SOL`.

Exchange integration is via [CCXT](https://github.com/ccxt/ccxt) against
**Hyperliquid** (spot). Paper trading is the default; real orders are placed
only when `LIVE_TRADING=true` is explicitly set.

> ⚠️ **Trading is risky. This software ships in paper mode and places no real
> orders unless you deliberately enable live trading. Use the testnet first.
> Nothing here is financial advice.**

---

## What the bot does

It maintains a price grid in a configured range (default 80–96 USDC, current
≈85). When price drifts **down**, it buys SOL with a limited slice of USDT;
when price drifts **up**, it sells *only grid-acquired* SOL — never the core.
Realized USDT profit can be recycled back into SOL (accumulation bias). The
bot trades only when the market is **ranging** and stands down during
trends, breakouts, high volatility, or thin liquidity.

### SOL accumulation philosophy

Capital is split into two conceptual buckets:

1. **Core SOL position** — long-term hold, *never traded*. Default 50% of your
   SOL is locked behind `CORE_SOL_MINIMUM`. The bot will refuse any sell that
   would dip below this floor.
2. **Active grid capital** — a bounded slice of USDT
   (`grid_capital_percentage`) plus the non-core SOL, used to harvest
   volatility and grow total SOL ownership.

The goal is to end each range cycle holding **more SOL than you started
with**, not more dollars.

### Why spot only, no leverage

Leverage introduces liquidation risk that is incompatible with "preserve
inventory first." Spot SOL cannot be liquidated out from under you. The bot
never uses leverage by default and never behaves like a martingale — every
buy is bounded by `MAX_USDT_DEPLOYMENT`, `MIN_FREE_USDT_RESERVE`, and the
grid order count.

### Why the core SOL must not be sold

The core is your long-term thesis position. The grid only ever risks the
*tradeable* portion. Even a string of sells in a rally cannot reduce your
holdings below `CORE_SOL_MINIMUM`.

---

## Risk explanation

The bot stops or skips trading when any of these trip
(see `config.yaml → risk`):

- `max_drawdown_percent`, `max_daily_loss_percent` — circuit breakers on value
- `max_usdt_deployment`, `max_position_sol` — hard exposure caps
- `min_free_usdt_reserve`, `min/core SOL reserve` — never spend the buffers
- `max_open_orders`, `max_order_retries` — bound order churn and error loops
- `api_stale_data_timeout_sec`, `max_spread_percent`, `price_gap_percent`
  — data integrity and abnormal-market guards
- `KILL_SWITCH_FILE` present — immediate halt
- startup reconciliation divergence (live) — halt until you `cancel-all`

Risk profile is selectable: `risk.profile: low | medium | high`.

---

## Project layout

```
sol-grid-bot/
  bot.py                  # CLI entry point
  config/config.example.yaml
  .env.example
  src/
    config.py exchange.py main.py cli.py
    strategy/  grid.py regime.py risk.py accumulation.py
    execution/ order_manager.py reconciliation.py paper_broker.py live_broker.py
    data/      market_data.py candles.py
    storage/   db.py models.py
    reporting/ metrics.py report.py
    alerts/    telegram.py logger.py
  tests/
```

---

## Setup

```bash
cd sol-grid-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python bot.py init        # creates config/config.yaml and .env from examples
```

Edit `config/config.yaml` (strategy) and `.env` (secrets + mode).

### Exchange API key guide (Hyperliquid)

Hyperliquid does **not** use a classic apiKey/secret. It uses your **wallet
address** plus an **API/agent wallet private key**:

1. Go to <https://app.hyperliquid.xyz/API> and create an **API wallet (agent)**.
2. Grant it **trading** permission only. **Do NOT enable transfers/withdrawals.**
3. Put the values in `.env`:
   ```
   HYPERLIQUID_WALLET_ADDRESS=0xYourMainAddress
   HYPERLIQUID_PRIVATE_KEY=0xYourAgentPrivateKey
   HYPERLIQUID_TESTNET=true
   ```
4. The bot never calls any withdrawal endpoint. Keep the agent key scoped to
   trading so a compromise cannot move funds out.

> Hyperliquid spot is quoted in **USDC** (`SOL/USDC:USDC`). "USDT" in the
> docs/metrics refers generically to the quote currency.

### Telegram alerts (optional)

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` to receive fill,
breakout, and circuit-breaker alerts. Leave blank to disable (no-op).

---

## Running

### Paper mode (default, safe)
Live market data, simulated fills, no real orders:
```bash
python bot.py paper
```

### Backtest mode
Replays historical OHLCV (`config.yaml → backtest.data_file`, a CSV with
`timestamp,open,high,low,close,volume`) and prints SOL-accumulation metrics:
```bash
python bot.py backtest
```
A sample ranging dataset is included at `data/sol_ohlcv.csv`.

### Live mode (real orders)
Disabled unless you opt in. Set `LIVE_TRADING=true` and `RUN_MODE=live` in
`.env`, then:
```bash
python bot.py live          # prompts you to type LIVE to confirm
```
On startup it reconciles local state against the exchange and refuses to
trade if they diverge.

### Other commands
```bash
python bot.py status          # snapshot of metrics, regime, risk
python bot.py report          # same as status
python bot.py cancel-all      # cancel all open orders
python bot.py emergency-stop  # create the kill switch file -> bot halts
python bot.py web             # launch the browser console (see below)
```

---

## Web console (control from a browser instead of the terminal)

Run the bot as a single hosted service with a password-protected dashboard:
the trading loop runs in a background thread inside the same process, and the
dashboard lets you view live state and trigger actions.

```bash
export CONSOLE_PASSWORD=choose-a-strong-password
python bot.py web                 # serves on http://0.0.0.0:8000
```

Sign in with `CONSOLE_PASSWORD` and you get:

- **Live metrics** — NET SOL accumulated, SOL/USDT balances, price, realized
  PnL, total value (auto-refreshes every 5s)
- **Regime + state** — current market regime and whether the loop is running,
  paused, skipping, or halted
- **Open orders** table and a **logs** tail
- **Action buttons** — Pause, Resume, Convert profit → SOL, Cancel all orders,
  **Emergency stop** (kill switch), Clear kill switch
- **Price chart** — candlesticks for a selectable token (5 by default) with a
  timeframe selector (5m/15m/1h/4h/1d). Entry (buy) and exit (sell) markers are
  overlaid from the bot's fills — these appear only when the selected token is
  the one the bot trades (`symbol`), since that is where fills exist. Configure
  the token list and timeframes under `console:` in `config.yaml`. A **Grid
  orders** toggle overlays the open buy/sell limit orders as dashed price lines
  (green = buy, red = sell) plus the active grid range, so you can see exactly
  where the grid is resting relative to price.
- **Grid position & orders** — a position summary (SOL held, avg cost,
  unrealized PnL, staged exits), a **Resting limit orders** table (status,
  side, price, distance from price, level) for orders still waiting to fill,
  and a **Filled trades** table of executed entries/exits with realized PnL.
  Timeframes include 3m/5m/15m/1h/4h/1d.

Actions are applied safely at cycle boundaries by the loop thread, so the
console never races the trader. API endpoints (`/api/status`, `/api/logs`,
`/api/action/<name>`) also accept `Authorization: Bearer <CONSOLE_PASSWORD>`.

> The console controls real trading in live mode — always set a strong
> `CONSOLE_PASSWORD` (and a fixed `CONSOLE_SECRET` in production). Without
> `CONSOLE_PASSWORD`, logins are refused.

### Deploy to Render

A `render.yaml` Blueprint is included (one **web** service, single worker, with
a 1 GB persistent disk at `/var/data` for SQLite state, logs, and the kill
switch so they survive restarts/deploys).

1. Push this repo to GitHub.
2. In Render: **New → Blueprint**, select the repo (it reads `render.yaml`).
3. Set the secret env vars in the dashboard (marked `sync: false`):
   `CONSOLE_PASSWORD`, `CONSOLE_SECRET`, and — only when going live —
   `HYPERLIQUID_WALLET_ADDRESS` / `HYPERLIQUID_PRIVATE_KEY`.
4. Deploy, open the service URL, and sign in.

Defaults are **paper mode** (`RUN_MODE=paper`, `LIVE_TRADING=false`). To go
live, flip both in the Render env and redeploy. Use a paid plan — free
instances sleep, which would stop the trader. The server runs with **exactly
one worker** by design: more workers would spawn multiple trading loops.
Render injects `PORT` and the console binds it automatically.

---

## Configuration reference

All strategy parameters live in `config/config.yaml`. Key groups:

- **top level** — `symbol`, `starting_sol`, `starting_usdt`,
  `core_sol_fraction`, `core_sol_minimum`, `grid_capital_percentage`
- **grid** — `lower_price`, `upper_price`, `count`, `spacing_mode`
  (`arithmetic|geometric|atr`), `dynamic`, range recalc settings
- **order** — `size_mode` (`fixed_usdt|fixed_sol|portfolio_percent`),
  sizes, `min_order_size_usdt`, `max_active_orders`
- **accumulation** — `accumulation_mode`, `profit_conversion_mode`
  (`none|partial_to_SOL|full_to_SOL`), `profit_conversion_percent`,
  `reduce_sells_in_uptrend`
- **regime** — EMA/ATR/ADX periods, thresholds, candle timeframe
- **breakout** — `upward_breakout_action` (`pause|shift_grid_up|reduce_sells`),
  `downward_breakdown_action` (`pause|reduce_buys|emergency_stop`)
- **risk** — see *Risk explanation*; `profile` selects a preset
- **engine** — poll/rebalance intervals, startup reconciliation
- **backtest** — `data_file`, `fee_rate`

---

## Docker deployment

```bash
cp .env.example .env && cp config/config.example.yaml config/config.yaml
# edit both files
docker compose up -d --build        # runs paper mode by default
docker compose logs -f
```
State (SQLite) and logs persist on mounted volumes. To go live, set
`LIVE_TRADING=true` in `.env` and change the compose `command` to `["live"]`
(note: `live` mode prompts for confirmation, so for unattended Docker use,
run it interactively first or wrap your own confirmation).

---

## Emergency stop

Create the kill switch file (the bot halts on its next cycle):
```bash
python bot.py emergency-stop        # or: touch KILL_SWITCH
```
Cancel everything and stop:
```bash
python bot.py cancel-all
python bot.py emergency-stop
```
Delete the `KILL_SWITCH` file to allow trading to resume.

---

## Metrics explanation

`python bot.py status` shows:

- **starting / current SOL** and **NET SOL ACCUMULATED** (the goal metric)
- **starting / current USDT**, grid SOL inventory and its average cost
- **realized PnL** (closed grid round-trips) and **unrealized PnL**
- **total value** in both USDT and SOL terms
- open orders, active grid range, current regime, risk status, last error,
  uptime

All state is persisted in SQLite (`data/bot_state.sqlite3`): config snapshot,
balances, orders, fills, regime history, and an audit log — so the bot is
restart-safe.

---

## Warnings

- Start in **paper** mode, then **testnet live**, before risking real funds.
- Grid bots **lose** in sustained trends. The regime filter reduces but does
  not eliminate this — that is exactly why the core SOL is never touched.
- Past backtest performance does not predict future results.
- Keep your agent key trade-scoped (no withdrawal) and never commit `.env`.

---

## Development

```bash
pip install pytest
python -m pytest -q
```

# Trading Scripts

Execution scripts for running strategies in backtest or live mode.

## Live Trading

Execute a strategy in real-time:

```bash
# Paper trading (recommended to start)
python live_trade.py \
  --strategy ../strategies/my_strategy.py \
  --dry-run \
  --poll-interval 60

# Live trading (requires API key)
python live_trade.py \
  --strategy ../strategies/my_strategy.py \
  --api-key $POLYMARKET_API_KEY \
  --poll-interval 60
```

**Options:**
- `--strategy`: Path to strategy Python file
- `--dry-run`: Paper trading mode (no real money)
- `--api-key`: Polymarket API key (for live trades)
- `--config`: YAML config file (optional)
- `--poll-interval`: Seconds between market scans (default: 60)
- `--clickhouse-host`: ClickHouse server for historical data

**Output:**
```
🚀 Starting live trading engine...
   Strategy: Replicated_0xABC123_Strategy
   Mode: DRY RUN (paper trading)
   Poll interval: 60s

ITERATION 1 - 2024-03-13 14:30:00
Fetching markets...
Found 127 active markets
Strategy filtered to 23 markets
Generated 2 trading signals

📝 PAPER TRADE: BUY 156.25 shares @ $0.641
   Market: Will Trump win the 2024 election?
   Outcome: Yes
   Size: $100.00
   Reason: Value bet: edge 7.8%, price 0.64
   Paper balance: $9,900.00

📊 CURRENT STATUS
   Open positions: 1
   Total trades: 1
   Paper balance: $9,900.00

💤 Sleeping for 60 seconds...
```

## Backtesting

*(Coming soon)*

Test strategy on historical data:

```bash
python backtest.py \
  --strategy ../strategies/my_strategy.py \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --capital 10000
```

## Configuration

Create `config.yaml` to customize strategy parameters:

```yaml
# Risk management
capital: 10000
max_position: 250
max_portfolio_pct: 0.1

# Strategy parameters
min_edge: 0.05
min_liquidity: 1000

# Execution
poll_interval: 60
max_open_positions: 10
```

Use with:
```bash
python live_trade.py --strategy my_strategy.py --config config.yaml --dry-run
```

## Safety

**Always start with paper trading:**
1. Test strategy with `--dry-run` first
2. Monitor for at least 1 week
3. Verify P&L matches expectations
4. Start live with small capital
5. Scale up gradually

**Never:**
- Trade with money you can't afford to lose
- Ignore risk limits
- Run untested strategies live
- Trade while intoxicated/emotional
- Trust backtest results blindly

## Troubleshooting

**Markets not loading:**
```
Failed to fetch markets: 500
```
→ Polymarket API may be down. Wait and retry.

**Strategy not found:**
```
No BaseStrategy subclass found in my_strategy.py
```
→ Ensure your strategy inherits from `BaseStrategy`

**ClickHouse connection failed:**
```
ClickHouse unavailable, using API only
```
→ Normal if ClickHouse not running. Script will use API fallback.

**Live trading not working:**
```
⚠️  Live trading not yet implemented!
```
→ Currently only paper trading is supported. Live execution coming soon.

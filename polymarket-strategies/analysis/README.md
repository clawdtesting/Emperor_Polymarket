# Wallet Analysis & Strategy Replication

Reverse-engineer successful trading strategies from any Polymarket wallet.

## Quick Start

### 1. Analyze a Wallet

```bash
python wallet_analyzer.py --wallet 0xYOUR_WALLET_ADDRESS --days 90
```

Output:
```
📊 ACTIVITY
  Total trades: 127
  Total volume: $12,450.00
  Unique markets: 45
  Days active: 62/90

💰 PERFORMANCE
  Total P&L: $3,245.67
  Win rate: 64.2%
  Avg win: $85.32
  Avg loss: -$42.18
  Sharpe ratio: 1.87

📈 STRATEGY
  Type: value
  Frequency: swing_trader
  Avg hold time: 72.5 hours
  Entry timing: early
  Contrarian score: 0.73

💵 POSITION SIZING
  Strategy: proportional
  Avg size: $98.03
  Max size: $250.00
  Kelly fraction: 0.18
```

Save detailed report:
```bash
python wallet_analyzer.py --wallet 0x... --output analysis.json
```

### 2. Replicate the Strategy

Generate executable Python code that mimics the wallet's approach:

```bash
python strategy_replicator.py --wallet 0x... --output strategies/my_strategy.py
```

Or use existing analysis:
```bash
python strategy_replicator.py --profile analysis.json --output strategies/my_strategy.py
```

This creates a ready-to-use strategy class:

```python
from strategies.my_strategy import Replicated_0xABC123_Strategy

strategy = Replicated_0xABC123_Strategy(config={
    'min_edge': 0.05,
    'capital': 10000,
})

# Use in backtest or live trading
```

### 3. Backtest the Replicated Strategy

```bash
cd .. && python scripts/backtest.py \
  --strategy strategies/my_strategy.py \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --capital 10000
```

### 4. Paper Trade (Dry Run)

```bash
python scripts/live_trade.py \
  --strategy strategies/my_strategy.py \
  --dry-run
```

## What Gets Analyzed

### Activity Metrics
- Total trades & volume
- Unique markets traded
- Days active
- Trade frequency classification

### Performance
- Realized & unrealized P&L
- Win rate & average win/loss
- Sharpe ratio
- Maximum drawdown

### Strategy Detection
- **Type classification:**
  - Value betting (contrarian, mispriced markets)
  - Momentum (trend following)
  - Arbitrage (quick inefficiency exploitation)
  - Market making (liquidity provision)
  - Mixed

- **Frequency classification:**
  - Scalper (>10 trades/day)
  - Day trader (2-10 trades/day)
  - Swing trader (0.5-2 trades/day)
  - Position trader (<0.5 trades/day)

### Position Sizing
- Average & max position size
- **Strategy detection:**
  - Fixed (consistent sizing)
  - Kelly criterion (variable based on edge)
  - Proportional (scales with confidence)
- Estimated Kelly fraction

### Market Selection
- Preferred categories
- Liquidity requirements
- Entry timing (early/mid/late in market lifecycle)
- Time to expiry patterns

### Edge Characteristics
- Entry timing relative to market lifecycle
- Contrarian score (0-1, how often trades against majority)
- News reaction speed (if detectable)

### Risk Profile
- Maximum drawdown
- Diversification score
- Kelly fraction (risk tolerance)

## Examples

### Example 1: Value Investor

```bash
$ python wallet_analyzer.py --wallet 0xValueInvestor...

Strategy Type: value
- Contrarian score: 0.82 (very contrarian)
- Entry timing: early (avg 45 days to expiry)
- Categories: politics, sports
- Win rate: 68%
- Avg hold: 120 hours (5 days)
```

**Interpretation:**
- Buys undervalued outcomes early
- Contrarian approach (bets against crowd)
- Patient holder (5 day avg)
- High win rate suggests good probability modeling

**Replication approach:**
- Build probability model for early prediction
- Filter for low-priced outcomes (<0.3)
- Target markets with long time horizons

### Example 2: Momentum Trader

```bash
$ python wallet_analyzer.py --wallet 0xMomentum...

Strategy Type: momentum
- Contrarian score: 0.21 (follows trends)
- Entry timing: mid (avg 14 days to expiry)
- Frequency: day_trader (3.2 trades/day)
- Avg hold: 18 hours
```

**Interpretation:**
- Rides existing trends
- Quick entry/exit (18 hours)
- High frequency
- Follows market momentum

**Replication approach:**
- Track price velocity (recent changes)
- Enter when momentum is strong (price > 0.6 or < 0.4)
- Quick exits (hours not days)

### Example 3: Market Maker

```bash
$ python wallet_analyzer.py --wallet 0xMarketMaker...

Strategy Type: market_maker
- Avg hold: 4 hours (very short)
- Position sizing: fixed
- Diversification: 0.92 (highly diversified)
- Frequency: scalper (15 trades/day)
```

**Interpretation:**
- Provides liquidity on both sides
- Very short holds (hours)
- Many small positions
- Profits from spread

**Replication approach:**
- Place limit orders on bid/ask
- Small fixed position sizes
- Many markets simultaneously
- Close positions quickly

## Limitations

**Data availability:**
- Analysis relies on on-chain data (The Graph)
- Off-chain signals (news, social media) not captured
- Some wallets have private transactions

**Strategy complexity:**
- Simple heuristics for classification
- Cannot capture complex multi-factor models
- Assumes stable strategy over analysis period

**Position matching:**
- Uses simplified FIFO matching
- May not reflect actual close decisions
- Partial fills not always accurate

**Probability models:**
- Replicated strategy uses placeholder probability estimation
- You must implement your own edge calculation
- Cannot reverse-engineer the original model

## Advanced Usage

### Custom Analysis Period

```bash
# Last 30 days only
python wallet_analyzer.py --wallet 0x... --days 30

# Full year
python wallet_analyzer.py --wallet 0x... --days 365
```

### ClickHouse Integration

If you have historical data in ClickHouse:

```bash
python wallet_analyzer.py \
  --wallet 0x... \
  --clickhouse-host your-clickhouse-server.com \
  --days 180
```

### Batch Analysis

Analyze multiple wallets:

```bash
# Create wallet list
cat > wallets.txt <<EOF
0xWallet1...
0xWallet2...
0xWallet3...
EOF

# Analyze all
for wallet in $(cat wallets.txt); do
  python wallet_analyzer.py --wallet $wallet --output "analysis_${wallet:0:10}.json"
done
```

### Compare Strategies

```python
import json

# Load multiple analyses
profiles = []
for path in ['analysis1.json', 'analysis2.json']:
    with open(path) as f:
        profiles.append(json.load(f))

# Compare win rates
for p in sorted(profiles, key=lambda x: x['win_rate'], reverse=True):
    print(f"{p['wallet_address'][:10]}: {p['win_rate']:.1%} win rate")
```

## Output Format

**JSON structure:**

```json
{
  "wallet_address": "0x...",
  "analysis_period_days": 90,
  "total_trades": 127,
  "total_volume": 12450.00,
  "win_rate": 0.642,
  "strategy_type": "value",
  "position_sizing_strategy": "proportional",
  "top_categories": [
    ["politics", 45],
    ["sports", 32],
    ["crypto", 18]
  ],
  "avg_hold_time_hours": 72.5,
  ...
}
```

See `wallet_analyzer.py` for complete `WalletProfile` schema.

## Next Steps

1. **Analyze successful wallets** - Find profitable traders to study
2. **Replicate their strategies** - Generate executable code
3. **Backtest** - Validate performance on historical data
4. **Refine** - Improve probability models, risk management
5. **Paper trade** - Test live with fake money
6. **Deploy** - Run with real capital (start small!)

## Contributing

Improvements welcome:
- Better strategy classification heuristics
- More sophisticated position matching
- Integration with news APIs for timing analysis
- Machine learning for pattern detection

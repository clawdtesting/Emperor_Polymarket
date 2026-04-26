# Polymarket Strategies

Automated prediction market strategy execution framework for Polymarket.

## Quick Start: Copy a Successful Trader

```bash
# 1. Analyze a successful wallet
python analysis/wallet_analyzer.py --wallet 0xSUCCESSFUL_WALLET --days 90

# 2. Generate executable strategy code
python analysis/strategy_replicator.py --wallet 0xSUCCESSFUL_WALLET --output strategies/my_strategy.py

# 3. Paper trade the strategy
python scripts/live_trade.py --strategy strategies/my_strategy.py --dry-run

# 4. Deploy live (when confident)
python scripts/live_trade.py --strategy strategies/my_strategy.py --api-key $YOUR_KEY
```

See [`analysis/README.md`](analysis/README.md) for detailed workflow.

## Overview

This repository provides infrastructure for:
- **Wallet Analysis**: Reverse-engineer strategies from successful traders
- **Strategy Replication**: Auto-generate executable code from wallet patterns
- **Data Pipeline**: Real-time ClickHouse ingestion (HTTP + WebSocket)
- **Strategy Development**: Modular strategy framework
- **Live Trading**: Real-time execution with paper trading mode
- **Backtesting**: Historical performance analysis *(coming soon)*

## Architecture

```
polymarket-strategies/
├── analysis/                    # Wallet analysis & replication
│   ├── wallet_analyzer.py      # Reverse-engineer trading patterns (22KB)
│   ├── strategy_replicator.py  # Generate strategy code (13KB)
│   └── README.md               # Analysis workflow guide
├── ingestion/                   # ClickHouse data pipeline
│   ├── clickhouse_schema.sql   # Complete schema (9.5KB)
│   ├── ingest.py               # Hybrid ingestion (polling + streaming)
│   └── README.md               # Setup & query examples
├── research/
│   └── polymarket-data-sources.md  # API documentation (10.6KB)
├── strategies/                  # Strategy implementations
│   ├── base.py                 # Base strategy class
│   └── (replicated strategies) # Auto-generated from wallet analysis
├── scripts/                     # Execution
│   ├── live_trade.py           # Live/paper trading engine (15KB)
│   └── README.md               # Usage guide
└── README.md                    # This file
```

## Common Polymarket Strategies

### 1. Value Betting
Identify markets where odds don't reflect true probabilities. Buy underpriced outcomes.

**Indicators:**
- News sentiment vs market price
- Model predictions vs odds
- Time decay inefficiencies

### 2. Arbitrage
Exploit price differences across correlated markets or platforms.

**Opportunities:**
- Binary markets with overlapping outcomes
- Cross-platform price discrepancies
- Related events (e.g., presidential primary outcomes)

### 3. Market Making
Provide liquidity by placing buy/sell orders with spreads.

**Profit sources:**
- Bid-ask spread capture
- Volatility harvesting
- Fee rebates (if available)

### 4. Momentum/Mean Reversion
Trade based on price patterns and market psychology.

**Signals:**
- Sharp price movements (fade or follow)
- Volume spikes
- Social sentiment shifts

### 5. Event-Driven
React to news/events faster than the market.

**Edge:**
- Automated news monitoring
- Fast execution
- Pre-positioned for scheduled events

## Installation

```bash
# Clone repository
git clone https://github.com/unju-ai/polymarket-strategies.git
cd polymarket-strategies

# Install dependencies
pip install -r requirements.txt

# Configure credentials
cp config/example.env config/.env
# Edit config/.env with your Polymarket API keys
```

## Usage

### Backtesting

```python
from strategies.value import ValueStrategy
from backtest.engine import BacktestEngine

strategy = ValueStrategy(config={
    'min_edge': 0.05,  # Minimum 5% edge to trade
    'max_position': 100,  # Max $100 per position
})

engine = BacktestEngine(
    strategy=strategy,
    start_date='2024-01-01',
    end_date='2024-12-31',
    initial_capital=10000
)

results = engine.run()
print(f"Total return: {results.total_return:.2%}")
print(f"Sharpe ratio: {results.sharpe_ratio:.2f}")
print(f"Win rate: {results.win_rate:.2%}")
```

### Live Trading

```python
from strategies.value import ValueStrategy
from core.executor import LiveExecutor

strategy = ValueStrategy(config={
    'min_edge': 0.05,
    'max_position': 100,
})

executor = LiveExecutor(
    strategy=strategy,
    dry_run=True,  # Set False for real trades
)

executor.run()  # Runs continuously
```

## Strategy Development

Create a new strategy by extending `BaseStrategy`:

```python
from strategies.base import BaseStrategy

class MyStrategy(BaseStrategy):
    def analyze_market(self, market):
        """Analyze a market and return signal."""
        # Your analysis logic
        edge = self.calculate_edge(market)
        
        if edge > self.config['min_edge']:
            return {
                'action': 'buy',
                'outcome': 'Yes',
                'size': self.calculate_position_size(edge),
                'confidence': edge
            }
        
        return None
    
    def calculate_edge(self, market):
        """Calculate edge (true probability - market price)."""
        # Your edge calculation
        pass
```

## Risk Management

Built-in risk controls:
- **Position limits**: Max $ per market, max % of portfolio
- **Diversification**: Max correlated positions
- **Stop losses**: Automatic exit on adverse moves
- **Drawdown limits**: Pause trading if losses exceed threshold

## Configuration

`config/strategies.yaml`:

```yaml
value_strategy:
  min_edge: 0.05          # Minimum 5% edge
  max_position: 100       # Max $100 per position
  max_portfolio_pct: 0.1  # Max 10% of portfolio per position
  markets:
    - category: politics
      min_liquidity: 1000
    - category: sports
      min_liquidity: 5000

risk_management:
  max_drawdown: 0.2       # Stop if down 20%
  max_correlated_exposure: 0.3  # Max 30% in correlated positions
  daily_loss_limit: 500   # Max $500 loss per day
```

## Data Sources

- **Polymarket API**: Real-time prices, volume, market metadata
- **Historical data**: Past prices for backtesting
- **News APIs**: Event monitoring (optional)
- **Social sentiment**: Twitter/Reddit analysis (optional)

## Performance Tracking

The framework tracks:
- Total P&L
- Win rate
- Average edge realized
- Sharpe ratio
- Maximum drawdown
- Per-strategy performance

Dashboard available at `http://localhost:8000` when running live.

## Security

**CRITICAL:**
- Never commit API keys to git
- Use environment variables or encrypted config
- Start with small positions
- Test strategies thoroughly in backtest before live trading
- Use `dry_run=True` for paper trading

## Wallet Strategy Analysis

To analyze a specific Polymarket wallet's strategy:

```python
from core.wallet_analyzer import WalletAnalyzer

analyzer = WalletAnalyzer(wallet_address='0x...')
profile = analyzer.get_trading_profile()

print(f"Strategy type: {profile.strategy_type}")
print(f"Avg hold time: {profile.avg_hold_time}")
print(f"Win rate: {profile.win_rate:.2%}")
print(f"Preferred markets: {profile.top_categories}")
```

## Contributing

Contributions welcome! Areas of interest:
- New strategy implementations
- Improved risk models
- Better backtesting metrics
- Integration with other prediction markets (Kalshi, Manifold, etc.)

## License

MIT

## Disclaimer

**Trading involves substantial risk of loss.**

This framework is for educational purposes. Use at your own risk. Past performance does not guarantee future results. The authors are not responsible for any financial losses.

Always start with small positions and thoroughly backtest strategies before deploying real capital.

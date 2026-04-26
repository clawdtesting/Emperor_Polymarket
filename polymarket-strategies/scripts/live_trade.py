#!/usr/bin/env python3
"""
Live Strategy Execution for Polymarket

Runs a strategy in real-time, generating and executing trades.

Usage:
    # Paper trading (no real money)
    python live_trade.py --strategy strategies/my_strategy.py --dry-run
    
    # Live trading (requires API key)
    python live_trade.py --strategy strategies/my_strategy.py --api-key $POLY_KEY
    
    # With custom config
    python live_trade.py --strategy strategies/my_strategy.py --config config.yaml
"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List
import logging

import aiohttp
from clickhouse_driver import Client

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.base import BaseStrategy, Market, TradingSignal

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


class PolymarketExecutor:
    """
    Execute trades on Polymarket.
    
    In dry-run mode, simulates trades without actually placing them.
    In live mode, uses Polymarket API to place real orders.
    """
    
    def __init__(self, api_key: str = None, dry_run: bool = True):
        self.api_key = api_key
        self.dry_run = dry_run
        self.base_url = "https://clob.polymarket.com"
        
        self.paper_positions = []  # Track paper trading positions
        self.paper_balance = 10000.0  # Starting paper balance
        
    async def place_order(self, signal: TradingSignal, market: Market) -> Dict:
        """
        Place an order based on trading signal.
        
        Args:
            signal: Trading signal from strategy
            market: Market data
            
        Returns:
            Order confirmation dict
        """
        
        if self.dry_run:
            return self._simulate_order(signal, market)
        else:
            return await self._execute_order(signal, market)
    
    def _simulate_order(self, signal: TradingSignal, market: Market) -> Dict:
        """Simulate order for paper trading."""
        
        # Calculate execution price (assume we get filled at current price + slippage)
        slippage = 0.001  # 0.1% slippage
        
        if signal.action == 'buy':
            if signal.outcome == 'Yes':
                price = market.yes_price * (1 + slippage)
            else:
                price = market.no_price * (1 + slippage)
        else:
            if signal.outcome == 'Yes':
                price = market.yes_price * (1 - slippage)
            else:
                price = market.no_price * (1 - slippage)
        
        # Calculate shares
        shares = signal.size / price
        
        # Update paper balance
        if signal.action == 'buy':
            self.paper_balance -= signal.size
        
        # Track position
        position = {
            'market_id': signal.market_id,
            'market_question': market.question,
            'outcome': signal.outcome,
            'side': signal.action,
            'shares': shares,
            'entry_price': price,
            'size': signal.size,
            'timestamp': datetime.now().isoformat(),
            'reason': signal.reason,
        }
        
        self.paper_positions.append(position)
        
        logger.info(f"📝 PAPER TRADE: {signal.action.upper()} {shares:.2f} shares @ ${price:.3f}")
        logger.info(f"   Market: {market.question[:60]}...")
        logger.info(f"   Outcome: {signal.outcome}")
        logger.info(f"   Size: ${signal.size:.2f}")
        logger.info(f"   Reason: {signal.reason}")
        logger.info(f"   Paper balance: ${self.paper_balance:.2f}")
        
        return {
            'order_id': f"paper_{len(self.paper_positions)}",
            'status': 'filled',
            'filled_price': price,
            'filled_shares': shares,
        }
    
    async def _execute_order(self, signal: TradingSignal, market: Market) -> Dict:
        """Execute real order via Polymarket API."""
        
        if not self.api_key:
            raise ValueError("API key required for live trading")
        
        # TODO: Implement actual Polymarket order placement
        # This requires:
        # 1. Authentication (sign with private key)
        # 2. Order creation (construct order payload)
        # 3. Order submission (POST to CLOB API)
        # 4. Order monitoring (check fill status)
        
        logger.warning("⚠️  Live trading not yet implemented!")
        logger.warning("   Use --dry-run for paper trading")
        
        return {
            'order_id': None,
            'status': 'not_implemented',
        }


class LiveTradingEngine:
    """Main execution engine for live strategy trading."""
    
    def __init__(
        self,
        strategy: BaseStrategy,
        executor: PolymarketExecutor,
        clickhouse_host: str = 'localhost',
        poll_interval: int = 60,
    ):
        self.strategy = strategy
        self.executor = executor
        self.poll_interval = poll_interval
        
        # Try to connect to ClickHouse (optional)
        try:
            self.ch_client = Client(host=clickhouse_host)
            self.use_clickhouse = True
            logger.info(f"✅ Connected to ClickHouse at {clickhouse_host}")
        except Exception as e:
            self.ch_client = None
            self.use_clickhouse = False
            logger.warning(f"⚠️  ClickHouse unavailable, using API only: {e}")
        
        self.running = False
        
    async def fetch_markets(self) -> List[Market]:
        """Fetch current markets from Polymarket API."""
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://gamma-api.polymarket.com/markets",
                params={'active': 'true', 'limit': 100}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    markets = []
                    for m in data:
                        try:
                            market = Market(
                                id=m['id'],
                                question=m['question'],
                                category=m.get('category', 'unknown'),
                                end_date=datetime.fromisoformat(m['end_date'].replace('Z', '+00:00')),
                                yes_price=float(m.get('yes_price', 0.5)),
                                no_price=float(m.get('no_price', 0.5)),
                                volume_24h=float(m.get('volume_24h', 0)),
                                liquidity=float(m.get('liquidity', 0)),
                                created_at=datetime.fromisoformat(m['created_at'].replace('Z', '+00:00')),
                                metadata=m,
                            )
                            markets.append(market)
                        except Exception as e:
                            logger.debug(f"Skipping market {m.get('id')}: {e}")
                            continue
                    
                    return markets
                else:
                    logger.error(f"Failed to fetch markets: {resp.status}")
                    return []
    
    async def trading_loop(self):
        """Main trading loop - runs continuously."""
        
        logger.info("🚀 Starting live trading engine...")
        logger.info(f"   Strategy: {self.strategy.__class__.__name__}")
        logger.info(f"   Mode: {'DRY RUN (paper trading)' if self.executor.dry_run else 'LIVE TRADING'}")
        logger.info(f"   Poll interval: {self.poll_interval}s")
        
        self.running = True
        iteration = 0
        
        while self.running:
            iteration += 1
            logger.info(f"\n{'='*60}")
            logger.info(f"ITERATION {iteration} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"{'='*60}")
            
            try:
                # Fetch markets
                logger.info("Fetching markets...")
                markets = await self.fetch_markets()
                logger.info(f"Found {len(markets)} active markets")
                
                # Filter markets
                filtered = self.strategy.filter_markets(markets)
                logger.info(f"Strategy filtered to {len(filtered)} markets")
                
                # Analyze each market
                signals = []
                for market in filtered:
                    signal = self.strategy.analyze_market(market)
                    if signal:
                        signals.append((signal, market))
                
                logger.info(f"Generated {len(signals)} trading signals")
                
                # Execute trades
                for signal, market in signals:
                    try:
                        result = await self.executor.place_order(signal, market)
                        
                        if result['status'] == 'filled':
                            # Update strategy with new position
                            from strategies.base import Position
                            
                            position = Position(
                                market_id=signal.market_id,
                                outcome=signal.outcome,
                                size=signal.size,
                                entry_price=result['filled_price'],
                                current_price=result['filled_price'],
                                unrealized_pnl=0.0,
                                opened_at=datetime.now(),
                            )
                            
                            self.strategy.on_position_opened(position)
                        
                    except Exception as e:
                        logger.error(f"Failed to execute trade: {e}")
                
                # Print summary
                self._print_summary()
                
                # Sleep until next iteration
                logger.info(f"\n💤 Sleeping for {self.poll_interval} seconds...")
                await asyncio.sleep(self.poll_interval)
                
            except KeyboardInterrupt:
                logger.info("\n⛔ Keyboard interrupt received")
                self.running = False
                break
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                await asyncio.sleep(10)
        
        logger.info("\n🛑 Trading engine stopped")
        self._print_final_summary()
    
    def _print_summary(self):
        """Print current status summary."""
        
        metrics = self.strategy.get_metrics()
        
        logger.info(f"\n📊 CURRENT STATUS")
        logger.info(f"   Open positions: {metrics['open_positions']}")
        logger.info(f"   Total trades: {metrics['total_trades']}")
        
        if metrics['total_trades'] > 0:
            logger.info(f"   Win rate: {metrics['win_rate']:.1%}")
            logger.info(f"   Avg P&L: ${metrics['avg_pnl']:.2f}")
            logger.info(f"   Total P&L: ${metrics['total_pnl']:.2f}")
        
        if self.executor.dry_run:
            logger.info(f"   Paper balance: ${self.executor.paper_balance:.2f}")
    
    def _print_final_summary(self):
        """Print final performance summary."""
        
        logger.info(f"\n{'='*60}")
        logger.info("FINAL SUMMARY")
        logger.info(f"{'='*60}")
        
        metrics = self.strategy.get_metrics()
        
        logger.info(f"Total trades: {metrics['total_trades']}")
        
        if metrics['total_trades'] > 0:
            logger.info(f"Win rate: {metrics['win_rate']:.1%}")
            logger.info(f"Total P&L: ${metrics['total_pnl']:.2f}")
            logger.info(f"Avg P&L per trade: ${metrics['avg_pnl']:.2f}")
        
        if self.executor.dry_run:
            initial_balance = 10000.0
            final_balance = self.executor.paper_balance + metrics['total_pnl']
            pnl_pct = (final_balance - initial_balance) / initial_balance
            
            logger.info(f"\nPaper Trading Results:")
            logger.info(f"  Starting balance: ${initial_balance:.2f}")
            logger.info(f"  Ending balance: ${final_balance:.2f}")
            logger.info(f"  Total return: {pnl_pct:.2%}")


def load_strategy_from_file(filepath: str, config: Dict) -> BaseStrategy:
    """Dynamically load strategy class from Python file."""
    
    # Load module
    spec = importlib.util.spec_from_file_location("custom_strategy", filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    # Find strategy class (subclass of BaseStrategy)
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, type) and issubclass(obj, BaseStrategy) and obj != BaseStrategy:
            logger.info(f"✅ Loaded strategy: {name}")
            return obj(config)
    
    raise ValueError(f"No BaseStrategy subclass found in {filepath}")


async def main():
    import argparse
    import yaml
    
    parser = argparse.ArgumentParser(description='Live Polymarket strategy execution')
    parser.add_argument('--strategy', required=True, help='Path to strategy .py file')
    parser.add_argument('--config', help='Path to config YAML file')
    parser.add_argument('--dry-run', action='store_true', help='Paper trading mode (no real orders)')
    parser.add_argument('--api-key', help='Polymarket API key (for live trading)')
    parser.add_argument('--poll-interval', type=int, default=60, help='Seconds between iterations')
    parser.add_argument('--clickhouse-host', default='localhost', help='ClickHouse host')
    
    args = parser.parse_args()
    
    # Load config
    if args.config:
        with open(args.config) as f:
            config = yaml.safe_load(f)
    else:
        # Default config
        config = {
            'min_edge': 0.05,
            'max_position': 100,
            'capital': 10000,
        }
    
    # Load strategy
    strategy = load_strategy_from_file(args.strategy, config)
    
    # Create executor
    executor = PolymarketExecutor(
        api_key=args.api_key,
        dry_run=args.dry_run or not args.api_key
    )
    
    # Create engine
    engine = LiveTradingEngine(
        strategy=strategy,
        executor=executor,
        clickhouse_host=args.clickhouse_host,
        poll_interval=args.poll_interval,
    )
    
    # Run
    await engine.trading_loop()


if __name__ == '__main__':
    asyncio.run(main())

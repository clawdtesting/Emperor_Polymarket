#!/usr/bin/env python3
"""
Polymarket Wallet Strategy Analyzer

Reverse-engineer trading patterns from any Polymarket wallet address.
Analyzes trades, positions, and market selection to identify strategy type.

Usage:
    python wallet_analyzer.py --wallet 0x... --days 90
    python wallet_analyzer.py --wallet 0x... --output report.json
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from collections import Counter, defaultdict

import aiohttp
from clickhouse_driver import Client


@dataclass
class WalletProfile:
    """Trading profile extracted from wallet history."""
    
    wallet_address: str
    analysis_period_days: int
    
    # Activity metrics
    total_trades: int
    total_volume: float
    unique_markets: int
    days_active: int
    
    # Performance
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    win_rate: float
    avg_win: float
    avg_loss: float
    sharpe_ratio: Optional[float]
    
    # Position sizing
    avg_position_size: float
    max_position_size: float
    position_sizing_strategy: str  # 'fixed', 'kelly', 'proportional'
    
    # Market selection
    top_categories: List[tuple]  # [(category, count), ...]
    avg_market_liquidity: float
    avg_time_to_expiry: float  # Days from trade to market end
    
    # Trading patterns
    strategy_type: str  # 'value', 'momentum', 'arbitrage', 'market_maker', 'mixed'
    avg_hold_time_hours: float
    trade_frequency: str  # 'scalper', 'day_trader', 'swing_trader', 'position_trader'
    
    # Edge characteristics
    entry_timing: str  # 'early', 'mid', 'late'
    contrarian_score: float  # 0-1, how often trades against majority
    news_reaction_speed: Optional[float]  # Minutes from news to trade
    
    # Risk profile
    max_drawdown: float
    kelly_fraction: Optional[float]
    diversification_score: float  # 0-1, based on position correlation


class PolymarketSubgraph:
    """GraphQL client for Polymarket subgraph (The Graph)."""
    
    SUBGRAPH_URL = "https://api.thegraph.com/subgraphs/name/polymarket/matic-markets"
    
    async def get_user_trades(self, wallet: str, since_days: int = 90) -> List[Dict]:
        """Fetch all trades for a wallet."""
        since_timestamp = int((datetime.now() - timedelta(days=since_days)).timestamp())
        
        query = """
        query UserTrades($user: String!, $timestamp: Int!) {
          trades(
            where: {user: $user, timestamp_gte: $timestamp}
            orderBy: timestamp
            orderDirection: desc
            first: 1000
          ) {
            id
            market {
              id
              question
              category
              endDate
              liquidity
            }
            outcome
            side
            price
            shares
            timestamp
            transactionHash
          }
        }
        """
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.SUBGRAPH_URL,
                json={
                    'query': query,
                    'variables': {
                        'user': wallet.lower(),
                        'timestamp': since_timestamp
                    }
                }
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('data', {}).get('trades', [])
                return []
    
    async def get_user_positions(self, wallet: str) -> List[Dict]:
        """Fetch current positions for a wallet."""
        query = """
        query UserPositions($user: String!) {
          positions(
            where: {user: $user, shares_gt: 0}
            first: 1000
          ) {
            id
            market {
              id
              question
              category
              currentPrice
            }
            outcome
            shares
            avgEntryPrice
            realizedPnL
          }
        }
        """
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.SUBGRAPH_URL,
                json={
                    'query': query,
                    'variables': {'user': wallet.lower()}
                }
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('data', {}).get('positions', [])
                return []


class WalletAnalyzer:
    """Analyze trading patterns from wallet history."""
    
    def __init__(self, clickhouse_host: str = 'localhost'):
        self.subgraph = PolymarketSubgraph()
        self.ch_client = Client(host=clickhouse_host)
    
    async def analyze(self, wallet: str, days: int = 90) -> WalletProfile:
        """Generate complete trading profile for a wallet."""
        
        # Fetch data
        trades = await self.subgraph.get_user_trades(wallet, days)
        positions = await self.subgraph.get_user_positions(wallet)
        
        if not trades:
            raise ValueError(f"No trades found for wallet {wallet} in last {days} days")
        
        # Calculate metrics
        profile = WalletProfile(
            wallet_address=wallet,
            analysis_period_days=days,
            
            # Activity
            total_trades=len(trades),
            total_volume=self._calculate_volume(trades),
            unique_markets=len(set(t['market']['id'] for t in trades)),
            days_active=self._calculate_active_days(trades),
            
            # Performance
            realized_pnl=self._calculate_realized_pnl(trades),
            unrealized_pnl=self._calculate_unrealized_pnl(positions),
            total_pnl=0,  # Will be calculated
            win_rate=self._calculate_win_rate(trades),
            avg_win=self._calculate_avg_win(trades),
            avg_loss=self._calculate_avg_loss(trades),
            sharpe_ratio=self._calculate_sharpe(trades),
            
            # Position sizing
            avg_position_size=self._calculate_avg_position_size(trades),
            max_position_size=self._calculate_max_position_size(trades),
            position_sizing_strategy=self._detect_position_sizing(trades),
            
            # Market selection
            top_categories=self._analyze_categories(trades),
            avg_market_liquidity=self._calculate_avg_liquidity(trades),
            avg_time_to_expiry=self._calculate_avg_time_to_expiry(trades),
            
            # Trading patterns
            strategy_type=self._detect_strategy_type(trades),
            avg_hold_time_hours=self._calculate_avg_hold_time(trades),
            trade_frequency=self._classify_frequency(trades, days),
            
            # Edge
            entry_timing=self._analyze_entry_timing(trades),
            contrarian_score=self._calculate_contrarian_score(trades),
            news_reaction_speed=None,  # Requires news data
            
            # Risk
            max_drawdown=self._calculate_max_drawdown(trades),
            kelly_fraction=self._estimate_kelly_fraction(trades),
            diversification_score=self._calculate_diversification(trades),
        )
        
        profile.total_pnl = profile.realized_pnl + profile.unrealized_pnl
        
        return profile
    
    def _calculate_volume(self, trades: List[Dict]) -> float:
        """Total trading volume in $."""
        return sum(float(t['price']) * float(t['shares']) for t in trades)
    
    def _calculate_active_days(self, trades: List[Dict]) -> int:
        """Number of unique days with trades."""
        timestamps = [int(t['timestamp']) for t in trades]
        dates = set(datetime.fromtimestamp(ts).date() for ts in timestamps)
        return len(dates)
    
    def _calculate_realized_pnl(self, trades: List[Dict]) -> float:
        """Calculate realized PnL from closed positions."""
        # Group trades by market
        positions = defaultdict(list)
        for t in trades:
            positions[t['market']['id']].append(t)
        
        total_pnl = 0
        for market_trades in positions.values():
            # Simple FIFO accounting
            buys = [t for t in market_trades if t['side'] == 'buy']
            sells = [t for t in market_trades if t['side'] == 'sell']
            
            for sell in sells:
                sell_value = float(sell['price']) * float(sell['shares'])
                # Match with earliest buy
                if buys:
                    buy = buys.pop(0)
                    buy_cost = float(buy['price']) * float(buy['shares'])
                    total_pnl += sell_value - buy_cost
        
        return total_pnl
    
    def _calculate_unrealized_pnl(self, positions: List[Dict]) -> float:
        """Calculate unrealized PnL from open positions."""
        total = 0
        for pos in positions:
            current_price = float(pos['market']['currentPrice'])
            entry_price = float(pos['avgEntryPrice'])
            shares = float(pos['shares'])
            total += (current_price - entry_price) * shares
        return total
    
    def _calculate_win_rate(self, trades: List[Dict]) -> float:
        """Percentage of profitable closed trades."""
        # Simplified: assume each trade pair (buy+sell) is one position
        positions = self._group_into_positions(trades)
        if not positions:
            return 0.0
        
        wins = sum(1 for p in positions if p['pnl'] > 0)
        return wins / len(positions)
    
    def _calculate_avg_win(self, trades: List[Dict]) -> float:
        """Average profit on winning trades."""
        positions = self._group_into_positions(trades)
        wins = [p['pnl'] for p in positions if p['pnl'] > 0]
        return sum(wins) / len(wins) if wins else 0.0
    
    def _calculate_avg_loss(self, trades: List[Dict]) -> float:
        """Average loss on losing trades."""
        positions = self._group_into_positions(trades)
        losses = [p['pnl'] for p in positions if p['pnl'] < 0]
        return sum(losses) / len(losses) if losses else 0.0
    
    def _calculate_sharpe(self, trades: List[Dict]) -> Optional[float]:
        """Sharpe ratio (returns / volatility)."""
        positions = self._group_into_positions(trades)
        if len(positions) < 2:
            return None
        
        returns = [p['pnl'] / p['cost'] for p in positions if p['cost'] > 0]
        if not returns:
            return None
        
        avg_return = sum(returns) / len(returns)
        variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
        std_dev = variance ** 0.5
        
        return (avg_return / std_dev) if std_dev > 0 else None
    
    def _calculate_avg_position_size(self, trades: List[Dict]) -> float:
        """Average $ size per position."""
        sizes = [float(t['price']) * float(t['shares']) for t in trades]
        return sum(sizes) / len(sizes) if sizes else 0.0
    
    def _calculate_max_position_size(self, trades: List[Dict]) -> float:
        """Largest single position."""
        sizes = [float(t['price']) * float(t['shares']) for t in trades]
        return max(sizes) if sizes else 0.0
    
    def _detect_position_sizing(self, trades: List[Dict]) -> str:
        """Detect position sizing strategy."""
        sizes = [float(t['price']) * float(t['shares']) for t in trades]
        
        # Calculate coefficient of variation
        avg = sum(sizes) / len(sizes)
        variance = sum((s - avg) ** 2 for s in sizes) / len(sizes)
        std_dev = variance ** 0.5
        cv = std_dev / avg if avg > 0 else 0
        
        if cv < 0.2:
            return 'fixed'  # Consistent sizing
        elif cv < 0.5:
            return 'proportional'  # Scales with confidence/edge
        else:
            return 'kelly'  # Variable based on Kelly criterion
    
    def _analyze_categories(self, trades: List[Dict]) -> List[tuple]:
        """Most traded categories."""
        categories = [t['market']['category'] for t in trades]
        counter = Counter(categories)
        return counter.most_common(5)
    
    def _calculate_avg_liquidity(self, trades: List[Dict]) -> float:
        """Average liquidity of traded markets."""
        liquidities = [float(t['market']['liquidity']) for t in trades]
        return sum(liquidities) / len(liquidities) if liquidities else 0.0
    
    def _calculate_avg_time_to_expiry(self, trades: List[Dict]) -> float:
        """Average days from trade to market end."""
        times = []
        for t in trades:
            trade_time = datetime.fromtimestamp(int(t['timestamp']))
            end_time = datetime.fromtimestamp(int(t['market']['endDate']))
            days = (end_time - trade_time).days
            times.append(days)
        
        return sum(times) / len(times) if times else 0.0
    
    def _detect_strategy_type(self, trades: List[Dict]) -> str:
        """Detect primary strategy type."""
        # Heuristics based on trading patterns
        
        avg_hold = self._calculate_avg_hold_time(trades)
        contrarian = self._calculate_contrarian_score(trades)
        
        # Market maker: very short holds, high frequency
        if avg_hold < 24:  # Less than 1 day
            return 'market_maker'
        
        # Arbitrage: quick trades, exploiting inefficiencies
        elif avg_hold < 72 and len(trades) > 50:
            return 'arbitrage'
        
        # Momentum: following trends
        elif contrarian < 0.3:
            return 'momentum'
        
        # Value: contrarian bets on mispriced markets
        elif contrarian > 0.6:
            return 'value'
        
        else:
            return 'mixed'
    
    def _calculate_avg_hold_time(self, trades: List[Dict]) -> float:
        """Average hold time in hours."""
        positions = self._group_into_positions(trades)
        hold_times = [p['hold_hours'] for p in positions if p.get('hold_hours')]
        return sum(hold_times) / len(hold_times) if hold_times else 0.0
    
    def _classify_frequency(self, trades: List[Dict], days: int) -> str:
        """Classify trading frequency."""
        trades_per_day = len(trades) / days
        
        if trades_per_day > 10:
            return 'scalper'
        elif trades_per_day > 2:
            return 'day_trader'
        elif trades_per_day > 0.5:
            return 'swing_trader'
        else:
            return 'position_trader'
    
    def _analyze_entry_timing(self, trades: List[Dict]) -> str:
        """When in market lifecycle does wallet typically enter."""
        avg_time_to_expiry = self._calculate_avg_time_to_expiry(trades)
        
        if avg_time_to_expiry > 30:
            return 'early'
        elif avg_time_to_expiry > 7:
            return 'mid'
        else:
            return 'late'
    
    def _calculate_contrarian_score(self, trades: List[Dict]) -> float:
        """How often trades against the majority (0-1)."""
        # Contrarian = buying when price is low, selling when high
        # Approximate: count trades where price < 0.4 or > 0.6
        
        contrarian_count = 0
        for t in trades:
            price = float(t['price'])
            side = t['side']
            
            # Buy at low price (contrarian)
            if side == 'buy' and price < 0.4:
                contrarian_count += 1
            # Sell at high price (contrarian)
            elif side == 'sell' and price > 0.6:
                contrarian_count += 1
        
        return contrarian_count / len(trades) if trades else 0.0
    
    def _calculate_max_drawdown(self, trades: List[Dict]) -> float:
        """Maximum peak-to-trough drawdown."""
        positions = self._group_into_positions(trades)
        if not positions:
            return 0.0
        
        # Calculate running PnL
        cumulative_pnl = 0
        peak = 0
        max_dd = 0
        
        for pos in positions:
            cumulative_pnl += pos['pnl']
            peak = max(peak, cumulative_pnl)
            drawdown = peak - cumulative_pnl
            max_dd = max(max_dd, drawdown)
        
        return max_dd
    
    def _estimate_kelly_fraction(self, trades: List[Dict]) -> Optional[float]:
        """Estimate Kelly fraction being used."""
        # Kelly = (win_rate * avg_win - (1-win_rate) * avg_loss) / avg_win
        
        win_rate = self._calculate_win_rate(trades)
        avg_win = abs(self._calculate_avg_win(trades))
        avg_loss = abs(self._calculate_avg_loss(trades))
        
        if avg_win == 0:
            return None
        
        kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
        
        # Position sizing as fraction of Kelly
        avg_size = self._calculate_avg_position_size(trades)
        total_capital = avg_size * 10  # Estimate (assume avg is 10% of capital)
        
        if kelly > 0 and total_capital > 0:
            fraction = (avg_size / total_capital) / kelly
            return max(0, min(1, fraction))  # Clamp to [0, 1]
        
        return None
    
    def _calculate_diversification(self, trades: List[Dict]) -> float:
        """Diversification score (0-1)."""
        unique_markets = len(set(t['market']['id'] for t in trades))
        total_trades = len(trades)
        
        # Higher score = more diversified
        return min(1.0, unique_markets / (total_trades ** 0.5))
    
    def _group_into_positions(self, trades: List[Dict]) -> List[Dict]:
        """Group trades into closed positions."""
        # Simplified: match buys and sells by market
        positions = []
        by_market = defaultdict(lambda: {'buys': [], 'sells': []})
        
        for t in trades:
            market_id = t['market']['id']
            if t['side'] == 'buy':
                by_market[market_id]['buys'].append(t)
            else:
                by_market[market_id]['sells'].append(t)
        
        for market_id, market_trades in by_market.items():
            buys = sorted(market_trades['buys'], key=lambda x: int(x['timestamp']))
            sells = sorted(market_trades['sells'], key=lambda x: int(x['timestamp']))
            
            # Match oldest buy with oldest sell
            for buy, sell in zip(buys, sells):
                cost = float(buy['price']) * float(buy['shares'])
                revenue = float(sell['price']) * float(sell['shares'])
                pnl = revenue - cost
                
                hold_hours = (int(sell['timestamp']) - int(buy['timestamp'])) / 3600
                
                positions.append({
                    'market_id': market_id,
                    'cost': cost,
                    'revenue': revenue,
                    'pnl': pnl,
                    'hold_hours': hold_hours,
                })
        
        return positions


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze Polymarket wallet strategy')
    parser.add_argument('--wallet', required=True, help='Wallet address (0x...)')
    parser.add_argument('--days', type=int, default=90, help='Analysis period in days')
    parser.add_argument('--output', help='Output JSON file (optional)')
    parser.add_argument('--clickhouse-host', default='localhost', help='ClickHouse host')
    
    args = parser.parse_args()
    
    analyzer = WalletAnalyzer(clickhouse_host=args.clickhouse_host)
    
    print(f"Analyzing wallet {args.wallet} (last {args.days} days)...")
    
    profile = await analyzer.analyze(args.wallet, args.days)
    
    # Print report
    print("\n" + "="*60)
    print(f"WALLET ANALYSIS: {profile.wallet_address}")
    print("="*60)
    
    print(f"\n📊 ACTIVITY")
    print(f"  Total trades: {profile.total_trades:,}")
    print(f"  Total volume: ${profile.total_volume:,.2f}")
    print(f"  Unique markets: {profile.unique_markets}")
    print(f"  Days active: {profile.days_active}/{profile.analysis_period_days}")
    
    print(f"\n💰 PERFORMANCE")
    print(f"  Total P&L: ${profile.total_pnl:,.2f}")
    print(f"  Realized P&L: ${profile.realized_pnl:,.2f}")
    print(f"  Unrealized P&L: ${profile.unrealized_pnl:,.2f}")
    print(f"  Win rate: {profile.win_rate:.1%}")
    print(f"  Avg win: ${profile.avg_win:,.2f}")
    print(f"  Avg loss: ${profile.avg_loss:,.2f}")
    if profile.sharpe_ratio:
        print(f"  Sharpe ratio: {profile.sharpe_ratio:.2f}")
    
    print(f"\n📈 STRATEGY")
    print(f"  Type: {profile.strategy_type}")
    print(f"  Frequency: {profile.trade_frequency}")
    print(f"  Avg hold time: {profile.avg_hold_time_hours:.1f} hours")
    print(f"  Entry timing: {profile.entry_timing}")
    print(f"  Contrarian score: {profile.contrarian_score:.2f}")
    
    print(f"\n💵 POSITION SIZING")
    print(f"  Strategy: {profile.position_sizing_strategy}")
    print(f"  Avg size: ${profile.avg_position_size:,.2f}")
    print(f"  Max size: ${profile.max_position_size:,.2f}")
    if profile.kelly_fraction:
        print(f"  Kelly fraction: {profile.kelly_fraction:.2f}")
    
    print(f"\n🎯 MARKET SELECTION")
    print(f"  Top categories:")
    for category, count in profile.top_categories:
        print(f"    - {category}: {count} trades")
    print(f"  Avg liquidity: ${profile.avg_market_liquidity:,.0f}")
    print(f"  Avg time to expiry: {profile.avg_time_to_expiry:.1f} days")
    
    print(f"\n⚠️  RISK")
    print(f"  Max drawdown: ${profile.max_drawdown:,.2f}")
    print(f"  Diversification: {profile.diversification_score:.2f}")
    
    # Save JSON
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(asdict(profile), f, indent=2)
        print(f"\n✅ Saved detailed report to {args.output}")


if __name__ == '__main__':
    asyncio.run(main())

#!/usr/bin/env python3
"""
Strategy Replicator - Generate trading strategy from wallet analysis

Takes a WalletProfile and generates executable strategy code that mimics
the trading patterns.

Usage:
    python strategy_replicator.py --wallet 0x... --output strategies/replicated_strategy.py
    python strategy_replicator.py --profile report.json --output my_strategy.py
"""

import json
import sys
from pathlib import Path
from typing import Dict
from dataclasses import asdict


STRATEGY_TEMPLATE = '''"""
Replicated Strategy: {strategy_name}

Auto-generated from wallet analysis: {wallet_address}
Analysis period: {analysis_period_days} days
Performance: {total_pnl:.2f} USD ({win_rate:.1%} win rate)

Strategy characteristics:
- Type: {strategy_type}
- Frequency: {trade_frequency}
- Hold time: {avg_hold_time_hours:.1f} hours
- Position sizing: {position_sizing_strategy}
- Contrarian score: {contrarian_score:.2f}
"""

from strategies.base import BaseStrategy, TradingSignal, Market
from typing import Optional, List
from datetime import datetime, timedelta


class {class_name}(BaseStrategy):
    """
    {description}
    
    Market selection:
{market_selection_logic}
    
    Entry rules:
{entry_rules}
    
    Position sizing:
{position_sizing_logic}
    """
    
    def __init__(self, config: Dict):
        super().__init__(config)
        
        # Replicated parameters
        self.preferred_categories = {preferred_categories}
        self.min_liquidity = {min_liquidity:.0f}
        self.target_time_to_expiry_days = {target_time_to_expiry:.0f}
        self.avg_position_size = {avg_position_size:.2f}
        self.max_position_size = {max_position_size:.2f}
        self.contrarian_threshold = {contrarian_threshold:.2f}
        self.hold_target_hours = {hold_target_hours:.1f}
        
    def filter_markets(self, markets: List[Market]) -> List[Market]:
        """Filter markets based on observed preferences."""
        filtered = []
        
        for market in markets:
            # Category filter
            if market.category not in self.preferred_categories:
                continue
            
            # Liquidity filter
            if market.liquidity < self.min_liquidity:
                continue
            
            # Time to expiry filter
            days_to_end = (market.end_date - datetime.now()).days
            min_days = max(1, self.target_time_to_expiry_days - 7)
            max_days = self.target_time_to_expiry_days + 7
            
            if not (min_days <= days_to_end <= max_days):
                continue
            
            filtered.append(market)
        
        return filtered
    
    def analyze_market(self, market: Market) -> Optional[TradingSignal]:
        """
        Analyze market and generate signal based on replicated strategy.
        
        {strategy_specific_logic}
        """
        
        # Extract key metrics
        yes_price = market.yes_price
        no_price = market.no_price
        
{analysis_logic}
        
        return None  # No signal
    
    def calculate_position_size(self, edge: float, confidence: float = 1.0) -> float:
        """
        Position sizing based on observed pattern: {position_sizing_strategy}
        """
{position_size_calculation}
        
        # Apply limits
        size = min(size, self.max_position_size)
        return size
'''


def generate_strategy_code(profile: Dict, output_path: str):
    """Generate Python strategy code from wallet profile."""
    
    # Generate class name
    wallet_short = profile['wallet_address'][:10]
    class_name = f"Replicated_{wallet_short.replace('0x', '')}_Strategy"
    strategy_name = f"Replicated from {profile['wallet_address'][:10]}..."
    
    # Build market selection logic description
    top_cats = [cat for cat, _ in profile['top_categories'][:3]]
    market_selection = "\n".join([
        f"    - Preferred categories: {', '.join(top_cats)}",
        f"    - Min liquidity: ${profile['avg_market_liquidity']:.0f}",
        f"    - Entry timing: {profile['entry_timing']} (avg {profile['avg_time_to_expiry']:.1f} days to expiry)",
    ])
    
    # Build entry rules
    entry_rules = []
    
    if profile['strategy_type'] == 'value':
        entry_rules.append("    - Buy undervalued outcomes (contrarian approach)")
        entry_rules.append(f"    - Threshold: price < {0.5 - profile['contrarian_score']/4:.2f} for Yes")
    elif profile['strategy_type'] == 'momentum':
        entry_rules.append("    - Follow market momentum")
        entry_rules.append("    - Buy rising prices, sell falling")
    elif profile['strategy_type'] == 'market_maker':
        entry_rules.append("    - Provide liquidity on both sides")
        entry_rules.append("    - Profit from bid-ask spread")
    elif profile['strategy_type'] == 'arbitrage':
        entry_rules.append("    - Exploit price inefficiencies")
        entry_rules.append("    - Quick entry/exit")
    else:
        entry_rules.append("    - Mixed strategy approach")
        entry_rules.append("    - Opportunistic entries")
    
    entry_rules_str = "\n".join(entry_rules)
    
    # Build position sizing logic
    if profile['position_sizing_strategy'] == 'fixed':
        sizing_logic = f"    - Fixed size: ${profile['avg_position_size']:.2f} per trade"
    elif profile['position_sizing_strategy'] == 'kelly':
        sizing_logic = f"    - Kelly criterion (fraction: {profile.get('kelly_fraction', 0.25):.2f})"
    else:
        sizing_logic = f"    - Proportional to edge/confidence"
    
    # Generate strategy-specific analysis logic
    if profile['strategy_type'] == 'value':
        analysis_logic = """        # Value strategy: look for mispriced outcomes
        
        # Calculate true probability estimate (placeholder - should use your model)
        true_prob = 0.5  # TODO: Replace with actual probability model
        
        # Calculate edge
        edge_yes = true_prob - yes_price
        edge_no = (1 - true_prob) - no_price
        
        # Contrarian filter: only trade if price is far from consensus
        if abs(yes_price - 0.5) < self.contrarian_threshold:
            return None  # Too close to 50/50, not enough edge
        
        # Generate signal if edge is significant
        min_edge = self.config.get('min_edge', 0.05)
        
        if edge_yes > min_edge:
            return TradingSignal(
                action='buy',
                market_id=market.id,
                outcome='Yes',
                size=self.calculate_position_size(edge_yes, confidence=edge_yes/0.1),
                confidence=edge_yes / 0.1,  # Normalize to 0-1
                reason=f"Value bet: edge {edge_yes:.2%}, price {yes_price:.2f}",
                metadata={'estimated_true_prob': true_prob}
            )
        
        elif edge_no > min_edge:
            return TradingSignal(
                action='buy',
                market_id=market.id,
                outcome='No',
                size=self.calculate_position_size(edge_no, confidence=edge_no/0.1),
                confidence=edge_no / 0.1,
                reason=f"Value bet: edge {edge_no:.2%}, price {no_price:.2f}",
                metadata={'estimated_true_prob': true_prob}
            )"""
    
    elif profile['strategy_type'] == 'momentum':
        analysis_logic = """        # Momentum strategy: follow price trends
        
        # TODO: Fetch recent price history from ClickHouse
        # For now, use current price as proxy
        
        # Buy if price is moving up (> 0.6) or down (< 0.4)
        if yes_price > 0.6:
            # Strong momentum up
            confidence = (yes_price - 0.6) / 0.4  # 0.6-1.0 -> 0.0-1.0
            return TradingSignal(
                action='buy',
                market_id=market.id,
                outcome='Yes',
                size=self.calculate_position_size(0.05, confidence),
                confidence=confidence,
                reason=f"Momentum: riding uptrend at {yes_price:.2f}",
            )
        
        elif yes_price < 0.4:
            # Strong momentum down
            confidence = (0.4 - yes_price) / 0.4  # 0.4-0.0 -> 0.0-1.0
            return TradingSignal(
                action='buy',
                market_id=market.id,
                outcome='No',
                size=self.calculate_position_size(0.05, confidence),
                confidence=confidence,
                reason=f"Momentum: riding downtrend at {yes_price:.2f}",
            )"""
    
    else:
        # Generic logic
        analysis_logic = """        # Generic strategy logic
        
        # Calculate edge (placeholder)
        edge = abs(yes_price - 0.5)
        
        if edge > self.config.get('min_edge', 0.05):
            outcome = 'Yes' if yes_price < 0.5 else 'No'
            
            return TradingSignal(
                action='buy',
                market_id=market.id,
                outcome=outcome,
                size=self.calculate_position_size(edge),
                confidence=edge / 0.5,
                reason=f"Edge detected: {edge:.2%}",
            )"""
    
    # Position size calculation based on detected strategy
    if profile['position_sizing_strategy'] == 'fixed':
        size_calc = f"""        # Fixed position sizing
        size = self.avg_position_size"""
    
    elif profile['position_sizing_strategy'] == 'kelly':
        kelly_frac = profile.get('kelly_fraction', 0.25)
        size_calc = f"""        # Kelly criterion position sizing
        kelly_fraction = {kelly_frac:.2f}
        
        # Kelly formula: f = edge / odds
        # For binary: f = (p * b - q) / b, where p = win prob, q = lose prob, b = odds
        # Simplified: f ≈ edge for even-money bets
        
        kelly_size = edge * kelly_fraction * confidence
        size = kelly_size * self.config.get('capital', 1000)"""
    
    else:
        # Proportional
        size_calc = """        # Proportional position sizing
        base_size = self.avg_position_size
        size = base_size * confidence"""
    
    # Format the strategy code
    code = STRATEGY_TEMPLATE.format(
        strategy_name=strategy_name,
        wallet_address=profile['wallet_address'],
        analysis_period_days=profile['analysis_period_days'],
        total_pnl=profile['total_pnl'],
        win_rate=profile['win_rate'],
        strategy_type=profile['strategy_type'],
        trade_frequency=profile['trade_frequency'],
        avg_hold_time_hours=profile['avg_hold_time_hours'],
        position_sizing_strategy=profile['position_sizing_strategy'],
        contrarian_score=profile['contrarian_score'],
        class_name=class_name,
        description=f"Replicated {profile['strategy_type']} strategy from successful wallet",
        market_selection_logic=market_selection,
        entry_rules=entry_rules_str,
        position_sizing_logic=sizing_logic,
        preferred_categories=top_cats,
        min_liquidity=profile['avg_market_liquidity'],
        target_time_to_expiry=profile['avg_time_to_expiry'],
        avg_position_size=profile['avg_position_size'],
        max_position_size=profile['max_position_size'],
        contrarian_threshold=0.1,  # Threshold for price distance from 0.5
        hold_target_hours=profile['avg_hold_time_hours'],
        strategy_specific_logic=f"Strategy type: {profile['strategy_type']}",
        analysis_logic=analysis_logic,
        position_size_calculation=size_calc,
    )
    
    # Write to file
    with open(output_path, 'w') as f:
        f.write(code)
    
    print(f"✅ Generated strategy: {output_path}")
    print(f"   Class: {class_name}")
    print(f"   Type: {profile['strategy_type']}")
    print(f"   Win rate: {profile['win_rate']:.1%}")
    print(f"   Total P&L: ${profile['total_pnl']:.2f}")


def main():
    import argparse
    import asyncio
    from wallet_analyzer import WalletAnalyzer
    
    parser = argparse.ArgumentParser(description='Replicate strategy from wallet analysis')
    parser.add_argument('--wallet', help='Wallet address (analyze and replicate)')
    parser.add_argument('--profile', help='Path to wallet analysis JSON')
    parser.add_argument('--output', required=True, help='Output Python file')
    parser.add_argument('--days', type=int, default=90, help='Analysis period')
    
    args = parser.parse_args()
    
    if not args.wallet and not args.profile:
        print("Error: Must provide either --wallet or --profile")
        sys.exit(1)
    
    # Load or generate profile
    if args.profile:
        print(f"Loading profile from {args.profile}...")
        with open(args.profile, 'r') as f:
            profile = json.load(f)
    else:
        print(f"Analyzing wallet {args.wallet}...")
        analyzer = WalletAnalyzer()
        profile_obj = asyncio.run(analyzer.analyze(args.wallet, args.days))
        profile = asdict(profile_obj)
    
    # Generate strategy code
    generate_strategy_code(profile, args.output)
    
    print("\n📝 Next steps:")
    print(f"1. Review generated strategy: {args.output}")
    print("2. Implement probability model (replace placeholder)")
    print("3. Backtest: python scripts/backtest.py --strategy {args.output}")
    print("4. Paper trade: python scripts/live_trade.py --strategy {args.output} --dry-run")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Analyze a Polymarket wallet to reverse-engineer its strategy.

Usage:
    python analyze_wallet.py <wallet_address>
    python analyze_wallet.py 0xk9Q2mX4L8A7ZP3R  # Example from user

The script will:
1. Fetch the wallet's trade history
2. Analyze trading patterns
3. Identify the strategy being used
4. Generate a config to replicate it
"""

import sys
import json
from core.wallet_analyzer import WalletAnalyzer, clone_wallet_strategy


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_wallet.py <wallet_address>")
        print("\nExample:")
        print("  python analyze_wallet.py 0xk9Q2mX4L8A7ZP3R")
        sys.exit(1)
    
    wallet_address = sys.argv[1]
    
    print(f"🔍 Analyzing wallet: {wallet_address}")
    print("=" * 60)
    
    try:
        # Analyze the wallet
        analyzer = WalletAnalyzer(wallet_address)
        profile = analyzer.analyze()
        
        # Print results
        print(f"\n📊 Trading Profile")
        print(f"Strategy Type: {profile.strategy_type} (confidence: {profile.confidence:.1%})")
        print(f"Risk Level: {profile.risk_level}")
        print(f"Diversification: {profile.diversification_score:.2f}/1.0")
        
        print(f"\n📈 Performance Metrics")
        print(f"Total Trades: {profile.total_trades}")
        print(f"Win Rate: {profile.win_rate:.2%}")
        print(f"Average Profit: ${profile.avg_profit:.2f}")
        print(f"Total P&L: ${profile.total_pnl:.2f}")
        print(f"Sharpe Ratio: {profile.sharpe_ratio:.2f}")
        print(f"Max Drawdown: {profile.max_drawdown:.2%}")
        
        print(f"\n⏱️  Behavior")
        print(f"Avg Hold Time: {profile.avg_hold_time}")
        print(f"Avg Position Size: ${profile.avg_position_size:.2f}")
        print(f"Position Size Std Dev: ${profile.position_size_std:.2f}")
        
        print(f"\n🎯 Market Preferences")
        print(f"Top Categories: {', '.join(profile.top_categories)}")
        print(f"\nCategory Distribution:")
        for category, count in sorted(
            profile.category_distribution.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]:
            print(f"  {category}: {count} trades")
        
        print(f"\n🔬 Patterns")
        if 'entry_price_distribution' in profile.patterns:
            entry = profile.patterns['entry_price_distribution']
            print(f"Entry Price Stats:")
            print(f"  Mean: {entry.get('mean', 0):.2f}")
            print(f"  Median: {entry.get('median', 0):.2f}")
            print(f"  Extreme Entries: {entry.get('extreme_entries', 0):.1%}")
        
        # Generate replication config
        print(f"\n⚙️  Replication Config")
        print("=" * 60)
        
        config = clone_wallet_strategy(wallet_address)
        print(json.dumps(config, indent=2))
        
        # Save config
        output_file = f"config/wallet_{wallet_address[:8]}.json"
        with open(output_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        print(f"\n✅ Config saved to: {output_file}")
        
        print(f"\n🚀 To run this strategy:")
        print(f"   python scripts/run_live.py --config {output_file}")
        
    except NotImplementedError as e:
        print(f"\n⚠️  {e}")
        print("\nNOTE: Polymarket API integration is needed.")
        print("Current implementation is a template.")
        print("\nTo complete:")
        print("1. Implement Polymarket GraphQL API calls in core/client.py")
        print("2. Fetch trade history in wallet_analyzer.py")
        print("3. Parse transaction data")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()

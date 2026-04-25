#!/usr/bin/env python3
"""
Leaderboard Chaser Strategy
Identifies top-performing traders and their recent successful markets
to generate copy-trading signals.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import sys
import re

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def load_latest_leaderboards(data_dir, hours_back=24):
    """Load leaderboard data from the last N hours."""
    leaderboard_dir = data_dir / "leaderboard"
    if not leaderboard_dir.exists():
        return []
    
    cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
    leaderboard_files = []
    
    for file_path in leaderboard_dir.glob("leaderboard_*.json"):
        try:
            file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            if file_mtime >= cutoff_time:
                leaderboard_files.append(file_path)
        except:
            leaderboard_files.append(file_path)
    
    leaderboards = []
    for file_path in leaderboard_files:
        try:
            with open(file_path) as f:
                data = json.load(f)
                leaderboards.append(data)
        except Exception as e:
            print(f"Error loading leaderboard {file_path}: {e}")
    
    return leaderboards

def extract_trader_performance(leaderboard_data, timeframe="today"):
    """
    Extract trader performance data from leaderboard.
    
    Returns:
        List of dicts with trader info and performance metrics
    """
    traders = []
    
    # Handle different leaderboard formats
    if isinstance(leaderboard_data, dict):
        # New format with timestamp
        data = leaderboard_data.get('data', leaderboard_data.get('leaderboard', []))
        timeframe = leaderboard_data.get('timeframe', timeframe)
    elif isinstance(leaderboard_data, list):
        data = leaderboard_data
    else:
        data = []
    
    for entry in data:
        if isinstance(entry, dict):
            # Handle structured entries
            trader = {
                'rank': entry.get('rank', 0),
                'username': entry.get('username', entry.get('name', 'Unknown')),
                'address': entry.get('address', ''),
                'profit': entry.get('profit', entry.get('profit_loss', 0)),
                'volume': entry.get('volume', 0),
                'timeframe': timeframe
            }
        elif isinstance(entry, (list, tuple)) and len(entry) >= 3:
            # Handle array format [rank, username, profit, ...]
            trader = {
                'rank': entry[0] if len(entry) > 0 else 0,
                'username': entry[1] if len(entry) > 1 else 'Unknown',
                'address': entry[2] if len(entry) > 2 else '',
                'profit': entry[3] if len(entry) > 3 else 0,
                'volume': entry[4] if len(entry) > 4 else 0,
                'timeframe': timeframe
            }
        else:
            # Skip unparseable entries
            continue
            
        # Only include traders with positive profit above threshold
        if trader['profit'] > 0:
            traders.append(trader)
    
    # Sort by profit descending
    traders.sort(key=lambda x: x['profit'], reverse=True)
    return traders

def get_trader_recent_markets(trader_address, limit=10):
    """
    Get recent markets a trader has participated in.
    Note: This would require the Data API or scraping trader profiles.
    For now, we'll return a placeholder - in practice, you'd query:
    GET /data-api.polymarket.com/trades?limit=N&address=TRADER_ADDRESS
    """
    # Placeholder implementation
    # In a real implementation, you would:
    # 1. Query Polymarket Data API for trader's recent trades
    # 2. Extract unique market IDs they've traded recently
    # 3. Get current market data for those markets
    # 4. Look for similar new markets to suggest
    
    return []  # Placeholder

def find_similar_markets(target_markets, current_markets, similarity_threshold=0.7):
    """
    Find current markets similar to those traded successfully by top traders.
    This would involve comparing market questions, categories, etc.
    """
    # Placeholder for market similarity logic
    # In practice, you could:
    # 1. Use text similarity on market questions (TF-IDF, embeddings)
    # 2. Match by category/tags
    # 3. Look for same event types (e.g., if trader won on soccer, look for new soccer markets)
    return []

def generate_leaderboard_signals(data_dir, top_n=5, min_profit_threshold=1000):
    """
    Generate signals based on leaderboard performance.
    
    Returns:
        List of signal dicts
    """
    print("🔍 Analyzing leaderboard data for top performers...")
    
    # Load recent leaderboards
    leaderboards = load_latest_leaderboards(data_dir, hours_back=24)
    
    if not leaderboards:
        print("⚠️  No leaderboard data found.")
        return []
    
    # Extract top performers from all timeframes
    all_traders = []
    for lb_data in leaderboards:
        timeframe = lb_data.get('timeframe', 'unknown') if isinstance(lb_data, dict) else 'unknown'
        traders = extract_trader_performance(lb_data, timeframe)
        
        # Filter by minimum profit
        qualified_traders = [t for t in traders if t['profit'] >= min_profit_threshold]
        all_traders.extend(qualified_traders)
    
    if not all_traders:
        print(f"📊 No traders found with profit >= ${min_profit_threshold}")
        return []
    
    # Deduplicate by address (keep highest profit entry)
    trader_dict = {}
    for trader in all_traders:
        addr = trader.get('address', '')
        if addr and addr not in trader_dict:
            trader_dict[addr] = trader
        elif addr and trader['profit'] > trader_dict[addr]['profit']:
            trader_dict[addr] = trader
    
    # Sort by profit and take top N
    top_traders = sorted(trader_dict.values(), key=lambda x: x['profit'], reverse=True)[:top_n]
    
    signals = []
    print(f"🏆 Found {len(top_traders)} qualifying top traders")
    
    for i, trader in enumerate(top_traders, 1):
        signal = {
            'type': 'LEADERBOARD_CHASER',
            'rank': i,
            'strategy': 'Follow top performer',
            'trader_username': trader['username'],
            'trader_address': trader.get('address', ''),
            'profit': trader['profit'],
            'volume': trader.get('volume', 0),
            'timeframe': trader.get('timeframe', 'unknown'),
            'signal_strength': 'HIGH' if trader['profit'] > 10000 else 'MEDIUM' if trader['profit'] > 1000 else 'LOW',
            'action_consideration': f"Research recent winning markets of {trader['username']} and look for similar new opportunities",
            'next_steps': [
                f"Visit trader profile: https://polymarket.com/profile/{trader.get('address', '')}" if trader.get('address') else "Search for trader by username",
                "Check their recent transaction history for market patterns",
                "Look for new markets in similar categories/events",
                "Consider entering early on similar market structures"
            ],
            'timestamp': datetime.utcnow().isoformat()
        }
        signals.append(signal)
        
        print(f"  {i}. {trader['username']} ({(trader.get('address',''))[:10]}...): +${trader['profit']:,.2f}")
    
    return signals

def main():
    """Main function to run the leaderboard chaser strategy."""
    print("=== Leaderboard Chaser Strategy ===")
    
    # Set up paths
    project_root = Path(__file__).parent.parent
    data_dir = project_root / "data"
    
    if not data_dir.exists():
        print("❌ Data directory not found. Please run the data collector first.")
        return
    
    # Load configuration
    config_path = project_root / "config" / "settings.json"
    try:
        with open(config_path) as f:
            config = json.load(f)
    except Exception as e:
        print(f"❌ Error loading config: {e}")
        # Use defaults
        config = {"strategies": {"leaderboard_chaser": {"min_profit_threshold": 1000, "top_n_traders": 5}}}
    
    lb_config = config.get("strategies", {}).get("leaderboard_chaser", {})
    min_profit = lb_config.get("min_profit_threshold", 1000)
    top_n = lb_config.get("top_n_traders", 5)
    
    # Generate signals
    signals = generate_leaderboard_signals(
        data_dir, 
        top_n=top_n, 
        min_profit_threshold=min_profit
    )
    
    # Report results
    if signals:
        print(f"\n🚨 Generated {len(signals)} leaderboard signal(s):")
        print("-" * 80)
        
        for signal in signals:
            print(f"{signal['rank']}. {signal['type']}")
            print(f"   Strategy: {signal['strategy']}")
            print(f"   Trader: {signal['trader_username']}")
            if signal['trader_address']:
                print(f"   Address: {signal['trader_address']}")
            print(f"   Profit: ${signal['profit']:,.2f}")
            print(f"   Volume: ${signal['volume']:,.2f}")
            print(f"   Timeframe: {signal['timeframe']}")
            print(f"   Strength: {signal['signal_strength']}")
            print(f"   💡 {signal['action_consideration']}")
            print()
        
        # Save signals
        signals_dir = project_root / "data" / "strategy_signals"
        signals_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        signals_file = signals_dir / f"leaderboard_signals_{timestamp}.json"
        
        with open(signals_file, 'w') as f:
            json.dump(signals, f, indent=2)
        
        print(f"💾 Signals saved to: {signals_file}")
        
    else:
        print("✅ No leaderboard signals generated.")
        print("   Try running longer to accumulate leaderboard data,")
        print("   or adjust the profit threshold in config.")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Front-running Strategy Detector
Scans orderbooks for large limit orders that could be front-run.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def load_latest_orderbooks(data_dir, minutes_back=5):
    """Load orderbook data from the last N minutes."""
    orderbook_dir = data_dir / "orderbooks"
    if not orderbook_dir.exists():
        return []
    
    cutoff_time = datetime.utcnow() - timedelta(minutes=minutes_back)
    orderbook_files = []
    
    for file_path in orderbook_dir.glob("orderbook_*.json"):
        # Extract timestamp from filename: orderbook_<market_id>_<outcome>_YYYYMMDD_HHMMSS.json
        try:
            # Simple approach: check file modification time
            file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            if file_mtime >= cutoff_time:
                orderbook_files.append(file_path)
        except:
            # If we can't parse time, include it anyway for safety
            orderbook_files.append(file_path)
    
    orderbooks = []
    for file_path in orderbook_files:
        try:
            with open(file_path) as f:
                data = json.load(f)
                orderbooks.append(data)
        except Exception as e:
            print(f"Error loading {file_path}: {e}")
    
    return orderbooks

def detect_large_orders(orderbooks, min_size_usd=1000, min_size_shares=100):
    """
    Detect large limit orders in orderbooks.
    
    Args:
        orderbooks: List of orderbook data dictionaries
        min_size_usd: Minimum order size in USD to consider
        min_size_shares: Minimum order size in shares
    
    Returns:
        List of detected large orders with details
    """
    large_orders = []
    
    for ob_data in orderbooks:
        try:
            orderbook = ob_data.get('orderbook', {})
            market_question = ob_data.get('market_question', 'Unknown')
            token_id = ob_data.get('token_id')
            outcome = ob_data.get('outcome', 'unknown')
            
            # Check bids (buy orders) - these are orders people want to BUY at
            # A large bid wall means someone wants to buy a lot at that price
            # We could front-run by buying slightly cheaper and selling to them at their bid
            bids = orderbook.get('bids', [])
            for bid in bids:
                price = float(bid.get('price', 0))
                size = float(bid.get('size', 0))
                if price > 0 and size > 0:
                    size_usd = price * size  # Since price is in USDC per share
                    if size_usd >= min_size_usd or size >= min_size_shares:
                        large_orders.append({
                            'type': 'large_bid',  # Someone wants to BUY at this price
                            'market_question': market_question,
                            'token_id': token_id,
                            'outcome': outcome,
                            'price': price,
                            'size': size,
                            'size_usd': size_usd,
                            'timestamp': ob_data.get('timestamp'),
                            'action_consideration': 'Consider buying cheaper and selling to this bid'
                        })
            
            # Check asks (sell orders) - these are orders people want to SELL at
            # A large ask wall means someone wants to sell a lot at that price
            # We could front-run by selling slightly higher and buying from them at their ask
            asks = orderbook.get('asks', [])
            for ask in asks:
                price = float(ask.get('price', 0))
                size = float(ask.get('size', 0))
                if price > 0 and size > 0:
                    size_usd = price * size
                    if size_usd >= min_size_usd or size >= min_size_shares:
                        large_orders.append({
                            'type': 'large_ask',  # Someone wants to SELL at this price
                            'market_question': market_question,
                            'token_id': token_id,
                            'outcome': outcome,
                            'price': price,
                            'size': size,
                            'size_usd': size_usd,
                            'timestamp': ob_data.get('timestamp'),
                            'action_consideration': 'Consider selling higher and buying from this ask'
                        })
        except Exception as e:
            print(f"Error processing orderbook: {e}")
    
    return large_orders

def main():
    """Main function to run the front-running strategy detector."""
    print("=== Front-running Strategy Detector ===")
    
    # Set up paths
    project_root = Path(__file__).parent.parent
    data_dir = project_root / "data"
    
    if not data_dir.exists():
        print("❌ Data directory not found. Please run the data collector first.")
        return
    
    # Load recent orderbooks
    print("🔍 Loading recent orderbook data...")
    orderbooks = load_latest_orderbooks(data_dir, minutes_back=10)
    
    if not orderbooks:
        print("⚠️  No orderbook data found in the last 10 minutes.")
        print("   Try running the data collector for a few minutes first.")
        return
    
    print(f"📊 Loaded {len(orderbooks)} orderbook snapshots")
    
    # Detect large orders
    print("🎯 Scanning for large limit orders...")
    large_orders = detect_large_orders(
        orderbooks,
        min_size_usd=float(1000),  # $1000 minimum
        min_size_shares=float(100)   # 100 shares minimum
    )
    
    # Report results
    if large_orders:
        print(f"\n🚨 Found {len(large_orders)} large order(s):")
        print("-" * 80)
        
        for i, order in enumerate(large_orders, 1):
            print(f"{i}. {order['type'].upper()}")
            print(f"   Market: {order['market_question']}")
            print(f"   Outcome: {order['outcome']}")
            print(f"   Price: {order['price']:.4f}")
            print(f"   Size: {order['size']:,.2f} shares")
            print(f"   Size (USD): ${order['size_usd']:,.2f}")
            print(f"   Time: {order['timestamp']}")
            print(f"   💡 {order['action_consideration']}")
            print()
        
        # Save signals
        signals_dir = project_root / "data" / "strategy_signals"
        signals_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        signals_file = signals_dir / f"front_run_signals_{timestamp}.json"
        
        with open(signals_file, 'w') as f:
            json.dump(large_orders, f, indent=2)
        
        print(f"💾 Signals saved to: {signals_file}")
        
    else:
        print("✅ No large orders detected above the threshold.")
        print("   Try adjusting the thresholds or wait for more data.")

if __name__ == "__main__":
    main()
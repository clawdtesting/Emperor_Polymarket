#!/usr/bin/env python3
"""
Polymarket Data Collector
Collects orderbook, leaderboard, and market data for strategy monitoring.
"""

import requests
import json
import time
import os
from datetime import datetime
from pathlib import Path

# Load config
CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.json"
with open(CONFIG_PATH) as f:
    config = json.load(f)

POLYMARKET_CONFIG = config["polymarket"]
MONITORING_CONFIG = config["monitoring"]

# API endpoints
GAMMA_API = POLYMARKET_CONFIG["gamma_api"]
CLOB_API = POLYMARKET_CONFIG["clob_api"]

# Data directories
DATA_DIR = Path(__file__).parent.parent / "data"
ORDERBOOK_DIR = DATA_DIR / "orderbooks"
LEADERBOARD_DIR = DATA_DIR / "leaderboard"
MARKETS_DIR = DATA_DIR / "markets"

# Create directories if they don't exist
for dir_path in [ORDERBOOK_DIR, LEADERBOARD_DIR, MARKETS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

def fetch_gamma_markets(limit=10):
    """Fetch active markets from Gamma API sorted by volume."""
    url = f"{GAMMA_API}/markets"
    params = {
        "limit": limit,
        "active": "true",
        "closed": "false",
        "order": "volume",
        "ascending": "false"
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching Gamma markets: {e}")
        return []

def fetch_orderbook(token_id):
    """Fetch orderbook for a specific token ID."""
    url = f"{CLOB_API}/book"
    params = {"token_id": token_id}
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching orderbook for token {token_id}: {e}")
        return None

def fetch_leaderboard(timeframe="today"):
    """Fetch leaderboard data."""
    # Note: Leaderboard data would need to be scraped or obtained via unofficial endpoints
    # For now, we'll create a placeholder
    return {
        "timeframe": timeframe,
        "timestamp": datetime.utcnow().isoformat(),
        "data": []  # Will implement scraping if needed
    }

def save_json_data(data, directory, prefix):
    """Save data as JSON with timestamp."""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = directory / f"{prefix}_{timestamp}.json"
    
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)
    
    return filename

def collect_data():
    """Main data collection function."""
    print(f"[{datetime.utcnow().isoformat()}] Starting data collection...")
    
    # Fetch markets
    markets = fetch_gamma_markets(
        limit=MONITORING_CONFIG["max_markets_to_monitor"]
    )
    
    if markets:
        # Save markets data
        save_json_data(markets, MARKETS_DIR, "markets")
        print(f"Saved {len(markets)} markets")
        
        # Process each market for orderbook data
        for market in markets:
            question = market.get("question", "Unknown")
            clob_token_ids_str = market.get("clobTokenIds", "[]")
            
            try:
                # Parse the double-encoded JSON string
                clob_token_ids = json.loads(clob_token_ids_str)
                if isinstance(clob_token_ids, list) and len(clob_token_ids) >= 2:
                    yes_token_id = clob_token_ids[0]
                    no_token_id = clob_token_ids[1]
                    
                    # Fetch orderbooks for both outcomes
                    for outcome, token_id in [("yes", yes_token_id), ("no", no_token_id)]:
                        orderbook = fetch_orderbook(token_id)
                        if orderbook:
                            orderbook_data = {
                                "market_question": question,
                                "market_id": market.get("id"),
                                "condition_id": market.get("conditionId"),
                                "outcome": outcome,
                                "token_id": token_id,
                                "timestamp": datetime.utcnow().isoformat(),
                                "orderbook": orderbook
                            }
                            save_json_data(
                                orderbook_data, 
                                ORDERBOOK_DIR, 
                                f"orderbook_{market.get('id', 'unknown')}_{outcome}"
                            )
            except Exception as e:
                print(f"Error processing market {market.get('id', 'unknown')}: {e}")
    
    # Fetch leaderboard (placeholder for now)
    leaderboard_data = fetch_leaderboard("today")
    save_json_data(leaderboard_data, LEADERBOARD_DIR, "leaderboard")
    
    print(f"[{datetime.utcnow().isoformat()}] Data collection completed.")

def main():
    """Run continuous data collection."""
    print("Starting Polymarket Data Collector...")
    print(f"Polling interval: {MONITORING_CONFIG['polling_interval_seconds']} seconds")
    
    while True:
        try:
            collect_data()
            time.sleep(MONITORING_CONFIG["polling_interval_seconds"])
        except KeyboardInterrupt:
            print("\nShutting down data collector...")
            break
        except Exception as e:
            print(f"Unexpected error in main loop: {e}")
            time.sleep(5)  # Brief pause before retrying

if __name__ == "__main__":
    main()
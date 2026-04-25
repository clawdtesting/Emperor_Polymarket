#!/usr/bin/env python3
"""
Leaderboard Collector for Polymarket
Extracts leaderboard data from the __NEXT_DATA__ script tag in the HTML.
"""

import json
import re
from datetime import datetime
from pathlib import Path
import sys
import requests

def extract_leaderboard_from_html(html, timeframe="today"):
    """Extract leaderboard data from the HTML by finding the embedded JSON."""
    try:
        # Find all script tags with type="application/json"
        script_tags = re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL)
        for script in script_tags:
            try:
                data = json.loads(script)
                # Check if this is the __NEXT_DATA__ by looking for props
                if isinstance(data, dict) and 'props' in data:
                    props = data.get('props', {})
                    page_props = props.get('pageProps', {})
                    dehydrated = page_props.get('dehydratedState', {})
                    queries = dehydrated.get('queries', [])
                    for query in queries:
                        if isinstance(query, dict) and 'state' in query:
                            state = query['state']
                            if 'data' in state:
                                data_field = state['data']
                                if isinstance(data_field, list) and len(data_field) > 0:
                                    first_item = data_field[0]
                                    if isinstance(first_item, dict) and 'rank' in first_item and 'pnl' in first_item:
                                        # Found leaderboard data
                                        leaders = []
                                        for item in data_field:
                                            leaders.append({
                                                'rank': item.get('rank'),
                                                'username': item.get('name') or item.get('pseudonym') or item.get('proxyWallet', '')[:10] + '...',
                                                'address': item.get('proxyWallet'),
                                                'profit': float(item.get('pnl', 0)),
                                                'volume': float(item.get('amount', 0)),  # amount seems to be the volume/staked
                                                'raw_data': item
                                            })
                                        return leaders
            except json.JSONDecodeError:
                continue
            except Exception as e:
                # Continue to next script if this one fails
                continue
        # If we didn't find any leaderboard data, return empty list
        return []
    except Exception as e:
        print(f"Error extracting leaderboard data: {e}")
        return []

def fetch_leaderboard_page(timeframe="today"):
    """Fetch the leaderboard page for a given timeframe."""
    url = f"https://polymarket.com/leaderboard?timeframe={timeframe}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def main():
    """Main function to collect leaderboard data for all timeframes."""
    print("=== Leaderboard Collector (final version) ===")
    
    timeframes = ["today", "weekly", "monthly", "all"]
    all_data = []
    
    for tf in timeframes:
        print(f"Fetching {tf} leaderboard...")
        html = fetch_leaderboard_page(tf)
        if html is None:
            print(f"  Failed to fetch {tf} leaderboard")
            data = []
        else:
            data = extract_leaderboard_from_html(html, timeframe=tf)
            print(f"  Found {len(data)} entries")
        all_data.append(data)
        
        # Save each timeframe separately
        project_root = Path(__file__).parent.parent
        data_dir = project_root / "data" / "leaderboard"
        data_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = data_dir / f"leaderboard_{tf}_{timestamp}.json"
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"  Saved {tf} leaderboard to {filename}")
    
    # Also save a combined file
    combined_data = {
        'timestamp': datetime.utcnow().isoformat(),
        'timeframes': dict(zip(timeframes, all_data))
    }
    project_root = Path(__file__).parent.parent
    data_dir = project_root / "data" / "leaderboard"
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    combined_file = data_dir / f"leaderboard_combined_{timestamp}.json"
    
    with open(combined_file, 'w') as f:
        json.dump(combined_data, f, indent=2)
    
    print(f"Saved combined leaderboard to {combined_file}")
    
    # Print a summary of what we found
    print("\n=== Summary ===")
    for tf, data in zip(timeframes, all_data):
        print(f"{tf.capitalize():<8}: {len(data)} traders")
        if data:
            top_trader = data[0]
            print(f"         Top: {top_trader.get('username')} (+${top_trader.get('profit', 0):,.2f})")

if __name__ == "__main__":
    main()
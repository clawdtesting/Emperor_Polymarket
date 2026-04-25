#!/usr/bin/env python3
"""
Leaderboard Collector that extracts data from Polymarket leaderboard page
by parsing the embedded JSON data.
"""

import json
import re
from datetime import datetime
from pathlib import Path
import sys
import requests

def extract_leaderboard_from_html(html):
    """Extract leaderboard data from the HTML by finding the embedded JSON."""
    try:
        # Look for the __NEXT_DATA__ script tag which contains the props
        next_data_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
        if next_data_match:
            json_str = next_data_match.group(1)
            data = json.loads(json_str)
            # Navigate to the leaderboard data in the props
            # Based on the earlier HTML we saw, the data is in props.pageProps or similar
            props = data.get('props', {})
            page_props = props.get('pageProps', {})
            
            # Look for leaderboard data in various possible locations
            # Try to find the dehydrated state or direct leaderboard data
            leaderboard_data = None
            
            # Check if there's a dehydratedState in the props
            if 'dehydratedState' in page_props:
                dehydrated = page_props['dehydratedState']
                queries = dehydrated.get('queries', [])
                for query in queries:
                    if isinstance(query, dict) and 'state' in query:
                        state_data = query['state'].get('data')
                        if isinstance(state_data, list) and len(state_data) > 0:
                            # Check if this looks like leaderboard data
                            first_item = state_data[0]
                            if isinstance(first_item, dict) and 'rank' in first_item and 'pnl' in first_item:
                                leaderboard_data = state_data
                                break
            
            # If not found in dehydratedState, look for direct leaderboard data
            if not leaderboard_data:
                # Look for any list that contains objects with rank and pnl
                def find_leaderboard_list(obj, path=""):
                    if isinstance(obj, list) and len(obj) > 0:
                        if all(isinstance(item, dict) and 'rank' in item and 'pnl' in item for item in obj[:3]):
                            return obj
                    elif isinstance(obj, dict):
                        for key, value in obj.items():
                            result = find_leaderboard_list(value, f"{path}.{key}")
                            if result is not None:
                                return result
                    return None
                
                leaderboard_data = find_leaderboard_list(page_props)
            
            # If still not found, look in the entire data structure
            if not leaderboard_data:
                leaderboard_data = find_leaderboard_list(data)
            
            if leaderboard_data:
                # Convert to our standard format
                leaders = []
                for item in leaderboard_data:
                    leaders.append({
                        'rank': item.get('rank'),
                        'username': item.get('name') or item.get('pseudonym') or item.get('proxyWallet', '')[:10] + '...',
                        'address': item.get('proxyWallet'),
                        'profit': float(item.get('pnl', 0)),
                        'volume': float(item.get('amount', 0)),  # amount seems to be the volume/staked
                        'raw_data': item
                    })
                return leaders
        
        # If we couldn't find the data in __NEXT_DATA__, try to look for other script tags
        # that might contain the dehydrated state
        dehydrated_matches = re.findall(r'"dehydratedState":({.*?})', html)
        for match in dehydrated_matches:
            try:
                dehydrated_data = json.loads(match)
                queries = dehydrated_data.get('queries', [])
                for query in queries:
                    if isinstance(query, dict) and 'state' in query:
                        state_data = query['state'].get('data')
                        if isinstance(state_data, list) and len(state_data) > 0:
                            first_item = state_data[0]
                            if isinstance(first_item, dict) and 'rank' in first_item and 'pnl' in first_item:
                                leaders = []
                                for item in state_data:
                                    leaders.append({
                                        'rank': item.get('rank'),
                                        'username': item.get('name') or item.get('pseudonym') or item.get('proxyWallet', '')[:10] + '...',
                                        'address': item.get('proxyWallet'),
                                        'profit': float(item.get('pnl', 0)),
                                        'volume': float(item.get('amount', 0)),
                                        'raw_data': item
                                    })
                                return leaders
            except:
                continue
        
        # If all else fails, return an empty list
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
    print("=== Leaderboard Collector (JSON extraction) ===")
    
    timeframes = ["today", "weekly", "monthly", "all"]
    all_data = []
    
    for tf in timeframes:
        print(f"Fetching {tf} leaderboard...")
        html = fetch_leaderboard_page(tf)
        if html is None:
            print(f"  Failed to fetch {tf} leaderboard")
            data = []
        else:
            data = extract_leaderboard_from_html(html)
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
#!/usr/bin/env python3
"""
Leaderboard Collector using browser tool to extract data from Polymarket leaderboard page.
"""

import json
import os
from datetime import datetime
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def collect_leaderboard(timeframe="today"):
    """
    Collect leaderboard data for a given timeframe using the browser tool.
    Returns a list of trader dicts.
    """
    from hermes_tools import browser_navigate, browser_snapshot, browser_console
    
    url = f"https://polymarket.com/leaderboard?timeframe={timeframe}"
    print(f"Fetching leaderboard for {timeframe} from {url}")
    
    try:
        # Navigate to the leaderboard page
        browser_navigate({"url": url})
        # Wait a bit for content to load - we can't sleep, but we can try to take snapshot and then console
        # Take a snapshot to ensure content is loaded (though not strictly necessary for console)
        browser_snapshot({"full": False})
        
        # Use browser_console to extract the leaderboard data from the page.
        # We'll try to get the data from the React component's props or from the dehydrated state.
        # The leaderboard data is likely stored in the window.__NEXT_DATA__ or in the dehydratedState.
        # We'll try to get the props from the page.
        
        js_expression = """
        (function() {
            // Try to get the dehydrated state from the page
            const scripts = Array.from(document.querySelectorAll('script'));
            for (const script of scripts) {
                if (script.textContent && script.textContent.includes('\"dehydratedState\"')) {
                    try {
                        const match = script.textContent.match(/\"dehydratedState\":({.*?})/);
                        if (match) {
                            return JSON.parse(match[1]);
                        }
                    } catch (e) { }
                }
            }
            // Try to get the props from the page
            const propsScript = document.querySelector('script#__NEXT_DATA__');
            if (propsScript && propsScript.textContent) {
                try {
                    const data = JSON.parse(propsScript.textContent);
                    return data.props || {};
                } catch (e) { }
            }
            // Fallback: try to get the leaderboard table from the DOM
            const table = document.querySelector('table');
            if (table) {
                const rows = Array.from(table.querySelectorAll('tr'));
                const data = [];
                for (const row of rows) {
                    const cols = Array.from(row.querySelectorAll('td, th'));
                    if (cols.length >= 4) {
                        data.push({
                            rank: cols[0]?.innerText.trim(),
                            username: cols[1]?.innerText.trim(),
                            profit: cols[2]?.innerText.trim(),
                            volume: cols[3]?.innerText.trim()
                        });
                    }
                }
                return data;
            }
            return null;
        })();
        """
        
        console_result = browser_console({"expression": js_expression, "clear": False})
        data = console_result.get('result')
        
        if data is None:
            print(f"  Warning: Could not extract leaderboard data for {timeframe}")
            return []
        
        # If we got the dehydrated state, we need to extract the leaderboard data from it.
        if isinstance(data, dict) and 'dehydratedState' in data:
            # The dehydrated state contains queries. We need to find the leaderboard query.
            queries = data.get('dehydratedState', {}).get('queries', [])
            for query in queries:
                if isinstance(query, dict) and query.get('state', {}).get('data'):
                    state_data = query['state']['data']
                    if isinstance(state_data, list) and len(state_data) > 0 and isinstance(state_data[0], dict):
                        # Check if this looks like leaderboard data (has rank, proxyWallet, pnl, etc.)
                        first_item = state_data[0]
                        if 'rank' in first_item and 'pnl' in first_item and 'proxyWallet' in first_item:
                            # This is likely the leaderboard data
                            leaders = []
                            for item in state_data:
                                leaders.append({
                                    'rank': item.get('rank'),
                                    'username': item.get('name') or item.get('pseudonym') or item.get('proxyWallet', '')[:10],
                                    'address': item.get('proxyWallet'),
                                    'profit': float(item.get('pnl', 0)),
                                    'volume': float(item.get('amount', 0)),  # amount seems to be the volume/staked
                                    'raw_data': item
                                })
                            return leaders
            # If we didn't find it in queries, try to look for it elsewhere
            # Let's just return the dehydrated state for inspection
            return [{'dehydrated_state': data}]
        elif isinstance(data, dict) and 'props' in data:
            # We got props, look for leaderboard data in there
            props = data['props']
            # Try to find pageProps or leaderboard data
            if 'pageProps' in props:
                pageProps = props['pageProps']
                # Look for leaderboard data in pageProps
                for key, value in pageProps.items():
                    if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
                        first_item = value[0]
                        if 'rank' in first_item and 'pnl' in first_item:
                            leaders = []
                            for item in value:
                                leaders.append({
                                    'rank': item.get('rank'),
                                    'username': item.get('name') or item.get('pseudonym') or item.get('proxyWallet', '')[:10],
                                    'address': item.get('proxyWallet'),
                                    'profit': float(item.get('pnl', 0)),
                                    'volume': float(item.get('amount', 0)),
                                    'raw_data': item
                                })
                            return leaders
            # If not found, return the props for inspection
            return [{'props': props}]
        elif isinstance(data, list):
            # We got a list directly, assume it's the leaderboard data
            leaders = []
            for item in data:
                if isinstance(item, dict):
                    leaders.append({
                        'rank': item.get('rank'),
                        'username': item.get('name') or item.get('pseudonym') or item.get('proxyWallet', '')[:10],
                        'address': item.get('proxyWallet'),
                        'profit': float(item.get('pnl', 0) or item.get('profit', 0)),
                        'volume': float(item.get('amount', 0) or item.get('volume', 0)),
                        'raw_data': item
                    })
            return leaders
        else:
            # Return the raw data for inspection
            return [{'raw_data': data}]
        
    except Exception as e:
        print(f"Error collecting leaderboard for {timeframe}: {e}")
        import traceback
        traceback.print_exc()
        return []

def main():
    """Main function to collect leaderboard data for all timeframes."""
    print("=== Leaderboard Collector (using browser tool) ===")
    
    timeframes = ["today", "weekly", "monthly", "all"]
    all_data = []
    
    for tf in timeframes:
        data = collect_leaderboard(tf)
        all_data.append(data)
        # Save each timeframe separately
        project_root = Path(__file__).parent.parent
        data_dir = project_root / "data" / "leaderboard"
        data_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = data_dir / f"leaderboard_{tf}_{timestamp}.json"
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"Saved {tf} leaderboard to {filename}")
        print(f"  Found {len(data)} entries (if list of traders) or complex data")
    
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

if __name__ == "__main__":
    main()
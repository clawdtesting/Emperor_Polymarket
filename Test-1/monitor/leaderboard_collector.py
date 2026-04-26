#!/usr/bin/env python3
"""
Leaderboard Collector for Polymarket
Uses browser tool to scrape leaderboard data and save it.
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
    Returns a dict with the leaderboard data.
    """
    from hermes_tools import browser_navigate, browser_snapshot, browser_vision
    
    url = f"https://polymarket.com/leaderboard?timeframe={timeframe}"
    print(f"Fetching leaderboard for {timeframe} from {url}")
    
    try:
        # Navigate to the leaderboard page
        browser_navigate({"url": url})
        # Wait a bit for dynamic content to load (we can't sleep in the tool, but we can try to take snapshot immediately)
        # Take a snapshot of the page
        snapshot_result = browser_snapshot({"full": False})
        # Also try to get the text content for parsing
        # We'll use browser_console to get the inner text of the page? Alternatively, we can use browser_vision to describe the page.
        # For now, let's try to extract the table from the snapshot.
        # The snapshot returns a text-based accessibility tree.
        # We'll parse that to extract the leaderboard table.
        
        # We'll also try to get the page content via browser_console with an expression to get the innerText of the body.
        try:
            console_result = browser_console({"expression": "document.body.innerText", "clear": False})
            page_text = console_result.get('result', '')
        except:
            page_text = ""
        
        # If we couldn't get the innerText, we'll use the snapshot text
        if not page_text:
            page_text = snapshot_result.get('snapshot', '')
        
        # Now parse the page_text to extract the leaderboard table.
        # This is a simplified parser. We'll look for lines that look like rank, username, profit, volume.
        # We'll assume the table has a header and then rows.
        
        lines = page_text.split('\n')
        leaderboard_data = []
        
        # We'll look for the start of the table. The header might contain words like "Rank", "Username", "Profit/Loss", "Volume"
        # We'll try to find a line that contains these words.
        header_found = False
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if 'rank' in line_lower and 'username' in line_lower and ('profit' in line_lower or 'volume' in line_lower):
                # Found header, now parse the following lines until we hit a non-data line or another header
                j = i + 1
                while j < len(lines):
                    data_line = lines[j].strip()
                    # Skip empty lines
                    if not data_line:
                        j += 1
                        continue
                    # If we hit another header or a separator, break
                    if any(h in data_line.lower() for h in ['rank', 'username', 'profit', 'volume', 'today', 'weekly', 'monthly', 'all']):
                        break
                    # Try to parse the data line
                    # We'll split by spaces and try to extract the fields.
                    # This is a very simplistic approach and might break if the format changes.
                    parts = data_line.split()
                    if len(parts) >= 4:
                        # Assume format: Rank Username Profit Volume
                        # But note: the username might have spaces, and the profit and volume might have symbols.
                        # We'll try to be more robust by looking for patterns.
                        # For now, we'll just take the first 4 parts and assume the username is the second part (if the first is rank).
                        # This is not ideal but works for now.
                        rank = parts[0]
                        # The username might be multiple parts until we see a number (profit) or a currency symbol.
                        # We'll do a simple approach: join parts[1:-2] as username, and the last two are profit and volume.
                        if len(parts) > 4:
                            username = ' '.join(parts[1:-2])
                            profit_str = parts[-2]
                            volume_str = parts[-1]
                        else:
                            username = parts[1]
                            profit_str = parts[2]
                            volume_str = parts[3]
                        
                        # Clean the profit and volume strings: remove $, +, , and convert to float
                        def clean_currency(s):
                            s = s.replace('$', '').replace(',', '').replace('+', '')
                            try:
                                return float(s)
                            except:
                                return 0.0
                        
                        profit = clean_currency(profit_str)
                        volume = clean_currency(volume_str)
                        
                        leaderboard_data.append({
                            'rank': rank,
                            'username': username,
                            'profit': profit,
                            'volume': volume,
                            'raw_line': data_line
                        })
                    j += 1
                break
        
        # If we didn't find any data with the above method, let's try a different approach: look for lines that contain a dollar sign and a number.
        if not leaderboard_data:
            for line in lines:
                if '$' in line and any(c.isdigit() for c in line):
                    # Try to extract a row
                    parts = line.split()
                    if len(parts) >= 4:
                        # Heuristic: look for a part that is a number (rank) at the beginning
                        if parts[0].isdigit():
                            rank = parts[0]
                            # Then look for a part that starts with $ (profit) and another for volume
                            # This is still heuristic.
                            username = ' '.join(parts[1:-2])
                            profit_str = parts[-2]
                            volume_str = parts[-1]
                            profit = clean_currency(profit_str)
                            volume = clean_currency(volume_str)
                            leaderboard_data.append({
                                'rank': rank,
                                'username': username,
                                'profit': profit,
                                'volume': volume,
                                'raw_line': line
                            })
        
        result = {
            'timeframe': timeframe,
            'timestamp': datetime.utcnow().isoformat(),
            'data': leaderboard_data,
            'source': 'browser_scrape',
            'note': 'Leaderboard data scraped from Polymarket leaderboard page using browser tool.'
        }
        
        return result
        
    except Exception as e:
        print(f"Error collecting leaderboard for {timeframe}: {e}")
        return {
            'timeframe': timeframe,
            'timestamp': datetime.utcnow().isoformat(),
            'data': [],
            'error': str(e)
        }

def main():
    """Main function to collect leaderboard data for all timeframes."""
    print("=== Leaderboard Collector ===")
    
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
        print(f"  Found {len(data.get('data', []))} entries")
    
    # Also save a combined file
    combined_data = {
        'timestamp': datetime.utcnow().isoformat(),
        'timeframes': all_data
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
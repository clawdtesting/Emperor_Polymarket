#!/usr/bin/env python3
"""
Polymarket to ClickHouse ingestion pipeline.

Architecture:
- WebSocket: Real-time price updates, trades
- HTTP Polling: Market metadata, orderbook snapshots (every 60s)
- Subgraph: Historical backfill, user positions (daily)

Usage:
    python ingest.py --clickhouse-host localhost --mode all
    
    # Or run individual components:
    python ingest.py --mode stream  # WebSocket only
    python ingest.py --mode poll    # HTTP polling only
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import List, Dict, Any
from dataclasses import dataclass

import aiohttp
import websockets
from clickhouse_driver import Client

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

CLOB_API_BASE = "https://clob.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com"

CLICKHOUSE_HOST = "localhost"
CLICKHOUSE_DATABASE = "polymarket"


# ============================================================================
# DATA CLIENTS
# ============================================================================

class PolymarketAPI:
    """HTTP API client for Polymarket CLOB and Gamma APIs."""
    
    def __init__(self):
        self.clob_base = CLOB_API_BASE
        self.gamma_base = GAMMA_API_BASE
        
    async def get_markets(self) -> List[Dict]:
        """Fetch all active markets from Gamma API."""
        async with aiohttp.ClientSession() as session:
            url = f"{self.gamma_base}/markets"
            async with session.get(url, params={'active': 'true'}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info(f"Fetched {len(data)} markets")
                    return data
                else:
                    logger.error(f"Failed to fetch markets: {resp.status}")
                    return []
    
    async def get_orderbook(self, token_id: str) -> Dict:
        """Fetch orderbook for a specific market."""
        async with aiohttp.ClientSession() as session:
            url = f"{self.clob_base}/book"
            params = {'token_id': token_id}
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.warning(f"Failed to fetch orderbook for {token_id}: {resp.status}")
                    return {}
    
    async def get_ticker(self, market_id: str) -> Dict:
        """Fetch 24h ticker data."""
        async with aiohttp.ClientSession() as session:
            url = f"{self.clob_base}/ticker"
            params = {'market': market_id}
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {}


class ClickHouseWriter:
    """Batched writer for ClickHouse."""
    
    def __init__(self, host: str = CLICKHOUSE_HOST):
        self.client = Client(host=host)
        self.batch_size = 1000
        
        # Batch buffers
        self.markets_batch = []
        self.trades_batch = []
        self.orderbook_batch = []
        self.ticker_batch = []
        
    def insert_markets(self, markets: List[Dict]):
        """Insert or update markets."""
        data = []
        for m in markets:
            data.append((
                m.get('id', ''),
                m.get('token_id', ''),
                m.get('condition_id', ''),
                m.get('question', ''),
                m.get('description', ''),
                m.get('category', ''),
                m.get('subcategory', ''),
                datetime.fromisoformat(m.get('end_date', '').replace('Z', '+00:00')) if m.get('end_date') else datetime.now(),
                m.get('resolution_source', ''),
                float(m.get('yes_price', 0)),
                float(m.get('no_price', 0)),
                float(m.get('last_trade_price', 0)),
                float(m.get('volume_24h', 0)),
                float(m.get('volume', 0)),
                float(m.get('liquidity', 0)),
                float(m.get('open_interest', 0)),
                int(m.get('num_traders', 0)),
                int(m.get('num_trades_24h', 0)),
                m.get('active', True),
                m.get('closed', False),
                m.get('resolved', False),
                m.get('winning_outcome'),
                datetime.fromisoformat(m.get('resolution_date', '').replace('Z', '+00:00')) if m.get('resolution_date') else None,
                datetime.fromisoformat(m.get('created_at', '').replace('Z', '+00:00')) if m.get('created_at') else datetime.now(),
                datetime.now(),  # updated_at
                m.get('tags', []),
            ))
        
        if data:
            self.client.execute(
                'INSERT INTO polymarket.markets VALUES',
                data
            )
            logger.info(f"Inserted {len(data)} markets")
    
    def insert_trades(self, trades: List[Dict]):
        """Insert trades."""
        data = []
        for t in trades:
            data.append((
                t.get('id', ''),
                t.get('market_id', ''),
                datetime.fromisoformat(t.get('timestamp', '').replace('Z', '+00:00')),
                t.get('outcome', 'yes'),
                t.get('side', 'buy'),
                float(t.get('price', 0)),
                float(t.get('size', 0)),
                t.get('maker_address', ''),
                t.get('taker_address', ''),
                t.get('transaction_hash', ''),
                float(t.get('fee', 0)),
            ))
        
        if data:
            self.client.execute(
                'INSERT INTO polymarket.trades VALUES',
                data
            )
            logger.info(f"Inserted {len(data)} trades")
    
    def insert_orderbook(self, market_id: str, orderbook: Dict):
        """Insert orderbook snapshot."""
        data = []
        timestamp = datetime.now()
        
        # Process bids (buy orders)
        for outcome in ['yes', 'no']:
            bids = orderbook.get(outcome, {}).get('bids', [])
            cumulative = 0
            for level, (price, size) in enumerate(bids):
                cumulative += size
                data.append((
                    market_id,
                    timestamp,
                    outcome,
                    'buy',
                    level,
                    float(price),
                    float(size),
                    cumulative,
                ))
        
        # Process asks (sell orders)
        for outcome in ['yes', 'no']:
            asks = orderbook.get(outcome, {}).get('asks', [])
            cumulative = 0
            for level, (price, size) in enumerate(asks):
                cumulative += size
                data.append((
                    market_id,
                    timestamp,
                    outcome,
                    'sell',
                    level,
                    float(price),
                    float(size),
                    cumulative,
                ))
        
        if data:
            self.client.execute(
                'INSERT INTO polymarket.orderbook VALUES',
                data
            )
    
    def insert_ticker(self, market_id: str, outcome: str, ticker: Dict):
        """Insert ticker snapshot."""
        data = [(
            market_id,
            datetime.now(),
            outcome,
            float(ticker.get('price', 0)),
            float(ticker.get('bid', 0)),
            float(ticker.get('ask', 0)),
            float(ticker.get('spread', 0)),
            float(ticker.get('volume_1h', 0)),
            float(ticker.get('volume_24h', 0)),
            int(ticker.get('num_trades_1h', 0)),
            datetime.now(),
        )]
        
        self.client.execute(
            'INSERT INTO polymarket.ticker VALUES',
            data
        )


# ============================================================================
# INGESTION WORKERS
# ============================================================================

class PollingWorker:
    """HTTP polling for markets and orderbooks."""
    
    def __init__(self, api: PolymarketAPI, writer: ClickHouseWriter):
        self.api = api
        self.writer = writer
        self.poll_interval = 60  # seconds
        
    async def run(self):
        """Main polling loop."""
        logger.info("Starting polling worker...")
        
        while True:
            try:
                # Fetch and insert markets
                markets = await self.api.get_markets()
                if markets:
                    self.writer.insert_markets(markets)
                
                # Fetch orderbooks for active markets (sample top 100 by volume)
                top_markets = sorted(
                    markets,
                    key=lambda m: m.get('volume_24h', 0),
                    reverse=True
                )[:100]
                
                for market in top_markets:
                    token_id = market.get('token_id')
                    if token_id:
                        orderbook = await self.api.get_orderbook(token_id)
                        if orderbook:
                            self.writer.insert_orderbook(market['id'], orderbook)
                
                logger.info(f"Polling cycle complete. Sleeping {self.poll_interval}s...")
                await asyncio.sleep(self.poll_interval)
                
            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(10)


class StreamingWorker:
    """WebSocket streaming for real-time price updates."""
    
    def __init__(self, writer: ClickHouseWriter):
        self.writer = writer
        self.ws_url = CLOB_WS_URL
        
    async def run(self):
        """Main streaming loop with reconnection."""
        logger.info("Starting streaming worker...")
        
        while True:
            try:
                await self._stream()
            except Exception as e:
                logger.error(f"Stream error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)
    
    async def _stream(self):
        """Connect to WebSocket and process messages."""
        async with websockets.connect(self.ws_url) as ws:
            logger.info("Connected to Polymarket WebSocket")
            
            # Subscribe to market updates
            await ws.send(json.dumps({
                'type': 'subscribe',
                'channel': 'market',
                'market_ids': ['*']  # Subscribe to all markets
            }))
            
            # Subscribe to trades
            await ws.send(json.dumps({
                'type': 'subscribe',
                'channel': 'trade',
                'market_ids': ['*']
            }))
            
            async for message in ws:
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except Exception as e:
                    logger.error(f"Message handling error: {e}")
    
    async def _handle_message(self, data: Dict):
        """Process WebSocket message."""
        msg_type = data.get('type')
        
        if msg_type == 'market':
            # Price update
            market_id = data.get('market_id')
            outcome = data.get('outcome', 'yes')
            self.writer.insert_ticker(market_id, outcome, data)
            
        elif msg_type == 'trade':
            # New trade
            self.writer.insert_trades([data])


# ============================================================================
# MAIN ORCHESTRATOR
# ============================================================================

async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Polymarket to ClickHouse ingestion')
    parser.add_argument('--clickhouse-host', default='localhost', help='ClickHouse host')
    parser.add_argument('--mode', choices=['all', 'poll', 'stream'], default='all',
                       help='Ingestion mode')
    parser.add_argument('--poll-interval', type=int, default=60,
                       help='Polling interval in seconds')
    
    args = parser.parse_args()
    
    # Initialize clients
    api = PolymarketAPI()
    writer = ClickHouseWriter(host=args.clickhouse_host)
    
    # Start workers
    tasks = []
    
    if args.mode in ['all', 'poll']:
        polling_worker = PollingWorker(api, writer)
        polling_worker.poll_interval = args.poll_interval
        tasks.append(polling_worker.run())
    
    if args.mode in ['all', 'stream']:
        streaming_worker = StreamingWorker(writer)
        tasks.append(streaming_worker.run())
    
    if not tasks:
        logger.error("No workers configured!")
        return
    
    logger.info(f"Starting {len(tasks)} workers...")
    await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())

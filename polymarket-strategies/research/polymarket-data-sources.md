# Polymarket Data Sources Research

## API Endpoints

### 1. CLOB API (Central Limit Order Book)
**Base URL:** `https://clob.polymarket.com`

Primary API for market data, orderbook, trades.

**Key endpoints:**
```
GET /markets - List all markets
GET /markets/{market_id} - Market details
GET /book - Orderbook snapshot
GET /trades - Recent trades
GET /ticker - Price ticker (24h stats)
```

### 2. Gamma API (Market Metadata)
**Base URL:** `https://gamma-api.polymarket.com`

Market questions, categories, resolution data.

**Key endpoints:**
```
GET /markets - Market metadata
GET /events - Event data (groups of related markets)
```

### 3. Strapi CMS API
**Base URL:** `https://strapi-matic.poly.market`

Content, market descriptions, curated data.

### 4. Subgraph (The Graph)
**URL:** `https://api.thegraph.com/subgraphs/name/polymarket/matic-markets`

Historical on-chain data (positions, trades, settlements).

GraphQL queries for:
- User positions
- Trade history
- Market volume
- Settlement data

### 5. WebSocket Feeds
Real-time price updates, orderbook changes.

**CLOB WebSocket:** `wss://ws-subscriptions-clob.polymarket.com`

Channels:
- `market` - Price updates
- `book` - Orderbook changes
- `trade` - Trade feed

## Data Schema

### Markets Table
```sql
CREATE TABLE polymarket.markets (
    market_id String,
    question String,
    category String,
    subcategory String,
    end_date DateTime,
    yes_price Float64,
    no_price Float64,
    volume_24h Float64,
    volume_total Float64,
    liquidity Float64,
    num_traders UInt32,
    created_at DateTime,
    updated_at DateTime,
    resolved Boolean,
    winning_outcome Nullable(String)
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (category, market_id)
PARTITION BY toYYYYMM(end_date);
```

### Orderbook Snapshots
```sql
CREATE TABLE polymarket.orderbook (
    market_id String,
    timestamp DateTime64(3),
    side Enum('buy', 'sell'),
    outcome Enum('yes', 'no'),
    price Float64,
    size Float64,
    level UInt16,  -- 0 = best bid/ask, 1 = second level, etc.
    total_size Float64  -- cumulative size at this level
) ENGINE = MergeTree()
ORDER BY (market_id, outcome, side, timestamp, level)
PARTITION BY toYYYYMMDD(timestamp);
```

### Trades
```sql
CREATE TABLE polymarket.trades (
    trade_id String,
    market_id String,
    timestamp DateTime64(3),
    outcome Enum('yes', 'no'),
    side Enum('buy', 'sell'),
    price Float64,
    size Float64,
    maker_address String,
    taker_address String
) ENGINE = MergeTree()
ORDER BY (market_id, timestamp)
PARTITION BY toYYYYMMDD(timestamp);
```

### Ticker (OHLCV + Stats)
```sql
CREATE TABLE polymarket.ticker (
    market_id String,
    timestamp DateTime,
    outcome Enum('yes', 'no'),
    open Float64,
    high Float64,
    low Float64,
    close Float64,
    volume Float64,
    num_trades UInt32,
    bid Float64,
    ask Float64,
    spread Float64
) ENGINE = ReplacingMergeTree(timestamp)
ORDER BY (market_id, outcome, timestamp)
PARTITION BY toYYYYMMDD(timestamp);
```

### User Positions (from Subgraph)
```sql
CREATE TABLE polymarket.positions (
    user_address String,
    market_id String,
    outcome Enum('yes', 'no'),
    shares Float64,
    avg_entry_price Float64,
    current_price Float64,
    unrealized_pnl Float64,
    realized_pnl Float64,
    updated_at DateTime
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (user_address, market_id, outcome);
```

## Ingestion Architecture

### Option 1: Polling (Batch)
**Pros:** Simple, reliable, works with any API  
**Cons:** Higher latency, less efficient

```python
# Every 60 seconds, fetch updates
while True:
    markets = fetch_markets()
    clickhouse.insert('polymarket.markets', markets)
    
    for market in active_markets:
        orderbook = fetch_orderbook(market.id)
        clickhouse.insert('polymarket.orderbook', orderbook)
    
    time.sleep(60)
```

### Option 2: WebSocket Streaming (Real-time)
**Pros:** Low latency, efficient  
**Cons:** More complex, needs reconnection logic

```python
async def stream_to_clickhouse():
    async with websocket_connect('wss://...') as ws:
        await ws.send(json.dumps({
            'type': 'subscribe',
            'channel': 'market',
            'market_ids': ['*']
        }))
        
        async for msg in ws:
            data = json.loads(msg)
            clickhouse.insert_async('polymarket.ticker', [data])
```

### Option 3: Hybrid (Best of Both)
- **WebSocket** for price updates, trades (real-time critical)
- **Polling** for market metadata, orderbook snapshots (lower frequency)
- **Subgraph** for historical backfill, user positions

```
WebSocket Stream ──┐
Polling (60s)    ──┼──> ClickHouse
Subgraph (daily) ──┘
```

## ClickHouse Optimizations

### Materialized Views for Analytics

**1-minute OHLCV candles:**
```sql
CREATE MATERIALIZED VIEW polymarket.candles_1m
ENGINE = SummingMergeTree()
ORDER BY (market_id, outcome, timestamp)
AS SELECT
    market_id,
    outcome,
    toStartOfMinute(timestamp) as timestamp,
    argMin(price, timestamp) as open,
    max(price) as high,
    min(price) as low,
    argMax(price, timestamp) as close,
    sum(size) as volume,
    count() as num_trades
FROM polymarket.trades
GROUP BY market_id, outcome, timestamp;
```

**Market stats (rolling 24h):**
```sql
CREATE MATERIALIZED VIEW polymarket.market_stats_24h
ENGINE = AggregatingMergeTree()
ORDER BY (market_id, hour)
AS SELECT
    market_id,
    toStartOfHour(timestamp) as hour,
    sumState(size) as volume,
    countState() as num_trades,
    uniqState(taker_address) as unique_traders,
    avgState(price) as avg_price
FROM polymarket.trades
WHERE timestamp >= now() - INTERVAL 24 HOUR
GROUP BY market_id, hour;
```

### Compression
```sql
-- Use ZSTD compression for text columns
ALTER TABLE polymarket.markets MODIFY COLUMN question String CODEC(ZSTD);
ALTER TABLE polymarket.markets MODIFY COLUMN category String CODEC(ZSTD);

-- Delta encoding for prices (efficient for time series)
ALTER TABLE polymarket.trades MODIFY COLUMN price Float64 CODEC(Delta, ZSTD);
ALTER TABLE polymarket.trades MODIFY COLUMN size Float64 CODEC(Delta, ZSTD);
```

## Ingestion Pipeline (Python)

### Dependencies
```bash
pip install clickhouse-driver websockets aiohttp graphql-client
```

### Implementation Sketch

**1. CLOB API Client:**
```python
import aiohttp
from clickhouse_driver import Client

class PolymarketCLOB:
    BASE_URL = "https://clob.polymarket.com"
    
    async def get_markets(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.BASE_URL}/markets") as resp:
                return await resp.json()
    
    async def get_orderbook(self, market_id):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.BASE_URL}/book",
                params={'market': market_id}
            ) as resp:
                return await resp.json()
```

**2. ClickHouse Inserter:**
```python
from clickhouse_driver import Client

class ClickHouseInserter:
    def __init__(self, host='localhost'):
        self.client = Client(host=host)
    
    def insert_markets(self, markets):
        data = [
            (
                m['id'],
                m['question'],
                m['category'],
                m['end_date'],
                m['yes_price'],
                m['no_price'],
                m['volume_24h'],
                # ... more fields
            )
            for m in markets
        ]
        
        self.client.execute(
            'INSERT INTO polymarket.markets VALUES',
            data
        )
    
    def insert_trades(self, trades):
        # Similar batched insert
        pass
```

**3. WebSocket Streamer:**
```python
import websockets
import json

async def stream_prices():
    uri = "wss://ws-subscriptions-clob.polymarket.com"
    
    async with websockets.connect(uri) as ws:
        # Subscribe to all markets
        await ws.send(json.dumps({
            'type': 'subscribe',
            'channel': 'market',
            'market_ids': ['*']
        }))
        
        async for message in ws:
            data = json.loads(message)
            # Insert to ClickHouse
            inserter.insert_ticker([data])
```

**4. Orchestrator:**
```python
import asyncio

async def main():
    clob = PolymarketCLOB()
    inserter = ClickHouseInserter()
    
    # Task 1: Poll markets every 60s
    async def poll_markets():
        while True:
            markets = await clob.get_markets()
            inserter.insert_markets(markets)
            await asyncio.sleep(60)
    
    # Task 2: Stream real-time prices
    async def stream():
        await stream_prices()
    
    # Run both concurrently
    await asyncio.gather(
        poll_markets(),
        stream()
    )

asyncio.run(main())
```

## Example Queries

**Top markets by volume (24h):**
```sql
SELECT 
    question,
    category,
    volume_24h,
    yes_price,
    liquidity
FROM polymarket.markets
WHERE end_date > now()
ORDER BY volume_24h DESC
LIMIT 20;
```

**Price chart data (1-hour candles):**
```sql
SELECT 
    toStartOfHour(timestamp) as hour,
    argMin(price, timestamp) as open,
    max(price) as high,
    min(price) as low,
    argMax(price, timestamp) as close,
    sum(size) as volume
FROM polymarket.trades
WHERE market_id = '...'
  AND outcome = 'yes'
  AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY hour
ORDER BY hour;
```

**Wallet analysis:**
```sql
-- Most profitable traders (last 30 days)
SELECT 
    taker_address,
    count() as num_trades,
    sum(size) as total_volume,
    -- Calculate realized PnL from positions table
FROM polymarket.trades
WHERE timestamp >= now() - INTERVAL 30 DAY
GROUP BY taker_address
ORDER BY total_volume DESC;
```

## Implementation Roadmap

1. **Phase 1: Core Infrastructure** (1 day)
   - ClickHouse schema creation
   - Basic API client
   - Batch polling ingestion

2. **Phase 2: Real-Time Streaming** (1 day)
   - WebSocket integration
   - Async pipeline
   - Error handling + reconnection

3. **Phase 3: Analytics** (1 day)
   - Materialized views
   - Query optimization
   - Dashboard queries

4. **Phase 4: Historical Backfill** (1 day)
   - Subgraph integration
   - Batch historical data import
   - Gap detection + filling

## Resources

- **Polymarket Docs:** https://docs.polymarket.com
- **CLOB API:** https://docs.polymarket.com/#clob-api
- **The Graph:** https://thegraph.com/hosted-service/subgraph/polymarket/matic-markets
- **ClickHouse Docs:** https://clickhouse.com/docs

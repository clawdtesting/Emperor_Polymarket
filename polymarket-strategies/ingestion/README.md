# Polymarket → ClickHouse Ingestion

Real-time and historical data pipeline for Polymarket prediction markets.

## Quick Start

### 1. Install ClickHouse

**Docker (easiest):**
```bash
docker run -d \
  --name clickhouse \
  -p 8123:8123 \
  -p 9000:9000 \
  clickhouse/clickhouse-server:latest
```

**Or install locally:** https://clickhouse.com/docs/en/install

### 2. Create Schema

```bash
# Connect to ClickHouse
clickhouse-client

# Run schema creation
clickhouse-client < clickhouse_schema.sql

# Verify tables created
SELECT name FROM system.tables WHERE database = 'polymarket';
```

### 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run Ingestion

**Full pipeline (polling + streaming):**
```bash
python ingest.py --clickhouse-host localhost --mode all
```

**HTTP polling only (markets + orderbooks every 60s):**
```bash
python ingest.py --mode poll --poll-interval 60
```

**WebSocket streaming only (real-time prices):**
```bash
python ingest.py --mode stream
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Polymarket APIs                        │
├──────────────────┬──────────────────┬───────────────────┤
│   CLOB REST      │   CLOB WebSocket │   The Graph       │
│   (markets, book)│   (prices, trades)│  (historical)    │
└────────┬─────────┴────────┬──────────┴─────────┬─────────┘
         │                  │                    │
         │ HTTP Polling     │ WebSocket Stream   │ GraphQL
         │ (60s interval)   │ (real-time)        │ (daily)
         │                  │                    │
         v                  v                    v
    ┌────────────────────────────────────────────────────┐
    │              ClickHouse Ingestion                   │
    │  - Batched inserts (1000 rows)                     │
    │  - Deduplication (ReplacingMergeTree)              │
    │  - Partitioning (by date, user hash)               │
    └─────────────────────┬──────────────────────────────┘
                          │
                          v
    ┌────────────────────────────────────────────────────┐
    │                  ClickHouse Tables                  │
    ├────────────────────┬───────────────────────────────┤
    │ Raw Tables         │ Materialized Views            │
    │ - markets          │ - candles_1m, 5m, 1h         │
    │ - trades           │ - daily_stats                 │
    │ - orderbook        │ - user_activity               │
    │ - ticker           │                               │
    │ - positions        │                               │
    └────────────────────┴───────────────────────────────┘
```

## Data Tables

### Raw Data
- **markets**: Market metadata (question, category, prices, volume)
- **trades**: Individual trades (price, size, participants)
- **orderbook**: Orderbook snapshots (bids/asks at each level)
- **ticker**: Price snapshots (every minute)
- **positions**: User positions (from subgraph)

### Materialized Views (Auto-Updated)
- **candles_1m, 5m, 1h**: OHLCV candles at different intervals
- **daily_stats**: Daily volume, trades, unique traders per market
- **user_activity**: Daily trading activity per user

## Example Queries

### Top markets by volume
```sql
SELECT 
    question,
    category,
    volume_24h,
    yes_price,
    num_traders
FROM polymarket.markets
WHERE active = 1 AND end_date > now()
ORDER BY volume_24h DESC
LIMIT 20;
```

### Price chart (1-hour candles)
```sql
SELECT 
    timestamp,
    open, high, low, close,
    volume
FROM polymarket.candles_1h
WHERE market_id = '0x...'
  AND outcome = 'yes'
  AND timestamp >= now() - INTERVAL 7 DAY
ORDER BY timestamp;
```

### Most active wallets (30 days)
```sql
SELECT 
    user_address,
    sum(num_trades) as total_trades,
    sum(total_volume) as total_volume,
    count(DISTINCT date) as days_active
FROM polymarket.user_activity
WHERE date >= today() - 30
GROUP BY user_address
ORDER BY total_volume DESC
LIMIT 100;
```

### Market momentum (biggest movers, last hour)
```sql
WITH recent AS (
    SELECT 
        market_id,
        argMax(close, timestamp) as current,
        argMin(close, timestamp) as hour_ago
    FROM polymarket.candles_1h
    WHERE timestamp >= now() - INTERVAL 1 HOUR
    GROUP BY market_id
)
SELECT 
    m.question,
    r.current,
    r.hour_ago,
    (r.current - r.hour_ago) / r.hour_ago * 100 as pct_change,
    m.volume_24h
FROM recent r
JOIN polymarket.markets m ON r.market_id = m.market_id
WHERE m.active = 1
ORDER BY abs(pct_change) DESC
LIMIT 20;
```

## Performance

**Storage estimates** (1 year):
- Markets: ~50K markets × 1KB = 50 MB
- Trades: ~100M trades × 200 bytes = 20 GB
- Orderbook: ~50K markets × 100 snapshots/day × 10 levels × 50 bytes = 2.5 GB
- Candles (1m): ~50K markets × 525,600 minutes × 50 bytes = 1.3 TB (compressed: ~130 GB)

**Query performance** (on standard hardware):
- Market listing: <10ms
- Price charts (7 days): <50ms
- User analysis (30 days): <100ms
- Full market scan: <1s

**Ingestion rate:**
- Polling: ~100 markets/minute
- Streaming: ~1000 events/second (peak)
- Batched inserts: 1000-row batches

## Monitoring

Check ingestion status:
```sql
-- Trades per hour (should be relatively steady)
SELECT 
    toStartOfHour(timestamp) as hour,
    count() as num_trades
FROM polymarket.trades
WHERE timestamp >= now() - INTERVAL 24 HOUR
GROUP BY hour
ORDER BY hour;

-- Latest data timestamps
SELECT 
    'markets' as table,
    max(updated_at) as latest
FROM polymarket.markets
UNION ALL
SELECT 
    'trades',
    max(timestamp)
FROM polymarket.trades
UNION ALL
SELECT 
    'ticker',
    max(timestamp)
FROM polymarket.ticker;
```

## Troubleshooting

**No data appearing:**
- Check ClickHouse is running: `clickhouse-client --query "SELECT 1"`
- Check ingestion script logs for errors
- Verify API connectivity: `curl https://clob.polymarket.com/markets`

**Slow queries:**
- Ensure partitions are used (query by date range)
- Check index usage: `EXPLAIN SELECT ...`
- Consider adding more indexes or materialized views

**High storage usage:**
- Configure TTL for orderbook snapshots: `ALTER TABLE polymarket.orderbook MODIFY TTL timestamp + INTERVAL 30 DAY`
- Drop old partitions: `ALTER TABLE polymarket.trades DROP PARTITION '202401'`

## Next Steps

1. **Historical backfill:** Fetch past trades from The Graph subgraph
2. **Dashboard:** Build Grafana/Metabase visualization
3. **Alerts:** Set up ClickHouse alerts for price movements, volume spikes
4. **Export:** Stream data to strategy execution layer

See `../research/polymarket-data-sources.md` for detailed API documentation.

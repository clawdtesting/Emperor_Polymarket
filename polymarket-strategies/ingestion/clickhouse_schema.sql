-- ClickHouse schema for Polymarket data
-- Run this to create all tables and materialized views

CREATE DATABASE IF NOT EXISTS polymarket;

-- ============================================================================
-- RAW DATA TABLES
-- ============================================================================

-- Markets metadata
CREATE TABLE IF NOT EXISTS polymarket.markets (
    market_id String,
    token_id String,
    condition_id String,
    question String,
    description String,
    category LowCardinality(String),
    subcategory LowCardinality(String),
    end_date DateTime,
    resolution_source String,
    
    -- Pricing
    yes_price Float64,
    no_price Float64,
    last_trade_price Float64,
    
    -- Volume & liquidity
    volume_24h Float64,
    volume_total Float64,
    liquidity Float64,
    open_interest Float64,
    
    -- Activity
    num_traders UInt32,
    num_trades_24h UInt32,
    
    -- Status
    active Boolean,
    closed Boolean,
    resolved Boolean,
    winning_outcome Nullable(String),
    resolution_date Nullable(DateTime),
    
    -- Metadata
    created_at DateTime,
    updated_at DateTime,
    tags Array(String)
    
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (category, market_id)
PARTITION BY toYYYYMM(end_date)
SETTINGS index_granularity = 8192;

-- Orderbook snapshots
CREATE TABLE IF NOT EXISTS polymarket.orderbook (
    market_id String,
    snapshot_time DateTime64(3),
    
    outcome Enum8('yes' = 1, 'no' = 2),
    side Enum8('buy' = 1, 'sell' = 2),
    
    -- Order levels (0 = best, 1 = second best, etc.)
    level UInt16,
    price Float64,
    size Float64,
    
    -- Cumulative size at this level and better
    cumulative_size Float64
    
) ENGINE = MergeTree()
ORDER BY (market_id, outcome, side, snapshot_time, level)
PARTITION BY toYYYYMMDD(snapshot_time)
TTL snapshot_time + INTERVAL 30 DAY  -- Keep 30 days of orderbook data
SETTINGS index_granularity = 8192;

-- Individual trades
CREATE TABLE IF NOT EXISTS polymarket.trades (
    trade_id String,
    market_id String,
    timestamp DateTime64(3),
    
    outcome Enum8('yes' = 1, 'no' = 2),
    side Enum8('buy' = 1, 'sell' = 2),
    
    price Float64,
    size Float64,
    
    -- Participants
    maker_address String,
    taker_address String,
    
    -- Transaction details
    transaction_hash String,
    fee Float64
    
) ENGINE = MergeTree()
ORDER BY (market_id, timestamp)
PARTITION BY toYYYYMMDD(timestamp)
SETTINGS index_granularity = 8192;

-- Price ticker (snapshots every minute)
CREATE TABLE IF NOT EXISTS polymarket.ticker (
    market_id String,
    timestamp DateTime,
    outcome Enum8('yes' = 1, 'no' = 2),
    
    price Float64,
    bid Float64,
    ask Float64,
    spread Float64,
    
    volume_1h Float64,
    volume_24h Float64,
    num_trades_1h UInt32,
    
    updated_at DateTime
    
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (market_id, outcome, timestamp)
PARTITION BY toYYYYMMDD(timestamp)
SETTINGS index_granularity = 8192;

-- User positions (from subgraph)
CREATE TABLE IF NOT EXISTS polymarket.positions (
    user_address String,
    market_id String,
    outcome Enum8('yes' = 1, 'no' = 2),
    
    -- Position details
    shares Float64,
    avg_entry_price Float64,
    total_invested Float64,
    
    -- Current state
    current_price Float64,
    current_value Float64,
    unrealized_pnl Float64,
    realized_pnl Float64,
    
    -- Activity
    num_trades UInt32,
    first_trade_at DateTime,
    last_trade_at DateTime,
    
    updated_at DateTime
    
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (user_address, market_id, outcome)
PARTITION BY cityHash64(user_address) % 10  -- Distribute by user hash
SETTINGS index_granularity = 8192;

-- ============================================================================
-- MATERIALIZED VIEWS (PRE-AGGREGATED ANALYTICS)
-- ============================================================================

-- 1-minute OHLCV candles
CREATE MATERIALIZED VIEW IF NOT EXISTS polymarket.candles_1m
ENGINE = SummingMergeTree()
ORDER BY (market_id, outcome, timestamp)
PARTITION BY toYYYYMMDD(timestamp)
AS SELECT
    market_id,
    outcome,
    toStartOfMinute(timestamp) as timestamp,
    
    argMin(price, timestamp) as open,
    max(price) as high,
    min(price) as low,
    argMax(price, timestamp) as close,
    
    sum(size) as volume,
    count() as num_trades,
    
    uniq(taker_address) as unique_buyers
FROM polymarket.trades
GROUP BY market_id, outcome, timestamp;

-- 5-minute candles
CREATE MATERIALIZED VIEW IF NOT EXISTS polymarket.candles_5m
ENGINE = SummingMergeTree()
ORDER BY (market_id, outcome, timestamp)
PARTITION BY toYYYYMMDD(timestamp)
AS SELECT
    market_id,
    outcome,
    toStartOfFiveMinutes(timestamp) as timestamp,
    
    argMin(price, timestamp) as open,
    max(price) as high,
    min(price) as low,
    argMax(price, timestamp) as close,
    
    sum(size) as volume,
    count() as num_trades,
    uniq(taker_address) as unique_buyers
FROM polymarket.trades
GROUP BY market_id, outcome, timestamp;

-- 1-hour candles
CREATE MATERIALIZED VIEW IF NOT EXISTS polymarket.candles_1h
ENGINE = SummingMergeTree()
ORDER BY (market_id, outcome, timestamp)
PARTITION BY toYYYYMM(timestamp)
AS SELECT
    market_id,
    outcome,
    toStartOfHour(timestamp) as timestamp,
    
    argMin(price, timestamp) as open,
    max(price) as high,
    min(price) as low,
    argMax(price, timestamp) as close,
    
    sum(size) as volume,
    count() as num_trades,
    uniq(taker_address) as unique_buyers
FROM polymarket.trades
GROUP BY market_id, outcome, timestamp;

-- Daily market statistics
CREATE MATERIALIZED VIEW IF NOT EXISTS polymarket.daily_stats
ENGINE = SummingMergeTree()
ORDER BY (market_id, date)
AS SELECT
    market_id,
    toDate(timestamp) as date,
    
    sum(size) as volume,
    count() as num_trades,
    uniq(taker_address) as unique_traders,
    
    avg(price) as avg_price,
    min(price) as min_price,
    max(price) as max_price,
    
    argMin(price, timestamp) as open,
    argMax(price, timestamp) as close
FROM polymarket.trades
GROUP BY market_id, date;

-- User trading activity
CREATE MATERIALIZED VIEW IF NOT EXISTS polymarket.user_activity
ENGINE = SummingMergeTree()
ORDER BY (user_address, date)
AS SELECT
    taker_address as user_address,
    toDate(timestamp) as date,
    
    count() as num_trades,
    sum(size) as total_volume,
    uniq(market_id) as unique_markets,
    
    avg(price) as avg_price
FROM polymarket.trades
GROUP BY user_address, date;

-- ============================================================================
-- INDEXES FOR FAST QUERIES
-- ============================================================================

-- Index on market category for filtering
ALTER TABLE polymarket.markets ADD INDEX idx_category category TYPE bloom_filter GRANULARITY 1;

-- Index on trade size for large trade detection
ALTER TABLE polymarket.trades ADD INDEX idx_size size TYPE minmax GRANULARITY 1;

-- Index on user address for wallet queries
ALTER TABLE polymarket.trades ADD INDEX idx_taker taker_address TYPE bloom_filter GRANULARITY 1;
ALTER TABLE polymarket.trades ADD INDEX idx_maker maker_address TYPE bloom_filter GRANULARITY 1;

-- ============================================================================
-- COMPRESSION SETTINGS
-- ============================================================================

-- Text compression
ALTER TABLE polymarket.markets MODIFY COLUMN question String CODEC(ZSTD);
ALTER TABLE polymarket.markets MODIFY COLUMN description String CODEC(ZSTD);

-- Time series delta encoding
ALTER TABLE polymarket.trades MODIFY COLUMN price Float64 CODEC(Delta, ZSTD);
ALTER TABLE polymarket.trades MODIFY COLUMN size Float64 CODEC(Delta, ZSTD);
ALTER TABLE polymarket.ticker MODIFY COLUMN price Float64 CODEC(Delta, ZSTD);

-- ============================================================================
-- EXAMPLE QUERIES
-- ============================================================================

/*
-- Top markets by 24h volume
SELECT 
    question,
    category,
    volume_24h,
    yes_price as current_price,
    num_traders
FROM polymarket.markets
WHERE active = 1 AND end_date > now()
ORDER BY volume_24h DESC
LIMIT 20;

-- Price chart (1h candles, last 7 days)
SELECT 
    timestamp,
    open, high, low, close,
    volume
FROM polymarket.candles_1h
WHERE market_id = '0x...'
  AND outcome = 'yes'
  AND timestamp >= now() - INTERVAL 7 DAY
ORDER BY timestamp;

-- Most active traders (last 30 days)
SELECT 
    user_address,
    sum(num_trades) as total_trades,
    sum(total_volume) as total_volume,
    avg(avg_price) as avg_entry_price
FROM polymarket.user_activity
WHERE date >= today() - INTERVAL 30 DAY
GROUP BY user_address
ORDER BY total_volume DESC
LIMIT 100;

-- Market momentum (biggest price changes in 1h)
WITH price_changes AS (
    SELECT 
        market_id,
        argMax(close, timestamp) as current_price,
        argMin(close, timestamp) as price_1h_ago,
        current_price - price_1h_ago as price_change,
        (price_change / price_1h_ago) * 100 as pct_change
    FROM polymarket.candles_1h
    WHERE timestamp >= now() - INTERVAL 1 HOUR
    GROUP BY market_id
)
SELECT 
    m.question,
    m.category,
    pc.current_price,
    pc.pct_change,
    m.volume_24h
FROM price_changes pc
JOIN polymarket.markets m ON pc.market_id = m.market_id
WHERE m.active = 1
ORDER BY abs(pc.pct_change) DESC
LIMIT 20;
*/

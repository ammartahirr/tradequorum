-- PostgreSQL Schema for AI Trading System
-- Replaces DynamoDB tables with relational schema

-- Enable TimescaleDB extension for time-series data (OHLCV)
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- CREATE SCHEMA
-- ============================================================

CREATE SCHEMA IF NOT EXISTS aitrading;

-- Set default schema for this session
SET search_path TO aitrading, public;

-- ============================================================
-- ENUM TYPES
-- ============================================================

CREATE TYPE aitrading.sentiment_type AS ENUM (
    'very_bullish', 'bullish', 'neutral', 'bearish', 'very_bearish'
);

CREATE TYPE aitrading.impact_type AS ENUM (
    'cash_flow', 'hype', 'regulatory', 'macro'
);

CREATE TYPE aitrading.trend_direction AS ENUM (
    'strong_uptrend', 'uptrend', 'sideways', 'downtrend', 'strong_downtrend'
);

CREATE TYPE aitrading.market_condition AS ENUM (
    'oversold', 'neutral', 'overbought'
);

CREATE TYPE aitrading.trade_action AS ENUM (
    'strong_buy', 'buy', 'wait_pullback', 'hold', 'sell', 'strong_sell', 'no_trade'
);

CREATE TYPE aitrading.trading_horizon AS ENUM (
    'short_term', 'medium_term', 'long_term'
);

CREATE TYPE aitrading.conviction_level AS ENUM (
    'high', 'medium', 'low'
);

CREATE TYPE aitrading.trade_status AS ENUM (
    'open', 'closed_profit', 'closed_loss', 'closed_sl', 'closed_tp'
);

CREATE TYPE aitrading.order_status AS ENUM (
    'filled', 'partial', 'rejected', 'pending'
);

-- ============================================================
-- NEWS SIGNALS TABLE (Requirement 9.1)
-- ============================================================

CREATE TABLE aitrading.news_signals (
    signal_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol VARCHAR(20) NOT NULL,
    sentiment aitrading.sentiment_type NOT NULL,
    impact_type aitrading.impact_type NOT NULL,
    impact_score DECIMAL(3,2) NOT NULL CHECK (impact_score >= 0 AND impact_score <= 1),
    confidence DECIMAL(3,2) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    reasoning TEXT NOT NULL,
    source_items JSONB NOT NULL DEFAULT '[]',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_by VARCHAR(50),
    resulted_in_trade BOOLEAN DEFAULT FALSE,
    trade_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_news_signals_symbol ON aitrading.news_signals(symbol);
CREATE INDEX idx_news_signals_timestamp ON aitrading.news_signals(timestamp DESC);
CREATE INDEX idx_news_signals_expires ON aitrading.news_signals(expires_at);

-- ============================================================
-- TECHNICAL SIGNALS TABLE (Requirement 9.2)
-- ============================================================

CREATE TABLE aitrading.technical_signals (
    signal_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol VARCHAR(20) NOT NULL,
    trend aitrading.trend_direction NOT NULL,
    condition aitrading.market_condition NOT NULL,
    rsi DECIMAL(5,2) NOT NULL CHECK (rsi >= 0 AND rsi <= 100),
    current_price DECIMAL(18,8) NOT NULL CHECK (current_price > 0),
    support_levels JSONB NOT NULL DEFAULT '[]',
    resistance_levels JSONB NOT NULL DEFAULT '[]',
    confluence_score DECIMAL(3,2) NOT NULL CHECK (confluence_score >= 0 AND confluence_score <= 1),
    confluence_factors JSONB NOT NULL DEFAULT '[]',
    confluence_description TEXT,
    volume_trend VARCHAR(20) NOT NULL,
    interest_rate_impact DECIMAL(3,2) CHECK (interest_rate_impact >= -1 AND interest_rate_impact <= 1),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consumed_by VARCHAR(50),
    resulted_in_trade BOOLEAN DEFAULT FALSE,
    trade_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_technical_signals_symbol ON aitrading.technical_signals(symbol);
CREATE INDEX idx_technical_signals_timestamp ON aitrading.technical_signals(timestamp DESC);

-- ============================================================
-- TRADE DECISIONS TABLE (Requirement 9.3)
-- ============================================================

CREATE TABLE aitrading.trade_decisions (
    decision_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol VARCHAR(20) NOT NULL,
    action aitrading.trade_action NOT NULL,
    conviction aitrading.conviction_level NOT NULL,
    horizon aitrading.trading_horizon NOT NULL,
    entry_price DECIMAL(18,8) NOT NULL CHECK (entry_price > 0),
    stop_loss DECIMAL(18,8) NOT NULL CHECK (stop_loss > 0),
    take_profit DECIMAL(18,8) NOT NULL CHECK (take_profit > 0),
    position_size_pct DECIMAL(5,4) NOT NULL CHECK (position_size_pct > 0 AND position_size_pct <= 1),
    risk_reward_ratio DECIMAL(6,2) NOT NULL CHECK (risk_reward_ratio >= 0),
    reasoning TEXT NOT NULL,
    news_signal_id UUID REFERENCES aitrading.news_signals(signal_id),
    technical_signal_id UUID REFERENCES aitrading.technical_signals(signal_id),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_trade_decisions_symbol ON aitrading.trade_decisions(symbol);
CREATE INDEX idx_trade_decisions_timestamp ON aitrading.trade_decisions(timestamp DESC);

-- ============================================================
-- TRADE RECORDS TABLE (Requirement 6.2)
-- ============================================================

CREATE TABLE aitrading.trade_records (
    trade_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol VARCHAR(20) NOT NULL,
    action aitrading.trade_action NOT NULL,
    horizon aitrading.trading_horizon NOT NULL,
    entry_price DECIMAL(18,8) NOT NULL CHECK (entry_price > 0),
    exit_price DECIMAL(18,8) CHECK (exit_price > 0),
    stop_loss DECIMAL(18,8) NOT NULL CHECK (stop_loss > 0),
    take_profit DECIMAL(18,8) NOT NULL CHECK (take_profit > 0),
    position_size DECIMAL(18,8) NOT NULL CHECK (position_size > 0),
    status aitrading.trade_status NOT NULL DEFAULT 'open',
    pnl DECIMAL(18,8),
    pnl_pct DECIMAL(8,4),
    conviction aitrading.conviction_level NOT NULL,
    news_signal_id UUID REFERENCES aitrading.news_signals(signal_id),
    technical_signal_id UUID REFERENCES aitrading.technical_signals(signal_id),
    decision_id UUID REFERENCES aitrading.trade_decisions(decision_id),
    decision_reasoning TEXT NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    exness_order_id VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_trade_records_symbol ON aitrading.trade_records(symbol);
CREATE INDEX idx_trade_records_status ON aitrading.trade_records(status);
CREATE INDEX idx_trade_records_opened ON aitrading.trade_records(opened_at DESC);

-- ============================================================
-- ORDER RESULTS TABLE
-- ============================================================

CREATE TABLE aitrading.order_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id VARCHAR(100) NOT NULL UNIQUE,
    trade_id UUID REFERENCES aitrading.trade_records(trade_id),
    symbol VARCHAR(20) NOT NULL,
    status aitrading.order_status NOT NULL,
    filled_price DECIMAL(18,8) NOT NULL CHECK (filled_price >= 0),
    filled_quantity DECIMAL(18,8) NOT NULL CHECK (filled_quantity >= 0),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_order_results_trade ON aitrading.order_results(trade_id);
CREATE INDEX idx_order_results_timestamp ON aitrading.order_results(timestamp DESC);

-- ============================================================
-- OHLCV MARKET DATA TABLE (Requirement 9.5)
-- TimescaleDB hypertable for efficient time-series queries
-- ============================================================

CREATE TABLE aitrading.ohlcv_candles (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,  -- '1m', '5m', '1h', '1d', '1w'
    open DECIMAL(18,8) NOT NULL CHECK (open > 0),
    high DECIMAL(18,8) NOT NULL CHECK (high > 0),
    low DECIMAL(18,8) NOT NULL CHECK (low > 0),
    close DECIMAL(18,8) NOT NULL CHECK (close > 0),
    volume BIGINT NOT NULL CHECK (volume >= 0),
    PRIMARY KEY (time, symbol, timeframe)
);

-- Convert to TimescaleDB hypertable for efficient time-series queries
SELECT create_hypertable('aitrading.ohlcv_candles', 'time', chunk_time_interval => INTERVAL '1 day');

CREATE INDEX idx_ohlcv_symbol_time ON aitrading.ohlcv_candles(symbol, time DESC);

-- ============================================================
-- RISK ASSESSMENTS TABLE
-- ============================================================

CREATE TABLE aitrading.risk_assessments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    decision_id UUID REFERENCES aitrading.trade_decisions(decision_id),
    approved BOOLEAN NOT NULL,
    adjusted_size DECIMAL(5,4) CHECK (adjusted_size > 0 AND adjusted_size <= 1),
    risk_score DECIMAL(3,2) NOT NULL CHECK (risk_score >= 0 AND risk_score <= 1),
    warnings JSONB NOT NULL DEFAULT '[]',
    rejection_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_risk_assessments_decision ON aitrading.risk_assessments(decision_id);

-- ============================================================
-- DAILY LOSS TRACKING TABLE (Requirement 5.4)
-- ============================================================

CREATE TABLE aitrading.daily_loss_tracking (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    date DATE NOT NULL UNIQUE,
    cumulative_loss DECIMAL(18,8) NOT NULL DEFAULT 0,
    portfolio_value DECIMAL(18,8) NOT NULL,
    loss_pct DECIMAL(8,4) NOT NULL DEFAULT 0,
    trading_halted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_daily_loss_date ON aitrading.daily_loss_tracking(date DESC);

-- ============================================================
-- WEBSOCKET CONNECTIONS TABLE
-- ============================================================

CREATE TABLE aitrading.websocket_connections (
    connection_id VARCHAR(100) PRIMARY KEY,
    user_id VARCHAR(100),
    connected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_ping TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- AUDIT LOG TABLE (Requirement 11.8)
-- ============================================================

CREATE TABLE aitrading.audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type VARCHAR(50) NOT NULL,  -- 'trade_decision', 'trade_execution', 'risk_breach'
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID NOT NULL,
    action VARCHAR(50) NOT NULL,
    details JSONB NOT NULL,
    user_id VARCHAR(100),
    ip_address INET,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_log_timestamp ON aitrading.audit_log(timestamp DESC);
CREATE INDEX idx_audit_log_entity ON aitrading.audit_log(entity_type, entity_id);

-- ============================================================
-- USERS TABLE (for Cognito replacement)
-- ============================================================

CREATE TABLE aitrading.users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    role VARCHAR(50) NOT NULL DEFAULT 'trader',  -- 'admin', 'trader'
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    mfa_secret VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login TIMESTAMPTZ
);

CREATE INDEX idx_users_email ON aitrading.users(email);

-- ============================================================
-- REFRESH TOKENS TABLE
-- ============================================================

CREATE TABLE aitrading.refresh_tokens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES aitrading.users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_refresh_tokens_user ON aitrading.refresh_tokens(user_id);

-- ============================================================
-- SECRETS TABLE (for MT5 credentials - Requirement 11.1)
-- ============================================================

CREATE TABLE aitrading.secrets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    encrypted_value TEXT NOT NULL,
    last_rotated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rotation_days INT NOT NULL DEFAULT 90,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- HELPER FUNCTIONS
-- ============================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION aitrading.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply trigger to tables with updated_at
CREATE TRIGGER update_trade_records_updated_at
    BEFORE UPDATE ON aitrading.trade_records
    FOR EACH ROW EXECUTE FUNCTION aitrading.update_updated_at_column();

CREATE TRIGGER update_daily_loss_updated_at
    BEFORE UPDATE ON aitrading.daily_loss_tracking
    FOR EACH ROW EXECUTE FUNCTION aitrading.update_updated_at_column();

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON aitrading.users
    FOR EACH ROW EXECUTE FUNCTION aitrading.update_updated_at_column();

CREATE TRIGGER update_secrets_updated_at
    BEFORE UPDATE ON aitrading.secrets
    FOR EACH ROW EXECUTE FUNCTION aitrading.update_updated_at_column();

-- ============================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================

-- Active signals view
CREATE VIEW aitrading.active_news_signals AS
SELECT * FROM aitrading.news_signals
WHERE expires_at > NOW()
ORDER BY timestamp DESC;

-- Open positions view
CREATE VIEW aitrading.open_positions AS
SELECT * FROM aitrading.trade_records
WHERE status = 'open'
ORDER BY opened_at DESC;

-- Performance metrics view
CREATE VIEW aitrading.performance_metrics AS
SELECT
    COUNT(*) as total_trades,
    COUNT(*) FILTER (WHERE status IN ('closed_profit', 'closed_tp')) as winning_trades,
    ROUND(
        COUNT(*) FILTER (WHERE status IN ('closed_profit', 'closed_tp'))::DECIMAL / 
        NULLIF(COUNT(*) FILTER (WHERE status != 'open'), 0) * 100, 2
    ) as win_rate,
    ROUND(AVG(pnl_pct) FILTER (WHERE status != 'open'), 2) as avg_pnl_pct,
    ROUND(MIN(pnl_pct) FILTER (WHERE status != 'open'), 2) as max_drawdown
FROM aitrading.trade_records;

-- ============================================================
-- SET DEFAULT SEARCH PATH FOR DATABASE
-- ============================================================

-- Set default schema for the trading database
ALTER DATABASE trading SET search_path TO aitrading, public;

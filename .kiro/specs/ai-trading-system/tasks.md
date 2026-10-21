# Implementation Plan: AI-Powered Multi-Agent Trading System

## Overview

This implementation plan covers the development of a multi-agent trading platform with three specialized agents (News Agent, Technical Agent, Strategy Agent), risk management, order execution via Exness MT5 API, and a real-time React dashboard. The plan follows an incremental approach, building core data models first, then agents, then execution layer, and finally the frontend.

## Tasks

- [x] 1. Set up project structure and core data models
  - [x] 1.1 Create Python project structure with Lambda handlers, shared modules, and tests directories
    - Set up `src/` with `agents/`, `execution/`, `models/`, `handlers/`, `utils/` subdirectories
    - Configure `pyproject.toml` with dependencies: boto3, aiohttp, pandas, numpy, ta-lib, MetaTrader5, pydantic, hypothesis
    - _Requirements: 9.1, 9.2, 9.3_

  - [x] 1.2 Implement core data model classes and enums
    - Create `Sentiment`, `ImpactType`, `TrendDirection`, `MarketCondition`, `TradeAction`, `TradingHorizon`, `Conviction` enums
    - Create `NewsItem`, `NewsSignal`, `OHLCV`, `SupportResistance`, `ConfluenceResult`, `TechnicalSignal` dataclasses
    - Create `TradeDecision`, `RiskLimits`, `RiskAssessment`, `OrderResult`, `TradeRecord` dataclasses
    - _Requirements: 1.5, 2.8, 3.7, 5.8, 6.2_

  - [x] 1.3 Write property test for data model validation
    - **Property 1: Stop-Loss Integrity**
    - **Validates: Requirements 4.1, 4.2, 4.3, 13.1, 13.2**

  - [x] 1.4 Write property test for RSI bounds
    - **Property 8: RSI Bounds**
    - **Validates: Requirements 2.2**

- [x] 2. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Implement News Agent (The Ear)
  - [x] 3.1 Create news scraper Lambda functions
    - Implement scrapers for Reuters, Bloomberg, SEC EDGAR, Twitter/X sources
    - Configure EventBridge scheduled triggers for periodic scraping
    - Implement deduplication logic for news items referencing the same event
    - _Requirements: 1.1, 1.2_

  - [x] 3.2 Implement AWS Bedrock Claude Opus 4.5 integration for news analysis
    - Create `analyze_news_impact()` function with LLM prompt construction
    - Use boto3 bedrock-runtime client with model ID `anthropic.claude-opus-4-5-20250514`
    - Implement impact type classification (CASH_FLOW, HYPE, REGULATORY, MACRO)
    - Implement confidence scoring with 0.7 threshold for CASH_FLOW classification
    - Implement fallback to rule-based keyword sentiment analysis when LLM fails
    - _Requirements: 1.3, 1.4, 10.1_

  - [x] 3.3 Implement NewsSignal generation and expiry logic
    - Generate NewsSignal with all required fields (sentiment, impact_score, confidence, reasoning)
    - Set signal expiry: 72h for CASH_FLOW, 168h for REGULATORY, 24h for HYPE/MACRO
    - Persist signals to DynamoDB with signal ID, agent type, symbol, payload, timestamp
    - _Requirements: 1.5, 1.6, 9.1_

  - [x] 3.4 Write property test for news impact classification
    - **Property 9: News Impact Classification**
    - **Validates: Requirements 1.4**

  - [x] 3.5 Write unit tests for News Agent
    - Test sentiment classification with mocked AWS Bedrock Claude Opus 4.5 responses
    - Test deduplication logic
    - Test expiry time calculation for each impact type
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [x] 4. Implement Technical Agent (The Eye)
  - [x] 4.1 Implement market data fetching from MT5 API
    - Create MT5 connection handler with authentication
    - Fetch OHLCV candles for configurable timeframes
    - Store candles in Timestream for time-series querying
    - Implement stale data detection (>5 min without update during trading hours)
    - _Requirements: 2.1, 9.5, 10.2_

  - [x] 4.2 Implement technical indicator calculations
    - Implement RSI calculation (14-period) with Wilder's smoothing
    - Implement MACD calculation
    - Implement Bollinger Bands calculation
    - Implement 50-day and 200-day moving average calculations
    - _Requirements: 2.1, 2.2_

  - [x] 4.3 Implement support/resistance level identification
    - Analyze up to 5 years of historical price data
    - Identify support and resistance levels with strength scoring
    - Flag levels as active when current price is within 2%
    - _Requirements: 2.3, 2.6_

  - [x] 4.4 Implement confluence detection algorithm
    - Check 6 factors: RSI condition, price at support/resistance, volume spike, MA alignment, MACD signal, Bollinger position
    - Calculate confluence score as aligned factors / total checks
    - Verify score >= 0.7 requires at least 3 aligned factors
    - Detect volume spike when current volume > 1.5x 20-day average
    - _Requirements: 2.4, 2.5, 2.7_

  - [x] 4.5 Implement TechnicalSignal generation
    - Generate TechnicalSignal with all required fields
    - Persist signals to DynamoDB
    - Integrate optional SageMaker pattern prediction with 10s timeout fallback
    - _Requirements: 2.8, 9.2, 10.3_

  - [x] 4.6 Write property test for RSI calculation
    - **Property 8: RSI Bounds**
    - **Validates: Requirements 2.2**

  - [x] 4.7 Write property test for confluence threshold
    - **Property 5: Confluence Threshold**
    - **Validates: Requirements 2.5**

  - [x] 4.8 Write unit tests for Technical Agent
    - Test RSI calculation with known OHLCV datasets
    - Test support/resistance identification
    - Test confluence detection with various indicator combinations
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement Strategy Agent (The Brain)
  - [x] 6.1 Implement decision matrix evaluation
    - Combine news (40% weight) and technical (60% weight) signals
    - Map sentiment and market condition to decision matrix inputs
    - Implement all decision matrix rules (VERY_BULLISH+OVERSOLD→STRONG_BUY, etc.)
    - Handle conflicting signals (bearish news + oversold technical → NO_TRADE)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 6.2 Implement signal freshness validation
    - Discard NewsSignals where expires_at <= current time
    - Discard TechnicalSignals where timestamp is >1 hour old
    - _Requirements: 3.8, 3.9_

  - [x] 6.3 Implement stop-loss calculation
    - Place stop-loss below nearest support (BUY) or above nearest resistance (SELL)
    - Apply 0.5-2% buffer below support to avoid false triggers
    - Use tighter stops for SHORT_TERM horizon
    - _Requirements: 4.1, 4.2, 4.3, 4.7_

  - [x] 6.4 Implement take-profit calculation
    - Set take-profit at resistance (BUY) or support (SELL) levels
    - Ensure risk-reward ratio >= 1.5 for all actionable trades
    - Target higher resistance levels for LONG_TERM horizon
    - _Requirements: 4.4, 4.5, 4.6, 4.8_

  - [x] 6.5 Implement TradeDecision generation
    - Generate TradeDecision with all required fields
    - Calculate position size based on conviction and risk
    - Persist decisions to DynamoDB with originating signal IDs
    - _Requirements: 3.7, 9.3_

  - [x] 6.6 Write property test for stop-loss integrity
    - **Property 1: Stop-Loss Integrity**
    - **Validates: Requirements 4.1, 4.2, 4.3, 13.1, 13.2**

  - [x] 6.7 Write property test for risk-reward minimum
    - **Property 2: Risk-Reward Minimum**
    - **Validates: Requirements 4.6, 13.4**

  - [x] 6.8 Write property test for decision matrix consistency
    - **Property 6: Decision Matrix Consistency**
    - **Validates: Requirements 3.2, 3.3, 3.4, 3.5**

  - [x] 6.9 Write property test for signal freshness
    - **Property 4: Signal Freshness**
    - **Validates: Requirements 3.8, 3.9**

  - [x] 6.10 Write unit tests for Strategy Agent
    - Test all decision matrix combinations
    - Test stop-loss and take-profit calculations
    - Test signal freshness validation
    - _Requirements: 3.1-3.9, 4.1-4.8_

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement Risk Manager
  - [x] 8.1 Implement position size validation
    - Validate position size does not exceed 5% of portfolio
    - Validate portfolio risk per trade does not exceed 2%
    - Adjust position size downward when limits exceeded but trade viable
    - _Requirements: 5.1, 5.2, 5.6_

  - [x] 8.2 Implement correlated exposure tracking
    - Track total exposure in correlated assets
    - Reject or reduce position when correlated exposure would exceed 20%
    - _Requirements: 5.3_

  - [x] 8.3 Implement daily loss limit enforcement
    - Track cumulative realized losses for current calendar day
    - Halt all new trade openings when daily loss exceeds 5%
    - Send critical alert to dashboard when limit breached
    - _Requirements: 5.4, 10.4_

  - [x] 8.4 Implement open position limit
    - Track count of open positions
    - Reject new trades when 10 positions are open
    - _Requirements: 5.5_

  - [x] 8.5 Implement RiskAssessment generation
    - Generate risk score in [0.0, 1.0] for every assessed trade
    - Provide non-empty rejection reason when trade rejected
    - _Requirements: 5.7, 5.8_

  - [x] 8.6 Write property test for position size limits
    - **Property 3: Position Size Limits**
    - **Validates: Requirements 5.1, 5.2, 13.3**

  - [x] 8.7 Write property test for daily loss limit
    - **Property 7: Daily Loss Limit**
    - **Validates: Requirements 5.4**

  - [x] 8.8 Write property test for portfolio exposure
    - **Property 10: Portfolio Exposure**
    - **Validates: Requirements 5.3, 5.5**

  - [x] 8.9 Write unit tests for Risk Manager
    - Test position sizing calculations
    - Test daily loss limit enforcement
    - Test correlated exposure tracking
    - _Requirements: 5.1-5.8_

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Implement Order Executor and Position Manager
  - [x] 10.1 Implement MT5 API order execution
    - Place orders via MT5 API with symbol, size, entry, stop-loss, take-profit
    - Handle partial fills and continue monitoring for full execution
    - Implement retry with exponential backoff (3 attempts: 1s, 2s, 4s)
    - Query open positions to verify state before retrying after connection failure
    - _Requirements: 6.1, 6.3, 6.4, 6.5_

  - [x] 10.2 Implement trade record persistence
    - Record trades in DynamoDB with order ID, filled price, quantity, status, timestamp
    - Validate trade records: stop_loss vs entry_price based on trade direction
    - Validate risk_reward_ratio >= 1.5 for all actionable trades
    - _Requirements: 6.2, 13.1, 13.2, 13.3, 13.4_

  - [x] 10.3 Implement Position Manager
    - Track open positions with trade ID, symbol, entry, SL, TP, size, timestamp
    - Record exit price, PnL, PnL percentage, close timestamp on position close
    - Record final status as closed_profit, closed_loss, closed_sl, or closed_tp
    - Maintain accurate count of open positions
    - _Requirements: 7.1, 7.2, 7.4, 13.5_

  - [x] 10.4 Implement WebSocket broadcast for position updates
    - Broadcast position status changes within 1 second
    - Broadcast trade execution results
    - _Requirements: 6.6, 7.3_

  - [x] 10.5 Write unit tests for Order Executor
    - Test order placement with mocked MT5 API
    - Test retry logic with simulated failures
    - Test trade record validation
    - _Requirements: 6.1-6.6_

  - [x] 10.6 Write unit tests for Position Manager
    - Test position tracking
    - Test PnL calculation
    - Test WebSocket broadcast timing
    - _Requirements: 7.1-7.4_

- [x] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Implement AWS Infrastructure
  - [x] 12.1 Create DynamoDB tables
    - Create tables for signals, trade decisions, trade records
    - Enable encryption at rest
    - Configure DAX cache for hot signal data
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 11.3_

  - [x] 12.2 Create Timestream database for market data
    - Configure time-series storage for OHLCV candles
    - _Requirements: 9.5_

  - [x] 12.3 Configure Lambda functions
    - Create Lambda handlers for each agent and execution component
    - Configure VPC with private subnets for database access
    - Apply least-privilege IAM roles
    - Configure reserved concurrency for Order Executor
    - _Requirements: 11.5, 11.6, 12.1, 12.2_

  - [x] 12.4 Configure API Gateway WebSocket API
    - Set up WebSocket endpoint for real-time dashboard updates
    - Configure support for up to 500 concurrent connections
    - Apply rate limiting
    - _Requirements: 11.7, 12.5_

  - [x] 12.5 Configure Secrets Manager
    - Store Exness MT5 credentials with 90-day rotation
    - Configure IAM roles for AWS Bedrock access (no API keys needed)
    - _Requirements: 11.1_

  - [x] 12.6 Configure Cognito authentication
    - Set up user pool for dashboard access
    - Protect API endpoints with Cognito authentication
    - _Requirements: 11.4_

  - [x] 12.7 Configure CloudWatch logging
    - Set up error logging with sufficient context for debugging
    - Configure tamper-evident audit trail for trade decisions and executions
    - _Requirements: 10.5, 11.8_

  - [x] 12.8 Configure SageMaker endpoint
    - Deploy pattern recognition model
    - Configure 5-second latency budget
    - _Requirements: 12.4_

- [x] 13. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Implement React Dashboard
  - [X] 14.1 Set up React project with TypeScript
    - Configure project with React, TypeScript, Recharts, TanStack Query
    - Set up WebSocket client for real-time updates
    - _Requirements: 8.1_

  - [X] 14.2 Implement WebSocket connection management
    - Connect to WebSocket API on load
    - Implement automatic reconnection with exponential backoff
    - Display connection status indicator
    - _Requirements: 8.5_

  - [X] 14.3 Implement real-time UI updates
    - Update UI components within 500ms of WebSocket message receipt
    - _Requirements: 8.2_

  - [X] 14.4 Implement positions and trade history display
    - Display current open positions
    - Display recent trade history
    - Display agent signal status
    - _Requirements: 8.1_

  - [X] 14.5 Implement trade signal display
    - Display symbol, action, conviction, entry, stop-loss, take-profit, reasoning
    - _Requirements: 8.3_

  - [X] 14.6 Implement performance metrics display
    - Display total trades, winning trades, win rate
    - Display average risk-reward ratio, max drawdown, Sharpe ratio
    - _Requirements: 8.4_

  - [X] 14.7 Write unit tests for Dashboard components
    - Test WebSocket message handling
    - Test UI update timing
    - Test reconnection logic
    - _Requirements: 8.1-8.5_

- [x] 15. Implement Error Handling and Graceful Degradation
  - [x] 15.1 Implement MT5 connection failure handling
    - Implement retry with exponential backoff
    - Query open positions to verify state before retry
    - Implement reconnection and signal recalculation on recovery
    - _Requirements: 6.4, 6.5, 10.6_

  - [x] 15.2 Implement stale market data handling
    - Mark Technical Agent signals as stale when data >5 min old
    - Halt new trade decisions when data is stale
    - _Requirements: 10.2_

  - [x] 15.3 Implement LLM fallback
    - Fall back to rule-based keyword sentiment analysis on AWS Bedrock Claude Opus 4.5 failure
    - Multiply confidence score by 0.5 in fallback mode
    - _Requirements: 10.1_

  - [x] 15.4 Implement SageMaker fallback
    - Skip ML-based pattern prediction on SageMaker error or >10s latency
    - Continue with traditional indicator calculations only
    - _Requirements: 10.3_

  - [x] 15.5 Write integration tests for error scenarios
    - Test MT5 connection failure and recovery
    - Test stale data handling
    - Test LLM and SageMaker fallbacks
    - _Requirements: 10.1-10.6_

- [x] 16. Final Integration and End-to-End Testing
  - [x] 16.1 Wire all components together
    - Connect data ingestion → agents → execution pipeline
    - Connect WebSocket broadcasts to dashboard
    - _Requirements: All_

  - [x] 16.2 Write end-to-end integration tests
    - Test full pipeline: news ingestion → signal → decision → risk check → order (using MT5 demo account)
    - Test WebSocket dashboard update flow
    - _Requirements: All_

  - [x] 16.3 Run backtest validation
    - Run strategy against 2+ years of historical data
    - Verify win rate and drawdown metrics
    - _Requirements: All_

- [x] 17. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Backend uses Python with boto3, pandas, ta-lib, MetaTrader5
- Frontend uses React with TypeScript, Recharts, TanStack Query

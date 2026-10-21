# Requirements Document

## Introduction

This document defines the requirements for an AI-powered multi-agent trading platform that connects to an Exness trading account to execute intelligent stock trades. The system employs three specialized agents — a News Agent ("The Ear"), a Technical Agent ("The Eye"), and a Strategy Agent ("The Brain") — that collaborate to analyze market conditions, build trading strategies, and execute trades. The platform targets an 80%+ trade success rate across short-term (5-day) and long-term (6-month) horizons, with a React-based dashboard for real-time monitoring.

## Glossary

- **News_Agent**: The agent responsible for scraping live news, CEO tweets, and global events, and using Claude Opus 4.5 via AWS Bedrock to classify their impact on stocks (cash-flow vs hype). Also referred to as "The Ear".
- **Technical_Agent**: The agent responsible for reading charts, calculating technical indicators (RSI, MACD, Bollinger Bands), identifying support/resistance levels, and detecting confluence patterns. Also referred to as "The Eye".
- **Strategy_Agent**: The agent responsible for synthesizing signals from the News Agent and Technical Agent using a weighted decision matrix to produce trade decisions. Also referred to as "The Brain".
- **Risk_Manager**: The component that validates trade decisions against portfolio risk constraints before execution.
- **Order_Executor**: The component that interfaces with the Exness API to place, modify, and close orders.
- **Position_Manager**: The component that tracks open positions and broadcasts updates via WebSocket.
- **Dashboard**: The React-based frontend providing real-time monitoring of agent activities, trade positions, and performance metrics.
- **NewsSignal**: A structured output from the News Agent containing sentiment, impact type, impact score, confidence, and reasoning for a given stock symbol.
- **TechnicalSignal**: A structured output from the Technical Agent containing trend direction, market condition, RSI, support/resistance levels, and confluence score.
- **TradeDecision**: A structured output from the Strategy Agent containing trade action, conviction level, entry/exit prices, stop-loss, take-profit, and position sizing.
- **Confluence**: The alignment of multiple independent technical indicators pointing in the same direction, measured as a score from 0.0 to 1.0.
- **Decision_Matrix**: The weighted scoring system used by the Strategy Agent to combine news sentiment (40% weight) and technical signals (60% weight) into a combined score.
- **OHLCV**: Open, High, Low, Close, Volume — standard candlestick market data format.
- **RSI**: Relative Strength Index — a momentum oscillator ranging from 0 to 100.
- **Risk_Limits**: The configurable set of constraints including max position size (5%), max portfolio risk per trade (2%), max correlated exposure (20%), max daily loss (5%), and max open positions (10).
- **Exness_API**: The external trading interface via MetaTrader 5 (MT5) used for order execution, position management, and account monitoring.
- **MT5**: MetaTrader 5 — the trading platform used by Exness for executing trades and retrieving market data.
- **WebSocket_API**: The API Gateway WebSocket endpoint used for real-time communication between backend services and the Dashboard.

## Requirements

### Requirement 1: News Ingestion and Analysis

**User Story:** As a trader, I want the system to automatically scrape and analyze news from multiple sources, so that I can understand whether news has genuine cash-flow impact or is merely market hype.

#### Acceptance Criteria

1. WHEN new articles, tweets, or SEC filings are published, THE News_Agent SHALL scrape them from configured sources (Reuters, Bloomberg, SEC EDGAR, Twitter/X) within the scheduled ingestion interval
2. WHEN multiple news items reference the same event for a symbol, THE News_Agent SHALL deduplicate them and produce a single consolidated analysis
3. WHEN a news item is received, THE News_Agent SHALL classify its impact type as one of: CASH_FLOW, HYPE, REGULATORY, or MACRO using Claude Opus 4.5 via AWS Bedrock
4. WHEN a news item is classified as CASH_FLOW impact, THE News_Agent SHALL assign a confidence score of 0.7 or higher; IF the confidence is below 0.7, THEN THE News_Agent SHALL downgrade the impact type to HYPE
5. WHEN a news item is analyzed, THE News_Agent SHALL produce a NewsSignal containing symbol, sentiment (VERY_BULLISH to VERY_BEARISH), impact_type, impact_score in [0.0, 1.0], confidence in [0.0, 1.0], reasoning text, source item IDs, timestamp, and expiry time
6. WHEN a CASH_FLOW signal is generated, THE News_Agent SHALL set the signal expiry to 72 hours; WHEN a REGULATORY signal is generated, THE News_Agent SHALL set the expiry to 168 hours; WHEN a HYPE or MACRO signal is generated, THE News_Agent SHALL set the expiry to 24 hours

### Requirement 2: Technical Analysis and Confluence Detection

**User Story:** As a trader, I want the system to perform comprehensive technical analysis with confluence detection, so that trades are only taken when multiple independent indicators align.

#### Acceptance Criteria

1. WHEN market data is received for a symbol, THE Technical_Agent SHALL calculate RSI (14-period), MACD, Bollinger Bands, and 50-day and 200-day moving averages
2. THE Technical_Agent SHALL produce RSI values in the range [0, 100] for all valid candle sequences; IF a calculated RSI falls outside this range, THEN THE Technical_Agent SHALL report a calculation error
3. WHEN analyzing a symbol, THE Technical_Agent SHALL identify support and resistance levels using up to 5 years of historical price data
4. WHEN calculating confluence, THE Technical_Agent SHALL check six independent factors: RSI condition, price at support/resistance, volume spike, moving average alignment, MACD signal, and Bollinger Band position
5. WHEN a confluence score of 0.7 or higher is calculated, THE Technical_Agent SHALL verify that at least 3 of the 6 factors are aligned
6. WHEN the current price is within 2% of a support or resistance level, THE Technical_Agent SHALL flag that level as active in the confluence calculation
7. WHEN current volume exceeds 1.5 times the 20-day average volume, THE Technical_Agent SHALL include a volume spike factor in the confluence result
8. WHEN analyzing a symbol, THE Technical_Agent SHALL produce a TechnicalSignal containing trend direction, market condition, RSI, current price, support levels, resistance levels, confluence result, and volume trend

### Requirement 3: Strategy Decision Making

**User Story:** As a trader, I want the system to synthesize news and technical signals into high-conviction trade decisions, so that trades are only executed when multiple data sources agree.

#### Acceptance Criteria

1. WHEN a NewsSignal and TechnicalSignal are available for the same symbol, THE Strategy_Agent SHALL combine them using the Decision_Matrix with 40% weight on news and 60% weight on technical signals
2. WHEN news sentiment is VERY_BULLISH and technical condition is OVERSOLD, THE Strategy_Agent SHALL produce a STRONG_BUY action with HIGH conviction
3. WHEN news sentiment is VERY_BEARISH and technical condition is OVERBOUGHT, THE Strategy_Agent SHALL produce a STRONG_SELL action with HIGH conviction
4. WHEN news sentiment is BULLISH and technical condition is OVERBOUGHT, THE Strategy_Agent SHALL produce a WAIT_PULLBACK action with MEDIUM conviction
5. WHEN news sentiment is strongly bearish and technical condition is OVERSOLD (conflicting signals), THE Strategy_Agent SHALL produce a NO_TRADE action
6. WHEN a trade action is STRONG_BUY or STRONG_SELL, THE Strategy_Agent SHALL assign HIGH conviction only
7. WHEN producing a TradeDecision, THE Strategy_Agent SHALL include entry price, stop-loss, take-profit, position size percentage, risk-reward ratio, and reasoning text
8. WHEN a NewsSignal has expired (expires_at <= current time), THE Strategy_Agent SHALL discard it and not use it in trade evaluation
9. WHEN a TechnicalSignal timestamp is more than 1 hour old relative to the decision timestamp, THE Strategy_Agent SHALL discard it and not use it in trade evaluation

### Requirement 4: Stop-Loss and Take-Profit Calculation

**User Story:** As a trader, I want the system to calculate precise stop-loss and take-profit levels based on support/resistance, so that every trade has defined risk boundaries.

#### Acceptance Criteria

1. THE Strategy_Agent SHALL set a stop-loss for every trade decision; no trade decision is produced without a stop-loss value
2. WHEN the trade action is BUY or STRONG_BUY, THE Strategy_Agent SHALL place the stop-loss below the nearest support level with a buffer of 0.5% to 2%
3. WHEN the trade action is SELL or STRONG_SELL, THE Strategy_Agent SHALL place the stop-loss above the nearest resistance level with a buffer of 0.5% to 2%
4. WHEN the trade action is BUY or STRONG_BUY, THE Strategy_Agent SHALL set the take-profit above the entry price, aligned with the nearest resistance level when possible
5. WHEN the trade action is SELL or STRONG_SELL, THE Strategy_Agent SHALL set the take-profit below the entry price, aligned with the nearest support level when possible
6. THE Strategy_Agent SHALL ensure the risk-reward ratio (|take_profit - entry| / |stop_loss - entry|) is at least 1.5 for every actionable trade
7. WHEN the trading horizon is SHORT_TERM, THE Strategy_Agent SHALL use tighter stop-loss distances than for LONG_TERM horizons
8. WHEN the trading horizon is LONG_TERM, THE Strategy_Agent SHALL target higher resistance levels for take-profit than for SHORT_TERM horizons

### Requirement 5: Risk Management

**User Story:** As a trader, I want the system to enforce strict risk limits on every trade, so that no single trade or sequence of trades can cause catastrophic portfolio loss.

#### Acceptance Criteria

1. WHEN a TradeDecision is received, THE Risk_Manager SHALL validate that the position size does not exceed 5% of the total portfolio value
2. WHEN a TradeDecision is received, THE Risk_Manager SHALL validate that the portfolio risk per trade does not exceed 2% of the total portfolio value
3. WHEN the total exposure in correlated assets would exceed 20% of the portfolio, THE Risk_Manager SHALL reject the trade or reduce the position size
4. WHEN the cumulative realized losses for the current calendar day exceed 5% of portfolio value, THE Risk_Manager SHALL halt all new trade openings until the next trading day
5. WHEN the number of open positions reaches 10, THE Risk_Manager SHALL reject new trade openings until an existing position is closed
6. WHEN a trade exceeds position size limits but is otherwise viable, THE Risk_Manager SHALL adjust the position size downward and approve the trade at the reduced size
7. WHEN a trade is rejected, THE Risk_Manager SHALL provide a non-empty rejection reason in the RiskAssessment
8. THE Risk_Manager SHALL produce a risk score in [0.0, 1.0] for every assessed trade, where 1.0 represents maximum risk

### Requirement 6: Order Execution

**User Story:** As a trader, I want the system to reliably execute approved trades through the Exness API, so that trade decisions are acted upon promptly and accurately.

#### Acceptance Criteria

1. WHEN a trade is approved by the Risk_Manager, THE Order_Executor SHALL place the order via the MT5 API with the specified symbol, size, entry price, stop-loss, and take-profit
2. WHEN an order is filled, THE Order_Executor SHALL record the trade in DynamoDB with order ID, filled price, filled quantity, status, and timestamp
3. WHEN an order is partially filled, THE Order_Executor SHALL record the partial fill and continue monitoring for full execution
4. WHEN the MT5 API returns a connection timeout or error, THE Order_Executor SHALL retry with exponential backoff (3 attempts at 1s, 2s, 4s delays)
5. IF an order may have been partially filled during a connection failure, THEN THE Order_Executor SHALL query open positions to verify state before retrying
6. WHEN an order is executed or fails, THE Order_Executor SHALL broadcast the result to the Dashboard via the WebSocket_API

### Requirement 7: Position Management

**User Story:** As a trader, I want the system to track all open positions and broadcast updates in real time, so that I always know the current state of my portfolio.

#### Acceptance Criteria

1. WHEN a new position is opened, THE Position_Manager SHALL track it with trade ID, symbol, entry price, stop-loss, take-profit, position size, and open timestamp
2. WHEN a position is closed (by stop-loss, take-profit, or manual action), THE Position_Manager SHALL record the exit price, PnL, PnL percentage, and close timestamp
3. WHEN a position status changes, THE Position_Manager SHALL broadcast the update to the Dashboard via the WebSocket_API within 1 second
4. THE Position_Manager SHALL maintain an accurate count of all open positions at all times

### Requirement 8: Real-Time Dashboard

**User Story:** As a trader, I want a real-time dashboard showing agent activities, trade positions, and performance metrics, so that I can monitor the system and make informed decisions.

#### Acceptance Criteria

1. WHEN the Dashboard loads, THE Dashboard SHALL display current open positions, recent trade history, and agent signal status
2. WHEN a WebSocket message is received, THE Dashboard SHALL update the relevant UI component within 500 milliseconds
3. WHEN a trade signal is generated, THE Dashboard SHALL display the symbol, action, conviction level, entry price, stop-loss, take-profit, and reasoning
4. WHEN displaying performance metrics, THE Dashboard SHALL show total trades, winning trades, win rate, average risk-reward ratio, max drawdown, and Sharpe ratio
5. WHEN the WebSocket connection is lost, THE Dashboard SHALL attempt automatic reconnection with exponential backoff and display a connection status indicator

### Requirement 9: Data Persistence and Signal Logging

**User Story:** As a trader, I want all signals, decisions, and trades to be persisted and logged, so that I can audit the system's behavior and improve its performance over time.

#### Acceptance Criteria

1. WHEN a NewsSignal is generated, THE News_Agent SHALL persist it to DynamoDB with signal ID, agent type, symbol, full signal payload, and timestamp
2. WHEN a TechnicalSignal is generated, THE Technical_Agent SHALL persist it to DynamoDB with signal ID, agent type, symbol, full signal payload, and timestamp
3. WHEN a TradeDecision is generated, THE Strategy_Agent SHALL persist it to DynamoDB with all decision fields including the originating signal IDs
4. THE system SHALL record for each signal whether it was consumed by a downstream agent and whether it resulted in a trade
5. WHEN market data is received, THE system SHALL store OHLCV candles in Timestream for efficient time-series querying

### Requirement 10: Error Handling and Graceful Degradation

**User Story:** As a trader, I want the system to handle failures gracefully without placing erroneous trades, so that system errors do not result in financial losses.

#### Acceptance Criteria

1. IF the AWS Bedrock Claude Opus 4.5 endpoint returns an error or timeout, THEN THE News_Agent SHALL fall back to rule-based keyword sentiment analysis and multiply the confidence score by 0.5
2. IF the market data feed has not updated for more than 5 minutes during trading hours, THEN THE Technical_Agent SHALL mark all its signals as stale and THE Strategy_Agent SHALL halt new trade decisions
3. IF the SageMaker endpoint returns an error or latency exceeds 10 seconds, THEN THE Technical_Agent SHALL skip ML-based pattern prediction and continue with traditional indicator calculations only
4. IF the daily loss limit is breached, THEN THE Risk_Manager SHALL halt all new trade openings, keep existing stop-losses active, and send a critical alert to the Dashboard
5. WHEN any error occurs in the trading pipeline, THE system SHALL log the error to CloudWatch with sufficient context for debugging
6. IF the MT5 connection is lost, THEN THE system SHALL attempt reconnection and recalculate all active signals once fresh data resumes before resuming trading

### Requirement 11: Security and Access Control

**User Story:** As a system operator, I want all credentials secured and access controlled, so that the trading system is protected from unauthorized access and data breaches.

#### Acceptance Criteria

1. THE system SHALL store Exness MT5 login credentials in AWS Secrets Manager with 90-day rotation
2. THE system SHALL encrypt all data in transit using TLS 1.3
3. THE system SHALL enable encryption at rest for all DynamoDB tables
4. THE system SHALL protect Dashboard API endpoints with Cognito authentication
5. THE system SHALL run all Lambda functions in a VPC with private subnets for database access
6. THE system SHALL apply least-privilege IAM roles to all Lambda functions, with the Order Executor having only the permissions required for trade execution
7. THE system SHALL apply rate limiting on all API endpoints
8. WHEN a trade decision or execution occurs, THE system SHALL log it to CloudWatch with a tamper-evident audit trail

### Requirement 12: Performance

**User Story:** As a trader, I want the system to process data and execute trades within strict latency bounds, so that trading opportunities are not missed due to slow processing.

#### Acceptance Criteria

1. WHEN market data is received, THE Technical_Agent SHALL produce a TechnicalSignal within 500 milliseconds
2. WHEN signals are received by the Strategy_Agent, THE system SHALL produce a TradeDecision and place the order within 2 seconds
3. WHEN a news article is analyzed, THE News_Agent SHALL complete AWS Bedrock Claude Opus 4.5 analysis within 10 seconds
4. WHEN a SageMaker prediction is requested, THE Technical_Agent SHALL receive the result within 5 seconds
5. THE WebSocket_API SHALL support up to 500 concurrent Dashboard connections

### Requirement 13: Trade Record Validation

**User Story:** As a trader, I want every trade record to be internally consistent, so that I can trust the system's data integrity.

#### Acceptance Criteria

1. WHEN a BUY trade is recorded, THE system SHALL validate that stop_loss is less than entry_price and take_profit is greater than entry_price
2. WHEN a SELL trade is recorded, THE system SHALL validate that stop_loss is greater than entry_price and take_profit is less than entry_price
3. THE system SHALL validate that position_size does not exceed the configured max_position_pct of the portfolio for every trade record
4. THE system SHALL validate that the risk_reward_ratio is at least 1.5 for every actionable trade record
5. WHEN a trade is closed, THE system SHALL record the final status as one of: closed_profit, closed_loss, closed_sl, or closed_tp

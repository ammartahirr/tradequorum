# AI-Powered Multi-Agent Trading System

An intelligent trading platform that connects to Exness via MT5 API, employing three specialized agents to analyze market conditions and execute trades.

## Architecture

- **News Agent (The Ear)**: Scrapes news, tweets, and SEC filings; uses Claude Opus to classify cash-flow impact vs hype
- **Technical Agent (The Eye)**: Calculates RSI, MACD, Bollinger Bands; detects confluence patterns
- **Strategy Agent (The Brain)**: Synthesizes signals using weighted decision matrix; generates trade decisions

## Project Structure

```
src/
├── agents/          # Trading agents (News, Technical, Strategy)
├── execution/       # Risk manager, order executor, position manager
├── handlers/        # AWS Lambda handlers
├── models/          # Data models, enums, dataclasses
└── utils/           # Shared utilities (indicators, MT5 client, AWS clients)

tests/
├── unit/            # Unit tests
├── property/        # Property-based tests (Hypothesis)
└── integration/     # Integration tests
```

## Setup

```bash
# Install dependencies
py pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=src
```

## Requirements

- Python 3.11+
- MetaTrader 5 terminal (for MT5 API)
- AWS account (for Lambda, DynamoDB, etc.)

# AI-Powered Multi-Agent Trading System

An intelligent trading platform that trades through **Interactive Brokers** (paper by default; legacy Exness/MT5 connector kept for Windows), employing three specialized agents to analyze market conditions and execute trades.

## Architecture

- **News Agent (The Ear)**: Scrapes news, tweets, and SEC filings; uses Claude Opus to classify cash-flow impact vs hype
- **Technical Agent (The Eye)**: Calculates RSI, MACD, Bollinger Bands; detects confluence patterns
- **Strategy Agent (The Brain)**: Synthesizes signals using weighted decision matrix; generates trade decisions

## Project Structure

```
src/
├── agents/          # Trading agents (News, Technical, Strategy, Risk)
├── backtest/        # Training sandbox / backtester (replays history through the real agents)
├── brokers/         # BrokerClient abstraction: IBKR (ib_async), PaperBroker, Yahoo/synthetic data
├── execution/       # Order executor, position manager
├── handlers/        # AWS Lambda handlers
├── models/          # Data models, enums, dataclasses
└── utils/           # Shared utilities (indicators, MT5 client, AWS clients)

tests/
├── unit/            # Unit tests
├── property/        # Property-based tests (Hypothesis)
└── integration/     # Integration tests
```

## Training sandbox

Dashboard → **Sandbox** tab (`/#/sandbox`), or `POST /api/sandbox/backtest`:

```bash
curl -X POST localhost/api/sandbox/backtest -H 'content-type: application/json' \
  -d '{"symbol":"AAPL","timeframe":"D1","bars":1500,"source":"yahoo"}'
```

The bot's real Technical and Strategy agents run on each historical bar. The signal comes from the bar close, the entry fills at the next bar's open with slippage, and SL/TP are checked bar by bar. If a bar touches both, the stop is assumed to hit first. Results are drawn as entry and exit markers on a [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/) candle chart, alongside win rate, P&L, drawdown, Sharpe, profit factor, R-multiples and an equity curve. Historical news isn't available, so the news agent is replaced by a price-momentum proxy (`news_mode`). Data sources are `yahoo` (free), `ibkr` and `synthetic`. No orders are sent.

## Setup

```bash
pip install -e ".[dev]"
pytest
```

Run the full stack (API, dashboard, Postgres, optional IB Gateway): see [DEPLOYMENT.md](DEPLOYMENT.md).

## Requirements

- Python 3.11+
- Interactive Brokers paper account + IB Gateway/TWS (optional; a built-in paper simulator is the default)
- AWS account (optional: Bedrock news analysis, SageMaker, Lambda handlers)

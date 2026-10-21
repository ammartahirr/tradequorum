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
├── backtest/        # Classic v1 backtester (replays history through the original agents)
├── quant/           # Quant engine v2: features, regimes, alpha ensemble, meta-model, risk, metrics
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

## Quant engine v2 (`src/quant/`)

The default strategy. Every step is causal: the decision is made at bar `t`'s close and the fill happens at `t+1`'s open.

1. **Features** (`features.py`): multi-horizon log returns, realized and Parkinson volatility, vol-of-vol, volatility percentile, ATR, RSI(2/14), MACD histogram in ATR units, Bollinger %B and squeeze, MA distances and slopes, ADX, Kaufman efficiency, Donchian position, volume z-score, rolling skew/kurtosis/autocorrelation.
2. **Regimes** (`regime.py`): trend_up, trend_down, range, transition and crisis. These come from ADX, efficiency ratio, Lo–MacKinlay variance ratio and the volatility percentile.
3. **Alpha ensemble** (`alphas.py`): vol-scaled time-series momentum, MA-spread trend, Donchian breakout after a volatility squeeze, and trend-aligned mean reversion. Weights are a regime prior multiplied by each alpha's own recent risk-adjusted P&L (EW Sharpe). News sentiment enters as a fifth alpha when available.
4. **Risk** (`engine.py`): ATR stop and target, move to breakeven after 1 ATR, chandelier trailing stop, exit on signal flip, time stop. Each trade risks a fixed fraction of equity, notional is capped by volatility targeting, and a drawdown throttle cuts risk, then stops trading. A 200-bar trend filter and a cost-to-edge filter are applied.
5. **ML meta-labeling** (`meta_model.py`, optional): triple-barrier labels feed a gradient-boosting plus logistic ensemble, trained walk-forward with purging and an embargo. It predicts P(win) and sizes trades with fractional Kelly, but only after it has earned trust (out-of-sample AUC ≥ 0.55 on ≥ 50 past trades).
6. **Validation**: Sharpe, Sortino, Calmar, Probabilistic Sharpe Ratio, a 1,000-run Monte Carlo of trade order, per-regime stats, alpha health, ML-vs-no-ML comparison, and a multi-symbol portfolio backtest (`POST /api/sandbox/portfolio`).

Live: `GET /api/quant/decision/{symbol}` returns the regime, alpha mix, P(win), size, SL/TP and reasons. With `STRATEGY_ENGINE=quant` the scheduler stores these as trade decisions every `QUANT_EVAL_INTERVAL_MINUTES`.

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

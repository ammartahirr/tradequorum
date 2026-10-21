"""
Historical market-data providers for the sandbox and live analysis.

- ``ibkr``      – Interactive Brokers (needs IB Gateway/TWS + data permissions)
- ``yahoo``     – Yahoo Finance via yfinance (free, no key, delayed/unofficial)
- ``synthetic`` – deterministic random walk (offline demos / CI)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.agents.technical.config import SUPPORTED_TIMEFRAMES, TIMEFRAME_MINUTES
from src.models.signals import OHLCV

from .base import BrokerError, MarketDataProvider
from .symbols import YF_INTERVALS, YF_MAX_PERIOD, parse_symbol, yahoo_ticker

logger = logging.getLogger(__name__)


def _validate(timeframe: str, count: int) -> None:
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe {timeframe}; use one of {SUPPORTED_TIMEFRAMES}")
    if count <= 0:
        raise ValueError("count must be positive")


def _make_bar(ts: datetime, o: float, h: float, l: float, c: float, v: float) -> Optional[OHLCV]:
    vals = (o, h, l, c)
    if any(x != x or x <= 0 for x in vals):  # NaN or non-positive
        return None
    return OHLCV(
        timestamp=ts, open=o, high=max(vals), low=min(vals), close=c,
        volume=max(0, int(v or 0)) if v == v else 0,
    )


class YahooDataProvider(MarketDataProvider):
    """Free Yahoo Finance candles (via ``yfinance``). Cached for ``cache_ttl`` seconds."""

    name = "yahoo"

    def __init__(self, cache_ttl: float = 300.0):
        self._cache: dict[tuple, tuple[float, list[OHLCV]]] = {}
        self._ttl = cache_ttl

    def _download(self, symbol: str, timeframe: str) -> list[OHLCV]:
        try:
            import yfinance as yf
        except ImportError as e:  # pragma: no cover
            raise BrokerError("yfinance is not installed: pip install yfinance") from e

        ticker = yahoo_ticker(symbol)
        df = yf.Ticker(ticker).history(
            period=YF_MAX_PERIOD[timeframe],
            interval=YF_INTERVALS[timeframe],
            auto_adjust=True,
        )
        if df is None or df.empty:
            raise BrokerError(f"Yahoo returned no data for {symbol} ({ticker})")

        if timeframe == "H4":
            df = (
                df.resample("4h", origin="start_day")
                .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
                .dropna()
            )

        now = datetime.now(timezone.utc)
        step = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
        out: list[OHLCV] = []
        for idx, row in df.iterrows():
            ts = idx.to_pydatetime()
            ts = ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            if timeframe in {"D1", "W1", "MN1"}:
                ts = ts.replace(hour=0, minute=0, second=0, microsecond=0)
            if ts + step > now:
                continue  # still-forming candle
            bar = _make_bar(ts, row["Open"], row["High"], row["Low"], row["Close"], row["Volume"])
            if bar:
                out.append(bar)
        return out

    async def get_candles(self, symbol, timeframe, count, end_time=None) -> list[OHLCV]:
        _validate(timeframe, count)
        key = (symbol.upper(), timeframe)
        cached = self._cache.get(key)
        if cached and _time.monotonic() - cached[0] < self._ttl:
            candles = cached[1]
        else:
            candles = await asyncio.to_thread(self._download, symbol, timeframe)
            self._cache[key] = (_time.monotonic(), candles)
        if end_time is not None:
            candles = [c for c in candles if c.timestamp <= end_time]
        return candles[-count:]


class SyntheticDataProvider(MarketDataProvider):
    """Deterministic geometric random walk – no network needed."""

    name = "synthetic"

    def __init__(self, seed: Optional[int] = None, volatility: float = 0.015, drift: float = 0.0002):
        self._seed = seed
        self._vol = volatility
        self._drift = drift

    async def get_candles(self, symbol, timeframe, count, end_time=None) -> list[OHLCV]:
        _validate(timeframe, count)
        seed = self._seed
        if seed is None:
            seed = int(hashlib.sha256(f"{symbol}{timeframe}".encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        step = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
        end = end_time or datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = end - step * count
        asset = parse_symbol(symbol)
        price = {"forex": 1.1, "crypto": 40000.0, "metal": 2000.0}.get(asset.asset_class, 100.0)
        scale = (TIMEFRAME_MINUTES[timeframe] / 1440) ** 0.5
        vol = self._vol * max(scale, 0.05)
        out: list[OHLCV] = []
        regime = 0.0
        for i in range(count):
            if i % 60 == 0:
                regime = rng.gauss(0, vol * 0.3)  # trending regimes
            r = rng.gauss(self._drift * scale + regime, vol)
            o = price
            c = max(o * (1 + r), 1e-6)
            wick = abs(r) + rng.uniform(0.1, 0.6) * vol
            h = max(o, c) * (1 + rng.uniform(0, wick))
            l = min(o, c) * (1 - rng.uniform(0, wick))
            out.append(OHLCV(timestamp=start + step * i, open=o, high=h, low=l, close=c,
                             volume=int(1_000_000 * rng.uniform(0.4, 2.5))))
            price = c
        return out


def create_data_provider(name: str, ibkr_client=None) -> MarketDataProvider:
    """Factory: ``ibkr`` | ``yahoo`` | ``synthetic``."""
    name = (name or "yahoo").lower()
    if name == "yahoo":
        return YahooDataProvider()
    if name == "synthetic":
        return SyntheticDataProvider()
    if name == "ibkr":
        if ibkr_client is None:
            from .ibkr import IBKRClient
            ibkr_client = IBKRClient()
        return ibkr_client
    raise ValueError(f"Unknown data source '{name}' (use ibkr, yahoo or synthetic)")

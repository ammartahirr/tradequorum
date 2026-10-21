"""
Training sandbox: replays historical candles through the real bot
(Technical Agent + Strategy Agent) and returns simulated entries/exits
for charting and performance stats. Never places real orders.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from core.config import settings
from services.broker_service import get_data_provider
from src.backtest.backtester import BacktestConfig, Backtester
from src.models.enums import TradingHorizon
from src.models.signals import OHLCV

logger = logging.getLogger(__name__)

_semaphore: Optional[asyncio.Semaphore] = None


def _sem() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.SANDBOX_MAX_CONCURRENT)
    return _semaphore


@dataclass
class SandboxRequest:
    symbol: str
    timeframe: str = "D1"
    bars: int = 1000
    source: Optional[str] = None
    horizon: str = "short_term"
    news_mode: str = "momentum"
    sizing_mode: str = "fixed"
    position_size_pct: float = 0.05
    max_risk_per_trade_pct: float = 0.02
    max_hold_bars: int = 30
    allow_short: bool = True
    initial_capital: float = 100000.0
    commission_pct: float = 0.001
    slippage_pct: float = 0.0005


def candle_to_dict(c: OHLCV) -> dict:
    return {
        "time": int(c.timestamp.timestamp()),
        "open": c.open,
        "high": c.high,
        "low": c.low,
        "close": c.close,
        "volume": c.volume,
    }


async def fetch_candles(symbol: str, timeframe: str, bars: int, source: Optional[str]) -> list[OHLCV]:
    bars = max(1, min(bars, settings.SANDBOX_MAX_BARS))
    provider = get_data_provider(source)
    return await provider.get_candles(symbol.upper(), timeframe, bars)


def _run_in_thread(bt: Backtester, symbol: str, candles: list[OHLCV], horizon: TradingHorizon):
    # The backtester is CPU-bound; run it on its own event loop in a worker
    # thread so the API (and the IB socket) stay responsive.
    return asyncio.run(bt.run_backtest(symbol, candles, horizon))


async def run_sandbox(req: SandboxRequest) -> dict:
    symbol = req.symbol.upper()
    source = (req.source or settings.DEFAULT_DATA_SOURCE).lower()
    started = time.perf_counter()
    candles = await fetch_candles(symbol, req.timeframe, req.bars, source)

    cfg = BacktestConfig(
        initial_capital=req.initial_capital,
        sizing_mode=req.sizing_mode,
        position_size_pct=req.position_size_pct,
        max_risk_per_trade_pct=req.max_risk_per_trade_pct,
        commission_pct=req.commission_pct,
        slippage_pct=req.slippage_pct,
        max_hold_bars=req.max_hold_bars,
        news_mode=req.news_mode,
        allow_short=req.allow_short,
    )
    min_bars = max(250, cfg.warmup_bars + 50)
    if len(candles) < min_bars:
        raise ValueError(
            f"Only {len(candles)} {req.timeframe} candles available for {symbol} from "
            f"'{source}'; need at least {min_bars}. Use more bars or a lower timeframe."
        )

    async with _sem():
        result = await asyncio.to_thread(
            _run_in_thread, Backtester(config=cfg), symbol, candles, TradingHorizon(req.horizon)
        )

    details = result.to_dict(include_details=True)
    trades = details.pop("trades")
    for t, tr in zip(trades, result.trades):
        t["entry_ts"] = int(tr.entry_time.timestamp())
        t["exit_ts"] = int(tr.exit_time.timestamp())
        t["signal_ts"] = int(tr.signal_time.timestamp()) if tr.signal_time else None
    equity = [
        {"time": int(t.timestamp()), "equity": e}
        for t, e in zip(result.equity_times, result.equity_curve)
    ]
    details.pop("equity_curve", None)
    skipped = details.pop("skipped_signals", [])

    return {
        "symbol": symbol,
        "timeframe": req.timeframe,
        "source": source,
        "bars": len(candles),
        "warmup_bars": cfg.warmup_bars,
        "first_bar": candles[0].timestamp.isoformat(),
        "last_bar": candles[-1].timestamp.isoformat(),
        "config": {
            "news_mode": cfg.news_mode,
            "sizing_mode": cfg.sizing_mode,
            "position_size_pct": cfg.position_size_pct,
            "max_risk_per_trade_pct": cfg.max_risk_per_trade_pct,
            "max_hold_bars": cfg.max_hold_bars,
            "commission_pct": cfg.commission_pct,
            "slippage_pct": cfg.slippage_pct,
            "allow_short": cfg.allow_short,
            "initial_capital": cfg.initial_capital,
            "horizon": req.horizon,
        },
        "stats": details,
        "trades": trades,
        "skipped_signals": skipped,
        "equity_curve": equity,
        "candles": [candle_to_dict(c) for c in candles],
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }

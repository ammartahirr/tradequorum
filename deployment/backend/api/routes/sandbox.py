"""Training sandbox API – backtest the bot on historical candles (no real orders)."""
import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.config import settings
from services.sandbox_service import SandboxRequest, candle_to_dict, fetch_candles, run_sandbox
from src.agents.technical.config import SUPPORTED_TIMEFRAMES
from src.brokers.base import BrokerError

logger = logging.getLogger(__name__)
router = APIRouter()

DataSource = Literal["ibkr", "yahoo", "synthetic"]


class BacktestBody(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, examples=["AAPL"])
    timeframe: str = Field("D1", description=f"One of {SUPPORTED_TIMEFRAMES}")
    bars: int = Field(1000, ge=250, le=20000)
    source: Optional[DataSource] = None
    horizon: Literal["short_term", "medium_term", "long_term"] = "short_term"
    news_mode: Literal["momentum", "neutral"] = "momentum"
    sizing_mode: Literal["fixed", "strategy"] = "fixed"
    position_size_pct: float = Field(0.05, gt=0, le=1)
    max_risk_per_trade_pct: float = Field(0.02, ge=0, le=1)
    max_hold_bars: int = Field(30, ge=1, le=1000)
    allow_short: bool = True
    initial_capital: float = Field(100000.0, gt=0)
    commission_pct: float = Field(0.001, ge=0, le=0.05)
    slippage_pct: float = Field(0.0005, ge=0, le=0.05)


def _check_timeframe(tf: str) -> str:
    tf = tf.upper()
    if tf not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(400, f"timeframe must be one of {SUPPORTED_TIMEFRAMES}")
    return tf


@router.get("/config")
async def sandbox_config():
    """Defaults for the dashboard form."""
    return {
        "symbols": settings.trading_symbols_list,
        "timeframes": SUPPORTED_TIMEFRAMES,
        "sources": ["yahoo", "ibkr", "synthetic"],
        "default_source": settings.DEFAULT_DATA_SOURCE,
        "max_bars": settings.SANDBOX_MAX_BARS,
    }


@router.get("/candles")
async def get_candles(
    symbol: str = Query(..., min_length=1, max_length=20),
    timeframe: str = "D1",
    bars: int = Query(500, ge=1, le=20000),
    source: Optional[DataSource] = None,
):
    """Raw candles for charting."""
    tf = _check_timeframe(timeframe)
    try:
        candles = await fetch_candles(symbol, tf, bars, source)
    except (BrokerError, ValueError) as e:
        raise HTTPException(502, str(e))
    return {"symbol": symbol.upper(), "timeframe": tf, "candles": [candle_to_dict(c) for c in candles]}


@router.post("/backtest")
async def backtest(body: BacktestBody):
    """
    Replay history through the bot and return simulated entries/exits,
    an equity curve and win-rate / drawdown / Sharpe statistics.
    """
    data = body.model_dump()
    data["timeframe"] = _check_timeframe(body.timeframe)
    try:
        return await run_sandbox(SandboxRequest(**data))
    except BrokerError as e:
        raise HTTPException(502, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

"""Live quant engine decisions."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from services.quant_service import live_decision
from src.brokers.base import BrokerError

router = APIRouter()


@router.get("/decision/{symbol}")
async def decision(
    symbol: str,
    timeframe: Optional[str] = Query(None, description="Defaults to QUANT_TIMEFRAME"),
    source: Optional[str] = Query(None, description="ibkr | yahoo | synthetic"),
):
    """What the engine would do on the next bar: regime, alpha mix, P(win), size, SL/TP, reasons."""
    try:
        return await live_decision(symbol, timeframe=timeframe.upper() if timeframe else None, source=source)
    except (BrokerError, ValueError) as e:
        raise HTTPException(400, str(e))

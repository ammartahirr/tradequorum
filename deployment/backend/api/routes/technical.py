"""Technical Agent API endpoints."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from api.routes.auth import get_current_user
from models.user import User

router = APIRouter()


class SupportResistanceResponse(BaseModel):
    level: float
    strength: float
    timeframe: str
    last_tested: datetime


class ConfluenceResponse(BaseModel):
    score: float
    factors: List[str]
    description: str


class TechnicalSignalResponse(BaseModel):
    signal_id: UUID
    symbol: str
    trend: str
    condition: str
    rsi: float
    current_price: float
    support_levels: List[SupportResistanceResponse]
    resistance_levels: List[SupportResistanceResponse]
    confluence_score: float
    confluence_factors: List[str]
    volume_trend: str
    timestamp: datetime

    class Config:
        from_attributes = True


class IndicatorsResponse(BaseModel):
    symbol: str
    rsi: float
    macd: dict
    bollinger: dict
    ma_50: float
    ma_200: float
    current_price: float
    timestamp: datetime


@router.get("/signals", response_model=List[TechnicalSignalResponse])
async def get_technical_signals(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get technical signals, optionally filtered by symbol."""
    from models.signal import TechnicalSignal
    
    query = select(TechnicalSignal)
    
    if symbol:
        query = query.where(TechnicalSignal.symbol == symbol)
    
    query = query.order_by(TechnicalSignal.timestamp.desc()).limit(limit)
    
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/signals/{signal_id}", response_model=TechnicalSignalResponse)
async def get_technical_signal(
    signal_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific technical signal by ID."""
    from models.signal import TechnicalSignal
    
    result = await db.execute(
        select(TechnicalSignal).where(TechnicalSignal.signal_id == signal_id)
    )
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal


@router.get("/analyze/{symbol}", response_model=TechnicalSignalResponse)
async def analyze_symbol(
    symbol: str,
    timeframe: str = Query("1d", description="Timeframe: 1m, 5m, 1h, 1d, 1w"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger technical analysis for a symbol."""
    from services.technical_service import TechnicalService
    
    service = TechnicalService()
    signal = await service.analyze_symbol(symbol, timeframe)
    return signal


@router.get("/indicators/{symbol}", response_model=IndicatorsResponse)
async def get_indicators(
    symbol: str,
    timeframe: str = Query("1d"),
    current_user: User = Depends(get_current_user),
):
    """Get current technical indicators for a symbol."""
    from services.technical_service import TechnicalService
    
    service = TechnicalService()
    indicators = await service.get_indicators(symbol, timeframe)
    return indicators


@router.get("/confluence/{symbol}", response_model=ConfluenceResponse)
async def get_confluence(
    symbol: str,
    current_user: User = Depends(get_current_user),
):
    """Get confluence analysis for a symbol."""
    from services.technical_service import TechnicalService
    
    service = TechnicalService()
    confluence = await service.get_confluence(symbol)
    return confluence


@router.get("/support-resistance/{symbol}")
async def get_support_resistance(
    symbol: str,
    lookback_years: int = Query(5, ge=1, le=10),
    current_user: User = Depends(get_current_user),
):
    """Get support and resistance levels for a symbol."""
    from services.technical_service import TechnicalService
    
    service = TechnicalService()
    levels = await service.get_support_resistance(symbol, lookback_years)
    return levels

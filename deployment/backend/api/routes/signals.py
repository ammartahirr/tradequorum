"""Combined signals API endpoints."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from api.routes.auth import get_current_user
from models.user import User

router = APIRouter()


class CombinedSignalResponse(BaseModel):
    signal_id: UUID
    agent_type: str  # "news" or "technical"
    symbol: str
    timestamp: datetime
    summary: dict  # Key fields from the signal


@router.get("/latest", response_model=List[CombinedSignalResponse])
async def get_latest_signals(
    symbol: Optional[str] = Query(None),
    agent_type: Optional[str] = Query(None, description="news or technical"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get latest signals from all agents."""
    from models.signal import NewsSignal, TechnicalSignal
    
    signals = []
    
    # Get news signals
    if agent_type is None or agent_type == "news":
        news_query = select(NewsSignal)
        if symbol:
            news_query = news_query.where(NewsSignal.symbol == symbol)
        news_query = news_query.order_by(NewsSignal.timestamp.desc()).limit(limit)
        
        result = await db.execute(news_query)
        for signal in result.scalars().all():
            signals.append(CombinedSignalResponse(
                signal_id=signal.signal_id,
                agent_type="news",
                symbol=signal.symbol,
                timestamp=signal.timestamp,
                summary={
                    "sentiment": signal.sentiment,
                    "impact_type": signal.impact_type,
                    "impact_score": signal.impact_score,
                    "confidence": signal.confidence,
                },
            ))
    
    # Get technical signals
    if agent_type is None or agent_type == "technical":
        tech_query = select(TechnicalSignal)
        if symbol:
            tech_query = tech_query.where(TechnicalSignal.symbol == symbol)
        tech_query = tech_query.order_by(TechnicalSignal.timestamp.desc()).limit(limit)
        
        result = await db.execute(tech_query)
        for signal in result.scalars().all():
            signals.append(CombinedSignalResponse(
                signal_id=signal.signal_id,
                agent_type="technical",
                symbol=signal.symbol,
                timestamp=signal.timestamp,
                summary={
                    "trend": signal.trend,
                    "condition": signal.condition,
                    "rsi": signal.rsi,
                    "confluence_score": signal.confluence_score,
                },
            ))
    
    # Sort by timestamp and limit
    signals.sort(key=lambda x: x.timestamp, reverse=True)
    return signals[:limit]


@router.get("/active")
async def get_active_signals(
    symbol: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get active (non-expired) signals that haven't been consumed."""
    from models.signal import NewsSignal, TechnicalSignal
    from datetime import timedelta
    
    now = datetime.utcnow()
    tech_cutoff = now - timedelta(hours=1)  # Technical signals valid for 1 hour
    
    result = {
        "news_signals": [],
        "technical_signals": [],
    }
    
    # Active news signals
    news_query = select(NewsSignal).where(
        and_(
            NewsSignal.expires_at > now,
            NewsSignal.consumed_by.is_(None),
        )
    )
    if symbol:
        news_query = news_query.where(NewsSignal.symbol == symbol)
    
    news_result = await db.execute(news_query)
    result["news_signals"] = [
        {
            "signal_id": str(s.signal_id),
            "symbol": s.symbol,
            "sentiment": s.sentiment,
            "impact_type": s.impact_type,
            "confidence": s.confidence,
            "expires_at": s.expires_at.isoformat(),
        }
        for s in news_result.scalars().all()
    ]
    
    # Active technical signals
    tech_query = select(TechnicalSignal).where(
        and_(
            TechnicalSignal.timestamp > tech_cutoff,
            TechnicalSignal.consumed_by.is_(None),
        )
    )
    if symbol:
        tech_query = tech_query.where(TechnicalSignal.symbol == symbol)
    
    tech_result = await db.execute(tech_query)
    result["technical_signals"] = [
        {
            "signal_id": str(s.signal_id),
            "symbol": s.symbol,
            "trend": s.trend,
            "condition": s.condition,
            "rsi": s.rsi,
            "confluence_score": s.confluence_score,
        }
        for s in tech_result.scalars().all()
    ]
    
    return result


@router.get("/symbols")
async def get_tracked_symbols(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get list of symbols with recent signals."""
    from models.signal import NewsSignal, TechnicalSignal
    from sqlalchemy import distinct, union_all
    
    # Get distinct symbols from both tables
    news_symbols = select(distinct(NewsSignal.symbol))
    tech_symbols = select(distinct(TechnicalSignal.symbol))
    
    news_result = await db.execute(news_symbols)
    tech_result = await db.execute(tech_symbols)
    
    symbols = set()
    symbols.update(row[0] for row in news_result.fetchall())
    symbols.update(row[0] for row in tech_result.fetchall())
    
    return {"symbols": sorted(list(symbols))}

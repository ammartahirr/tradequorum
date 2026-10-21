"""News Agent API endpoints."""
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


class NewsSignalResponse(BaseModel):
    signal_id: UUID
    symbol: str
    sentiment: str
    impact_type: str
    impact_score: float
    confidence: float
    reasoning: str
    source_items: List[str]
    timestamp: datetime
    expires_at: datetime

    class Config:
        from_attributes = True


class NewsAnalysisRequest(BaseModel):
    headline: str
    content: str
    symbols: List[str]
    source: str = "manual"
    url: Optional[str] = None


@router.get("/signals", response_model=List[NewsSignalResponse])
async def get_news_signals(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    limit: int = Query(50, ge=1, le=200),
    include_expired: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get news signals, optionally filtered by symbol."""
    from models.signal import NewsSignal
    
    query = select(NewsSignal)
    
    conditions = []
    if symbol:
        conditions.append(NewsSignal.symbol == symbol)
    if not include_expired:
        conditions.append(NewsSignal.expires_at > datetime.utcnow())
    
    if conditions:
        query = query.where(and_(*conditions))
    
    query = query.order_by(NewsSignal.timestamp.desc()).limit(limit)
    
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/signals/{signal_id}", response_model=NewsSignalResponse)
async def get_news_signal(
    signal_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific news signal by ID."""
    from models.signal import NewsSignal
    
    result = await db.execute(
        select(NewsSignal).where(NewsSignal.signal_id == signal_id)
    )
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal


@router.post("/analyze", response_model=NewsSignalResponse)
async def analyze_news(
    request: NewsAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger news analysis for a given article."""
    from services.news_service import NewsService
    
    service = NewsService()
    signal = await service.analyze_single_news(
        headline=request.headline,
        content=request.content,
        symbols=request.symbols,
        source=request.source,
        url=request.url,
    )
    return signal


@router.post("/scrape")
async def trigger_scrape(
    current_user: User = Depends(get_current_user),
):
    """Manually trigger news scraping (admin only)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from services.news_service import NewsService
    
    service = NewsService()
    count = await service.scrape_and_analyze_news()
    return {"message": f"Scraped and analyzed {count} news items"}


@router.get("/sentiment/{symbol}")
async def get_aggregate_sentiment(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get aggregate sentiment for a symbol from recent news."""
    from services.news_service import NewsService
    
    service = NewsService()
    sentiment = await service.get_aggregate_sentiment(symbol)
    return {"symbol": symbol, "sentiment": sentiment}

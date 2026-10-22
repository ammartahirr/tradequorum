"""Strategy Agent API endpoints."""
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


class TradeDecisionResponse(BaseModel):
    decision_id: UUID
    symbol: str
    action: str
    conviction: str
    horizon: str
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size_pct: float
    risk_reward_ratio: float
    reasoning: str
    news_signal_id: Optional[UUID]
    technical_signal_id: Optional[UUID]
    timestamp: datetime
    expires_at: datetime

    class Config:
        from_attributes = True


class EvaluateRequest(BaseModel):
    symbol: str
    news_signal_id: UUID
    technical_signal_id: UUID
    horizon: str = "short_term"


class PerformanceResponse(BaseModel):
    total_trades: int
    winning_trades: int
    win_rate: float
    avg_risk_reward: float
    max_drawdown: float
    sharpe_ratio: Optional[float]


@router.get("/decisions", response_model=List[TradeDecisionResponse])
async def get_trade_decisions(
    symbol: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    include_expired: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get trade decisions, optionally filtered."""
    from models.trade import TradeDecision
    
    query = select(TradeDecision)
    
    conditions = []
    if symbol:
        conditions.append(TradeDecision.symbol == symbol)
    if action:
        conditions.append(TradeDecision.action == action)
    if not include_expired:
        conditions.append(TradeDecision.expires_at > datetime.utcnow())
    
    if conditions:
        query = query.where(and_(*conditions))
    
    query = query.order_by(TradeDecision.timestamp.desc()).limit(limit)
    
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/decisions/{decision_id}", response_model=TradeDecisionResponse)
async def get_trade_decision(
    decision_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific trade decision by ID."""
    from models.trade import TradeDecision
    
    result = await db.execute(
        select(TradeDecision).where(TradeDecision.decision_id == decision_id)
    )
    decision = result.scalar_one_or_none()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    return decision


@router.post("/evaluate", response_model=TradeDecisionResponse)
async def evaluate_signals(
    request: EvaluateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger strategy evaluation for given signals."""
    from services.strategy_service import StrategyService
    
    service = StrategyService()
    decision = await service.evaluate_signals(
        symbol=request.symbol,
        news_signal_id=request.news_signal_id,
        technical_signal_id=request.technical_signal_id,
        horizon=request.horizon,
    )
    if decision is None:
        raise HTTPException(status_code=422, detail="Signals did not produce an actionable trade")
    return decision


@router.get("/performance", response_model=PerformanceResponse)
async def get_performance(
    period: str = Query("30d", description="Period: 7d, 30d, 90d, 1y, all"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get strategy performance metrics."""
    from services.strategy_service import StrategyService
    
    service = StrategyService()
    performance = await service.get_performance(period)
    return performance


@router.post("/backtest")
async def run_backtest(
    symbol: str,
    start_date: datetime,
    end_date: datetime,
    current_user: User = Depends(get_current_user),
):
    """Run backtest for a symbol over a date range."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from services.strategy_service import StrategyService
    
    service = StrategyService()
    results = await service.backtest(symbol, start_date, end_date)
    return results

"""Position Manager API endpoints."""
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


class TradeRecordResponse(BaseModel):
    trade_id: UUID
    symbol: str
    action: str
    horizon: str
    entry_price: float
    exit_price: Optional[float]
    stop_loss: float
    take_profit: float
    position_size: float
    status: str
    pnl: Optional[float]
    pnl_pct: Optional[float]
    conviction: str
    decision_reasoning: str
    opened_at: datetime
    closed_at: Optional[datetime]
    exness_order_id: str

    class Config:
        from_attributes = True


class PositionSummary(BaseModel):
    total_open: int
    total_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float


@router.get("/", response_model=List[TradeRecordResponse])
async def get_positions(
    symbol: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="open, closed_profit, closed_loss, closed_sl, closed_tp"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get trade records/positions, optionally filtered."""
    from models.trade import TradeRecord
    
    query = select(TradeRecord)
    
    conditions = []
    if symbol:
        conditions.append(TradeRecord.symbol == symbol)
    if status:
        conditions.append(TradeRecord.status == status)
    
    if conditions:
        query = query.where(and_(*conditions))
    
    query = query.order_by(TradeRecord.opened_at.desc()).limit(limit)
    
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/open", response_model=List[TradeRecordResponse])
async def get_open_positions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all open positions."""
    from models.trade import TradeRecord
    
    result = await db.execute(
        select(TradeRecord)
        .where(TradeRecord.status == "open")
        .order_by(TradeRecord.opened_at.desc())
    )
    return result.scalars().all()


@router.get("/summary", response_model=PositionSummary)
async def get_position_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get summary of open positions."""
    from services.position_service import PositionService
    
    service = PositionService()
    summary = await service.get_position_summary()
    return summary


@router.get("/{trade_id}", response_model=TradeRecordResponse)
async def get_position(
    trade_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific trade record by ID."""
    from models.trade import TradeRecord
    
    result = await db.execute(
        select(TradeRecord).where(TradeRecord.trade_id == trade_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Position not found")
    return record


@router.post("/{trade_id}/close")
async def close_position(
    trade_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually close a position."""
    from services.position_service import PositionService
    
    service = PositionService()
    result = await service.close_position(trade_id)
    return result


@router.get("/history/closed", response_model=List[TradeRecordResponse])
async def get_closed_positions(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get closed positions from the last N days."""
    from models.trade import TradeRecord
    from datetime import timedelta
    
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    result = await db.execute(
        select(TradeRecord)
        .where(
            and_(
                TradeRecord.status != "open",
                TradeRecord.closed_at >= cutoff,
            )
        )
        .order_by(TradeRecord.closed_at.desc())
    )
    return result.scalars().all()

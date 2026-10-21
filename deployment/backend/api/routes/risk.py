"""Risk Manager API endpoints."""
from datetime import datetime, date
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from api.routes.auth import get_current_user
from models.user import User

router = APIRouter()


class RiskAssessmentResponse(BaseModel):
    id: UUID
    decision_id: UUID
    approved: bool
    adjusted_size: Optional[float]
    risk_score: float
    warnings: List[str]
    rejection_reason: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class RiskLimitsResponse(BaseModel):
    max_position_pct: float
    max_portfolio_risk_pct: float
    max_correlated_exposure: float
    max_daily_loss_pct: float
    max_open_positions: int


class PortfolioRiskResponse(BaseModel):
    total_value: float
    open_positions_count: int
    total_exposure: float
    correlated_exposure: dict
    daily_loss: float
    daily_loss_pct: float
    trading_halted: bool


class DailyLossResponse(BaseModel):
    date: date
    cumulative_loss: float
    portfolio_value: float
    loss_pct: float
    trading_halted: bool


@router.get("/assessments", response_model=List[RiskAssessmentResponse])
async def get_risk_assessments(
    decision_id: Optional[UUID] = Query(None),
    approved: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get risk assessments, optionally filtered."""
    from models.risk import RiskAssessment
    
    query = select(RiskAssessment)
    
    if decision_id:
        query = query.where(RiskAssessment.decision_id == decision_id)
    if approved is not None:
        query = query.where(RiskAssessment.approved == approved)
    
    query = query.order_by(RiskAssessment.created_at.desc()).limit(limit)
    
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/limits", response_model=RiskLimitsResponse)
async def get_risk_limits(
    current_user: User = Depends(get_current_user),
):
    """Get current risk limits configuration."""
    from core.config import settings
    
    return RiskLimitsResponse(
        max_position_pct=settings.MAX_POSITION_PCT,
        max_portfolio_risk_pct=settings.MAX_PORTFOLIO_RISK_PCT,
        max_correlated_exposure=settings.MAX_CORRELATED_EXPOSURE,
        max_daily_loss_pct=settings.MAX_DAILY_LOSS_PCT,
        max_open_positions=settings.MAX_OPEN_POSITIONS,
    )


@router.get("/portfolio", response_model=PortfolioRiskResponse)
async def get_portfolio_risk(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current portfolio risk status."""
    from services.risk_service import RiskService
    
    service = RiskService()
    risk = await service.get_portfolio_risk()
    return risk


@router.get("/daily-loss", response_model=DailyLossResponse)
async def get_daily_loss(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current day's loss tracking."""
    from services.risk_service import RiskService
    
    service = RiskService()
    daily_loss = await service.get_daily_loss()
    return daily_loss


@router.post("/assess/{decision_id}", response_model=RiskAssessmentResponse)
async def assess_trade(
    decision_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger risk assessment for a trade decision."""
    from services.risk_service import RiskService
    
    service = RiskService()
    assessment = await service.assess_trade(decision_id)
    return assessment


@router.post("/reset-daily-loss")
async def reset_daily_loss(
    current_user: User = Depends(get_current_user),
):
    """Reset daily loss tracking (admin only, for testing)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from services.risk_service import RiskService
    
    service = RiskService()
    await service.reset_daily_loss()
    return {"message": "Daily loss tracking reset"}

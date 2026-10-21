"""Risk management models."""
import uuid
from datetime import datetime, date

from sqlalchemy import Column, String, Float, Boolean, DateTime, Date, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from core.database import Base


class RiskAssessment(Base):
    """Risk assessment for a trade decision."""
    __tablename__ = "risk_assessments"
    __table_args__ = {"schema": "aitrading"}
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    decision_id = Column(UUID(as_uuid=True), ForeignKey("aitrading.trade_decisions.decision_id"))
    approved = Column(Boolean, nullable=False)
    adjusted_size = Column(Float)
    risk_score = Column(Float, nullable=False)
    warnings = Column(JSONB, nullable=False, default=list)
    rejection_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class DailyLossTracking(Base):
    """Daily loss tracking for risk management."""
    __tablename__ = "daily_loss_tracking"
    __table_args__ = {"schema": "aitrading"}
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(Date, unique=True, nullable=False, index=True)
    cumulative_loss = Column(Float, nullable=False, default=0)
    portfolio_value = Column(Float, nullable=False)
    loss_pct = Column(Float, nullable=False, default=0)
    trading_halted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

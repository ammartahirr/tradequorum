"""Signal models for News and Technical agents."""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Float, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB

from core.database import Base


class NewsSignal(Base):
    """News signal from the News Agent."""
    __tablename__ = "news_signals"
    __table_args__ = {"schema": "aitrading"}
    
    signal_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String(20), nullable=False, index=True)
    sentiment = Column(String(20), nullable=False)  # very_bullish, bullish, neutral, bearish, very_bearish
    impact_type = Column(String(20), nullable=False)  # cash_flow, hype, regulatory, macro
    impact_score = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    reasoning = Column(Text, nullable=False)
    source_items = Column(JSONB, nullable=False, default=list)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed_by = Column(String(50))
    resulted_in_trade = Column(Boolean, default=False)
    trade_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class TechnicalSignal(Base):
    """Technical signal from the Technical Agent."""
    __tablename__ = "technical_signals"
    __table_args__ = {"schema": "aitrading"}
    
    signal_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String(20), nullable=False, index=True)
    trend = Column(String(20), nullable=False)  # strong_uptrend, uptrend, sideways, downtrend, strong_downtrend
    condition = Column(String(20), nullable=False)  # oversold, neutral, overbought
    rsi = Column(Float, nullable=False)
    current_price = Column(Float, nullable=False)
    support_levels = Column(JSONB, nullable=False, default=list)
    resistance_levels = Column(JSONB, nullable=False, default=list)
    confluence_score = Column(Float, nullable=False)
    confluence_factors = Column(JSONB, nullable=False, default=list)
    confluence_description = Column(Text)
    volume_trend = Column(String(20), nullable=False)
    interest_rate_impact = Column(Float)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    consumed_by = Column(String(50))
    resulted_in_trade = Column(Boolean, default=False)
    trade_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

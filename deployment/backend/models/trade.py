"""Trade models for decisions and records."""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Float, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from core.database import Base


class TradeDecision(Base):
    """Trade decision from the Strategy Agent."""
    __tablename__ = "trade_decisions"
    __table_args__ = {"schema": "aitrading"}
    
    decision_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String(20), nullable=False, index=True)
    action = Column(String(20), nullable=False)  # strong_buy, buy, wait_pullback, hold, sell, strong_sell, no_trade
    conviction = Column(String(20), nullable=False)  # high, medium, low
    horizon = Column(String(20), nullable=False)  # short_term, medium_term, long_term
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    position_size_pct = Column(Float, nullable=False)
    risk_reward_ratio = Column(Float, nullable=False)
    reasoning = Column(Text, nullable=False)
    news_signal_id = Column(UUID(as_uuid=True), ForeignKey("aitrading.news_signals.signal_id"))
    technical_signal_id = Column(UUID(as_uuid=True), ForeignKey("aitrading.technical_signals.signal_id"))
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class TradeRecord(Base):
    """Executed trade record."""
    __tablename__ = "trade_records"
    __table_args__ = {"schema": "aitrading"}
    
    trade_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String(20), nullable=False, index=True)
    action = Column(String(20), nullable=False)
    horizon = Column(String(20), nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float)
    stop_loss = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    position_size = Column(Float, nullable=False)
    status = Column(String(20), nullable=False, default="open", index=True)  # open, closed_profit, closed_loss, closed_sl, closed_tp
    pnl = Column(Float)
    pnl_pct = Column(Float)
    conviction = Column(String(20), nullable=False)
    news_signal_id = Column(UUID(as_uuid=True), ForeignKey("aitrading.news_signals.signal_id"))
    technical_signal_id = Column(UUID(as_uuid=True), ForeignKey("aitrading.technical_signals.signal_id"))
    decision_id = Column(UUID(as_uuid=True), ForeignKey("aitrading.trade_decisions.decision_id"))
    decision_reasoning = Column(Text, nullable=False)
    opened_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    closed_at = Column(DateTime(timezone=True))
    exness_order_id = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

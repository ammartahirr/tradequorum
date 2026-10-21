"""Order models."""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Float, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from core.database import Base


class OrderResult(Base):
    """Order execution result."""
    __tablename__ = "order_results"
    __table_args__ = {"schema": "aitrading"}
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(String(100), unique=True, nullable=False)
    trade_id = Column(UUID(as_uuid=True), ForeignKey("aitrading.trade_records.trade_id"))
    symbol = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False)  # filled, partial, rejected, pending
    filled_price = Column(Float, nullable=False)
    filled_quantity = Column(Float, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

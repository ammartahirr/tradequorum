"""Position Manager service."""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_

from core.database import get_db_context
from models.trade import TradeRecord
from api.websocket import broadcast_position_update

logger = logging.getLogger(__name__)


class PositionService:
    """Service for position management and monitoring."""
    
    async def monitor_positions(self):
        """Monitor open positions for SL/TP hits."""
        async with get_db_context() as db:
            # Get all open positions
            result = await db.execute(
                select(TradeRecord).where(TradeRecord.status == "open")
            )
            positions = result.scalars().all()
            
            for position in positions:
                await self._check_position(position, db)
    
    async def _check_position(self, position: TradeRecord, db):
        """Check if a position has hit SL or TP."""
        # Get current price
        current_price = await self._get_current_price(position.symbol)
        
        if current_price is None:
            return
        
        is_buy = position.action in ["strong_buy", "buy"]
        
        # Check stop-loss
        if is_buy and current_price <= position.stop_loss:
            await self._close_position(position, current_price, "closed_sl", db)
        elif not is_buy and current_price >= position.stop_loss:
            await self._close_position(position, current_price, "closed_sl", db)
        
        # Check take-profit
        elif is_buy and current_price >= position.take_profit:
            await self._close_position(position, current_price, "closed_tp", db)
        elif not is_buy and current_price <= position.take_profit:
            await self._close_position(position, current_price, "closed_tp", db)
    
    async def _close_position(
        self,
        position: TradeRecord,
        exit_price: float,
        status: str,
        db,
    ):
        """Close a position and update records."""
        is_buy = position.action in ["strong_buy", "buy"]
        
        # Calculate PnL
        if is_buy:
            pnl = (exit_price - position.entry_price) * position.position_size
            pnl_pct = (exit_price - position.entry_price) / position.entry_price * 100
        else:
            pnl = (position.entry_price - exit_price) * position.position_size
            pnl_pct = (position.entry_price - exit_price) / position.entry_price * 100
        
        # Update position
        position.exit_price = exit_price
        position.status = status
        position.pnl = pnl
        position.pnl_pct = pnl_pct
        position.closed_at = datetime.utcnow()
        
        from services.broker_service import get_broker
        broker = get_broker()
        if broker.name == "paper" or status in {"closed_profit", "closed_loss"}:
            # Manual closes (and all paper-sim closes) must flatten at the broker;
            # on IBKR the attached bracket SL/TP orders handle closed_sl / closed_tp.
            try:
                await broker.close_position(position.symbol)
            except Exception as e:
                logger.warning(f"Broker close for {position.symbol} failed: {e}")

        # Update daily loss tracking if loss
        if pnl < 0:
            await self._update_daily_loss(abs(pnl), db)
        
        logger.info(f"Position {position.trade_id} closed: {status}, PnL: {pnl:.2f} ({pnl_pct:.2f}%)")
        
        # Broadcast update
        await broadcast_position_update({
            "trade_id": str(position.trade_id),
            "symbol": position.symbol,
            "status": status,
            "exit_price": exit_price,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
        })
    
    async def _get_current_price(self, symbol: str) -> Optional[float]:
        """Current mid price from the configured broker (None if unavailable)."""
        from services.broker_service import get_broker

        try:
            broker = get_broker()
            await broker.ensure_connected()
            quote = await broker.get_current_price(symbol)
            return float(quote["mid"]) if quote else None
        except Exception as e:
            logger.warning(f"Price unavailable for {symbol}: {e}")
            return None
    
    async def _update_daily_loss(self, loss: float, db):
        """Update daily loss tracking."""
        from datetime import date
        from models.risk import DailyLossTracking
        from core.config import settings
        
        today = date.today()
        
        result = await db.execute(
            select(DailyLossTracking).where(DailyLossTracking.date == today)
        )
        tracking = result.scalar_one_or_none()
        
        if tracking:
            tracking.cumulative_loss += loss
            tracking.loss_pct = tracking.cumulative_loss / tracking.portfolio_value * 100
            
            # Check if limit breached
            if tracking.loss_pct >= settings.MAX_DAILY_LOSS_PCT * 100:
                tracking.trading_halted = True
                logger.warning(f"Daily loss limit breached: {tracking.loss_pct:.2f}%")
    
    async def close_position(self, trade_id: UUID) -> dict:
        """Manually close a position."""
        async with get_db_context() as db:
            position = await db.get(TradeRecord, trade_id)
            
            if not position:
                return {"success": False, "error": "Position not found"}
            
            if position.status != "open":
                return {"success": False, "error": "Position already closed"}
            
            # Get current price
            current_price = await self._get_current_price(position.symbol)
            
            if current_price is None:
                return {"success": False, "error": "Could not get current price"}
            
            # Determine status based on PnL
            is_buy = position.action in ["strong_buy", "buy"]
            if is_buy:
                pnl = (current_price - position.entry_price) * position.position_size
            else:
                pnl = (position.entry_price - current_price) * position.position_size
            
            status = "closed_profit" if pnl >= 0 else "closed_loss"
            
            await self._close_position(position, current_price, status, db)
            
            return {
                "success": True,
                "exit_price": current_price,
                "pnl": pnl,
                "status": status,
            }
    
    async def get_position_summary(self) -> dict:
        """Get summary of open positions."""
        async with get_db_context() as db:
            result = await db.execute(
                select(TradeRecord).where(TradeRecord.status == "open")
            )
            positions = result.scalars().all()
            
            total_value = 0
            unrealized_pnl = 0
            
            for pos in positions:
                current_price = await self._get_current_price(pos.symbol)
                if current_price:
                    position_value = pos.position_size * current_price
                    total_value += position_value
                    
                    is_buy = pos.action in ["strong_buy", "buy"]
                    if is_buy:
                        unrealized_pnl += (current_price - pos.entry_price) * pos.position_size
                    else:
                        unrealized_pnl += (pos.entry_price - current_price) * pos.position_size
            
            entry_value = sum(p.position_size * p.entry_price for p in positions)
            unrealized_pnl_pct = (unrealized_pnl / entry_value * 100) if entry_value > 0 else 0
            
            return {
                "total_open": len(positions),
                "total_value": total_value,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": unrealized_pnl_pct,
            }

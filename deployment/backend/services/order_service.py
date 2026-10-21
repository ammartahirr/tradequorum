"""Order Executor service - interfaces with MT5."""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from core.config import settings
from core.database import get_db_context
from models.trade import TradeDecision, TradeRecord
from models.order import OrderResult
from api.websocket import broadcast_trade_update

logger = logging.getLogger(__name__)


class OrderService:
    """Service for order execution via MT5."""
    
    def __init__(self):
        self.mt5_connected = False
    
    async def _ensure_mt5_connection(self):
        """Ensure MT5 is connected."""
        if self.mt5_connected:
            return
        
        try:
            import MetaTrader5 as mt5
            
            if not mt5.initialize():
                raise ConnectionError("MT5 initialization failed")
            
            if not mt5.login(
                login=int(settings.MT5_LOGIN),
                password=settings.MT5_PASSWORD,
                server=settings.MT5_SERVER,
            ):
                raise ConnectionError(f"MT5 login failed: {mt5.last_error()}")
            
            self.mt5_connected = True
            logger.info("MT5 connected successfully")
            
        except ImportError:
            logger.warning("MetaTrader5 not available - using mock mode")
            self.mt5_connected = True  # Mock mode
    
    async def place_order(self, decision_id: UUID) -> OrderResult:
        """Place an order based on a trade decision."""
        await self._ensure_mt5_connection()
        
        async with get_db_context() as db:
            decision = await db.get(TradeDecision, decision_id)
            if not decision:
                raise ValueError("Decision not found")
            
            # Check if already executed
            from sqlalchemy import select
            existing = await db.execute(
                select(TradeRecord).where(TradeRecord.decision_id == decision_id)
            )
            if existing.scalar_one_or_none():
                raise ValueError("Decision already executed")
            
            # Execute order with retry
            order_result = await self._execute_with_retry(decision)
            
            if order_result.status == "filled":
                # Create trade record
                trade = TradeRecord(
                    trade_id=uuid4(),
                    symbol=decision.symbol,
                    action=decision.action,
                    horizon=decision.horizon,
                    entry_price=order_result.filled_price,
                    stop_loss=decision.stop_loss,
                    take_profit=decision.take_profit,
                    position_size=order_result.filled_quantity,
                    status="open",
                    conviction=decision.conviction,
                    news_signal_id=decision.news_signal_id,
                    technical_signal_id=decision.technical_signal_id,
                    decision_id=decision_id,
                    decision_reasoning=decision.reasoning,
                    exness_order_id=order_result.order_id,
                )
                db.add(trade)
                
                # Link order result to trade
                order_result.trade_id = trade.trade_id
            
            db.add(order_result)
            
            # Broadcast update
            await broadcast_trade_update({
                "order_id": order_result.order_id,
                "symbol": order_result.symbol,
                "status": order_result.status,
                "filled_price": order_result.filled_price,
                "filled_quantity": order_result.filled_quantity,
            })
            
            return order_result
    
    async def _execute_with_retry(self, decision: TradeDecision, max_retries: int = 3) -> OrderResult:
        """Execute order with exponential backoff retry."""
        import asyncio
        
        delays = [1, 2, 4]  # Exponential backoff
        last_error = None
        
        for attempt in range(max_retries):
            try:
                return await self._execute_order(decision)
            except Exception as e:
                last_error = e
                logger.warning(f"Order attempt {attempt + 1} failed: {e}")
                
                if attempt < max_retries - 1:
                    # Check position state before retry
                    await self._verify_position_state(decision.symbol)
                    await asyncio.sleep(delays[attempt])
        
        # All retries failed
        return OrderResult(
            id=uuid4(),
            order_id=f"FAILED-{uuid4().hex[:8]}",
            symbol=decision.symbol,
            status="rejected",
            filled_price=0,
            filled_quantity=0,
            timestamp=datetime.utcnow(),
        )
    
    async def _execute_order(self, decision: TradeDecision) -> OrderResult:
        """Execute a single order via MT5."""
        try:
            import MetaTrader5 as mt5
            
            # Determine order type
            if decision.action in ["strong_buy", "buy"]:
                order_type = mt5.ORDER_TYPE_BUY
            else:
                order_type = mt5.ORDER_TYPE_SELL
            
            # Calculate lot size (simplified)
            lot_size = 0.1  # Would calculate based on position_size_pct and account
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": decision.symbol,
                "volume": lot_size,
                "type": order_type,
                "price": mt5.symbol_info_tick(decision.symbol).ask if order_type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(decision.symbol).bid,
                "sl": decision.stop_loss,
                "tp": decision.take_profit,
                "deviation": 20,
                "magic": 234000,
                "comment": f"AI Trading - {decision.decision_id}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            result = mt5.order_send(request)
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                raise Exception(f"Order failed: {result.comment}")
            
            return OrderResult(
                id=uuid4(),
                order_id=str(result.order),
                symbol=decision.symbol,
                status="filled",
                filled_price=result.price,
                filled_quantity=result.volume,
                timestamp=datetime.utcnow(),
            )
            
        except ImportError:
            # Mock mode for development
            logger.info(f"Mock order execution for {decision.symbol}")
            return OrderResult(
                id=uuid4(),
                order_id=f"MOCK-{uuid4().hex[:8]}",
                symbol=decision.symbol,
                status="filled",
                filled_price=decision.entry_price,
                filled_quantity=decision.position_size_pct * 1000,  # Mock quantity
                timestamp=datetime.utcnow(),
            )
    
    async def _verify_position_state(self, symbol: str):
        """Verify position state before retry."""
        try:
            import MetaTrader5 as mt5
            positions = mt5.positions_get(symbol=symbol)
            logger.info(f"Current positions for {symbol}: {len(positions) if positions else 0}")
        except ImportError:
            pass
    
    async def modify_order(
        self,
        order_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> bool:
        """Modify an existing order's SL/TP."""
        await self._ensure_mt5_connection()
        
        try:
            import MetaTrader5 as mt5
            
            # Get position by order ID
            positions = mt5.positions_get()
            position = next((p for p in positions if str(p.ticket) == order_id), None)
            
            if not position:
                return False
            
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": position.ticket,
                "sl": stop_loss or position.sl,
                "tp": take_profit or position.tp,
            }
            
            result = mt5.order_send(request)
            return result.retcode == mt5.TRADE_RETCODE_DONE
            
        except ImportError:
            logger.info(f"Mock modify order {order_id}")
            return True
    
    async def close_position(self, order_id: str) -> dict:
        """Close a position."""
        await self._ensure_mt5_connection()
        
        try:
            import MetaTrader5 as mt5
            
            positions = mt5.positions_get()
            position = next((p for p in positions if str(p.ticket) == order_id), None)
            
            if not position:
                return {"success": False, "error": "Position not found"}
            
            # Close position
            close_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(position.symbol).bid if close_type == mt5.ORDER_TYPE_SELL else mt5.symbol_info_tick(position.symbol).ask
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": position.ticket,
                "symbol": position.symbol,
                "volume": position.volume,
                "type": close_type,
                "price": price,
                "deviation": 20,
                "magic": 234000,
                "comment": "AI Trading - Close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            result = mt5.order_send(request)
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                return {"success": True, "close_price": result.price}
            return {"success": False, "error": result.comment}
            
        except ImportError:
            logger.info(f"Mock close position {order_id}")
            return {"success": True, "close_price": 100.0}
    
    async def get_account_info(self) -> dict:
        """Get MT5 account information."""
        await self._ensure_mt5_connection()
        
        try:
            import MetaTrader5 as mt5
            
            info = mt5.account_info()
            if info is None:
                return {"error": "Failed to get account info"}
            
            return {
                "balance": info.balance,
                "equity": info.equity,
                "margin": info.margin,
                "free_margin": info.margin_free,
                "profit": info.profit,
                "leverage": info.leverage,
                "currency": info.currency,
            }
            
        except ImportError:
            return {
                "balance": 100000.0,
                "equity": 100000.0,
                "margin": 0,
                "free_margin": 100000.0,
                "profit": 0,
                "leverage": 100,
                "currency": "USD",
                "mode": "mock",
            }

"""Order Executor service – routes orders to the configured broker (IBKR paper / paper sim)."""
import asyncio
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select

from api.websocket import broadcast_trade_update
from core.database import get_db_context
from models.order import OrderResult
from models.trade import TradeDecision, TradeRecord
from services.broker_service import get_broker

logger = logging.getLogger(__name__)

BUY_ACTIONS = {"strong_buy", "buy"}
SELL_ACTIONS = {"strong_sell", "sell"}


class OrderService:
    """Order execution via the broker abstraction (src/brokers)."""

    def __init__(self):
        self.broker = get_broker()

    async def place_order(self, decision_id: UUID) -> OrderResult:
        """Place a bracket order (market entry + SL + TP) for a trade decision."""
        async with get_db_context() as db:
            decision = await db.get(TradeDecision, decision_id)
            if not decision:
                raise ValueError("Decision not found")
            if decision.action not in BUY_ACTIONS | SELL_ACTIONS:
                raise ValueError(f"Decision action '{decision.action}' is not tradable")

            existing = await db.execute(
                select(TradeRecord).where(TradeRecord.decision_id == decision_id)
            )
            if existing.scalar_one_or_none():
                raise ValueError("Decision already executed")

            order_result = await self._execute_with_retry(decision)

            if order_result.status in {"filled", "partial", "pending"}:
                trade = TradeRecord(
                    trade_id=uuid4(),
                    symbol=decision.symbol,
                    action=decision.action,
                    horizon=decision.horizon,
                    entry_price=order_result.filled_price or decision.entry_price,
                    stop_loss=decision.stop_loss,
                    take_profit=decision.take_profit,
                    position_size=order_result.filled_quantity or self._last_requested_qty,
                    status="open",
                    conviction=decision.conviction,
                    news_signal_id=decision.news_signal_id,
                    technical_signal_id=decision.technical_signal_id,
                    decision_id=decision_id,
                    decision_reasoning=decision.reasoning,
                    exness_order_id=order_result.order_id,  # generic broker order id
                )
                db.add(trade)
                await db.flush()
                order_result.trade_id = trade.trade_id

            db.add(order_result)

            await broadcast_trade_update({
                "order_id": order_result.order_id,
                "symbol": order_result.symbol,
                "status": order_result.status,
                "filled_price": order_result.filled_price,
                "filled_quantity": order_result.filled_quantity,
                "broker": self.broker.name,
            })
            return order_result

    async def _quantity_for(self, decision: TradeDecision) -> float:
        account = await self.broker.get_account_info()
        equity = float(account.get("equity") or account.get("balance") or 0.0)
        if equity <= 0:
            raise ValueError("Broker reported zero equity – cannot size order")
        notional = equity * float(decision.position_size_pct)
        return notional / float(decision.entry_price)

    async def _execute_with_retry(self, decision: TradeDecision, max_retries: int = 3) -> OrderResult:
        delays = [1, 2, 4]
        last_error: Optional[Exception] = None
        self._last_requested_qty = 0.0
        for attempt in range(max_retries):
            try:
                return await self._execute_order(decision)
            except Exception as e:
                last_error = e
                logger.warning(f"Order attempt {attempt + 1} failed: {e}")
                # Never double-fill: if a position appeared, stop retrying
                if await self._has_position(decision.symbol):
                    logger.error(f"Position for {decision.symbol} exists after failure – not retrying")
                    break
                if attempt < max_retries - 1:
                    await asyncio.sleep(delays[attempt])

        logger.error(f"Order for {decision.symbol} failed: {last_error}")
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
        await self.broker.ensure_connected()
        qty = await self._quantity_for(decision)
        self._last_requested_qty = qty
        side = "BUY" if decision.action in BUY_ACTIONS else "SELL"
        res = await self.broker.place_bracket_order(
            symbol=decision.symbol,
            side=side,
            quantity=qty,
            stop_loss=float(decision.stop_loss),
            take_profit=float(decision.take_profit),
            reference=f"tq-{str(decision.decision_id)[:8]}",
        )
        if res.status == "rejected":
            raise RuntimeError(f"Broker rejected order: {res.message}")
        logger.info(f"{self.broker.name} order {res.order_id} {side} {res.requested_quantity} "
                    f"{decision.symbol}: {res.status} {res.message}")
        return OrderResult(
            id=uuid4(),
            order_id=f"{self.broker.name}-{res.order_id}",
            symbol=decision.symbol,
            status=res.status,
            filled_price=res.avg_fill_price,
            filled_quantity=res.filled_quantity,
            timestamp=datetime.utcnow(),
        )

    async def _has_position(self, symbol: str) -> bool:
        try:
            positions = await self.broker.get_open_positions()
            return any(p.get("symbol") == symbol.upper() for p in positions)
        except Exception:
            return False

    @staticmethod
    def _broker_order_id(order_id: str) -> str:
        return order_id.split("-", 1)[1] if "-" in order_id else order_id

    async def modify_order(
        self,
        order_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> bool:
        """Modify SL/TP of a bracket order."""
        await self.broker.ensure_connected()
        ok = await self.broker.modify_protective_orders(
            self._broker_order_id(order_id), stop_loss=stop_loss, take_profit=take_profit
        )
        if ok:
            async with get_db_context() as db:
                rec = (await db.execute(
                    select(TradeRecord).where(TradeRecord.exness_order_id == order_id)
                )).scalar_one_or_none()
                if rec:
                    if stop_loss is not None:
                        rec.stop_loss = stop_loss
                    if take_profit is not None:
                        rec.take_profit = take_profit
        return ok

    async def close_position(self, order_id: str) -> dict:
        """Close the position opened by ``order_id``."""
        async with get_db_context() as db:
            rec = (await db.execute(
                select(TradeRecord).where(TradeRecord.exness_order_id == order_id)
            )).scalar_one_or_none()
        if rec is None:
            return {"success": False, "error": "Position not found"}
        try:
            res = await self.broker.close_position(rec.symbol)
        except Exception as e:
            return {"success": False, "error": str(e)}
        return {"success": True, "close_price": res.avg_fill_price, "status": res.status}

    async def get_account_info(self) -> dict:
        """Broker account summary."""
        await self.broker.ensure_connected()
        return await self.broker.get_account_info()

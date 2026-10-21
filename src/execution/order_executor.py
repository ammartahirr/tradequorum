"""
Order Executor for the AI Trading System.

Interfaces with the Exness trading account via MetaTrader 5 (MT5) API
to place, modify, and close orders.

Requirements:
- 6.1: Place orders via MT5 API with symbol, size, entry, stop-loss, take-profit
- 6.3: Handle partial fills and continue monitoring for full execution
- 6.4: Retry with exponential backoff (3 attempts: 1s, 2s, 4s)
- 6.5: Query open positions to verify state before retrying after connection failure
- 6.6: Broadcast order execution results via WebSocket
- 13.1, 13.2: Validate stop_loss vs entry_price based on trade direction
- 13.4: Validate risk_reward_ratio >= 1.5 for actionable trades
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Callable, Any

from src.models.enums import TradeAction
from src.models.trading import TradeDecision, OrderResult

from .config import ExecutionConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


class OrderExecutionError(Exception):
    """Exception raised when order execution fails."""
    pass


class OrderValidationError(Exception):
    """Exception raised when order validation fails."""
    pass


class PartialFillError(Exception):
    """Exception raised when order is partially filled during connection failure."""
    
    def __init__(self, message: str, partial_fill_info: dict = None):
        super().__init__(message)
        self.partial_fill_info = partial_fill_info or {}


class OrderExecutor:
    """
    Executes orders via MT5 API with retry logic and validation.
    
    Requirements:
    - 6.1: Place orders with symbol, size, entry, stop-loss, take-profit
    - 6.3: Handle partial fills
    - 6.4: Retry with exponential backoff (3 attempts: 1s, 2s, 4s)
    - 6.5: Query open positions to verify state before retrying
    - 6.6: Broadcast execution results via WebSocket
    """
    
    def __init__(
        self,
        config: ExecutionConfig = None,
        mt5_client: Any = None,
        websocket_broadcaster: Any = None,
        trade_persistence: Any = None,
    ):
        """
        Initialize the Order Executor.
        
        Args:
            config: Execution configuration. Uses defaults if not provided.
            mt5_client: MT5 client for API calls. If None, uses mock for testing.
            websocket_broadcaster: WebSocket broadcaster for notifications.
            trade_persistence: Trade persistence layer for recording trades.
        """
        self.config = config or DEFAULT_CONFIG
        self._mt5_client = mt5_client
        self._websocket_broadcaster = websocket_broadcaster
        self._trade_persistence = trade_persistence
    
    def _validate_trade_decision(self, decision: TradeDecision, size: float) -> None:
        """
        Validate trade decision before execution.
        
        Requirements:
        - 13.1, 13.2: Validate stop_loss vs entry_price based on direction
        - 13.4: Validate risk_reward_ratio >= 1.5
        
        Args:
            decision: The trade decision to validate.
            size: The position size.
            
        Raises:
            OrderValidationError: If validation fails.
        """
        buy_actions = {TradeAction.STRONG_BUY, TradeAction.BUY}
        sell_actions = {TradeAction.STRONG_SELL, TradeAction.SELL}
        
        # Validate stop-loss position (Requirements 13.1, 13.2)
        if decision.action in buy_actions:
            if decision.stop_loss >= decision.entry_price:
                raise OrderValidationError(
                    f"For BUY trades, stop_loss ({decision.stop_loss}) must be below "
                    f"entry_price ({decision.entry_price})"
                )
            if decision.take_profit <= decision.entry_price:
                raise OrderValidationError(
                    f"For BUY trades, take_profit ({decision.take_profit}) must be above "
                    f"entry_price ({decision.entry_price})"
                )
        elif decision.action in sell_actions:
            if decision.stop_loss <= decision.entry_price:
                raise OrderValidationError(
                    f"For SELL trades, stop_loss ({decision.stop_loss}) must be above "
                    f"entry_price ({decision.entry_price})"
                )
            if decision.take_profit >= decision.entry_price:
                raise OrderValidationError(
                    f"For SELL trades, take_profit ({decision.take_profit}) must be below "
                    f"entry_price ({decision.entry_price})"
                )
        
        # Validate risk-reward ratio (Requirement 13.4)
        min_rr = self.config.order_execution.min_risk_reward_ratio
        if decision.risk_reward_ratio < min_rr:
            raise OrderValidationError(
                f"Risk-reward ratio ({decision.risk_reward_ratio}) must be >= {min_rr}"
            )
        
        # Validate size
        if size <= 0:
            raise OrderValidationError(f"Position size must be positive, got {size}")
    
    async def _check_existing_position(self, symbol: str) -> Optional[dict]:
        """
        Check if there's an existing position for the symbol.
        
        Used to verify state before retrying after connection failure
        (Requirement 6.5).
        
        Args:
            symbol: The trading symbol.
            
        Returns:
            Position info if exists, None otherwise.
        """
        if self._mt5_client is None:
            return None
        
        try:
            positions = await self._mt5_client.get_open_positions()
            for pos in positions:
                if pos.get("symbol") == symbol:
                    return pos
            return None
        except Exception as e:
            logger.warning(f"Failed to check existing position for {symbol}: {e}")
            return None
    
    async def _execute_order_mt5(
        self,
        decision: TradeDecision,
        size: float,
    ) -> OrderResult:
        """
        Execute order via MT5 API.
        
        Args:
            decision: The trade decision.
            size: The position size.
            
        Returns:
            OrderResult with execution details.
            
        Raises:
            OrderExecutionError: If execution fails.
        """
        if self._mt5_client is None:
            # Mock execution for testing
            return OrderResult(
                order_id=str(uuid.uuid4()),
                symbol=decision.symbol,
                status="filled",
                filled_price=decision.entry_price,
                filled_quantity=size,
                timestamp=datetime.now(timezone.utc),
            )
        
        mt5 = self._mt5_client._get_mt5_module()
        
        # Determine order type
        buy_actions = {TradeAction.STRONG_BUY, TradeAction.BUY}
        order_type = mt5.ORDER_TYPE_BUY if decision.action in buy_actions else mt5.ORDER_TYPE_SELL
        
        # Get current price
        price_info = await self._mt5_client.get_current_price(decision.symbol)
        if price_info is None:
            raise OrderExecutionError(f"Failed to get price for {decision.symbol}")
        
        # Use ask for buy, bid for sell
        price = price_info["ask"] if decision.action in buy_actions else price_info["bid"]
        
        # Prepare order request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": decision.symbol,
            "volume": size,
            "type": order_type,
            "price": price,
            "sl": decision.stop_loss,
            "tp": decision.take_profit,
            "deviation": 20,  # Maximum price deviation in points
            "magic": 234000,  # Magic number for identification
            "comment": f"AI Trading: {decision.action.value}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        # Send order
        result = mt5.order_send(request)
        
        if result is None:
            error = mt5.last_error()
            raise OrderExecutionError(f"Order send failed: {error}")
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            raise OrderExecutionError(
                f"Order failed with code {result.retcode}: {result.comment}"
            )
        
        # Determine status
        status = "filled"
        if result.volume < size:
            status = "partial"
        
        return OrderResult(
            order_id=str(result.order),
            symbol=decision.symbol,
            status=status,
            filled_price=result.price,
            filled_quantity=result.volume,
            timestamp=datetime.now(timezone.utc),
        )
    
    async def place_order(
        self,
        decision: TradeDecision,
        size: float,
    ) -> OrderResult:
        """
        Place an order with retry logic.
        
        Requirements:
        - 6.1: Place order via MT5 API
        - 6.3: Handle partial fills
        - 6.4: Retry with exponential backoff (3 attempts: 1s, 2s, 4s)
        - 6.5: Query open positions to verify state before retrying
        
        Args:
            decision: The trade decision to execute.
            size: The position size.
            
        Returns:
            OrderResult with execution details.
            
        Raises:
            OrderValidationError: If validation fails.
            OrderExecutionError: If execution fails after all retries.
            PartialFillError: If order may have been partially filled.
        """
        # Validate before execution
        self._validate_trade_decision(decision, size)
        
        last_error = None
        retry_delays = self.config.order_execution.retry_delays_seconds
        
        for attempt, delay in enumerate(retry_delays):
            try:
                # Execute order
                result = await self._execute_order_mt5(decision, size)
                
                # Broadcast success (Requirement 6.6)
                await self._broadcast_execution_result(result, decision)
                
                # Persist trade record
                await self._persist_trade_record(result, decision, size)
                
                # Handle partial fill (Requirement 6.3)
                if result.status == "partial":
                    logger.info(
                        f"Partial fill for {decision.symbol}: "
                        f"{result.filled_quantity}/{size}"
                    )
                    # Continue monitoring for full execution
                    # (In production, this would spawn a monitoring task)
                
                return result
                
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Order attempt {attempt + 1} failed for {decision.symbol}: {e}"
                )
                
                # Check for partial fill before retrying (Requirement 6.5)
                existing_position = await self._check_existing_position(decision.symbol)
                if existing_position is not None:
                    # Position exists - may have been partially filled
                    raise PartialFillError(
                        f"Order may have been partially filled for {decision.symbol}. "
                        f"Existing position found: {existing_position}",
                        partial_fill_info=existing_position,
                    )
                
                # Wait before retry
                if attempt < len(retry_delays) - 1:
                    await asyncio.sleep(delay)
        
        # All retries exhausted
        raise OrderExecutionError(
            f"Failed to place order for {decision.symbol} after "
            f"{len(retry_delays)} attempts: {last_error}"
        )
    
    async def modify_order(
        self,
        order_id: str,
        stop_loss: float = None,
        take_profit: float = None,
    ) -> bool:
        """
        Modify an existing order's stop-loss or take-profit.
        
        Args:
            order_id: The order ID to modify.
            stop_loss: New stop-loss price (optional).
            take_profit: New take-profit price (optional).
            
        Returns:
            True if modification successful.
        """
        if self._mt5_client is None:
            return True  # Mock success for testing
        
        mt5 = self._mt5_client._get_mt5_module()
        
        # Get position by ticket
        position = mt5.positions_get(ticket=int(order_id))
        if position is None or len(position) == 0:
            logger.error(f"Position not found: {order_id}")
            return False
        
        pos = position[0]
        
        # Prepare modification request
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": int(order_id),
            "sl": stop_loss if stop_loss is not None else pos.sl,
            "tp": take_profit if take_profit is not None else pos.tp,
        }
        
        result = mt5.order_send(request)
        
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Failed to modify order {order_id}: {result}")
            return False
        
        return True
    
    async def close_position(self, order_id: str) -> OrderResult:
        """
        Close an open position.
        
        Args:
            order_id: The order/position ID to close.
            
        Returns:
            OrderResult with close details.
        """
        if self._mt5_client is None:
            # Mock close for testing
            return OrderResult(
                order_id=order_id,
                symbol="UNKNOWN",
                status="filled",
                filled_price=0.0,
                filled_quantity=0.0,
                timestamp=datetime.now(timezone.utc),
            )
        
        mt5 = self._mt5_client._get_mt5_module()
        
        # Get position
        position = mt5.positions_get(ticket=int(order_id))
        if position is None or len(position) == 0:
            raise OrderExecutionError(f"Position not found: {order_id}")
        
        pos = position[0]
        
        # Determine close order type (opposite of position)
        close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
        
        # Get current price
        price_info = await self._mt5_client.get_current_price(pos.symbol)
        price = price_info["bid"] if pos.type == 0 else price_info["ask"]
        
        # Prepare close request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": int(order_id),
            "price": price,
            "deviation": 20,
            "magic": 234000,
            "comment": "AI Trading: Close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        result = mt5.order_send(request)
        
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise OrderExecutionError(f"Failed to close position {order_id}: {result}")
        
        return OrderResult(
            order_id=str(result.order),
            symbol=pos.symbol,
            status="filled",
            filled_price=result.price,
            filled_quantity=result.volume,
            timestamp=datetime.now(timezone.utc),
        )
    
    async def get_open_positions(self) -> list[dict]:
        """
        Get all open positions.
        
        Returns:
            List of open position dictionaries.
        """
        if self._mt5_client is None:
            return []
        
        return await self._mt5_client.get_open_positions()
    
    async def get_account_info(self) -> dict:
        """
        Get account information.
        
        Returns:
            Dictionary with account info.
        """
        if self._mt5_client is None:
            return {
                "balance": 100000.0,
                "equity": 100000.0,
                "margin": 0.0,
                "free_margin": 100000.0,
            }
        
        mt5 = self._mt5_client._get_mt5_module()
        info = mt5.account_info()
        
        if info is None:
            return {}
        
        return {
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "profit": info.profit,
            "leverage": info.leverage,
        }
    
    async def _broadcast_execution_result(
        self,
        result: OrderResult,
        decision: TradeDecision,
    ) -> None:
        """
        Broadcast execution result via WebSocket (Requirement 6.6).
        
        Args:
            result: The order result.
            decision: The original trade decision.
        """
        if self._websocket_broadcaster is None:
            return
        
        await self._websocket_broadcaster.broadcast_trade_execution(
            result=result,
            decision=decision,
        )
    
    async def _persist_trade_record(
        self,
        result: OrderResult,
        decision: TradeDecision,
        size: float,
    ) -> None:
        """
        Persist trade record to DynamoDB (Requirement 6.2).
        
        Args:
            result: The order result.
            decision: The original trade decision.
            size: The requested position size.
        """
        if self._trade_persistence is None:
            return
        
        await self._trade_persistence.save_trade_record(
            result=result,
            decision=decision,
            size=size,
        )

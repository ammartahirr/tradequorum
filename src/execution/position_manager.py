"""
Position Manager for the AI Trading System.

Tracks open positions and broadcasts updates via WebSocket.

Requirements:
- 7.1: Track open positions with trade ID, symbol, entry, SL, TP, size, timestamp
- 7.2: Record exit price, PnL, PnL percentage, close timestamp on position close
- 7.3: Broadcast position status changes within 1 second via WebSocket
- 7.4: Maintain accurate count of open positions
- 13.5: Record final status as closed_profit, closed_loss, closed_sl, or closed_tp
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable

from src.models.enums import TradeAction

from .config import ExecutionConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """
    Represents an open trading position.
    
    Requirement 7.1: Track with trade ID, symbol, entry, SL, TP, size, timestamp.
    """
    trade_id: str
    symbol: str
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float
    opened_at: datetime
    action: TradeAction
    exness_order_id: str
    
    # Fields populated on close (Requirement 7.2)
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    closed_at: Optional[datetime] = None
    status: str = "open"


@dataclass
class PositionUpdate:
    """Represents a position status update for broadcasting."""
    trade_id: str
    symbol: str
    update_type: str  # "opened", "closed", "modified"
    position: Position
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PositionManager:
    """
    Manages open positions and broadcasts updates.
    
    Requirements:
    - 7.1: Track open positions with all required fields
    - 7.2: Record exit details on position close
    - 7.3: Broadcast updates within 1 second
    - 7.4: Maintain accurate count of open positions
    - 13.5: Record final status correctly
    """
    
    def __init__(
        self,
        config: ExecutionConfig = None,
        websocket_broadcaster: Any = None,
        trade_persistence: Any = None,
        risk_manager: Any = None,
    ):
        """
        Initialize the Position Manager.
        
        Args:
            config: Execution configuration. Uses defaults if not provided.
            websocket_broadcaster: WebSocket broadcaster for notifications.
            trade_persistence: Trade persistence layer for recording updates.
            risk_manager: Risk manager for recording trade results.
        """
        self.config = config or DEFAULT_CONFIG
        self._websocket_broadcaster = websocket_broadcaster
        self._trade_persistence = trade_persistence
        self._risk_manager = risk_manager
        
        # In-memory position tracking (Requirement 7.4)
        self._positions: Dict[str, Position] = {}
    
    @property
    def open_position_count(self) -> int:
        """
        Get the count of open positions (Requirement 7.4).
        
        Returns:
            Number of open positions.
        """
        return len(self._positions)
    
    def get_open_positions(self) -> List[Position]:
        """
        Get all open positions.
        
        Returns:
            List of open Position objects.
        """
        return list(self._positions.values())
    
    def get_position(self, trade_id: str) -> Optional[Position]:
        """
        Get a specific position by trade ID.
        
        Args:
            trade_id: The trade ID.
            
        Returns:
            Position if found, None otherwise.
        """
        return self._positions.get(trade_id)
    
    def get_position_by_symbol(self, symbol: str) -> Optional[Position]:
        """
        Get a position by symbol.
        
        Args:
            symbol: The trading symbol.
            
        Returns:
            Position if found, None otherwise.
        """
        for position in self._positions.values():
            if position.symbol == symbol:
                return position
        return None
    
    async def open_position(
        self,
        trade_id: str,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        position_size: float,
        action: TradeAction,
        exness_order_id: str,
        opened_at: datetime = None,
    ) -> Position:
        """
        Open a new position (Requirement 7.1).
        
        Args:
            trade_id: Unique trade identifier.
            symbol: Trading symbol.
            entry_price: Entry price.
            stop_loss: Stop-loss price.
            take_profit: Take-profit price.
            position_size: Position size.
            action: Trade action (BUY/SELL).
            exness_order_id: Exness order ID.
            opened_at: Open timestamp (defaults to now).
            
        Returns:
            The created Position.
        """
        if opened_at is None:
            opened_at = datetime.now(timezone.utc)
        
        position = Position(
            trade_id=trade_id,
            symbol=symbol,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            opened_at=opened_at,
            action=action,
            exness_order_id=exness_order_id,
        )
        
        self._positions[trade_id] = position
        
        logger.info(
            f"Opened position: {trade_id} for {symbol} at {entry_price} "
            f"(SL: {stop_loss}, TP: {take_profit})"
        )
        
        # Broadcast update (Requirement 7.3)
        await self._broadcast_position_update(
            position=position,
            update_type="opened",
        )
        
        return position
    
    async def close_position(
        self,
        trade_id: str,
        exit_price: float,
        close_reason: str = "manual",
        closed_at: datetime = None,
    ) -> Position:
        """
        Close a position and record exit details (Requirements 7.2, 13.5).
        
        Args:
            trade_id: The trade ID to close.
            exit_price: The exit price.
            close_reason: Reason for close ("manual", "sl", "tp").
            closed_at: Close timestamp (defaults to now).
            
        Returns:
            The closed Position.
            
        Raises:
            ValueError: If position not found.
        """
        if trade_id not in self._positions:
            raise ValueError(f"Position not found: {trade_id}")
        
        if closed_at is None:
            closed_at = datetime.now(timezone.utc)
        
        position = self._positions[trade_id]
        
        # Calculate PnL (Requirement 7.2)
        pnl, pnl_pct = self._calculate_pnl(position, exit_price)
        
        # Determine final status (Requirement 13.5)
        status = self._determine_close_status(
            pnl=pnl,
            close_reason=close_reason,
        )
        
        # Update position
        position.exit_price = exit_price
        position.pnl = pnl
        position.pnl_pct = pnl_pct
        position.closed_at = closed_at
        position.status = status
        
        # Remove from open positions
        del self._positions[trade_id]
        
        logger.info(
            f"Closed position: {trade_id} for {position.symbol} at {exit_price} "
            f"(PnL: {pnl:.2f}, Status: {status})"
        )
        
        # Update trade record in persistence
        if self._trade_persistence is not None:
            await self._trade_persistence.update_trade_record(
                trade_id=trade_id,
                exit_price=exit_price,
                status=status,
                pnl=pnl,
                pnl_pct=pnl_pct,
                closed_at=closed_at,
            )
        
        # Record trade result in risk manager
        if self._risk_manager is not None:
            self._risk_manager.record_trade_result(pnl)
        
        # Broadcast update (Requirement 7.3)
        await self._broadcast_position_update(
            position=position,
            update_type="closed",
        )
        
        return position
    
    async def modify_position(
        self,
        trade_id: str,
        stop_loss: float = None,
        take_profit: float = None,
    ) -> Position:
        """
        Modify a position's stop-loss or take-profit.
        
        Args:
            trade_id: The trade ID to modify.
            stop_loss: New stop-loss price (optional).
            take_profit: New take-profit price (optional).
            
        Returns:
            The modified Position.
            
        Raises:
            ValueError: If position not found.
        """
        if trade_id not in self._positions:
            raise ValueError(f"Position not found: {trade_id}")
        
        position = self._positions[trade_id]
        
        if stop_loss is not None:
            position.stop_loss = stop_loss
        if take_profit is not None:
            position.take_profit = take_profit
        
        logger.info(
            f"Modified position: {trade_id} - SL: {position.stop_loss}, "
            f"TP: {position.take_profit}"
        )
        
        # Broadcast update (Requirement 7.3)
        await self._broadcast_position_update(
            position=position,
            update_type="modified",
        )
        
        return position
    
    def _calculate_pnl(
        self,
        position: Position,
        exit_price: float,
    ) -> tuple[float, float]:
        """
        Calculate PnL and PnL percentage (Requirement 7.2).
        
        Args:
            position: The position.
            exit_price: The exit price.
            
        Returns:
            Tuple of (pnl, pnl_pct).
        """
        buy_actions = {TradeAction.STRONG_BUY, TradeAction.BUY}
        
        if position.action in buy_actions:
            # For BUY: profit when exit > entry
            price_diff = exit_price - position.entry_price
        else:
            # For SELL: profit when exit < entry
            price_diff = position.entry_price - exit_price
        
        pnl = price_diff * position.position_size
        pnl_pct = (price_diff / position.entry_price) * 100
        
        return pnl, pnl_pct
    
    def _determine_close_status(
        self,
        pnl: float,
        close_reason: str,
    ) -> str:
        """
        Determine the final close status (Requirement 13.5).
        
        Args:
            pnl: The profit/loss amount.
            close_reason: The reason for closing.
            
        Returns:
            Status string: closed_profit, closed_loss, closed_sl, or closed_tp.
        """
        if close_reason == "sl":
            return "closed_sl"
        elif close_reason == "tp":
            return "closed_tp"
        elif pnl >= 0:
            return "closed_profit"
        else:
            return "closed_loss"
    
    async def _broadcast_position_update(
        self,
        position: Position,
        update_type: str,
    ) -> None:
        """
        Broadcast position update via WebSocket (Requirement 7.3).
        
        Must complete within 1 second.
        
        Args:
            position: The position.
            update_type: Type of update ("opened", "closed", "modified").
        """
        if self._websocket_broadcaster is None:
            return
        
        max_delay = self.config.position_manager.max_broadcast_delay_seconds
        
        try:
            # Use asyncio.wait_for to enforce timeout
            await asyncio.wait_for(
                self._websocket_broadcaster.broadcast_position_update(
                    position=position,
                    update_type=update_type,
                ),
                timeout=max_delay,
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"Position update broadcast timed out for {position.trade_id}"
            )
        except Exception as e:
            logger.error(
                f"Failed to broadcast position update for {position.trade_id}: {e}"
            )
    
    async def sync_with_mt5(self, mt5_positions: List[dict]) -> None:
        """
        Synchronize internal state with MT5 positions.
        
        Used after reconnection to ensure accurate tracking.
        
        Args:
            mt5_positions: List of positions from MT5.
        """
        mt5_tickets = {str(p.get("ticket")) for p in mt5_positions}
        
        # Find positions that were closed while disconnected
        closed_positions = []
        for trade_id, position in list(self._positions.items()):
            if position.exness_order_id not in mt5_tickets:
                closed_positions.append(trade_id)
        
        # Mark them as closed (status unknown)
        for trade_id in closed_positions:
            position = self._positions[trade_id]
            logger.warning(
                f"Position {trade_id} ({position.symbol}) appears to have been "
                f"closed while disconnected"
            )
            # We don't have exit price, so we can't properly close it
            # This would need manual reconciliation
    
    def get_positions_summary(self) -> dict:
        """
        Get a summary of all open positions.
        
        Returns:
            Dictionary with position summary.
        """
        total_exposure = sum(p.position_size for p in self._positions.values())
        
        by_symbol = {}
        for position in self._positions.values():
            if position.symbol not in by_symbol:
                by_symbol[position.symbol] = []
            by_symbol[position.symbol].append({
                "trade_id": position.trade_id,
                "entry_price": position.entry_price,
                "position_size": position.position_size,
                "action": position.action.value,
            })
        
        return {
            "open_count": self.open_position_count,
            "total_exposure": total_exposure,
            "by_symbol": by_symbol,
        }

"""
Trade Record Persistence for the AI Trading System.

Handles persistence of trade records to DynamoDB with validation.

Requirements:
- 6.2: Record trades in DynamoDB with order ID, filled price, quantity, status, timestamp
- 13.1: Validate stop_loss < entry_price for BUY trades
- 13.2: Validate stop_loss > entry_price for SELL trades
- 13.3: Validate position_size does not exceed max_position_pct
- 13.4: Validate risk_reward_ratio >= 1.5 for actionable trades
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

from src.models.enums import TradeAction, Conviction, TradingHorizon
from src.models.trading import TradeDecision, OrderResult, TradeRecord

from .config import ExecutionConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


class TradeValidationError(Exception):
    """Exception raised when trade record validation fails."""
    pass


class TradePersistence:
    """
    Handles trade record persistence to DynamoDB.
    
    Requirements:
    - 6.2: Record trades with order ID, filled price, quantity, status, timestamp
    - 13.1, 13.2: Validate stop_loss vs entry_price based on direction
    - 13.3: Validate position_size does not exceed max_position_pct
    - 13.4: Validate risk_reward_ratio >= 1.5
    """
    
    def __init__(
        self,
        config: ExecutionConfig = None,
        dynamodb_client: Any = None,
        max_position_pct: float = 0.05,
    ):
        """
        Initialize the Trade Persistence layer.
        
        Args:
            config: Execution configuration. Uses defaults if not provided.
            dynamodb_client: DynamoDB client. If None, uses mock for testing.
            max_position_pct: Maximum position size as percentage of portfolio.
        """
        self.config = config or DEFAULT_CONFIG
        self._dynamodb = dynamodb_client
        self._max_position_pct = max_position_pct
    
    def _validate_trade_record(
        self,
        action: TradeAction,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        position_size_pct: float,
        risk_reward_ratio: float,
    ) -> None:
        """
        Validate trade record fields.
        
        Requirements:
        - 13.1: For BUY, stop_loss < entry_price
        - 13.2: For SELL, stop_loss > entry_price
        - 13.3: position_size <= max_position_pct
        - 13.4: risk_reward_ratio >= 1.5
        
        Args:
            action: The trade action.
            entry_price: Entry price.
            stop_loss: Stop-loss price.
            take_profit: Take-profit price.
            position_size_pct: Position size as percentage.
            risk_reward_ratio: Risk-reward ratio.
            
        Raises:
            TradeValidationError: If validation fails.
        """
        buy_actions = {TradeAction.STRONG_BUY, TradeAction.BUY}
        sell_actions = {TradeAction.STRONG_SELL, TradeAction.SELL}
        actionable = buy_actions | sell_actions
        
        # Validate stop-loss position (Requirements 13.1, 13.2)
        if action in buy_actions:
            if stop_loss >= entry_price:
                raise TradeValidationError(
                    f"For BUY trades, stop_loss ({stop_loss}) must be below "
                    f"entry_price ({entry_price})"
                )
            if take_profit <= entry_price:
                raise TradeValidationError(
                    f"For BUY trades, take_profit ({take_profit}) must be above "
                    f"entry_price ({entry_price})"
                )
        elif action in sell_actions:
            if stop_loss <= entry_price:
                raise TradeValidationError(
                    f"For SELL trades, stop_loss ({stop_loss}) must be above "
                    f"entry_price ({entry_price})"
                )
            if take_profit >= entry_price:
                raise TradeValidationError(
                    f"For SELL trades, take_profit ({take_profit}) must be below "
                    f"entry_price ({entry_price})"
                )
        
        # Validate position size (Requirement 13.3)
        if position_size_pct > self._max_position_pct:
            raise TradeValidationError(
                f"Position size ({position_size_pct:.2%}) exceeds maximum "
                f"({self._max_position_pct:.2%})"
            )
        
        # Validate risk-reward ratio (Requirement 13.4)
        if action in actionable and risk_reward_ratio < 1.5:
            raise TradeValidationError(
                f"Risk-reward ratio ({risk_reward_ratio}) must be >= 1.5 "
                f"for actionable trades"
            )
    
    def create_trade_record(
        self,
        result: OrderResult,
        decision: TradeDecision,
        size: float,
    ) -> TradeRecord:
        """
        Create a validated trade record.
        
        Args:
            result: The order execution result.
            decision: The original trade decision.
            size: The position size.
            
        Returns:
            Validated TradeRecord.
            
        Raises:
            TradeValidationError: If validation fails.
        """
        # Validate before creating record
        self._validate_trade_record(
            action=decision.action,
            entry_price=result.filled_price,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            position_size_pct=decision.position_size_pct,
            risk_reward_ratio=decision.risk_reward_ratio,
        )
        
        # Determine initial status
        status = "open"
        if result.status == "partial":
            status = "partial"
        elif result.status == "rejected":
            status = "rejected"
        
        return TradeRecord(
            trade_id=str(uuid.uuid4()),
            symbol=decision.symbol,
            action=decision.action,
            horizon=decision.horizon,
            entry_price=result.filled_price,
            exit_price=None,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            position_size=result.filled_quantity,
            status=status,
            pnl=None,
            pnl_pct=None,
            conviction=decision.conviction,
            news_signal_id=str(id(decision.news_signal)),  # Use signal ID if available
            technical_signal_id=str(id(decision.technical_signal)),
            decision_reasoning=decision.reasoning,
            opened_at=result.timestamp,
            closed_at=None,
            exness_order_id=result.order_id,
        )
    
    async def save_trade_record(
        self,
        result: OrderResult,
        decision: TradeDecision,
        size: float,
    ) -> TradeRecord:
        """
        Save a trade record to DynamoDB (Requirement 6.2).
        
        Args:
            result: The order execution result.
            decision: The original trade decision.
            size: The position size.
            
        Returns:
            The saved TradeRecord.
        """
        record = self.create_trade_record(result, decision, size)
        
        if self._dynamodb is not None:
            await self._save_to_dynamodb(record)
        
        logger.info(
            f"Saved trade record: {record.trade_id} for {record.symbol} "
            f"({record.action.value})"
        )
        
        return record
    
    async def update_trade_record(
        self,
        trade_id: str,
        exit_price: float,
        status: str,
        pnl: float,
        pnl_pct: float,
        closed_at: datetime,
    ) -> None:
        """
        Update a trade record when position is closed.
        
        Args:
            trade_id: The trade ID to update.
            exit_price: The exit price.
            status: The final status (closed_profit, closed_loss, closed_sl, closed_tp).
            pnl: The profit/loss amount.
            pnl_pct: The profit/loss percentage.
            closed_at: The close timestamp.
        """
        # Validate status
        valid_statuses = self.config.position_manager.valid_closed_statuses
        if status not in valid_statuses:
            raise TradeValidationError(
                f"Invalid closed status: {status}. "
                f"Must be one of: {valid_statuses}"
            )
        
        if self._dynamodb is not None:
            await self._update_in_dynamodb(
                trade_id=trade_id,
                exit_price=exit_price,
                status=status,
                pnl=pnl,
                pnl_pct=pnl_pct,
                closed_at=closed_at,
            )
        
        logger.info(
            f"Updated trade record: {trade_id} - {status}, PnL: {pnl:.2f}"
        )
    
    async def get_trade_record(self, trade_id: str) -> Optional[dict]:
        """
        Get a trade record by ID.
        
        Args:
            trade_id: The trade ID.
            
        Returns:
            Trade record dictionary or None if not found.
        """
        if self._dynamodb is None:
            return None
        
        return await self._get_from_dynamodb(trade_id)
    
    async def get_open_trades(self) -> list[dict]:
        """
        Get all open trade records.
        
        Returns:
            List of open trade record dictionaries.
        """
        if self._dynamodb is None:
            return []
        
        return await self._query_open_trades()
    
    async def _save_to_dynamodb(self, record: TradeRecord) -> None:
        """Save trade record to DynamoDB."""
        table_name = self.config.persistence.trades_table
        
        item = {
            "trade_id": record.trade_id,
            "symbol": record.symbol,
            "action": record.action.value,
            "horizon": record.horizon.value,
            "entry_price": str(record.entry_price),
            "stop_loss": str(record.stop_loss),
            "take_profit": str(record.take_profit),
            "position_size": str(record.position_size),
            "status": record.status,
            "conviction": record.conviction.value,
            "news_signal_id": record.news_signal_id,
            "technical_signal_id": record.technical_signal_id,
            "decision_reasoning": record.decision_reasoning,
            "opened_at": record.opened_at.isoformat(),
            "exness_order_id": record.exness_order_id,
        }
        
        if record.exit_price is not None:
            item["exit_price"] = str(record.exit_price)
        if record.pnl is not None:
            item["pnl"] = str(record.pnl)
        if record.pnl_pct is not None:
            item["pnl_pct"] = str(record.pnl_pct)
        if record.closed_at is not None:
            item["closed_at"] = record.closed_at.isoformat()
        
        self._dynamodb.put_item(TableName=table_name, Item=item)
    
    async def _update_in_dynamodb(
        self,
        trade_id: str,
        exit_price: float,
        status: str,
        pnl: float,
        pnl_pct: float,
        closed_at: datetime,
    ) -> None:
        """Update trade record in DynamoDB."""
        table_name = self.config.persistence.trades_table
        
        self._dynamodb.update_item(
            TableName=table_name,
            Key={"trade_id": trade_id},
            UpdateExpression=(
                "SET exit_price = :ep, #st = :st, pnl = :pnl, "
                "pnl_pct = :pnl_pct, closed_at = :ca"
            ),
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":ep": str(exit_price),
                ":st": status,
                ":pnl": str(pnl),
                ":pnl_pct": str(pnl_pct),
                ":ca": closed_at.isoformat(),
            },
        )
    
    async def _get_from_dynamodb(self, trade_id: str) -> Optional[dict]:
        """Get trade record from DynamoDB."""
        table_name = self.config.persistence.trades_table
        
        response = self._dynamodb.get_item(
            TableName=table_name,
            Key={"trade_id": trade_id},
        )
        
        return response.get("Item")
    
    async def _query_open_trades(self) -> list[dict]:
        """Query open trades from DynamoDB."""
        table_name = self.config.persistence.trades_table
        
        response = self._dynamodb.scan(
            TableName=table_name,
            FilterExpression="#st = :status",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":status": "open"},
        )
        
        return response.get("Items", [])

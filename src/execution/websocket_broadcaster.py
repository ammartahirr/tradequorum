"""
WebSocket Broadcaster for the AI Trading System.

Broadcasts position updates and trade execution results via WebSocket.

Requirements:
- 6.6: Broadcast trade execution results
- 7.3: Broadcast position status changes within 1 second
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.models.trading import TradeDecision, OrderResult

from .config import ExecutionConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


class WebSocketBroadcastError(Exception):
    """Exception raised when WebSocket broadcast fails."""
    pass


class WebSocketBroadcaster:
    """
    Broadcasts updates via WebSocket API Gateway.
    
    Requirements:
    - 6.6: Broadcast trade execution results
    - 7.3: Broadcast position status changes within 1 second
    """
    
    def __init__(
        self,
        config: ExecutionConfig = None,
        api_gateway_client: Any = None,
    ):
        """
        Initialize the WebSocket Broadcaster.
        
        Args:
            config: Execution configuration. Uses defaults if not provided.
            api_gateway_client: API Gateway Management client for WebSocket.
        """
        self.config = config or DEFAULT_CONFIG
        self._api_gateway = api_gateway_client
        self._connection_ids: List[str] = []
    
    def add_connection(self, connection_id: str) -> None:
        """
        Add a WebSocket connection to broadcast to.
        
        Args:
            connection_id: The WebSocket connection ID.
        """
        if connection_id not in self._connection_ids:
            self._connection_ids.append(connection_id)
            logger.info(f"Added WebSocket connection: {connection_id}")
    
    def remove_connection(self, connection_id: str) -> None:
        """
        Remove a WebSocket connection.
        
        Args:
            connection_id: The WebSocket connection ID.
        """
        if connection_id in self._connection_ids:
            self._connection_ids.remove(connection_id)
            logger.info(f"Removed WebSocket connection: {connection_id}")
    
    async def broadcast_trade_execution(
        self,
        result: OrderResult,
        decision: TradeDecision,
    ) -> None:
        """
        Broadcast trade execution result (Requirement 6.6).
        
        Args:
            result: The order execution result.
            decision: The original trade decision.
        """
        if not self.config.websocket.broadcasts_enabled:
            return
        
        message = {
            "type": "trade_execution",
            "data": {
                "order_id": result.order_id,
                "symbol": result.symbol,
                "status": result.status,
                "filled_price": result.filled_price,
                "filled_quantity": result.filled_quantity,
                "action": decision.action.value,
                "conviction": decision.conviction.value,
                "stop_loss": decision.stop_loss,
                "take_profit": decision.take_profit,
                "risk_reward_ratio": decision.risk_reward_ratio,
                "reasoning": decision.reasoning,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        await self._broadcast(message)
    
    async def broadcast_position_update(
        self,
        position: Any,  # Position from position_manager
        update_type: str,
    ) -> None:
        """
        Broadcast position status change (Requirement 7.3).
        
        Must complete within 1 second.
        
        Args:
            position: The position object.
            update_type: Type of update ("opened", "closed", "modified").
        """
        if not self.config.websocket.broadcasts_enabled:
            return
        
        data = {
            "trade_id": position.trade_id,
            "symbol": position.symbol,
            "entry_price": position.entry_price,
            "stop_loss": position.stop_loss,
            "take_profit": position.take_profit,
            "position_size": position.position_size,
            "action": position.action.value,
            "status": position.status,
        }
        
        # Add close details if position is closed
        if update_type == "closed":
            data.update({
                "exit_price": position.exit_price,
                "pnl": position.pnl,
                "pnl_pct": position.pnl_pct,
                "closed_at": position.closed_at.isoformat() if position.closed_at else None,
            })
        
        message = {
            "type": "position_update",
            "update_type": update_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        await self._broadcast(message)
    
    async def broadcast_alert(
        self,
        alert_type: str,
        alert_data: Dict,
    ) -> None:
        """
        Broadcast an alert message.
        
        Args:
            alert_type: Type of alert (e.g., "DAILY_LOSS_LIMIT_BREACHED").
            alert_data: Alert details.
        """
        if not self.config.websocket.broadcasts_enabled:
            return
        
        message = {
            "type": "alert",
            "alert_type": alert_type,
            "data": alert_data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        await self._broadcast(message)
    
    async def _broadcast(self, message: Dict) -> None:
        """
        Broadcast a message to all connected clients.
        
        Args:
            message: The message to broadcast.
        """
        if not self._connection_ids:
            logger.debug("No WebSocket connections to broadcast to")
            return
        
        message_json = json.dumps(message)
        
        # Broadcast to all connections concurrently
        tasks = [
            self._send_to_connection(conn_id, message_json)
            for conn_id in self._connection_ids
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Remove stale connections
        stale_connections = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                stale_connections.append(self._connection_ids[i])
        
        for conn_id in stale_connections:
            self.remove_connection(conn_id)
    
    async def _send_to_connection(
        self,
        connection_id: str,
        message: str,
    ) -> None:
        """
        Send a message to a specific connection.
        
        Args:
            connection_id: The WebSocket connection ID.
            message: The JSON message string.
        """
        if self._api_gateway is None:
            # Mock send for testing
            logger.debug(f"Mock broadcast to {connection_id}: {message[:100]}...")
            return
        
        try:
            self._api_gateway.post_to_connection(
                ConnectionId=connection_id,
                Data=message.encode("utf-8"),
            )
        except Exception as e:
            # Connection may be stale
            logger.warning(f"Failed to send to connection {connection_id}: {e}")
            raise WebSocketBroadcastError(f"Failed to send to {connection_id}: {e}")


class MockWebSocketBroadcaster(WebSocketBroadcaster):
    """
    Mock WebSocket broadcaster for testing.
    
    Records all broadcasts for verification.
    """
    
    def __init__(self, config: ExecutionConfig = None):
        """Initialize mock broadcaster."""
        super().__init__(config)
        self.broadcasts: List[Dict] = []
        self.broadcast_times: List[datetime] = []
    
    async def _broadcast(self, message: Dict) -> None:
        """Record broadcast instead of sending."""
        self.broadcasts.append(message)
        self.broadcast_times.append(datetime.now(timezone.utc))
        logger.debug(f"Mock broadcast: {message.get('type')}")
    
    def get_broadcasts_of_type(self, message_type: str) -> List[Dict]:
        """Get all broadcasts of a specific type."""
        return [b for b in self.broadcasts if b.get("type") == message_type]
    
    def clear_broadcasts(self) -> None:
        """Clear recorded broadcasts."""
        self.broadcasts.clear()
        self.broadcast_times.clear()

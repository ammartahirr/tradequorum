# Execution layer modules
"""
Contains order execution and position management:
- config: Configuration for execution layer
- order_executor: Interfaces with Exness MT5 API for order placement
- trade_persistence: DynamoDB trade record persistence
- position_manager: Tracks open positions and broadcasts updates
- websocket_broadcaster: WebSocket broadcast functionality
"""

from .config import (
    ExecutionConfig,
    OrderExecutionConfig,
    PositionManagerConfig,
    WebSocketConfig,
    PersistenceConfig,
    DEFAULT_CONFIG,
)
from .order_executor import (
    OrderExecutor,
    OrderExecutionError,
    OrderValidationError,
    PartialFillError,
)
from .trade_persistence import (
    TradePersistence,
    TradeValidationError,
)
from .position_manager import (
    PositionManager,
    Position,
    PositionUpdate,
)
from .websocket_broadcaster import (
    WebSocketBroadcaster,
    WebSocketBroadcastError,
    MockWebSocketBroadcaster,
)

__all__ = [
    # Config
    "ExecutionConfig",
    "OrderExecutionConfig",
    "PositionManagerConfig",
    "WebSocketConfig",
    "PersistenceConfig",
    "DEFAULT_CONFIG",
    # Order Executor
    "OrderExecutor",
    "OrderExecutionError",
    "OrderValidationError",
    "PartialFillError",
    # Trade Persistence
    "TradePersistence",
    "TradeValidationError",
    # Position Manager
    "PositionManager",
    "Position",
    "PositionUpdate",
    # WebSocket
    "WebSocketBroadcaster",
    "WebSocketBroadcastError",
    "MockWebSocketBroadcaster",
]

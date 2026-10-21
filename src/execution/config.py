"""
Configuration for the Execution Layer.

Contains constants and configuration classes for:
- Order execution settings
- Position management settings
- WebSocket broadcast settings
- DynamoDB table names
"""

from dataclasses import dataclass
from typing import List


@dataclass
class OrderExecutionConfig:
    """Configuration for order execution (Requirements 6.1, 6.4, 6.5)."""
    
    # Retry delays in seconds for exponential backoff (Requirement 6.4)
    retry_delays_seconds: List[float] = None
    
    # Connection timeout in seconds
    connection_timeout_seconds: int = 30
    
    # Order timeout in seconds
    order_timeout_seconds: int = 60
    
    # Minimum risk-reward ratio for actionable trades (Requirement 13.4)
    min_risk_reward_ratio: float = 1.5
    
    def __post_init__(self):
        """Initialize default retry delays if not provided."""
        if self.retry_delays_seconds is None:
            self.retry_delays_seconds = [1.0, 2.0, 4.0]  # 3 attempts: 1s, 2s, 4s


@dataclass
class PositionManagerConfig:
    """Configuration for position management (Requirements 7.1-7.4)."""
    
    # Maximum time in seconds for WebSocket broadcast (Requirement 7.3)
    max_broadcast_delay_seconds: float = 1.0
    
    # Valid closed statuses (Requirement 13.5)
    valid_closed_statuses: List[str] = None
    
    def __post_init__(self):
        """Initialize default closed statuses if not provided."""
        if self.valid_closed_statuses is None:
            self.valid_closed_statuses = [
                "closed_profit",
                "closed_loss",
                "closed_sl",
                "closed_tp",
            ]


@dataclass
class WebSocketConfig:
    """Configuration for WebSocket broadcasts (Requirements 6.6, 7.3)."""
    
    # WebSocket API endpoint
    endpoint: str = ""
    
    # Connection timeout in seconds
    connection_timeout_seconds: int = 10
    
    # Enable/disable broadcasts
    broadcasts_enabled: bool = True


@dataclass
class PersistenceConfig:
    """Configuration for DynamoDB persistence (Requirements 6.2, 7.1, 7.2)."""
    
    # DynamoDB table names
    trades_table: str = "trading-trades"
    positions_table: str = "trading-positions"
    
    # AWS region
    region: str = "us-east-1"


@dataclass
class ExecutionConfig:
    """Complete configuration for the Execution Layer."""
    
    order_execution: OrderExecutionConfig = None
    position_manager: PositionManagerConfig = None
    websocket: WebSocketConfig = None
    persistence: PersistenceConfig = None
    
    def __post_init__(self):
        """Initialize nested configs with defaults if not provided."""
        if self.order_execution is None:
            self.order_execution = OrderExecutionConfig()
        if self.position_manager is None:
            self.position_manager = PositionManagerConfig()
        if self.websocket is None:
            self.websocket = WebSocketConfig()
        if self.persistence is None:
            self.persistence = PersistenceConfig()


# Default configuration instance
DEFAULT_CONFIG = ExecutionConfig()

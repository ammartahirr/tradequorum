"""
Configuration for the Strategy Agent.

Contains constants and configuration classes for:
- Decision matrix weights
- Stop-loss buffer ranges
- Take-profit targets
- Signal freshness thresholds
"""

from dataclasses import dataclass
from datetime import timedelta


@dataclass
class DecisionMatrixConfig:
    """Configuration for the decision matrix evaluation."""
    
    # Signal weights (Requirement 3.1)
    news_weight: float = 0.4
    technical_weight: float = 0.6
    
    # Combined score thresholds for BUY/SELL decisions
    buy_threshold: float = 0.6
    sell_threshold: float = -0.6


@dataclass
class StopLossConfig:
    """Configuration for stop-loss calculation."""
    
    # Buffer range for stop-loss placement (Requirements 4.2, 4.3)
    min_buffer_pct: float = 0.005  # 0.5%
    max_buffer_pct: float = 0.02   # 2%
    
    # Horizon-based buffer adjustments (Requirement 4.7)
    short_term_buffer_multiplier: float = 0.7  # Tighter stops
    medium_term_buffer_multiplier: float = 1.0
    long_term_buffer_multiplier: float = 1.3   # Wider stops
    
    # Fallback buffer when no support/resistance found
    default_buffer_pct: float = 0.015  # 1.5%


@dataclass
class TakeProfitConfig:
    """Configuration for take-profit calculation."""
    
    # Minimum risk-reward ratio (Requirement 4.6)
    min_risk_reward_ratio: float = 1.5
    
    # Horizon-based target adjustments (Requirement 4.8)
    short_term_target_multiplier: float = 1.0
    medium_term_target_multiplier: float = 1.3
    long_term_target_multiplier: float = 1.6  # Higher targets
    
    # Fallback multiplier when no resistance/support found
    default_reward_multiplier: float = 2.0


@dataclass
class SignalFreshnessConfig:
    """Configuration for signal freshness validation."""
    
    # Technical signal max age (Requirement 3.9)
    technical_signal_max_age: timedelta = timedelta(hours=1)


@dataclass
class StaleDataConfig:
    """Configuration for stale market data handling.
    
    Requirements:
    - 10.2: Mark signals as stale when data >5 min old during trading hours
    """
    
    # Threshold in minutes for stale data detection
    stale_threshold_minutes: int = 5
    
    # Whether to halt trade decisions when data is stale
    halt_on_stale_data: bool = True


@dataclass
class PositionSizingConfig:
    """Configuration for position sizing."""
    
    # Position size by conviction level
    high_conviction_size_pct: float = 0.05    # 5% of portfolio
    medium_conviction_size_pct: float = 0.03  # 3% of portfolio
    low_conviction_size_pct: float = 0.01     # 1% of portfolio
    
    # Maximum position size
    max_position_size_pct: float = 0.05  # 5% max


@dataclass
class StrategyConfig:
    """Complete configuration for the Strategy Agent."""
    
    decision_matrix: DecisionMatrixConfig = None
    stop_loss: StopLossConfig = None
    take_profit: TakeProfitConfig = None
    signal_freshness: SignalFreshnessConfig = None
    position_sizing: PositionSizingConfig = None
    stale_data: StaleDataConfig = None
    
    # DynamoDB table name for decisions
    decisions_table: str = "trading-decisions"
    
    # Decision expiry time
    decision_expiry_hours: int = 4
    
    def __post_init__(self):
        """Initialize nested configs with defaults if not provided."""
        if self.decision_matrix is None:
            self.decision_matrix = DecisionMatrixConfig()
        if self.stop_loss is None:
            self.stop_loss = StopLossConfig()
        if self.take_profit is None:
            self.take_profit = TakeProfitConfig()
        if self.signal_freshness is None:
            self.signal_freshness = SignalFreshnessConfig()
        if self.position_sizing is None:
            self.position_sizing = PositionSizingConfig()
        if self.stale_data is None:
            self.stale_data = StaleDataConfig()


# Default configuration instance
DEFAULT_CONFIG = StrategyConfig()

"""
Configuration for the Risk Manager.

Contains constants and configuration classes for:
- Position size limits
- Portfolio risk limits
- Correlated exposure limits
- Daily loss limits
- Open position limits
"""

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class PositionLimitsConfig:
    """Configuration for position size limits (Requirements 5.1, 5.2)."""
    
    # Maximum position size as percentage of portfolio (Requirement 5.1)
    max_position_pct: float = 0.05  # 5%
    
    # Maximum portfolio risk per trade (Requirement 5.2)
    max_portfolio_risk_pct: float = 0.02  # 2%


@dataclass
class ExposureConfig:
    """Configuration for exposure tracking (Requirements 5.3, 5.5)."""
    
    # Maximum correlated exposure (Requirement 5.3)
    max_correlated_exposure_pct: float = 0.20  # 20%
    
    # Maximum number of open positions (Requirement 5.5)
    max_open_positions: int = 10
    
    # Asset correlation groups - assets in same group are considered correlated
    correlation_groups: Dict[str, List[str]] = None
    
    def __post_init__(self):
        """Initialize default correlation groups if not provided."""
        if self.correlation_groups is None:
            self.correlation_groups = {
                "tech": ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "NVDA"],
                "finance": ["JPM", "BAC", "GS", "MS", "C", "WFC"],
                "energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
                "healthcare": ["JNJ", "UNH", "PFE", "MRK", "ABBV"],
                "consumer": ["WMT", "PG", "KO", "PEP", "COST"],
            }


@dataclass
class DailyLossConfig:
    """Configuration for daily loss limits (Requirement 5.4)."""
    
    # Maximum daily loss as percentage of portfolio
    max_daily_loss_pct: float = 0.05  # 5%


@dataclass
class AlertConfig:
    """Configuration for alerts (Requirement 10.4)."""
    
    # WebSocket endpoint for dashboard alerts
    websocket_endpoint: str = ""
    
    # Enable/disable alerts
    alerts_enabled: bool = True


@dataclass
class RiskConfig:
    """Complete configuration for the Risk Manager."""
    
    position_limits: PositionLimitsConfig = None
    exposure: ExposureConfig = None
    daily_loss: DailyLossConfig = None
    alerts: AlertConfig = None
    
    # DynamoDB table names
    positions_table: str = "trading-positions"
    daily_losses_table: str = "trading-daily-losses"
    
    def __post_init__(self):
        """Initialize nested configs with defaults if not provided."""
        if self.position_limits is None:
            self.position_limits = PositionLimitsConfig()
        if self.exposure is None:
            self.exposure = ExposureConfig()
        if self.daily_loss is None:
            self.daily_loss = DailyLossConfig()
        if self.alerts is None:
            self.alerts = AlertConfig()


# Default configuration instance
DEFAULT_CONFIG = RiskConfig()

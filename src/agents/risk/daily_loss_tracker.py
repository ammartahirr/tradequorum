"""
Daily loss limit enforcement for the Risk Manager.

Tracks and enforces daily loss limits:
- Track cumulative realized losses for current calendar day - Requirement 5.4
- Halt all new trade openings when daily loss exceeds 5% - Requirement 5.4
- Send critical alert to dashboard when limit breached - Requirement 10.4
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Optional
import logging

from .config import DailyLossConfig, AlertConfig


logger = logging.getLogger(__name__)


@dataclass
class DailyLossRecord:
    """Record of daily realized losses."""
    
    date: date
    total_loss: float  # Absolute value of losses (positive number)
    total_profit: float  # Absolute value of profits (positive number)
    trade_count: int
    
    @property
    def net_pnl(self) -> float:
        """Net P&L for the day (can be negative)."""
        return self.total_profit - self.total_loss


@dataclass
class DailyLossValidationResult:
    """Result of daily loss limit validation."""
    
    is_valid: bool
    current_daily_loss_pct: float
    max_daily_loss_pct: float
    rejection_reason: Optional[str]
    alert_sent: bool


class DailyLossTracker:
    """
    Tracks and enforces daily loss limits.
    
    Requirements:
    - 5.4: Track cumulative realized losses, halt trading when > 5%
    - 10.4: Send critical alert to dashboard when limit breached
    """
    
    def __init__(
        self,
        loss_config: DailyLossConfig = None,
        alert_config: AlertConfig = None,
        alert_callback: Optional[Callable[[str, dict], None]] = None,
    ):
        """
        Initialize the daily loss tracker.
        
        Args:
            loss_config: Daily loss configuration. Uses defaults if not provided.
            alert_config: Alert configuration. Uses defaults if not provided.
            alert_callback: Optional callback for sending alerts. 
                           Signature: callback(alert_type: str, data: dict)
        """
        self.loss_config = loss_config or DailyLossConfig()
        self.alert_config = alert_config or AlertConfig()
        self._alert_callback = alert_callback
        self._daily_records: dict[date, DailyLossRecord] = {}
        self._alert_sent_today = False
        self._last_alert_date: Optional[date] = None
    
    def _get_today(self) -> date:
        """Get current date in UTC."""
        return datetime.now(timezone.utc).date()
    
    def _get_or_create_record(self, day: date = None) -> DailyLossRecord:
        """Get or create a daily loss record for the given day."""
        day = day or self._get_today()
        
        if day not in self._daily_records:
            self._daily_records[day] = DailyLossRecord(
                date=day,
                total_loss=0.0,
                total_profit=0.0,
                trade_count=0,
            )
        
        return self._daily_records[day]
    
    def record_trade_result(self, pnl: float, trade_date: date = None) -> None:
        """
        Record a trade result (profit or loss).
        
        Args:
            pnl: The profit/loss amount. Negative for losses, positive for profits.
            trade_date: The date of the trade. Defaults to today.
        """
        record = self._get_or_create_record(trade_date)
        record.trade_count += 1
        
        if pnl < 0:
            record.total_loss += abs(pnl)
        else:
            record.total_profit += pnl
    
    def get_daily_loss(self, day: date = None) -> float:
        """
        Get the cumulative realized loss for a given day.
        
        Args:
            day: The date to check. Defaults to today.
        
        Returns:
            Total realized loss (positive number) for the day.
        """
        record = self._get_or_create_record(day)
        return record.total_loss
    
    def get_daily_loss_pct(self, portfolio_value: float, day: date = None) -> float:
        """
        Get the daily loss as a percentage of portfolio value.
        
        Args:
            portfolio_value: Current portfolio value.
            day: The date to check. Defaults to today.
        
        Returns:
            Daily loss as a percentage (0.0 to 1.0+).
        """
        if portfolio_value <= 0:
            return 0.0
        
        daily_loss = self.get_daily_loss(day)
        return daily_loss / portfolio_value
    
    def is_trading_halted(self, portfolio_value: float) -> bool:
        """
        Check if trading should be halted due to daily loss limit.
        
        Args:
            portfolio_value: Current portfolio value.
        
        Returns:
            True if daily loss exceeds limit and trading should be halted.
        """
        daily_loss_pct = self.get_daily_loss_pct(portfolio_value)
        return daily_loss_pct >= self.loss_config.max_daily_loss_pct
    
    def validate(self, portfolio_value: float) -> DailyLossValidationResult:
        """
        Validate if new trades are allowed based on daily loss limit.
        
        Args:
            portfolio_value: Current portfolio value.
        
        Returns:
            DailyLossValidationResult with validation status.
        
        Preconditions:
            - portfolio_value > 0
        
        Postconditions:
            - If is_valid: daily_loss_pct < max_daily_loss_pct
            - If not is_valid: rejection_reason is non-empty
            - If limit breached and alerts enabled: alert_sent is True
        """
        daily_loss_pct = self.get_daily_loss_pct(portfolio_value)
        is_halted = daily_loss_pct >= self.loss_config.max_daily_loss_pct
        alert_sent = False
        
        if is_halted:
            # Send alert if not already sent today (Requirement 10.4)
            alert_sent = self._send_alert_if_needed(portfolio_value, daily_loss_pct)
            
            return DailyLossValidationResult(
                is_valid=False,
                current_daily_loss_pct=daily_loss_pct,
                max_daily_loss_pct=self.loss_config.max_daily_loss_pct,
                rejection_reason=(
                    f"Daily loss limit breached. Current loss: {daily_loss_pct:.2%}, "
                    f"Limit: {self.loss_config.max_daily_loss_pct:.2%}. "
                    f"Trading halted until next trading day."
                ),
                alert_sent=alert_sent,
            )
        
        return DailyLossValidationResult(
            is_valid=True,
            current_daily_loss_pct=daily_loss_pct,
            max_daily_loss_pct=self.loss_config.max_daily_loss_pct,
            rejection_reason=None,
            alert_sent=False,
        )
    
    def _send_alert_if_needed(self, portfolio_value: float, daily_loss_pct: float) -> bool:
        """
        Send a critical alert if not already sent today.
        
        Returns:
            True if alert was sent, False if already sent or alerts disabled.
        """
        today = self._get_today()
        
        # Check if alert already sent today
        if self._last_alert_date == today:
            return False
        
        # Check if alerts are enabled
        if not self.alert_config.alerts_enabled:
            return False
        
        # Send alert
        self._last_alert_date = today
        
        alert_data = {
            "type": "CRITICAL",
            "category": "DAILY_LOSS_LIMIT",
            "message": f"Daily loss limit breached! Loss: {daily_loss_pct:.2%}",
            "portfolio_value": portfolio_value,
            "daily_loss_pct": daily_loss_pct,
            "max_daily_loss_pct": self.loss_config.max_daily_loss_pct,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        if self._alert_callback:
            try:
                self._alert_callback("DAILY_LOSS_LIMIT_BREACHED", alert_data)
            except Exception as e:
                logger.error(f"Failed to send daily loss alert: {e}")
        
        logger.critical(
            f"DAILY LOSS LIMIT BREACHED - Loss: {daily_loss_pct:.2%}, "
            f"Limit: {self.loss_config.max_daily_loss_pct:.2%}"
        )
        
        return True
    
    def reset_daily_record(self, day: date = None) -> None:
        """
        Reset the daily loss record for a given day.
        
        Args:
            day: The date to reset. Defaults to today.
        """
        day = day or self._get_today()
        self._daily_records.pop(day, None)
        
        if self._last_alert_date == day:
            self._last_alert_date = None
    
    def get_daily_record(self, day: date = None) -> DailyLossRecord:
        """
        Get the daily loss record for a given day.
        
        Args:
            day: The date to get. Defaults to today.
        
        Returns:
            DailyLossRecord for the day.
        """
        return self._get_or_create_record(day)

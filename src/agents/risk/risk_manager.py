"""
Risk Manager for the AI Trading System.

Validates trade decisions against portfolio risk constraints:
- Position size limits (5% max) - Requirement 5.1
- Portfolio risk per trade (2% max) - Requirement 5.2
- Correlated exposure (20% max) - Requirement 5.3
- Daily loss limit (5% max) - Requirement 5.4
- Open position limit (10 max) - Requirement 5.5
- Position size adjustment - Requirement 5.6
- Risk score generation - Requirement 5.8
"""

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
import logging

from src.models.trading import RiskAssessment, RiskLimits, TradeDecision

from .config import RiskConfig, DEFAULT_CONFIG
from .position_validator import PositionValidator, PositionValidationResult
from .exposure_tracker import ExposureTracker, ExposureValidationResult, OpenPosition
from .daily_loss_tracker import DailyLossTracker, DailyLossValidationResult


logger = logging.getLogger(__name__)


@dataclass
class Portfolio:
    """Portfolio state for risk assessment."""
    
    total_value: float
    open_positions: List[OpenPosition]


class RiskManager:
    """
    Validates trade decisions against portfolio risk constraints.
    
    Requirements:
    - 5.1: Position size does not exceed 5% of portfolio
    - 5.2: Portfolio risk per trade does not exceed 2%
    - 5.3: Correlated exposure does not exceed 20%
    - 5.4: Daily loss does not exceed 5%
    - 5.5: Open positions do not exceed 10
    - 5.6: Adjust position size downward when limits exceeded
    - 5.7: Provide non-empty rejection reason when trade rejected
    - 5.8: Generate risk score in [0.0, 1.0] for every assessed trade
    """
    
    def __init__(
        self,
        config: RiskConfig = None,
        alert_callback: Optional[Callable[[str, dict], None]] = None,
    ):
        """
        Initialize the Risk Manager.
        
        Args:
            config: Risk configuration. Uses defaults if not provided.
            alert_callback: Optional callback for sending alerts.
        """
        self.config = config or DEFAULT_CONFIG
        
        # Initialize sub-components
        self._position_validator = PositionValidator(self.config.position_limits)
        self._exposure_tracker = ExposureTracker(self.config.exposure)
        self._daily_loss_tracker = DailyLossTracker(
            self.config.daily_loss,
            self.config.alerts,
            alert_callback,
        )
    
    def assess_trade(
        self,
        decision: TradeDecision,
        portfolio: Portfolio,
    ) -> RiskAssessment:
        """
        Assess a trade decision against all risk constraints.
        
        Args:
            decision: The trade decision to assess.
            portfolio: Current portfolio state.
        
        Returns:
            RiskAssessment with approval status, adjustments, and risk score.
        
        Preconditions:
            - decision.position_size_pct > 0
            - portfolio.total_value > 0
        
        Postconditions:
            - If approved: all risk checks pass
            - If not approved: rejection_reason is non-empty
            - risk_score is in [0.0, 1.0]
        """
        warnings = []
        adjusted_size = None
        current_size = decision.position_size_pct
        
        # Update exposure tracker with current positions
        self._exposure_tracker.set_positions(portfolio.open_positions)
        
        # Check 1: Daily loss limit (Requirement 5.4)
        daily_loss_result = self._daily_loss_tracker.validate(portfolio.total_value)
        if not daily_loss_result.is_valid:
            return RiskAssessment(
                approved=False,
                adjusted_size=None,
                risk_score=1.0,  # Maximum risk
                warnings=[
                    f"Daily loss: {daily_loss_result.current_daily_loss_pct:.2%}"
                ],
                rejection_reason=daily_loss_result.rejection_reason,
            )
        
        # Check 2: Open position limit (Requirement 5.5)
        exposure_result = self._exposure_tracker.validate(decision)
        if not exposure_result.is_valid:
            return RiskAssessment(
                approved=False,
                adjusted_size=None,
                risk_score=self._calculate_risk_score(
                    decision, portfolio, exposure_result, None, daily_loss_result
                ),
                warnings=exposure_result.warnings,
                rejection_reason=exposure_result.rejection_reason,
            )
        
        # Apply exposure adjustment if needed
        if exposure_result.adjusted_size_pct is not None:
            current_size = exposure_result.adjusted_size_pct
            adjusted_size = current_size
            warnings.extend(exposure_result.warnings)
        
        # Check 3: Position size limits (Requirements 5.1, 5.2)
        # Create a modified decision with potentially adjusted size for validation
        position_result = self._position_validator.validate(decision, portfolio.total_value)
        if not position_result.is_valid:
            return RiskAssessment(
                approved=False,
                adjusted_size=None,
                risk_score=self._calculate_risk_score(
                    decision, portfolio, exposure_result, position_result, daily_loss_result
                ),
                warnings=position_result.warnings,
                rejection_reason=position_result.rejection_reason,
            )
        
        # Apply position size adjustment if needed (Requirement 5.6)
        if position_result.adjusted_size_pct is not None:
            # Take the minimum of exposure and position adjustments
            if adjusted_size is not None:
                adjusted_size = min(adjusted_size, position_result.adjusted_size_pct)
            else:
                adjusted_size = position_result.adjusted_size_pct
            warnings.extend(position_result.warnings)
        
        # Calculate final risk score (Requirement 5.8)
        risk_score = self._calculate_risk_score(
            decision, portfolio, exposure_result, position_result, daily_loss_result
        )
        
        return RiskAssessment(
            approved=True,
            adjusted_size=adjusted_size,
            risk_score=risk_score,
            warnings=warnings,
            rejection_reason=None,
        )
    
    def _calculate_risk_score(
        self,
        decision: TradeDecision,
        portfolio: Portfolio,
        exposure_result: ExposureValidationResult,
        position_result: Optional[PositionValidationResult],
        daily_loss_result: DailyLossValidationResult,
    ) -> float:
        """
        Calculate a risk score in [0.0, 1.0] for the trade.
        
        The risk score is a weighted combination of:
        - Position size relative to max (25%)
        - Correlated exposure relative to max (25%)
        - Daily loss relative to max (25%)
        - Open positions relative to max (25%)
        
        Returns:
            Risk score in [0.0, 1.0] where 1.0 is maximum risk.
        """
        # Position size component
        position_size = decision.position_size_pct
        if position_result and position_result.adjusted_size_pct:
            position_size = position_result.adjusted_size_pct
        position_risk = min(1.0, position_size / self.config.position_limits.max_position_pct)
        
        # Correlated exposure component
        correlated_exposure = exposure_result.current_correlated_exposure + position_size
        exposure_risk = min(1.0, correlated_exposure / self.config.exposure.max_correlated_exposure_pct)
        
        # Daily loss component
        daily_loss_risk = min(
            1.0,
            daily_loss_result.current_daily_loss_pct / self.config.daily_loss.max_daily_loss_pct
        )
        
        # Open positions component
        open_positions = exposure_result.current_open_positions
        # Add 1 for the new position if it's not already counted
        if decision.symbol not in [p.symbol for p in portfolio.open_positions]:
            open_positions += 1
        max_positions = max(1, self.config.exposure.max_open_positions)  # Avoid division by zero
        positions_risk = min(1.0, open_positions / max_positions)
        
        # Weighted average
        risk_score = (
            position_risk * 0.25 +
            exposure_risk * 0.25 +
            daily_loss_risk * 0.25 +
            positions_risk * 0.25
        )
        
        return min(1.0, max(0.0, risk_score))
    
    def record_trade_result(self, pnl: float) -> None:
        """
        Record a trade result for daily loss tracking.
        
        Args:
            pnl: The profit/loss amount. Negative for losses.
        """
        self._daily_loss_tracker.record_trade_result(pnl)
    
    def add_position(self, position: OpenPosition) -> None:
        """
        Add an open position to tracking.
        
        Args:
            position: The position to track.
        """
        self._exposure_tracker.add_position(position)
    
    def remove_position(self, symbol: str) -> None:
        """
        Remove a closed position from tracking.
        
        Args:
            symbol: The symbol of the position to remove.
        """
        self._exposure_tracker.remove_position(symbol)
    
    def get_portfolio_risk(self, portfolio: Portfolio) -> Dict:
        """
        Get current portfolio risk metrics.
        
        Args:
            portfolio: Current portfolio state.
        
        Returns:
            Dictionary with risk metrics.
        """
        self._exposure_tracker.set_positions(portfolio.open_positions)
        
        # Calculate total exposure by correlation group
        group_exposures = {}
        for group_name, symbols in self.config.exposure.correlation_groups.items():
            group_exposure = 0.0
            for pos in portfolio.open_positions:
                if pos.symbol in symbols:
                    group_exposure += pos.position_size_pct
            if group_exposure > 0:
                group_exposures[group_name] = group_exposure
        
        return {
            "open_positions": self._exposure_tracker.get_open_position_count(),
            "max_open_positions": self.config.exposure.max_open_positions,
            "daily_loss_pct": self._daily_loss_tracker.get_daily_loss_pct(portfolio.total_value),
            "max_daily_loss_pct": self.config.daily_loss.max_daily_loss_pct,
            "group_exposures": group_exposures,
            "max_correlated_exposure_pct": self.config.exposure.max_correlated_exposure_pct,
            "trading_halted": self._daily_loss_tracker.is_trading_halted(portfolio.total_value),
        }
    
    def check_daily_limits(self, portfolio_value: float) -> bool:
        """
        Check if daily loss limit has been breached.
        
        Args:
            portfolio_value: Current portfolio value.
        
        Returns:
            True if trading is allowed, False if halted.
        """
        return not self._daily_loss_tracker.is_trading_halted(portfolio_value)

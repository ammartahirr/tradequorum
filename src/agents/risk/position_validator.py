"""
Position size validation for the Risk Manager.

Validates that trade decisions comply with position size limits:
- Maximum position size (5% of portfolio) - Requirement 5.1
- Maximum portfolio risk per trade (2%) - Requirement 5.2
- Adjusts position size downward when limits exceeded - Requirement 5.6
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from src.models.enums import TradeAction
from src.models.trading import TradeDecision

from .config import PositionLimitsConfig


@dataclass
class PositionValidationResult:
    """Result of position size validation."""
    
    is_valid: bool
    original_size_pct: float
    adjusted_size_pct: Optional[float]
    warnings: list[str]
    rejection_reason: Optional[str]


class PositionValidator:
    """
    Validates position sizes against portfolio limits.
    
    Requirements:
    - 5.1: Position size does not exceed 5% of portfolio
    - 5.2: Portfolio risk per trade does not exceed 2%
    - 5.6: Adjust position size downward when limits exceeded but trade viable
    """
    
    def __init__(self, config: PositionLimitsConfig = None):
        """
        Initialize the position validator.
        
        Args:
            config: Position limits configuration. Uses defaults if not provided.
        """
        self.config = config or PositionLimitsConfig()
    
    def validate(
        self,
        decision: TradeDecision,
        portfolio_value: float,
    ) -> PositionValidationResult:
        """
        Validate position size against portfolio limits.
        
        Args:
            decision: The trade decision to validate.
            portfolio_value: Total portfolio value in currency.
        
        Returns:
            PositionValidationResult with validation status and any adjustments.
        
        Preconditions:
            - decision.position_size_pct > 0
            - portfolio_value > 0
            - decision.entry_price > 0
            - decision.stop_loss > 0
        
        Postconditions:
            - If is_valid: adjusted_size_pct <= max_position_pct
            - If is_valid: portfolio_risk <= max_portfolio_risk_pct
            - If not is_valid: rejection_reason is non-empty
        """
        warnings = []
        original_size = decision.position_size_pct
        adjusted_size = original_size
        
        # Check 1: Position size limit (Requirement 5.1)
        if original_size > self.config.max_position_pct:
            warnings.append(
                f"Position size {original_size:.2%} exceeds max {self.config.max_position_pct:.2%}"
            )
            adjusted_size = self.config.max_position_pct
        
        # Check 2: Portfolio risk per trade (Requirement 5.2)
        risk_per_share = self._calculate_risk_per_share(decision)
        position_value = portfolio_value * adjusted_size
        position_risk = self._calculate_position_risk(
            position_value, decision.entry_price, risk_per_share
        )
        portfolio_risk_pct = position_risk / portfolio_value if portfolio_value > 0 else 0
        
        if portfolio_risk_pct > self.config.max_portfolio_risk_pct:
            warnings.append(
                f"Portfolio risk {portfolio_risk_pct:.2%} exceeds max {self.config.max_portfolio_risk_pct:.2%}"
            )
            # Adjust position size to meet risk limit (Requirement 5.6)
            max_risk = portfolio_value * self.config.max_portfolio_risk_pct
            if risk_per_share > 0:
                max_shares = max_risk / risk_per_share
                max_position_value = max_shares * decision.entry_price
                adjusted_size = min(adjusted_size, max_position_value / portfolio_value)
        
        # Ensure adjusted size is still positive and meaningful
        if adjusted_size <= 0:
            return PositionValidationResult(
                is_valid=False,
                original_size_pct=original_size,
                adjusted_size_pct=None,
                warnings=warnings,
                rejection_reason="Position size would be zero or negative after risk adjustment",
            )
        
        # Return result with adjustment if needed
        return PositionValidationResult(
            is_valid=True,
            original_size_pct=original_size,
            adjusted_size_pct=adjusted_size if adjusted_size != original_size else None,
            warnings=warnings,
            rejection_reason=None,
        )
    
    def _calculate_risk_per_share(self, decision: TradeDecision) -> float:
        """
        Calculate the risk per share based on entry and stop-loss.
        
        For BUY: risk = entry_price - stop_loss
        For SELL: risk = stop_loss - entry_price
        """
        buy_actions = {TradeAction.STRONG_BUY, TradeAction.BUY}
        sell_actions = {TradeAction.STRONG_SELL, TradeAction.SELL}
        
        if decision.action in buy_actions:
            return decision.entry_price - decision.stop_loss
        elif decision.action in sell_actions:
            return decision.stop_loss - decision.entry_price
        else:
            return 0.0
    
    def _calculate_position_risk(
        self,
        position_value: float,
        entry_price: float,
        risk_per_share: float,
    ) -> float:
        """
        Calculate total position risk in currency.
        
        Args:
            position_value: Total value of the position.
            entry_price: Entry price per share.
            risk_per_share: Risk per share (entry - stop_loss for BUY).
        
        Returns:
            Total risk in currency.
        """
        if entry_price <= 0:
            return 0.0
        
        num_shares = position_value / entry_price
        return num_shares * risk_per_share

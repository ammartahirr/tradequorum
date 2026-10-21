"""
Correlated exposure tracking for the Risk Manager.

Tracks and validates exposure in correlated assets:
- Track total exposure in correlated assets - Requirement 5.3
- Reject or reduce position when correlated exposure would exceed 20% - Requirement 5.3
- Track count of open positions - Requirement 5.5
- Reject new trades when 10 positions are open - Requirement 5.5
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from src.models.trading import TradeDecision

from .config import ExposureConfig


@dataclass
class OpenPosition:
    """Represents an open position for exposure tracking."""
    
    symbol: str
    position_size_pct: float  # As percentage of portfolio
    entry_price: float


@dataclass
class ExposureValidationResult:
    """Result of exposure validation."""
    
    is_valid: bool
    original_size_pct: float
    adjusted_size_pct: Optional[float]
    current_correlated_exposure: float
    current_open_positions: int
    warnings: list[str]
    rejection_reason: Optional[str]


class ExposureTracker:
    """
    Tracks and validates portfolio exposure.
    
    Requirements:
    - 5.3: Track total exposure in correlated assets, reject/reduce when > 20%
    - 5.5: Track count of open positions, reject when 10 positions open
    """
    
    def __init__(self, config: ExposureConfig = None):
        """
        Initialize the exposure tracker.
        
        Args:
            config: Exposure configuration. Uses defaults if not provided.
        """
        self.config = config or ExposureConfig()
        self._open_positions: Dict[str, OpenPosition] = {}
        self._symbol_to_group: Dict[str, str] = self._build_symbol_to_group_map()
    
    def _build_symbol_to_group_map(self) -> Dict[str, str]:
        """Build a reverse mapping from symbol to correlation group."""
        symbol_to_group = {}
        for group_name, symbols in self.config.correlation_groups.items():
            for symbol in symbols:
                symbol_to_group[symbol] = group_name
        return symbol_to_group
    
    def add_position(self, position: OpenPosition) -> None:
        """
        Add an open position to tracking.
        
        Args:
            position: The position to track.
        """
        self._open_positions[position.symbol] = position
    
    def remove_position(self, symbol: str) -> None:
        """
        Remove a closed position from tracking.
        
        Args:
            symbol: The symbol of the position to remove.
        """
        self._open_positions.pop(symbol, None)
    
    def get_open_position_count(self) -> int:
        """Get the current count of open positions."""
        return len(self._open_positions)
    
    def get_correlated_exposure(self, symbol: str) -> float:
        """
        Get total exposure in assets correlated with the given symbol.
        
        Args:
            symbol: The symbol to check correlation for.
        
        Returns:
            Total exposure as percentage of portfolio in correlated assets.
        """
        group = self._symbol_to_group.get(symbol)
        if not group:
            # Symbol not in any correlation group, only count its own exposure
            pos = self._open_positions.get(symbol)
            return pos.position_size_pct if pos else 0.0
        
        # Sum exposure of all positions in the same correlation group
        total_exposure = 0.0
        correlated_symbols = set(self.config.correlation_groups.get(group, []))
        
        for pos_symbol, position in self._open_positions.items():
            if pos_symbol in correlated_symbols:
                total_exposure += position.position_size_pct
        
        return total_exposure
    
    def get_symbols_in_group(self, symbol: str) -> Set[str]:
        """
        Get all symbols in the same correlation group as the given symbol.
        
        Args:
            symbol: The symbol to find correlated assets for.
        
        Returns:
            Set of correlated symbols (including the input symbol).
        """
        group = self._symbol_to_group.get(symbol)
        if not group:
            return {symbol}
        return set(self.config.correlation_groups.get(group, [symbol]))
    
    def validate(
        self,
        decision: TradeDecision,
    ) -> ExposureValidationResult:
        """
        Validate a trade decision against exposure limits.
        
        Args:
            decision: The trade decision to validate.
        
        Returns:
            ExposureValidationResult with validation status and any adjustments.
        
        Preconditions:
            - decision.position_size_pct > 0
        
        Postconditions:
            - If is_valid: open_positions < max_open_positions OR symbol already has position
            - If is_valid: correlated_exposure + new_position <= max_correlated_exposure
            - If not is_valid: rejection_reason is non-empty
        """
        warnings = []
        original_size = decision.position_size_pct
        adjusted_size = original_size
        
        current_positions = self.get_open_position_count()
        current_correlated = self.get_correlated_exposure(decision.symbol)
        
        # Check 1: Open position limit (Requirement 5.5)
        # Allow if we already have a position in this symbol (modifying existing)
        has_existing_position = decision.symbol in self._open_positions
        
        if current_positions >= self.config.max_open_positions and not has_existing_position:
            return ExposureValidationResult(
                is_valid=False,
                original_size_pct=original_size,
                adjusted_size_pct=None,
                current_correlated_exposure=current_correlated,
                current_open_positions=current_positions,
                warnings=warnings,
                rejection_reason=(
                    f"Maximum open positions ({self.config.max_open_positions}) reached. "
                    f"Close an existing position before opening new trades."
                ),
            )
        
        # Check 2: Correlated exposure limit (Requirement 5.3)
        # Calculate what the new total correlated exposure would be
        # If we already have a position in this symbol, subtract it first
        existing_exposure = 0.0
        if has_existing_position:
            existing_exposure = self._open_positions[decision.symbol].position_size_pct
        
        new_correlated_exposure = current_correlated - existing_exposure + original_size
        
        if new_correlated_exposure > self.config.max_correlated_exposure_pct:
            # Calculate maximum allowed size for this trade
            available_exposure = self.config.max_correlated_exposure_pct - (current_correlated - existing_exposure)
            
            if available_exposure <= 0:
                return ExposureValidationResult(
                    is_valid=False,
                    original_size_pct=original_size,
                    adjusted_size_pct=None,
                    current_correlated_exposure=current_correlated,
                    current_open_positions=current_positions,
                    warnings=warnings,
                    rejection_reason=(
                        f"Correlated exposure ({current_correlated:.2%}) already at or exceeds "
                        f"maximum ({self.config.max_correlated_exposure_pct:.2%}). "
                        f"Reduce exposure in correlated assets before adding new positions."
                    ),
                )
            
            # Reduce position size to fit within limit
            warnings.append(
                f"Position size reduced from {original_size:.2%} to {available_exposure:.2%} "
                f"to stay within correlated exposure limit"
            )
            adjusted_size = available_exposure
        
        return ExposureValidationResult(
            is_valid=True,
            original_size_pct=original_size,
            adjusted_size_pct=adjusted_size if adjusted_size != original_size else None,
            current_correlated_exposure=current_correlated,
            current_open_positions=current_positions,
            warnings=warnings,
            rejection_reason=None,
        )
    
    def set_positions(self, positions: List[OpenPosition]) -> None:
        """
        Set the current open positions (for initialization from database).
        
        Args:
            positions: List of open positions to track.
        """
        self._open_positions = {pos.symbol: pos for pos in positions}
    
    def get_all_positions(self) -> List[OpenPosition]:
        """Get all currently tracked open positions."""
        return list(self._open_positions.values())

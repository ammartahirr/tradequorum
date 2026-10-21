"""
Stop-Loss Calculation for the Strategy Agent.

Implements stop-loss calculation based on support/resistance levels
with appropriate buffers.

Requirements:
- 4.1: Every trade decision must have a stop-loss
- 4.2: For BUY, stop-loss below nearest support with 0.5-2% buffer
- 4.3: For SELL, stop-loss above nearest resistance with 0.5-2% buffer
- 4.7: SHORT_TERM uses tighter stops than LONG_TERM
"""

import logging
from typing import List, Optional

from src.models.enums import TradeAction, TradingHorizon
from src.models.signals import SupportResistance

from .config import StopLossConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


def _get_buffer_multiplier(horizon: TradingHorizon, config: StopLossConfig) -> float:
    """
    Get the buffer multiplier based on trading horizon.
    
    Args:
        horizon: Trading horizon
        config: Stop-loss configuration
        
    Returns:
        Buffer multiplier for the horizon
    """
    multipliers = {
        TradingHorizon.SHORT_TERM: config.short_term_buffer_multiplier,
        TradingHorizon.MEDIUM_TERM: config.medium_term_buffer_multiplier,
        TradingHorizon.LONG_TERM: config.long_term_buffer_multiplier,
    }
    return multipliers.get(horizon, config.medium_term_buffer_multiplier)


def _find_nearest_support_below(
    entry_price: float,
    support_levels: List[SupportResistance],
) -> Optional[SupportResistance]:
    """
    Find the nearest support level below the entry price.
    
    Args:
        entry_price: Entry price for the trade
        support_levels: List of support levels
        
    Returns:
        Nearest support level below entry price, or None if not found
    """
    # Filter supports below entry price and sort by level descending
    valid_supports = [s for s in support_levels if s.level < entry_price]
    if not valid_supports:
        return None
    
    # Return the highest support below entry (nearest)
    return max(valid_supports, key=lambda s: s.level)


def _find_nearest_resistance_above(
    entry_price: float,
    resistance_levels: List[SupportResistance],
) -> Optional[SupportResistance]:
    """
    Find the nearest resistance level above the entry price.
    
    Args:
        entry_price: Entry price for the trade
        resistance_levels: List of resistance levels
        
    Returns:
        Nearest resistance level above entry price, or None if not found
    """
    # Filter resistances above entry price and sort by level ascending
    valid_resistances = [r for r in resistance_levels if r.level > entry_price]
    if not valid_resistances:
        return None
    
    # Return the lowest resistance above entry (nearest)
    return min(valid_resistances, key=lambda r: r.level)


def calculate_stop_loss(
    action: TradeAction,
    entry_price: float,
    support_levels: List[SupportResistance],
    resistance_levels: List[SupportResistance],
    horizon: TradingHorizon,
    config: StopLossConfig = None,
) -> float:
    """
    Calculate stop-loss level for a trade.
    
    For BUY trades: Stop-loss is placed below the nearest support level
    For SELL trades: Stop-loss is placed above the nearest resistance level
    
    A buffer of 0.5-2% is applied to avoid false triggers, adjusted by
    the trading horizon (tighter for short-term, wider for long-term).
    
    Args:
        action: Trade action (BUY, STRONG_BUY, SELL, STRONG_SELL)
        entry_price: Entry price for the trade
        support_levels: List of support levels from technical analysis
        resistance_levels: List of resistance levels from technical analysis
        horizon: Trading horizon
        config: Stop-loss configuration
        
    Returns:
        Stop-loss price level
        
    Requirements:
    - 4.1: Every trade decision must have a stop-loss
    - 4.2: For BUY, stop-loss below nearest support with 0.5-2% buffer
    - 4.3: For SELL, stop-loss above nearest resistance with 0.5-2% buffer
    - 4.7: SHORT_TERM uses tighter stops than LONG_TERM
    """
    if config is None:
        config = DEFAULT_CONFIG.stop_loss
    
    # Get horizon-adjusted buffer multiplier
    buffer_multiplier = _get_buffer_multiplier(horizon, config)
    
    # Calculate base buffer percentage (middle of range)
    base_buffer = (config.min_buffer_pct + config.max_buffer_pct) / 2
    adjusted_buffer = base_buffer * buffer_multiplier
    
    # Clamp buffer to valid range
    adjusted_buffer = max(config.min_buffer_pct, min(config.max_buffer_pct, adjusted_buffer))
    
    buy_actions = {TradeAction.BUY, TradeAction.STRONG_BUY}
    sell_actions = {TradeAction.SELL, TradeAction.STRONG_SELL}
    
    if action in buy_actions:
        return _calculate_buy_stop_loss(
            entry_price,
            support_levels,
            adjusted_buffer,
            config,
        )
    elif action in sell_actions:
        return _calculate_sell_stop_loss(
            entry_price,
            resistance_levels,
            adjusted_buffer,
            config,
        )
    else:
        # For non-actionable trades, return a default stop-loss
        # This shouldn't normally be called, but provides a fallback
        return entry_price * (1 - config.default_buffer_pct)


def _calculate_buy_stop_loss(
    entry_price: float,
    support_levels: List[SupportResistance],
    buffer_pct: float,
    config: StopLossConfig,
) -> float:
    """
    Calculate stop-loss for BUY trades.
    
    Stop-loss is placed below the nearest support level with a buffer.
    
    Args:
        entry_price: Entry price for the trade
        support_levels: List of support levels
        buffer_pct: Buffer percentage to apply
        config: Stop-loss configuration
        
    Returns:
        Stop-loss price level (always below entry_price)
    """
    # Find nearest support below entry price
    nearest_support = _find_nearest_support_below(entry_price, support_levels)
    
    if nearest_support is not None:
        # Place stop-loss below support with buffer
        stop_loss = nearest_support.level * (1 - buffer_pct)
        
        # Ensure stop-loss is below entry price
        if stop_loss >= entry_price:
            # Support is too close to entry, use default buffer from entry
            stop_loss = entry_price * (1 - config.default_buffer_pct)
        
        logger.debug(
            f"BUY stop-loss: support={nearest_support.level:.2f}, "
            f"buffer={buffer_pct:.3f}, stop_loss={stop_loss:.2f}"
        )
    else:
        # No support found, use default buffer from entry price
        stop_loss = entry_price * (1 - config.default_buffer_pct)
        logger.debug(
            f"BUY stop-loss: no support found, using default buffer, "
            f"stop_loss={stop_loss:.2f}"
        )
    
    return stop_loss


def _calculate_sell_stop_loss(
    entry_price: float,
    resistance_levels: List[SupportResistance],
    buffer_pct: float,
    config: StopLossConfig,
) -> float:
    """
    Calculate stop-loss for SELL trades.
    
    Stop-loss is placed above the nearest resistance level with a buffer.
    
    Args:
        entry_price: Entry price for the trade
        resistance_levels: List of resistance levels
        buffer_pct: Buffer percentage to apply
        config: Stop-loss configuration
        
    Returns:
        Stop-loss price level (always above entry_price)
    """
    # Find nearest resistance above entry price
    nearest_resistance = _find_nearest_resistance_above(entry_price, resistance_levels)
    
    if nearest_resistance is not None:
        # Place stop-loss above resistance with buffer
        stop_loss = nearest_resistance.level * (1 + buffer_pct)
        
        # Ensure stop-loss is above entry price
        if stop_loss <= entry_price:
            # Resistance is too close to entry, use default buffer from entry
            stop_loss = entry_price * (1 + config.default_buffer_pct)
        
        logger.debug(
            f"SELL stop-loss: resistance={nearest_resistance.level:.2f}, "
            f"buffer={buffer_pct:.3f}, stop_loss={stop_loss:.2f}"
        )
    else:
        # No resistance found, use default buffer from entry price
        stop_loss = entry_price * (1 + config.default_buffer_pct)
        logger.debug(
            f"SELL stop-loss: no resistance found, using default buffer, "
            f"stop_loss={stop_loss:.2f}"
        )
    
    return stop_loss


class StopLossCalculator:
    """
    Calculator for stop-loss levels.
    
    Provides methods to calculate stop-loss based on support/resistance
    levels with appropriate buffers for different trading horizons.
    
    Requirements:
    - 4.1: Every trade decision must have a stop-loss
    - 4.2: For BUY, stop-loss below nearest support with 0.5-2% buffer
    - 4.3: For SELL, stop-loss above nearest resistance with 0.5-2% buffer
    - 4.7: SHORT_TERM uses tighter stops than LONG_TERM
    """
    
    def __init__(self, config: StopLossConfig = None):
        """
        Initialize the stop-loss calculator.
        
        Args:
            config: Stop-loss configuration
        """
        self.config = config or DEFAULT_CONFIG.stop_loss
    
    def calculate(
        self,
        action: TradeAction,
        entry_price: float,
        support_levels: List[SupportResistance],
        resistance_levels: List[SupportResistance],
        horizon: TradingHorizon,
    ) -> float:
        """
        Calculate stop-loss level for a trade.
        
        Args:
            action: Trade action
            entry_price: Entry price for the trade
            support_levels: List of support levels
            resistance_levels: List of resistance levels
            horizon: Trading horizon
            
        Returns:
            Stop-loss price level
        """
        return calculate_stop_loss(
            action=action,
            entry_price=entry_price,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            horizon=horizon,
            config=self.config,
        )
    
    def validate_stop_loss(
        self,
        action: TradeAction,
        entry_price: float,
        stop_loss: float,
    ) -> bool:
        """
        Validate that a stop-loss is correctly positioned.
        
        Args:
            action: Trade action
            entry_price: Entry price for the trade
            stop_loss: Stop-loss price to validate
            
        Returns:
            True if stop-loss is valid, False otherwise
        """
        buy_actions = {TradeAction.BUY, TradeAction.STRONG_BUY}
        sell_actions = {TradeAction.SELL, TradeAction.STRONG_SELL}
        
        if action in buy_actions:
            return stop_loss < entry_price
        elif action in sell_actions:
            return stop_loss > entry_price
        else:
            # Non-actionable trades don't have strict stop-loss requirements
            return True

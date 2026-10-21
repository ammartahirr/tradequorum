"""
Take-Profit Calculation for the Strategy Agent.

Implements take-profit calculation based on support/resistance levels
with minimum risk-reward ratio enforcement.

Requirements:
- 4.4: For BUY, take-profit at resistance levels
- 4.5: For SELL, take-profit at support levels
- 4.6: Risk-reward ratio must be >= 1.5 for actionable trades
- 4.8: LONG_TERM targets higher resistance levels
"""

import logging
from typing import List, Optional

from src.models.enums import TradeAction, TradingHorizon
from src.models.signals import SupportResistance

from .config import TakeProfitConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


def _get_target_multiplier(horizon: TradingHorizon, config: TakeProfitConfig) -> float:
    """
    Get the target multiplier based on trading horizon.
    
    Args:
        horizon: Trading horizon
        config: Take-profit configuration
        
    Returns:
        Target multiplier for the horizon
    """
    multipliers = {
        TradingHorizon.SHORT_TERM: config.short_term_target_multiplier,
        TradingHorizon.MEDIUM_TERM: config.medium_term_target_multiplier,
        TradingHorizon.LONG_TERM: config.long_term_target_multiplier,
    }
    return multipliers.get(horizon, config.medium_term_target_multiplier)


def _find_resistance_above(
    entry_price: float,
    resistance_levels: List[SupportResistance],
    horizon: TradingHorizon,
) -> Optional[SupportResistance]:
    """
    Find an appropriate resistance level above the entry price.
    
    For LONG_TERM horizons, targets higher resistance levels.
    For SHORT_TERM horizons, targets the nearest resistance.
    
    Args:
        entry_price: Entry price for the trade
        resistance_levels: List of resistance levels
        horizon: Trading horizon
        
    Returns:
        Appropriate resistance level, or None if not found
    """
    # Filter resistances above entry price
    valid_resistances = [r for r in resistance_levels if r.level > entry_price]
    if not valid_resistances:
        return None
    
    # Sort by level ascending
    sorted_resistances = sorted(valid_resistances, key=lambda r: r.level)
    
    if horizon == TradingHorizon.LONG_TERM and len(sorted_resistances) > 1:
        # For long-term, target a higher resistance (second or third level)
        index = min(len(sorted_resistances) - 1, 2)
        return sorted_resistances[index]
    elif horizon == TradingHorizon.MEDIUM_TERM and len(sorted_resistances) > 1:
        # For medium-term, target second resistance if available
        index = min(len(sorted_resistances) - 1, 1)
        return sorted_resistances[index]
    else:
        # For short-term or when only one level, use nearest
        return sorted_resistances[0]


def _find_support_below(
    entry_price: float,
    support_levels: List[SupportResistance],
    horizon: TradingHorizon,
) -> Optional[SupportResistance]:
    """
    Find an appropriate support level below the entry price.
    
    For LONG_TERM horizons, targets lower support levels.
    For SHORT_TERM horizons, targets the nearest support.
    
    Args:
        entry_price: Entry price for the trade
        support_levels: List of support levels
        horizon: Trading horizon
        
    Returns:
        Appropriate support level, or None if not found
    """
    # Filter supports below entry price
    valid_supports = [s for s in support_levels if s.level < entry_price]
    if not valid_supports:
        return None
    
    # Sort by level descending (highest first)
    sorted_supports = sorted(valid_supports, key=lambda s: s.level, reverse=True)
    
    if horizon == TradingHorizon.LONG_TERM and len(sorted_supports) > 1:
        # For long-term, target a lower support (second or third level)
        index = min(len(sorted_supports) - 1, 2)
        return sorted_supports[index]
    elif horizon == TradingHorizon.MEDIUM_TERM and len(sorted_supports) > 1:
        # For medium-term, target second support if available
        index = min(len(sorted_supports) - 1, 1)
        return sorted_supports[index]
    else:
        # For short-term or when only one level, use nearest
        return sorted_supports[0]


def calculate_take_profit(
    action: TradeAction,
    entry_price: float,
    stop_loss: float,
    support_levels: List[SupportResistance],
    resistance_levels: List[SupportResistance],
    horizon: TradingHorizon,
    config: TakeProfitConfig = None,
) -> float:
    """
    Calculate take-profit level for a trade.
    
    For BUY trades: Take-profit is set at resistance levels
    For SELL trades: Take-profit is set at support levels
    
    The take-profit is adjusted to ensure the risk-reward ratio is at least 1.5.
    
    Args:
        action: Trade action (BUY, STRONG_BUY, SELL, STRONG_SELL)
        entry_price: Entry price for the trade
        stop_loss: Stop-loss price level
        support_levels: List of support levels from technical analysis
        resistance_levels: List of resistance levels from technical analysis
        horizon: Trading horizon
        config: Take-profit configuration
        
    Returns:
        Take-profit price level
        
    Requirements:
    - 4.4: For BUY, take-profit at resistance levels
    - 4.5: For SELL, take-profit at support levels
    - 4.6: Risk-reward ratio must be >= 1.5 for actionable trades
    - 4.8: LONG_TERM targets higher resistance levels
    """
    if config is None:
        config = DEFAULT_CONFIG.take_profit
    
    buy_actions = {TradeAction.BUY, TradeAction.STRONG_BUY}
    sell_actions = {TradeAction.SELL, TradeAction.STRONG_SELL}
    
    if action in buy_actions:
        return _calculate_buy_take_profit(
            entry_price,
            stop_loss,
            resistance_levels,
            horizon,
            config,
        )
    elif action in sell_actions:
        return _calculate_sell_take_profit(
            entry_price,
            stop_loss,
            support_levels,
            horizon,
            config,
        )
    else:
        # For non-actionable trades, return a default take-profit
        return entry_price * (1 + config.default_reward_multiplier * 0.01)


def _calculate_buy_take_profit(
    entry_price: float,
    stop_loss: float,
    resistance_levels: List[SupportResistance],
    horizon: TradingHorizon,
    config: TakeProfitConfig,
) -> float:
    """
    Calculate take-profit for BUY trades.
    
    Take-profit is set at resistance levels, ensuring minimum risk-reward ratio.
    
    Args:
        entry_price: Entry price for the trade
        stop_loss: Stop-loss price level
        resistance_levels: List of resistance levels
        horizon: Trading horizon
        config: Take-profit configuration
        
    Returns:
        Take-profit price level (always above entry_price)
    """
    # Calculate risk (distance from entry to stop-loss)
    risk = entry_price - stop_loss
    
    # Calculate minimum reward needed for 1.5 risk-reward ratio
    min_reward = risk * config.min_risk_reward_ratio
    min_take_profit = entry_price + min_reward
    
    # Find appropriate resistance level
    target_resistance = _find_resistance_above(entry_price, resistance_levels, horizon)
    
    if target_resistance is not None:
        # Use resistance level if it meets minimum risk-reward
        if target_resistance.level >= min_take_profit:
            take_profit = target_resistance.level
            logger.debug(
                f"BUY take-profit: using resistance={target_resistance.level:.2f}, "
                f"rr_ratio={(take_profit - entry_price) / risk:.2f}"
            )
        else:
            # Resistance doesn't meet minimum, use calculated minimum
            take_profit = min_take_profit
            logger.debug(
                f"BUY take-profit: resistance too close, using min_rr, "
                f"take_profit={take_profit:.2f}"
            )
    else:
        # No resistance found, use default multiplier
        target_multiplier = _get_target_multiplier(horizon, config)
        default_reward = risk * config.default_reward_multiplier * target_multiplier
        take_profit = max(entry_price + default_reward, min_take_profit)
        logger.debug(
            f"BUY take-profit: no resistance found, using default, "
            f"take_profit={take_profit:.2f}"
        )
    
    return take_profit


def _calculate_sell_take_profit(
    entry_price: float,
    stop_loss: float,
    support_levels: List[SupportResistance],
    horizon: TradingHorizon,
    config: TakeProfitConfig,
) -> float:
    """
    Calculate take-profit for SELL trades.
    
    Take-profit is set at support levels, ensuring minimum risk-reward ratio.
    
    Args:
        entry_price: Entry price for the trade
        stop_loss: Stop-loss price level
        support_levels: List of support levels
        horizon: Trading horizon
        config: Take-profit configuration
        
    Returns:
        Take-profit price level (always below entry_price)
    """
    # Calculate risk (distance from entry to stop-loss)
    risk = stop_loss - entry_price
    
    # Calculate minimum reward needed for 1.5 risk-reward ratio
    min_reward = risk * config.min_risk_reward_ratio
    max_take_profit = entry_price - min_reward  # Max because we want lower price
    
    # Find appropriate support level
    target_support = _find_support_below(entry_price, support_levels, horizon)
    
    if target_support is not None:
        # Use support level if it meets minimum risk-reward
        if target_support.level <= max_take_profit:
            take_profit = target_support.level
            logger.debug(
                f"SELL take-profit: using support={target_support.level:.2f}, "
                f"rr_ratio={(entry_price - take_profit) / risk:.2f}"
            )
        else:
            # Support doesn't meet minimum, use calculated minimum
            take_profit = max_take_profit
            logger.debug(
                f"SELL take-profit: support too close, using min_rr, "
                f"take_profit={take_profit:.2f}"
            )
    else:
        # No support found, use default multiplier
        target_multiplier = _get_target_multiplier(horizon, config)
        default_reward = risk * config.default_reward_multiplier * target_multiplier
        take_profit = min(entry_price - default_reward, max_take_profit)
        logger.debug(
            f"SELL take-profit: no support found, using default, "
            f"take_profit={take_profit:.2f}"
        )
    
    # Ensure take-profit is positive
    if take_profit <= 0:
        # Fallback to a reasonable take-profit
        take_profit = entry_price * 0.5
        logger.warning(
            f"SELL take-profit would be negative, using fallback: {take_profit:.2f}"
        )
    
    return take_profit


def calculate_risk_reward_ratio(
    action: TradeAction,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
) -> float:
    """
    Calculate the risk-reward ratio for a trade.
    
    Args:
        action: Trade action
        entry_price: Entry price for the trade
        stop_loss: Stop-loss price level
        take_profit: Take-profit price level
        
    Returns:
        Risk-reward ratio (reward / risk)
    """
    buy_actions = {TradeAction.BUY, TradeAction.STRONG_BUY}
    sell_actions = {TradeAction.SELL, TradeAction.STRONG_SELL}
    
    if action in buy_actions:
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
    elif action in sell_actions:
        risk = stop_loss - entry_price
        reward = entry_price - take_profit
    else:
        return 0.0
    
    if risk <= 0:
        return 0.0
    
    return reward / risk


class TakeProfitCalculator:
    """
    Calculator for take-profit levels.
    
    Provides methods to calculate take-profit based on support/resistance
    levels with minimum risk-reward ratio enforcement.
    
    Requirements:
    - 4.4: For BUY, take-profit at resistance levels
    - 4.5: For SELL, take-profit at support levels
    - 4.6: Risk-reward ratio must be >= 1.5 for actionable trades
    - 4.8: LONG_TERM targets higher resistance levels
    """
    
    def __init__(self, config: TakeProfitConfig = None):
        """
        Initialize the take-profit calculator.
        
        Args:
            config: Take-profit configuration
        """
        self.config = config or DEFAULT_CONFIG.take_profit
    
    def calculate(
        self,
        action: TradeAction,
        entry_price: float,
        stop_loss: float,
        support_levels: List[SupportResistance],
        resistance_levels: List[SupportResistance],
        horizon: TradingHorizon,
    ) -> float:
        """
        Calculate take-profit level for a trade.
        
        Args:
            action: Trade action
            entry_price: Entry price for the trade
            stop_loss: Stop-loss price level
            support_levels: List of support levels
            resistance_levels: List of resistance levels
            horizon: Trading horizon
            
        Returns:
            Take-profit price level
        """
        return calculate_take_profit(
            action=action,
            entry_price=entry_price,
            stop_loss=stop_loss,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            horizon=horizon,
            config=self.config,
        )
    
    def validate_risk_reward(
        self,
        action: TradeAction,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> bool:
        """
        Validate that a trade meets the minimum risk-reward ratio.
        
        Args:
            action: Trade action
            entry_price: Entry price for the trade
            stop_loss: Stop-loss price level
            take_profit: Take-profit price level
            
        Returns:
            True if risk-reward ratio >= 1.5, False otherwise
        """
        rr_ratio = calculate_risk_reward_ratio(action, entry_price, stop_loss, take_profit)
        return rr_ratio >= self.config.min_risk_reward_ratio

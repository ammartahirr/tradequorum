"""
Confluence detection algorithm for the Technical Agent.

Implements:
- Detection of 6 independent technical factors
- Confluence score calculation (aligned factors / total checks)
- Volume spike detection (current > 1.5x 20-day average)

Requirements:
- 2.4: Check six independent factors for confluence
- 2.5: Score >= 0.7 requires at least 3 aligned factors
- 2.7: Volume spike when current volume > 1.5x 20-day average
"""

import logging
from typing import Optional

from src.models import OHLCV, ConfluenceResult, SupportResistance

from .indicators import (
    calculate_rsi,
    calculate_macd,
    calculate_bollinger_bands,
    calculate_moving_averages,
)
from .support_resistance import (
    get_active_levels,
    ACTIVE_LEVEL_THRESHOLD_PCT,
)

logger = logging.getLogger(__name__)


# --- Constants ---

# Total number of confluence factors to check
TOTAL_CONFLUENCE_FACTORS = 6

# RSI thresholds for oversold/overbought conditions
RSI_OVERSOLD_THRESHOLD = 30
RSI_OVERBOUGHT_THRESHOLD = 70

# Volume spike multiplier (Requirement 2.7: > 1.5x 20-day average)
VOLUME_SPIKE_MULTIPLIER = 1.5
VOLUME_AVERAGE_PERIOD = 20


# --- Volume Spike Detection ---

def detect_volume_spike(
    candles: list[OHLCV],
    multiplier: float = VOLUME_SPIKE_MULTIPLIER,
    period: int = VOLUME_AVERAGE_PERIOD,
) -> bool:
    """
    Detect if current volume is a spike compared to the average.
    
    A volume spike is detected when current volume exceeds the
    multiplier times the average volume over the specified period.
    
    Requirements:
    - 2.7: Volume spike when current volume > 1.5x 20-day average
    
    Args:
        candles: List of OHLCV candles sorted by timestamp ascending
        multiplier: Volume spike multiplier (default 1.5)
        period: Period for calculating average volume (default 20)
        
    Returns:
        True if volume spike detected, False otherwise
    """
    if len(candles) < period + 1:
        logger.debug(
            f"Not enough candles for volume spike detection: "
            f"need {period + 1}, got {len(candles)}"
        )
        return False
    
    # Calculate average volume over the period (excluding current candle)
    volume_period_candles = candles[-(period + 1):-1]
    avg_volume = sum(c.volume for c in volume_period_candles) / period
    
    # Get current volume
    current_volume = candles[-1].volume
    
    # Check for spike
    if avg_volume <= 0:
        return False
    
    is_spike = current_volume > (avg_volume * multiplier)
    
    if is_spike:
        logger.debug(
            f"Volume spike detected: current={current_volume}, "
            f"avg={avg_volume:.0f}, threshold={avg_volume * multiplier:.0f}"
        )
    
    return is_spike


# --- Confluence Detection ---

def detect_confluence(
    candles: list[OHLCV],
    support_levels: Optional[list[SupportResistance]] = None,
    resistance_levels: Optional[list[SupportResistance]] = None,
) -> ConfluenceResult:
    """
    Detect confluence of multiple technical factors.
    
    Expert logic: Don't trade on a single indicator — trade when multiple align.
    
    Checks 6 independent factors:
    1. RSI condition (oversold < 30 or overbought > 70)
    2. Price at support/resistance (within 2%)
    3. Volume spike (current > 1.5x 20-day average)
    4. MA alignment (golden cross or death cross)
    5. MACD signal (bullish or bearish)
    6. Bollinger position (below lower or above upper)
    
    Preconditions:
        - candles contains at least 200 data points (for 200-day MA)
        - candles are sorted by timestamp ascending
        - All candle prices are positive floats
    
    Postconditions:
        - confluence.score in [0.0, 1.0]
        - confluence.factors contains only verified factor names
        - score >= 0.7 requires at least 3 aligned factors
    
    Loop Invariants:
        - factors list only contains confirmed (True) indicators
        - score is recalculated as len(factors) / total_checks after each check
    
    Requirements:
    - 2.4: Check six independent factors for confluence
    - 2.5: Score >= 0.7 requires at least 3 aligned factors
    - 2.7: Volume spike when current volume > 1.5x 20-day average
    
    Args:
        candles: List of OHLCV candles sorted by timestamp ascending
        support_levels: Optional list of support levels (will be calculated if not provided)
        resistance_levels: Optional list of resistance levels (will be calculated if not provided)
        
    Returns:
        ConfluenceResult with score, factors, and description
        
    Raises:
        ValueError: If insufficient candles for calculation
    """
    # Validate minimum candle count
    if len(candles) < 200:
        raise ValueError(
            f"Need at least 200 candles for confluence detection, got: {len(candles)}"
        )
    
    factors: list[str] = []
    current_price = candles[-1].close
    
    # --- Check 1: RSI condition ---
    try:
        rsi = calculate_rsi(candles, period=14)
        if rsi <= RSI_OVERSOLD_THRESHOLD:
            factors.append("rsi_oversold")
            logger.debug(f"RSI oversold: {rsi:.2f}")
        elif rsi >= RSI_OVERBOUGHT_THRESHOLD:
            factors.append("rsi_overbought")
            logger.debug(f"RSI overbought: {rsi:.2f}")
    except Exception as e:
        logger.warning(f"RSI calculation failed: {e}")
    
    # --- Check 2: Price at support/resistance (within 2%) ---
    # Check support levels
    if support_levels:
        active_support = get_active_levels(
            support_levels, current_price, ACTIVE_LEVEL_THRESHOLD_PCT
        )
        if active_support:
            # Use the timeframe from the first active level
            timeframe = active_support[0].timeframe
            factors.append(f"{timeframe}_support")
            logger.debug(
                f"Price at support: {current_price:.2f} near "
                f"{active_support[0].level:.2f} ({timeframe})"
            )
    
    # Check resistance levels
    if resistance_levels:
        active_resistance = get_active_levels(
            resistance_levels, current_price, ACTIVE_LEVEL_THRESHOLD_PCT
        )
        if active_resistance:
            # Use the timeframe from the first active level
            timeframe = active_resistance[0].timeframe
            factors.append(f"{timeframe}_resistance")
            logger.debug(
                f"Price at resistance: {current_price:.2f} near "
                f"{active_resistance[0].level:.2f} ({timeframe})"
            )
    
    # --- Check 3: Volume spike ---
    if detect_volume_spike(candles):
        factors.append("volume_spike")
    
    # --- Check 4: Moving average alignment ---
    try:
        ma_result = calculate_moving_averages(candles)
        if ma_result.is_golden_cross:
            factors.append("golden_cross")
            logger.debug(f"Golden cross: MA50={ma_result.ma_50:.2f} > MA200={ma_result.ma_200:.2f}")
        elif ma_result.is_death_cross:
            factors.append("death_cross")
            logger.debug(f"Death cross: MA50={ma_result.ma_50:.2f} < MA200={ma_result.ma_200:.2f}")
    except Exception as e:
        logger.warning(f"Moving average calculation failed: {e}")
    
    # --- Check 5: MACD signal ---
    try:
        macd_result = calculate_macd(candles)
        if macd_result.is_bullish:
            factors.append("macd_bullish")
            logger.debug(
                f"MACD bullish: line={macd_result.macd_line:.4f} > "
                f"signal={macd_result.signal_line:.4f}"
            )
        elif macd_result.is_bearish:
            factors.append("macd_bearish")
            logger.debug(
                f"MACD bearish: line={macd_result.macd_line:.4f} < "
                f"signal={macd_result.signal_line:.4f}"
            )
    except Exception as e:
        logger.warning(f"MACD calculation failed: {e}")
    
    # --- Check 6: Bollinger Band position ---
    try:
        bollinger = calculate_bollinger_bands(candles)
        position = bollinger.get_position(current_price)
        if position == "below_lower":
            factors.append("below_bollinger_lower")
            logger.debug(
                f"Below Bollinger lower: price={current_price:.2f} < "
                f"lower={bollinger.lower_band:.2f}"
            )
        elif position == "above_upper":
            factors.append("above_bollinger_upper")
            logger.debug(
                f"Above Bollinger upper: price={current_price:.2f} > "
                f"upper={bollinger.upper_band:.2f}"
            )
    except Exception as e:
        logger.warning(f"Bollinger Bands calculation failed: {e}")
    
    # Calculate confluence score
    # Up to 13 factors can fire (S/R is per-timeframe), so clamp to the model's [0, 1] range
    score = min(1.0, len(factors) / TOTAL_CONFLUENCE_FACTORS)
    
    # Build description
    description = f"Confluence: {len(factors)}/{TOTAL_CONFLUENCE_FACTORS} factors aligned"
    
    logger.info(f"Confluence detection complete: score={score:.2f}, factors={factors}")
    
    return ConfluenceResult(
        score=score,
        factors=factors,
        description=description,
    )


def validate_confluence_score(result: ConfluenceResult) -> bool:
    """
    Validate that a confluence score meets the minimum factor requirement.
    
    Requirements:
    - 2.5: Score >= 0.7 requires at least 3 aligned factors
    
    Args:
        result: ConfluenceResult to validate
        
    Returns:
        True if the score is valid (either < 0.7 or has >= 3 factors)
    """
    if result.score >= 0.7:
        # Score >= 0.7 requires at least 3 factors
        # With 6 total factors, 3/6 = 0.5, so score >= 0.7 means >= 5 factors
        # But requirement says "at least 3 aligned factors" for score >= 0.7
        # This means: if score >= 0.7, we must have >= 3 factors
        return len(result.factors) >= 3
    return True


def get_confluence_summary(result: ConfluenceResult) -> dict:
    """
    Get a summary of the confluence result for reporting.
    
    Args:
        result: ConfluenceResult to summarize
        
    Returns:
        Dictionary with summary information
    """
    # Categorize factors
    bullish_factors = [
        f for f in result.factors
        if f in ("rsi_oversold", "golden_cross", "macd_bullish", "below_bollinger_lower")
        or f.endswith("_support")
    ]
    
    bearish_factors = [
        f for f in result.factors
        if f in ("rsi_overbought", "death_cross", "macd_bearish", "above_bollinger_upper")
        or f.endswith("_resistance")
    ]
    
    neutral_factors = [
        f for f in result.factors
        if f not in bullish_factors and f not in bearish_factors
    ]
    
    return {
        "score": result.score,
        "total_factors": len(result.factors),
        "bullish_factors": bullish_factors,
        "bearish_factors": bearish_factors,
        "neutral_factors": neutral_factors,
        "is_high_confluence": result.score >= 0.7,
        "is_valid": validate_confluence_score(result),
    }

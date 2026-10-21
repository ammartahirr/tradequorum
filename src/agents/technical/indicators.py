"""
Technical indicator calculations for the Technical Agent.

Implements:
- RSI (14-period) with Wilder's smoothing
- MACD (12, 26, 9 periods)
- Bollinger Bands (20-period SMA, 2 standard deviations)
- 50-day and 200-day moving averages

Requirements:
- 2.1: Calculate RSI, MACD, Bollinger Bands, 50-day and 200-day moving averages
- 2.2: RSI must produce values in range [0, 100] for all valid candle sequences
"""

import logging
import math
from dataclasses import dataclass
from typing import Optional

from src.models import OHLCV

logger = logging.getLogger(__name__)


class IndicatorCalculationError(Exception):
    """Raised when an indicator calculation fails or produces invalid results."""
    pass


# --- RSI Calculation ---

def calculate_rsi(candles: list[OHLCV], period: int = 14) -> float:
    """
    Calculate the Relative Strength Index (RSI) using Wilder's smoothing method.
    
    Preconditions:
        - len(candles) >= period + 1
        - All candle.close > 0
        - period > 0
    
    Postconditions:
        - 0 <= rsi <= 100
        - rsi < 30 indicates oversold
        - rsi > 70 indicates overbought
        - Uses Wilder's smoothing method
    
    Loop Invariants:
        - avg_gain >= 0 and avg_loss >= 0 at each iteration
        - Running averages use previous period's smoothed values
    
    Requirements:
        - 2.1: Calculate RSI (14-period)
        - 2.2: RSI must produce values in range [0, 100]
    
    Args:
        candles: List of OHLCV candles sorted by timestamp ascending
        period: RSI period (default 14)
        
    Returns:
        RSI value in range [0, 100]
        
    Raises:
        ValueError: If preconditions are not met
        IndicatorCalculationError: If calculation produces invalid result
    """
    # Validate preconditions
    if period <= 0:
        raise ValueError(f"Period must be positive, got: {period}")
    
    min_candles = period + 1
    if len(candles) < min_candles:
        raise ValueError(
            f"Need at least {min_candles} candles for RSI calculation with period {period}, "
            f"got: {len(candles)}"
        )
    
    # Validate all close prices are positive
    for i, candle in enumerate(candles):
        if candle.close <= 0:
            raise ValueError(f"Candle at index {i} has non-positive close price: {candle.close}")
    
    # Calculate price changes
    changes = []
    for i in range(1, len(candles)):
        change = candles[i].close - candles[i - 1].close
        changes.append(change)
    
    # Separate gains and losses
    gains = [max(0, change) for change in changes]
    losses = [abs(min(0, change)) for change in changes]
    
    # Calculate initial average gain and loss (simple average for first period)
    initial_gains = gains[:period]
    initial_losses = losses[:period]
    
    avg_gain = sum(initial_gains) / period
    avg_loss = sum(initial_losses) / period
    
    # Loop invariant: avg_gain >= 0 and avg_loss >= 0
    assert avg_gain >= 0, f"avg_gain must be non-negative: {avg_gain}"
    assert avg_loss >= 0, f"avg_loss must be non-negative: {avg_loss}"
    
    # Apply Wilder's smoothing for remaining periods
    for i in range(period, len(changes)):
        current_gain = gains[i]
        current_loss = losses[i]
        
        # Wilder's smoothing: new_avg = (prev_avg * (period - 1) + current_value) / period
        avg_gain = (avg_gain * (period - 1) + current_gain) / period
        avg_loss = (avg_loss * (period - 1) + current_loss) / period
        
        # Loop invariant check
        assert avg_gain >= 0, f"avg_gain must be non-negative: {avg_gain}"
        assert avg_loss >= 0, f"avg_loss must be non-negative: {avg_loss}"
    
    # Calculate RSI
    if avg_loss == 0:
        # No losses means RSI = 100 (maximum strength)
        rsi = 100.0
    elif avg_gain == 0:
        # No gains means RSI = 0 (minimum strength)
        rsi = 0.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
    
    # Validate postcondition: RSI must be in [0, 100]
    if not (0 <= rsi <= 100):
        raise IndicatorCalculationError(
            f"RSI calculation produced invalid value: {rsi}. "
            f"RSI must be in range [0, 100]. "
            f"avg_gain={avg_gain}, avg_loss={avg_loss}"
        )
    
    logger.debug(f"RSI calculated: {rsi:.2f} (avg_gain={avg_gain:.4f}, avg_loss={avg_loss:.4f})")
    
    return rsi


# --- MACD Calculation ---

@dataclass
class MACDResult:
    """Result of MACD calculation."""
    macd_line: float      # MACD line (fast EMA - slow EMA)
    signal_line: float    # Signal line (EMA of MACD line)
    histogram: float      # MACD histogram (MACD line - signal line)
    
    @property
    def is_bullish(self) -> bool:
        """Returns True if MACD is above signal line (bullish)."""
        return self.macd_line > self.signal_line
    
    @property
    def is_bearish(self) -> bool:
        """Returns True if MACD is below signal line (bearish)."""
        return self.macd_line < self.signal_line


def _calculate_ema(values: list[float], period: int) -> list[float]:
    """
    Calculate Exponential Moving Average (EMA).
    
    Args:
        values: List of values
        period: EMA period
        
    Returns:
        List of EMA values (same length as input, with initial values as SMA)
    """
    if len(values) < period:
        raise ValueError(f"Need at least {period} values for EMA, got: {len(values)}")
    
    ema_values = []
    multiplier = 2 / (period + 1)
    
    # First EMA value is SMA of first 'period' values
    sma = sum(values[:period]) / period
    ema_values.extend([sma] * period)  # Fill initial values with SMA
    
    # Calculate EMA for remaining values
    ema = sma
    for i in range(period, len(values)):
        ema = (values[i] - ema) * multiplier + ema
        ema_values.append(ema)
    
    return ema_values


def calculate_macd(
    candles: list[OHLCV],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> MACDResult:
    """
    Calculate MACD (Moving Average Convergence Divergence).
    
    MACD uses standard periods: 12, 26, 9
    - Fast EMA: 12-period EMA of close prices
    - Slow EMA: 26-period EMA of close prices
    - MACD Line: Fast EMA - Slow EMA
    - Signal Line: 9-period EMA of MACD Line
    - Histogram: MACD Line - Signal Line
    
    Requirements:
        - 2.1: Implement MACD calculation
    
    Args:
        candles: List of OHLCV candles sorted by timestamp ascending
        fast_period: Fast EMA period (default 12)
        slow_period: Slow EMA period (default 26)
        signal_period: Signal line EMA period (default 9)
        
    Returns:
        MACDResult with macd_line, signal_line, and histogram
        
    Raises:
        ValueError: If insufficient candles for calculation
    """
    # Validate parameters
    if fast_period <= 0 or slow_period <= 0 or signal_period <= 0:
        raise ValueError("All periods must be positive")
    
    if fast_period >= slow_period:
        raise ValueError(f"Fast period ({fast_period}) must be less than slow period ({slow_period})")
    
    # Need enough candles for slow EMA + signal EMA
    min_candles = slow_period + signal_period - 1
    if len(candles) < min_candles:
        raise ValueError(
            f"Need at least {min_candles} candles for MACD calculation, got: {len(candles)}"
        )
    
    # Extract close prices
    closes = [candle.close for candle in candles]
    
    # Calculate EMAs
    fast_ema = _calculate_ema(closes, fast_period)
    slow_ema = _calculate_ema(closes, slow_period)
    
    # Calculate MACD line (fast EMA - slow EMA)
    # Start from slow_period - 1 since that's when slow EMA becomes valid
    macd_line_values = []
    for i in range(slow_period - 1, len(closes)):
        macd_value = fast_ema[i] - slow_ema[i]
        macd_line_values.append(macd_value)
    
    # Calculate signal line (EMA of MACD line)
    if len(macd_line_values) < signal_period:
        raise ValueError(
            f"Not enough MACD values ({len(macd_line_values)}) for signal line calculation "
            f"(need {signal_period})"
        )
    
    signal_ema = _calculate_ema(macd_line_values, signal_period)
    
    # Get latest values
    macd_line = macd_line_values[-1]
    signal_line = signal_ema[-1]
    histogram = macd_line - signal_line
    
    logger.debug(
        f"MACD calculated: line={macd_line:.4f}, signal={signal_line:.4f}, "
        f"histogram={histogram:.4f}"
    )
    
    return MACDResult(
        macd_line=macd_line,
        signal_line=signal_line,
        histogram=histogram,
    )


# --- Bollinger Bands Calculation ---

@dataclass
class BollingerBandsResult:
    """Result of Bollinger Bands calculation."""
    upper_band: float     # Upper band (SMA + 2 * std_dev)
    middle_band: float    # Middle band (SMA)
    lower_band: float     # Lower band (SMA - 2 * std_dev)
    bandwidth: float      # Band width percentage
    
    @property
    def is_price_above_upper(self) -> bool:
        """Check if current price is above upper band (requires price comparison)."""
        # This is a helper property - actual comparison done externally
        return False
    
    def get_position(self, price: float) -> str:
        """
        Get price position relative to bands.
        
        Args:
            price: Current price
            
        Returns:
            "above_upper", "below_lower", or "within_bands"
        """
        if price >= self.upper_band:
            return "above_upper"
        elif price <= self.lower_band:
            return "below_lower"
        else:
            return "within_bands"


def calculate_bollinger_bands(
    candles: list[OHLCV],
    period: int = 20,
    num_std_dev: float = 2.0,
) -> BollingerBandsResult:
    """
    Calculate Bollinger Bands.
    
    Bollinger Bands consist of:
    - Middle Band: 20-period Simple Moving Average (SMA)
    - Upper Band: Middle Band + (2 * standard deviation)
    - Lower Band: Middle Band - (2 * standard deviation)
    
    Requirements:
        - 2.1: Implement Bollinger Bands calculation
    
    Args:
        candles: List of OHLCV candles sorted by timestamp ascending
        period: SMA period (default 20)
        num_std_dev: Number of standard deviations (default 2.0)
        
    Returns:
        BollingerBandsResult with upper, middle, lower bands and bandwidth
        
    Raises:
        ValueError: If insufficient candles for calculation
    """
    if period <= 0:
        raise ValueError(f"Period must be positive, got: {period}")
    
    if num_std_dev <= 0:
        raise ValueError(f"Number of standard deviations must be positive, got: {num_std_dev}")
    
    if len(candles) < period:
        raise ValueError(
            f"Need at least {period} candles for Bollinger Bands calculation, "
            f"got: {len(candles)}"
        )
    
    # Use the most recent 'period' candles
    recent_candles = candles[-period:]
    closes = [candle.close for candle in recent_candles]
    
    # Calculate SMA (middle band)
    middle_band = sum(closes) / period
    
    # Calculate standard deviation
    variance = sum((close - middle_band) ** 2 for close in closes) / period
    std_dev = math.sqrt(variance)
    
    # Calculate upper and lower bands
    upper_band = middle_band + (num_std_dev * std_dev)
    lower_band = middle_band - (num_std_dev * std_dev)
    
    # Calculate bandwidth percentage
    bandwidth = ((upper_band - lower_band) / middle_band) * 100 if middle_band > 0 else 0
    
    logger.debug(
        f"Bollinger Bands calculated: upper={upper_band:.4f}, middle={middle_band:.4f}, "
        f"lower={lower_band:.4f}, bandwidth={bandwidth:.2f}%"
    )
    
    return BollingerBandsResult(
        upper_band=upper_band,
        middle_band=middle_band,
        lower_band=lower_band,
        bandwidth=bandwidth,
    )


# --- Moving Average Calculations ---

def calculate_sma(candles: list[OHLCV], period: int) -> float:
    """
    Calculate Simple Moving Average (SMA).
    
    Args:
        candles: List of OHLCV candles sorted by timestamp ascending
        period: SMA period
        
    Returns:
        SMA value
        
    Raises:
        ValueError: If insufficient candles for calculation
    """
    if period <= 0:
        raise ValueError(f"Period must be positive, got: {period}")
    
    if len(candles) < period:
        raise ValueError(
            f"Need at least {period} candles for SMA calculation, got: {len(candles)}"
        )
    
    # Use the most recent 'period' candles
    recent_closes = [candle.close for candle in candles[-period:]]
    sma = sum(recent_closes) / period
    
    return sma


def calculate_ema(candles: list[OHLCV], period: int) -> float:
    """
    Calculate Exponential Moving Average (EMA).
    
    Args:
        candles: List of OHLCV candles sorted by timestamp ascending
        period: EMA period
        
    Returns:
        Latest EMA value
        
    Raises:
        ValueError: If insufficient candles for calculation
    """
    if period <= 0:
        raise ValueError(f"Period must be positive, got: {period}")
    
    if len(candles) < period:
        raise ValueError(
            f"Need at least {period} candles for EMA calculation, got: {len(candles)}"
        )
    
    closes = [candle.close for candle in candles]
    ema_values = _calculate_ema(closes, period)
    
    return ema_values[-1]


@dataclass
class MovingAveragesResult:
    """Result of moving average calculations."""
    ma_50: float          # 50-day moving average
    ma_200: float         # 200-day moving average
    
    @property
    def is_golden_cross(self) -> bool:
        """Returns True if 50-day MA is above 200-day MA (bullish)."""
        return self.ma_50 > self.ma_200
    
    @property
    def is_death_cross(self) -> bool:
        """Returns True if 50-day MA is below 200-day MA (bearish)."""
        return self.ma_50 < self.ma_200
    
    @property
    def alignment(self) -> str:
        """Returns the MA alignment status."""
        if self.is_golden_cross:
            return "golden_cross"
        elif self.is_death_cross:
            return "death_cross"
        else:
            return "neutral"


def calculate_moving_averages(candles: list[OHLCV]) -> MovingAveragesResult:
    """
    Calculate 50-day and 200-day moving averages.
    
    Requirements:
        - 2.1: Implement 50-day and 200-day moving average calculations
    
    Args:
        candles: List of OHLCV candles sorted by timestamp ascending
                 (must have at least 200 candles for full calculation)
        
    Returns:
        MovingAveragesResult with ma_50 and ma_200
        
    Raises:
        ValueError: If insufficient candles for calculation
    """
    if len(candles) < 200:
        raise ValueError(
            f"Need at least 200 candles for moving average calculation, got: {len(candles)}"
        )
    
    ma_50 = calculate_sma(candles, 50)
    ma_200 = calculate_sma(candles, 200)
    
    logger.debug(f"Moving averages calculated: MA50={ma_50:.4f}, MA200={ma_200:.4f}")
    
    return MovingAveragesResult(ma_50=ma_50, ma_200=ma_200)


# --- Combined Indicator Calculation ---

@dataclass
class TechnicalIndicators:
    """Combined result of all technical indicator calculations."""
    rsi: float
    macd: MACDResult
    bollinger_bands: BollingerBandsResult
    moving_averages: MovingAveragesResult
    
    @property
    def is_oversold(self) -> bool:
        """Returns True if RSI indicates oversold condition (< 30)."""
        return self.rsi < 30
    
    @property
    def is_overbought(self) -> bool:
        """Returns True if RSI indicates overbought condition (> 70)."""
        return self.rsi > 70


def calculate_all_indicators(
    candles: list[OHLCV],
    rsi_period: int = 14,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    bollinger_period: int = 20,
    bollinger_std_dev: float = 2.0,
) -> TechnicalIndicators:
    """
    Calculate all technical indicators for a given set of candles.
    
    This is a convenience function that calculates RSI, MACD, Bollinger Bands,
    and moving averages in a single call.
    
    Requirements:
        - 2.1: Calculate RSI, MACD, Bollinger Bands, 50-day and 200-day moving averages
        - 2.2: RSI must produce values in range [0, 100]
    
    Args:
        candles: List of OHLCV candles sorted by timestamp ascending
                 (must have at least 200 candles for full calculation)
        rsi_period: RSI period (default 14)
        macd_fast: MACD fast EMA period (default 12)
        macd_slow: MACD slow EMA period (default 26)
        macd_signal: MACD signal line period (default 9)
        bollinger_period: Bollinger Bands SMA period (default 20)
        bollinger_std_dev: Bollinger Bands standard deviations (default 2.0)
        
    Returns:
        TechnicalIndicators with all calculated values
        
    Raises:
        ValueError: If insufficient candles for any calculation
        IndicatorCalculationError: If any calculation produces invalid results
    """
    # Validate minimum candle count (200 for moving averages)
    if len(candles) < 200:
        raise ValueError(
            f"Need at least 200 candles for full indicator calculation, got: {len(candles)}"
        )
    
    # Calculate all indicators
    rsi = calculate_rsi(candles, rsi_period)
    macd = calculate_macd(candles, macd_fast, macd_slow, macd_signal)
    bollinger = calculate_bollinger_bands(candles, bollinger_period, bollinger_std_dev)
    moving_avgs = calculate_moving_averages(candles)
    
    return TechnicalIndicators(
        rsi=rsi,
        macd=macd,
        bollinger_bands=bollinger,
        moving_averages=moving_avgs,
    )

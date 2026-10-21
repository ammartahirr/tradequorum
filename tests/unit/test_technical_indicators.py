"""
Unit tests for technical indicator calculations.

Tests for:
- RSI calculation with Wilder's smoothing
- MACD calculation
- Bollinger Bands calculation
- 50-day and 200-day moving average calculations

Requirements:
- 2.1: Calculate RSI, MACD, Bollinger Bands, 50-day and 200-day moving averages
- 2.2: RSI must produce values in range [0, 100]
"""

import math
from datetime import datetime, timedelta, timezone

import pytest

from src.models import OHLCV
from src.agents.technical.indicators import (
    calculate_rsi,
    calculate_macd,
    calculate_bollinger_bands,
    calculate_sma,
    calculate_ema,
    calculate_moving_averages,
    calculate_all_indicators,
    MACDResult,
    BollingerBandsResult,
    MovingAveragesResult,
    TechnicalIndicators,
    IndicatorCalculationError,
)


# --- Test Fixtures ---

def create_candles(
    prices: list[float],
    start_time: datetime = None,
    interval_minutes: int = 1440,  # Daily by default
) -> list[OHLCV]:
    """
    Create a list of OHLCV candles from close prices.
    
    For simplicity, sets open=high=low=close for each candle.
    """
    if start_time is None:
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    
    candles = []
    for i, price in enumerate(prices):
        timestamp = start_time + timedelta(minutes=interval_minutes * i)
        candles.append(OHLCV(
            timestamp=timestamp,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=1000000,
        ))
    return candles


def create_trending_candles(
    start_price: float,
    num_candles: int,
    trend: str = "up",
    volatility: float = 0.01,
) -> list[OHLCV]:
    """
    Create candles with a trending pattern.
    
    Args:
        start_price: Starting price
        num_candles: Number of candles to generate
        trend: "up", "down", or "sideways"
        volatility: Price change percentage per candle
    """
    prices = [start_price]
    for i in range(1, num_candles):
        if trend == "up":
            change = prices[-1] * volatility
        elif trend == "down":
            change = -prices[-1] * volatility
        else:  # sideways
            change = 0
        prices.append(prices[-1] + change)
    
    return create_candles(prices)


# --- RSI Tests ---

class TestCalculateRSI:
    """Tests for RSI calculation."""
    
    def test_rsi_with_all_gains(self):
        """
        Test RSI when all price changes are gains.
        
        When there are only gains and no losses, RSI should be 100.
        """
        # Create 15 candles with increasing prices (14 gains)
        prices = [100 + i for i in range(16)]  # 100, 101, 102, ..., 115
        candles = create_candles(prices)
        
        rsi = calculate_rsi(candles, period=14)
        
        assert rsi == 100.0, f"RSI with all gains should be 100, got {rsi}"
    
    def test_rsi_with_all_losses(self):
        """
        Test RSI when all price changes are losses.
        
        When there are only losses and no gains, RSI should be 0.
        """
        # Create 15 candles with decreasing prices (14 losses)
        prices = [115 - i for i in range(16)]  # 115, 114, 113, ..., 100
        candles = create_candles(prices)
        
        rsi = calculate_rsi(candles, period=14)
        
        assert rsi == 0.0, f"RSI with all losses should be 0, got {rsi}"
    
    def test_rsi_with_equal_gains_and_losses(self):
        """
        Test RSI when gains equal losses.
        
        When average gain equals average loss, RSI should be 50.
        """
        # Create alternating up/down pattern
        prices = [100]
        for i in range(15):
            if i % 2 == 0:
                prices.append(prices[-1] + 1)  # Gain
            else:
                prices.append(prices[-1] - 1)  # Loss
        
        candles = create_candles(prices)
        rsi = calculate_rsi(candles, period=14)
        
        # RSI should be close to 50 (may not be exactly 50 due to Wilder's smoothing)
        assert 45 <= rsi <= 55, f"RSI with equal gains/losses should be ~50, got {rsi}"
    
    def test_rsi_bounds_always_valid(self):
        """
        Test that RSI is always in [0, 100] range.
        
        **Validates: Requirements 2.2**
        """
        # Test with various price patterns
        test_cases = [
            [100 + i for i in range(20)],  # Uptrend
            [120 - i for i in range(20)],  # Downtrend
            [100, 105, 102, 108, 103, 110, 105, 112, 107, 115, 110, 118, 113, 120, 115, 122],  # Volatile up
            [100, 95, 98, 92, 97, 90, 95, 88, 93, 86, 91, 84, 89, 82, 87, 80],  # Volatile down
        ]
        
        for prices in test_cases:
            candles = create_candles(prices)
            rsi = calculate_rsi(candles, period=14)
            
            assert 0 <= rsi <= 100, f"RSI must be in [0, 100], got {rsi}"
    
    def test_rsi_oversold_condition(self):
        """
        Test that RSI < 30 indicates oversold.
        
        **Validates: Requirements 2.2**
        """
        # Create strong downtrend
        prices = [100 - i * 2 for i in range(20)]  # Strong decline
        candles = create_candles(prices)
        
        rsi = calculate_rsi(candles, period=14)
        
        assert rsi < 30, f"Strong downtrend should produce oversold RSI (<30), got {rsi}"
    
    def test_rsi_overbought_condition(self):
        """
        Test that RSI > 70 indicates overbought.
        
        **Validates: Requirements 2.2**
        """
        # Create strong uptrend
        prices = [100 + i * 2 for i in range(20)]  # Strong rise
        candles = create_candles(prices)
        
        rsi = calculate_rsi(candles, period=14)
        
        assert rsi > 70, f"Strong uptrend should produce overbought RSI (>70), got {rsi}"
    
    def test_rsi_insufficient_candles_raises_error(self):
        """Test that RSI raises error with insufficient candles."""
        prices = [100 + i for i in range(10)]  # Only 10 candles
        candles = create_candles(prices)
        
        with pytest.raises(ValueError, match="Need at least"):
            calculate_rsi(candles, period=14)
    
    def test_rsi_invalid_period_raises_error(self):
        """Test that RSI raises error with invalid period."""
        prices = [100 + i for i in range(20)]
        candles = create_candles(prices)
        
        with pytest.raises(ValueError, match="Period must be positive"):
            calculate_rsi(candles, period=0)
        
        with pytest.raises(ValueError, match="Period must be positive"):
            calculate_rsi(candles, period=-5)
    
    def test_rsi_custom_period(self):
        """Test RSI with custom period."""
        prices = [100 + i for i in range(30)]
        candles = create_candles(prices)
        
        rsi_7 = calculate_rsi(candles, period=7)
        rsi_21 = calculate_rsi(candles, period=21)
        
        # Both should be valid
        assert 0 <= rsi_7 <= 100
        assert 0 <= rsi_21 <= 100
        
        # Shorter period should be more sensitive (higher in uptrend)
        assert rsi_7 >= rsi_21, "Shorter period RSI should be more sensitive"


# --- MACD Tests ---

class TestCalculateMACD:
    """Tests for MACD calculation."""
    
    def test_macd_basic_calculation(self):
        """Test basic MACD calculation."""
        # Create enough candles for MACD (26 + 9 - 1 = 34 minimum)
        prices = [100 + i * 0.5 for i in range(50)]  # Uptrend
        candles = create_candles(prices)
        
        result = calculate_macd(candles)
        
        assert isinstance(result, MACDResult)
        assert isinstance(result.macd_line, float)
        assert isinstance(result.signal_line, float)
        assert isinstance(result.histogram, float)
    
    def test_macd_bullish_in_uptrend(self):
        """Test that MACD is bullish in uptrend."""
        # Create accelerating uptrend where fast EMA pulls ahead of slow EMA
        # Start flat, then accelerate upward to create positive histogram
        prices = [100] * 30 + [100 + (i ** 1.5) for i in range(1, 21)]
        candles = create_candles(prices)
        
        result = calculate_macd(candles)
        
        assert result.macd_line > 0, "MACD line should be positive in uptrend"
        # In accelerating uptrend, MACD line should be above signal line
        assert result.histogram > 0, "Histogram should be positive in accelerating uptrend"
        assert result.is_bullish, "MACD should be bullish in uptrend"
    
    def test_macd_bearish_in_downtrend(self):
        """Test that MACD is bearish in downtrend."""
        # Create accelerating downtrend where fast EMA drops below slow EMA
        # Start flat, then accelerate downward to create negative histogram
        prices = [200] * 30 + [200 - (i ** 1.5) for i in range(1, 21)]
        candles = create_candles(prices)
        
        result = calculate_macd(candles)
        
        assert result.macd_line < 0, "MACD line should be negative in downtrend"
        # In accelerating downtrend, MACD line should be below signal line
        assert result.histogram < 0, "Histogram should be negative in accelerating downtrend"
        assert result.is_bearish, "MACD should be bearish in downtrend"
    
    def test_macd_histogram_calculation(self):
        """Test that histogram equals MACD line minus signal line."""
        prices = [100 + i for i in range(50)]
        candles = create_candles(prices)
        
        result = calculate_macd(candles)
        
        expected_histogram = result.macd_line - result.signal_line
        assert abs(result.histogram - expected_histogram) < 0.0001, \
            f"Histogram should be MACD - Signal: expected {expected_histogram}, got {result.histogram}"
    
    def test_macd_insufficient_candles_raises_error(self):
        """Test that MACD raises error with insufficient candles."""
        prices = [100 + i for i in range(30)]  # Not enough for 26 + 9 - 1 = 34
        candles = create_candles(prices)
        
        with pytest.raises(ValueError, match="Need at least"):
            calculate_macd(candles)
    
    def test_macd_custom_periods(self):
        """Test MACD with custom periods."""
        # Create accelerating uptrend for positive histogram
        prices = [100] * 50 + [100 + (i ** 1.5) for i in range(1, 51)]
        candles = create_candles(prices)
        
        result = calculate_macd(candles, fast_period=8, slow_period=17, signal_period=9)
        
        assert isinstance(result, MACDResult)
        assert result.macd_line > 0, "MACD line should be positive in uptrend"


# --- Bollinger Bands Tests ---

class TestCalculateBollingerBands:
    """Tests for Bollinger Bands calculation."""
    
    def test_bollinger_basic_calculation(self):
        """Test basic Bollinger Bands calculation."""
        prices = [100 + i * 0.1 for i in range(25)]
        candles = create_candles(prices)
        
        result = calculate_bollinger_bands(candles)
        
        assert isinstance(result, BollingerBandsResult)
        assert result.upper_band > result.middle_band
        assert result.middle_band > result.lower_band
    
    def test_bollinger_middle_band_is_sma(self):
        """Test that middle band equals 20-period SMA."""
        prices = [100 + i for i in range(25)]
        candles = create_candles(prices)
        
        result = calculate_bollinger_bands(candles, period=20)
        
        # Calculate expected SMA manually
        expected_sma = sum(prices[-20:]) / 20
        
        assert abs(result.middle_band - expected_sma) < 0.0001, \
            f"Middle band should be SMA: expected {expected_sma}, got {result.middle_band}"
    
    def test_bollinger_bands_symmetry(self):
        """Test that upper and lower bands are symmetric around middle."""
        prices = [100 + i for i in range(25)]
        candles = create_candles(prices)
        
        result = calculate_bollinger_bands(candles)
        
        upper_distance = result.upper_band - result.middle_band
        lower_distance = result.middle_band - result.lower_band
        
        assert abs(upper_distance - lower_distance) < 0.0001, \
            "Bands should be symmetric around middle"
    
    def test_bollinger_position_detection(self):
        """Test price position detection relative to bands."""
        # Create prices with some variance so bands have width
        prices = [100 + (i % 5) - 2 for i in range(25)]  # Oscillates 98-102
        candles = create_candles(prices)
        
        result = calculate_bollinger_bands(candles)
        
        # With variance, bands should have width
        assert result.upper_band > result.middle_band
        assert result.lower_band < result.middle_band
        
        # Test position detection
        assert result.get_position(result.middle_band) == "within_bands"
        assert result.get_position(result.upper_band + 1) == "above_upper"
        assert result.get_position(result.lower_band - 1) == "below_lower"
    
    def test_bollinger_bandwidth_calculation(self):
        """Test bandwidth percentage calculation."""
        prices = [100 + i for i in range(25)]
        candles = create_candles(prices)
        
        result = calculate_bollinger_bands(candles)
        
        expected_bandwidth = ((result.upper_band - result.lower_band) / result.middle_band) * 100
        
        assert abs(result.bandwidth - expected_bandwidth) < 0.0001, \
            f"Bandwidth calculation incorrect: expected {expected_bandwidth}, got {result.bandwidth}"
    
    def test_bollinger_insufficient_candles_raises_error(self):
        """Test that Bollinger Bands raises error with insufficient candles."""
        prices = [100 + i for i in range(15)]  # Not enough for 20-period
        candles = create_candles(prices)
        
        with pytest.raises(ValueError, match="Need at least"):
            calculate_bollinger_bands(candles, period=20)
    
    def test_bollinger_custom_parameters(self):
        """Test Bollinger Bands with custom parameters."""
        prices = [100 + i for i in range(30)]
        candles = create_candles(prices)
        
        result_default = calculate_bollinger_bands(candles, period=20, num_std_dev=2.0)
        result_wider = calculate_bollinger_bands(candles, period=20, num_std_dev=3.0)
        
        # Wider bands with more standard deviations
        assert result_wider.upper_band > result_default.upper_band
        assert result_wider.lower_band < result_default.lower_band


# --- Moving Average Tests ---

class TestCalculateMovingAverages:
    """Tests for moving average calculations."""
    
    def test_sma_calculation(self):
        """Test SMA calculation."""
        prices = list(range(1, 11))  # 1, 2, 3, ..., 10
        candles = create_candles(prices)
        
        sma = calculate_sma(candles, period=5)
        
        # SMA of last 5 values: (6+7+8+9+10)/5 = 8
        expected = 8.0
        assert abs(sma - expected) < 0.0001, f"SMA incorrect: expected {expected}, got {sma}"
    
    def test_ema_calculation(self):
        """Test EMA calculation."""
        prices = [100 + i for i in range(20)]
        candles = create_candles(prices)
        
        ema = calculate_ema(candles, period=10)
        
        # EMA should be a valid number
        assert isinstance(ema, float)
        assert ema > 0
    
    def test_moving_averages_50_200(self):
        """Test 50-day and 200-day moving average calculation."""
        prices = [100 + i * 0.1 for i in range(250)]
        candles = create_candles(prices)
        
        result = calculate_moving_averages(candles)
        
        assert isinstance(result, MovingAveragesResult)
        assert result.ma_50 > 0
        assert result.ma_200 > 0
    
    def test_golden_cross_detection(self):
        """Test golden cross detection (50 MA > 200 MA)."""
        # Create uptrend where recent prices are higher
        prices = [100 + i * 0.5 for i in range(250)]
        candles = create_candles(prices)
        
        result = calculate_moving_averages(candles)
        
        # In uptrend, 50 MA should be above 200 MA
        assert result.is_golden_cross, "Should detect golden cross in uptrend"
        assert result.alignment == "golden_cross"
    
    def test_death_cross_detection(self):
        """Test death cross detection (50 MA < 200 MA)."""
        # Create downtrend where recent prices are lower
        prices = [200 - i * 0.5 for i in range(250)]
        candles = create_candles(prices)
        
        result = calculate_moving_averages(candles)
        
        # In downtrend, 50 MA should be below 200 MA
        assert result.is_death_cross, "Should detect death cross in downtrend"
        assert result.alignment == "death_cross"
    
    def test_moving_averages_insufficient_candles_raises_error(self):
        """Test that moving averages raises error with insufficient candles."""
        prices = [100 + i for i in range(150)]  # Not enough for 200-day
        candles = create_candles(prices)
        
        with pytest.raises(ValueError, match="Need at least 200"):
            calculate_moving_averages(candles)


# --- Combined Indicators Tests ---

class TestCalculateAllIndicators:
    """Tests for combined indicator calculation."""
    
    def test_calculate_all_indicators(self):
        """Test calculating all indicators at once."""
        prices = [100 + i * 0.5 for i in range(250)]
        candles = create_candles(prices)
        
        result = calculate_all_indicators(candles)
        
        assert isinstance(result, TechnicalIndicators)
        assert 0 <= result.rsi <= 100
        assert isinstance(result.macd, MACDResult)
        assert isinstance(result.bollinger_bands, BollingerBandsResult)
        assert isinstance(result.moving_averages, MovingAveragesResult)
    
    def test_oversold_detection(self):
        """Test oversold condition detection."""
        # Create strong downtrend with prices staying positive
        prices = [500 - i * 1.5 for i in range(250)]  # Start high, decline steadily
        # Ensure all prices are positive
        prices = [max(p, 10) for p in prices]
        candles = create_candles(prices)
        
        result = calculate_all_indicators(candles)
        
        assert result.is_oversold, f"Should detect oversold, RSI={result.rsi}"
    
    def test_overbought_detection(self):
        """Test overbought condition detection."""
        # Create strong uptrend
        prices = [100 + i * 2 for i in range(250)]
        candles = create_candles(prices)
        
        result = calculate_all_indicators(candles)
        
        assert result.is_overbought, f"Should detect overbought, RSI={result.rsi}"
    
    def test_insufficient_candles_raises_error(self):
        """Test that combined calculation raises error with insufficient candles."""
        prices = [100 + i for i in range(150)]
        candles = create_candles(prices)
        
        with pytest.raises(ValueError, match="Need at least 200"):
            calculate_all_indicators(candles)
    
    def test_custom_parameters(self):
        """Test combined calculation with custom parameters."""
        prices = [100 + i * 0.5 for i in range(250)]
        candles = create_candles(prices)
        
        result = calculate_all_indicators(
            candles,
            rsi_period=7,
            macd_fast=8,
            macd_slow=17,
            macd_signal=9,
            bollinger_period=15,
            bollinger_std_dev=2.5,
        )
        
        assert isinstance(result, TechnicalIndicators)
        assert 0 <= result.rsi <= 100


# --- Edge Cases ---

class TestEdgeCases:
    """Tests for edge cases and error handling."""
    
    def test_rsi_with_zero_close_price_raises_error(self):
        """Test that OHLCV validation rejects zero close price."""
        # OHLCV model validation should reject prices <= 0
        with pytest.raises(Exception):  # pydantic ValidationError
            create_candles([100, 101, 0])
    
    def test_bollinger_with_constant_prices(self):
        """Test Bollinger Bands with constant prices (zero std dev)."""
        prices = [100] * 25  # All same price
        candles = create_candles(prices)
        
        result = calculate_bollinger_bands(candles)
        
        # With zero std dev, all bands should equal the price
        assert result.upper_band == 100
        assert result.middle_band == 100
        assert result.lower_band == 100
        assert result.bandwidth == 0
    
    def test_macd_with_constant_prices(self):
        """Test MACD with constant prices."""
        prices = [100] * 50  # All same price
        candles = create_candles(prices)
        
        result = calculate_macd(candles)
        
        # With constant prices, MACD should be near zero
        assert abs(result.macd_line) < 0.0001
        assert abs(result.signal_line) < 0.0001
        assert abs(result.histogram) < 0.0001
    
    def test_rsi_with_minimum_candles(self):
        """Test RSI with exactly minimum required candles."""
        prices = [100 + i for i in range(15)]  # Exactly 15 candles for period=14
        candles = create_candles(prices)
        
        rsi = calculate_rsi(candles, period=14)
        
        assert 0 <= rsi <= 100
    
    def test_indicators_with_volatile_prices(self):
        """Test indicators with highly volatile prices."""
        # Create volatile price series
        import random
        random.seed(42)
        prices = [100]
        for _ in range(249):
            change = random.uniform(-5, 5)
            prices.append(max(1, prices[-1] + change))  # Ensure positive
        
        candles = create_candles(prices)
        
        result = calculate_all_indicators(candles)
        
        # All indicators should still be valid
        assert 0 <= result.rsi <= 100
        assert isinstance(result.macd.macd_line, float)
        assert result.bollinger_bands.upper_band > result.bollinger_bands.lower_band

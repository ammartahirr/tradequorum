"""
Unit tests for the confluence detection module.

Tests:
- Volume spike detection (Requirement 2.7)
- Confluence factor detection (Requirement 2.4)
- Confluence score calculation (Requirement 2.5)
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from src.models import OHLCV, SupportResistance, ConfluenceResult
from src.agents.technical.confluence import (
    detect_confluence,
    detect_volume_spike,
    validate_confluence_score,
    get_confluence_summary,
    TOTAL_CONFLUENCE_FACTORS,
    RSI_OVERSOLD_THRESHOLD,
    RSI_OVERBOUGHT_THRESHOLD,
    VOLUME_SPIKE_MULTIPLIER,
    VOLUME_AVERAGE_PERIOD,
)


# --- Test Fixtures ---

def create_candle(
    close: float,
    volume: int = 1000,
    high: float = None,
    low: float = None,
    open_price: float = None,
    timestamp: datetime = None,
) -> OHLCV:
    """Create a test OHLCV candle."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    if high is None:
        high = close * 1.01
    if low is None:
        low = close * 0.99
    if open_price is None:
        open_price = close
    
    return OHLCV(
        timestamp=timestamp,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def create_candles(
    count: int,
    base_price: float = 100.0,
    base_volume: int = 1000,
    price_trend: float = 0.0,
) -> list[OHLCV]:
    """Create a list of test candles."""
    candles = []
    for i in range(count):
        price = base_price + (i * price_trend)
        candles.append(create_candle(
            close=price,
            volume=base_volume,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ))
    return candles


def create_support_level(
    level: float,
    strength: float = 0.5,
    timeframe: str = "1y",
) -> SupportResistance:
    """Create a test support/resistance level."""
    return SupportResistance(
        level=level,
        strength=strength,
        timeframe=timeframe,
        last_tested=datetime.now(timezone.utc),
    )


# --- Volume Spike Detection Tests ---

class TestVolumeSpike:
    """Tests for volume spike detection (Requirement 2.7)."""
    
    def test_volume_spike_detected_when_above_threshold(self):
        """Volume spike should be detected when current > 1.5x average."""
        # Create 20 candles with volume 1000, then one with volume 2000
        candles = create_candles(20, base_volume=1000)
        candles.append(create_candle(close=100.0, volume=2000))
        
        # 2000 > 1000 * 1.5 = 1500, so spike should be detected
        assert detect_volume_spike(candles) is True
    
    def test_no_volume_spike_when_below_threshold(self):
        """No volume spike when current <= 1.5x average."""
        # Create 20 candles with volume 1000, then one with volume 1400
        candles = create_candles(20, base_volume=1000)
        candles.append(create_candle(close=100.0, volume=1400))
        
        # 1400 <= 1000 * 1.5 = 1500, so no spike
        assert detect_volume_spike(candles) is False
    
    def test_volume_spike_at_exact_threshold(self):
        """No volume spike when current equals exactly 1.5x average."""
        candles = create_candles(20, base_volume=1000)
        candles.append(create_candle(close=100.0, volume=1500))
        
        # 1500 is not > 1500, so no spike
        assert detect_volume_spike(candles) is False
    
    def test_volume_spike_just_above_threshold(self):
        """Volume spike detected when just above 1.5x threshold."""
        candles = create_candles(20, base_volume=1000)
        candles.append(create_candle(close=100.0, volume=1501))
        
        # 1501 > 1500, so spike detected
        assert detect_volume_spike(candles) is True
    
    def test_insufficient_candles_for_volume_spike(self):
        """No volume spike detection with insufficient candles."""
        candles = create_candles(10, base_volume=1000)  # Need 21 for 20-day average
        
        assert detect_volume_spike(candles) is False
    
    def test_volume_spike_with_custom_multiplier(self):
        """Volume spike detection with custom multiplier."""
        candles = create_candles(20, base_volume=1000)
        candles.append(create_candle(close=100.0, volume=2500))
        
        # With multiplier 2.0: 2500 > 1000 * 2.0 = 2000
        assert detect_volume_spike(candles, multiplier=2.0) is True
        
        # With multiplier 3.0: 2500 <= 1000 * 3.0 = 3000
        assert detect_volume_spike(candles, multiplier=3.0) is False
    
    def test_volume_spike_with_zero_average(self):
        """No volume spike when average volume is zero."""
        candles = create_candles(20, base_volume=0)
        candles.append(create_candle(close=100.0, volume=1000))
        
        assert detect_volume_spike(candles) is False


# --- Confluence Detection Tests ---

class TestConfluenceDetection:
    """Tests for confluence detection (Requirements 2.4, 2.5)."""
    
    def test_confluence_requires_minimum_candles(self):
        """Confluence detection requires at least 200 candles."""
        candles = create_candles(100)
        
        with pytest.raises(ValueError, match="Need at least 200 candles"):
            detect_confluence(candles)
    
    def test_confluence_with_200_candles(self):
        """Confluence detection works with exactly 200 candles."""
        candles = create_candles(200)
        
        result = detect_confluence(candles)
        
        assert isinstance(result, ConfluenceResult)
        assert 0.0 <= result.score <= 1.0
        assert isinstance(result.factors, list)
        assert isinstance(result.description, str)
    
    def test_confluence_score_calculation(self):
        """Confluence score is calculated as factors / total checks."""
        candles = create_candles(200)
        
        result = detect_confluence(candles)
        
        expected_score = len(result.factors) / TOTAL_CONFLUENCE_FACTORS
        assert result.score == expected_score
    
    def test_confluence_description_format(self):
        """Confluence description follows expected format."""
        candles = create_candles(200)
        
        result = detect_confluence(candles)
        
        assert f"/{TOTAL_CONFLUENCE_FACTORS}" in result.description
        assert "Confluence:" in result.description
    
    def test_confluence_with_support_levels(self):
        """Confluence detects price at support level."""
        candles = create_candles(200, base_price=100.0)
        # Create support level within 2% of current price (100.0)
        support_levels = [create_support_level(level=99.0, timeframe="5y")]
        
        result = detect_confluence(candles, support_levels=support_levels)
        
        # Price 100.0 is within 2% of 99.0 (1.01% difference)
        assert any("support" in f for f in result.factors)
    
    def test_confluence_with_resistance_levels(self):
        """Confluence detects price at resistance level."""
        candles = create_candles(200, base_price=100.0)
        # Create resistance level within 2% of current price (100.0)
        resistance_levels = [create_support_level(level=101.0, timeframe="1y")]
        
        result = detect_confluence(candles, resistance_levels=resistance_levels)
        
        # Price 100.0 is within 2% of 101.0 (0.99% difference)
        assert any("resistance" in f for f in result.factors)
    
    def test_confluence_no_support_when_price_far(self):
        """No support factor when price is far from support level."""
        candles = create_candles(200, base_price=100.0)
        # Create support level more than 2% away
        support_levels = [create_support_level(level=90.0, timeframe="5y")]
        
        result = detect_confluence(candles, support_levels=support_levels)
        
        # Price 100.0 is 11% away from 90.0
        assert not any("support" in f for f in result.factors)


# --- Confluence Score Validation Tests ---

class TestConfluenceScoreValidation:
    """Tests for confluence score validation (Requirement 2.5)."""
    
    def test_score_below_0_7_always_valid(self):
        """Scores below 0.7 are always valid regardless of factor count."""
        result = ConfluenceResult(
            score=0.5,
            factors=["rsi_oversold"],
            description="Test",
        )
        
        assert validate_confluence_score(result) is True
    
    def test_score_0_7_with_3_factors_valid(self):
        """Score >= 0.7 with 3+ factors is valid."""
        result = ConfluenceResult(
            score=0.7,
            factors=["rsi_oversold", "volume_spike", "macd_bullish"],
            description="Test",
        )
        
        assert validate_confluence_score(result) is True
    
    def test_score_0_7_with_2_factors_invalid(self):
        """Score >= 0.7 with < 3 factors is invalid."""
        # This is an edge case that shouldn't happen in practice
        # (0.7 score requires 4+ factors with 6 total)
        result = ConfluenceResult(
            score=0.7,
            factors=["rsi_oversold", "volume_spike"],
            description="Test",
        )
        
        assert validate_confluence_score(result) is False
    
    def test_score_1_0_with_6_factors_valid(self):
        """Perfect score with all 6 factors is valid."""
        result = ConfluenceResult(
            score=1.0,
            factors=[
                "rsi_oversold",
                "5y_support",
                "volume_spike",
                "golden_cross",
                "macd_bullish",
                "below_bollinger_lower",
            ],
            description="Test",
        )
        
        assert validate_confluence_score(result) is True


# --- Confluence Summary Tests ---

class TestConfluenceSummary:
    """Tests for confluence summary generation."""
    
    def test_summary_categorizes_bullish_factors(self):
        """Summary correctly categorizes bullish factors."""
        result = ConfluenceResult(
            score=0.5,
            factors=["rsi_oversold", "golden_cross", "macd_bullish"],
            description="Test",
        )
        
        summary = get_confluence_summary(result)
        
        assert "rsi_oversold" in summary["bullish_factors"]
        assert "golden_cross" in summary["bullish_factors"]
        assert "macd_bullish" in summary["bullish_factors"]
    
    def test_summary_categorizes_bearish_factors(self):
        """Summary correctly categorizes bearish factors."""
        result = ConfluenceResult(
            score=0.5,
            factors=["rsi_overbought", "death_cross", "macd_bearish"],
            description="Test",
        )
        
        summary = get_confluence_summary(result)
        
        assert "rsi_overbought" in summary["bearish_factors"]
        assert "death_cross" in summary["bearish_factors"]
        assert "macd_bearish" in summary["bearish_factors"]
    
    def test_summary_identifies_high_confluence(self):
        """Summary correctly identifies high confluence scores."""
        high_result = ConfluenceResult(score=0.7, factors=["a", "b", "c", "d"], description="Test")
        low_result = ConfluenceResult(score=0.5, factors=["a", "b", "c"], description="Test")
        
        assert get_confluence_summary(high_result)["is_high_confluence"] is True
        assert get_confluence_summary(low_result)["is_high_confluence"] is False
    
    def test_summary_includes_validation_status(self):
        """Summary includes validation status."""
        result = ConfluenceResult(
            score=0.7,
            factors=["a", "b", "c", "d"],
            description="Test",
        )
        
        summary = get_confluence_summary(result)
        
        assert "is_valid" in summary
        assert summary["is_valid"] is True


# --- Integration Tests with Mocked Indicators ---

class TestConfluenceIntegration:
    """Integration tests for confluence detection with mocked indicators."""
    
    @patch("src.agents.technical.confluence.calculate_rsi")
    def test_rsi_oversold_factor(self, mock_rsi):
        """RSI oversold condition adds factor."""
        mock_rsi.return_value = 25.0  # Below 30
        candles = create_candles(200)
        
        result = detect_confluence(candles)
        
        assert "rsi_oversold" in result.factors
    
    @patch("src.agents.technical.confluence.calculate_rsi")
    def test_rsi_overbought_factor(self, mock_rsi):
        """RSI overbought condition adds factor."""
        mock_rsi.return_value = 75.0  # Above 70
        candles = create_candles(200)
        
        result = detect_confluence(candles)
        
        assert "rsi_overbought" in result.factors
    
    @patch("src.agents.technical.confluence.calculate_rsi")
    def test_rsi_neutral_no_factor(self, mock_rsi):
        """RSI in neutral range adds no factor."""
        mock_rsi.return_value = 50.0  # Between 30 and 70
        candles = create_candles(200)
        
        result = detect_confluence(candles)
        
        assert "rsi_oversold" not in result.factors
        assert "rsi_overbought" not in result.factors
    
    @patch("src.agents.technical.confluence.calculate_moving_averages")
    def test_golden_cross_factor(self, mock_ma):
        """Golden cross adds factor."""
        mock_result = MagicMock()
        mock_result.is_golden_cross = True
        mock_result.is_death_cross = False
        mock_result.ma_50 = 110.0
        mock_result.ma_200 = 100.0
        mock_ma.return_value = mock_result
        candles = create_candles(200)
        
        result = detect_confluence(candles)
        
        assert "golden_cross" in result.factors
    
    @patch("src.agents.technical.confluence.calculate_moving_averages")
    def test_death_cross_factor(self, mock_ma):
        """Death cross adds factor."""
        mock_result = MagicMock()
        mock_result.is_golden_cross = False
        mock_result.is_death_cross = True
        mock_result.ma_50 = 90.0
        mock_result.ma_200 = 100.0
        mock_ma.return_value = mock_result
        candles = create_candles(200)
        
        result = detect_confluence(candles)
        
        assert "death_cross" in result.factors
    
    @patch("src.agents.technical.confluence.calculate_macd")
    def test_macd_bullish_factor(self, mock_macd):
        """MACD bullish signal adds factor."""
        mock_result = MagicMock()
        mock_result.is_bullish = True
        mock_result.is_bearish = False
        mock_result.macd_line = 1.0
        mock_result.signal_line = 0.5
        mock_macd.return_value = mock_result
        candles = create_candles(200)
        
        result = detect_confluence(candles)
        
        assert "macd_bullish" in result.factors
    
    @patch("src.agents.technical.confluence.calculate_macd")
    def test_macd_bearish_factor(self, mock_macd):
        """MACD bearish signal adds factor."""
        mock_result = MagicMock()
        mock_result.is_bullish = False
        mock_result.is_bearish = True
        mock_result.macd_line = -1.0
        mock_result.signal_line = -0.5
        mock_macd.return_value = mock_result
        candles = create_candles(200)
        
        result = detect_confluence(candles)
        
        assert "macd_bearish" in result.factors
    
    @patch("src.agents.technical.confluence.calculate_bollinger_bands")
    def test_below_bollinger_lower_factor(self, mock_bb):
        """Price below Bollinger lower band adds factor."""
        mock_result = MagicMock()
        mock_result.get_position.return_value = "below_lower"
        mock_bb.return_value = mock_result
        candles = create_candles(200)
        
        result = detect_confluence(candles)
        
        assert "below_bollinger_lower" in result.factors
    
    @patch("src.agents.technical.confluence.calculate_bollinger_bands")
    def test_above_bollinger_upper_factor(self, mock_bb):
        """Price above Bollinger upper band adds factor."""
        mock_result = MagicMock()
        mock_result.get_position.return_value = "above_upper"
        mock_bb.return_value = mock_result
        candles = create_candles(200)
        
        result = detect_confluence(candles)
        
        assert "above_bollinger_upper" in result.factors


# --- Constants Tests ---

class TestConfluenceConstants:
    """Tests for confluence module constants."""
    
    def test_total_factors_is_6(self):
        """Total confluence factors should be 6 per requirements."""
        assert TOTAL_CONFLUENCE_FACTORS == 6
    
    def test_rsi_thresholds(self):
        """RSI thresholds should match standard values."""
        assert RSI_OVERSOLD_THRESHOLD == 30
        assert RSI_OVERBOUGHT_THRESHOLD == 70
    
    def test_volume_spike_constants(self):
        """Volume spike constants should match requirements."""
        assert VOLUME_SPIKE_MULTIPLIER == 1.5
        assert VOLUME_AVERAGE_PERIOD == 20

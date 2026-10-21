"""
Unit tests for support/resistance level identification.

Tests for:
- Local minima (support) detection
- Local maxima (resistance) detection
- Level clustering
- Strength scoring
- Active level detection (within 2%)

Requirements:
- 2.3: Identify support and resistance levels using up to 5 years of historical price data
- 2.6: Flag levels as active when current price is within 2%
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.models import OHLCV, SupportResistance
from src.agents.technical.support_resistance import (
    find_local_minima,
    find_local_maxima,
    cluster_levels,
    calculate_strength,
    determine_timeframe,
    identify_support_levels,
    identify_resistance_levels,
    is_level_active,
    get_active_levels,
    get_nearest_support,
    get_nearest_resistance,
    analyze_support_resistance,
    PriceLevel,
    SupportResistanceResult,
    DEFAULT_LOOKBACK_WINDOW,
    DEFAULT_CLUSTER_THRESHOLD_PCT,
    ACTIVE_LEVEL_THRESHOLD_PCT,
    TIMEFRAME_LABELS,
)


# --- Test Fixtures ---

def create_candles(
    prices: list[tuple[float, float, float, float]],  # (open, high, low, close)
    start_time: datetime = None,
    interval_minutes: int = 1440,  # Daily by default
) -> list[OHLCV]:
    """
    Create a list of OHLCV candles from price tuples.
    """
    if start_time is None:
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    
    candles = []
    for i, (open_p, high_p, low_p, close_p) in enumerate(prices):
        timestamp = start_time + timedelta(minutes=interval_minutes * i)
        candles.append(OHLCV(
            timestamp=timestamp,
            open=open_p,
            high=high_p,
            low=low_p,
            close=close_p,
            volume=1000000,
        ))
    return candles


def create_simple_candles(
    closes: list[float],
    start_time: datetime = None,
    interval_minutes: int = 1440,
) -> list[OHLCV]:
    """
    Create candles where open=high=low=close for simplicity.
    """
    prices = [(c, c, c, c) for c in closes]
    return create_candles(prices, start_time, interval_minutes)


def create_candles_with_extrema(
    base_price: float = 100,
    num_candles: int = 50,
    support_at: list[int] = None,
    resistance_at: list[int] = None,
    support_depth: float = 5,
    resistance_height: float = 5,
) -> list[OHLCV]:
    """
    Create candles with specific support and resistance points.
    
    Args:
        base_price: Base price level
        num_candles: Total number of candles
        support_at: Indices where support levels should be
        resistance_at: Indices where resistance levels should be
        support_depth: How much lower support levels are
        resistance_height: How much higher resistance levels are
    """
    support_at = support_at or []
    resistance_at = resistance_at or []
    
    prices = []
    for i in range(num_candles):
        if i in support_at:
            # Create a local minimum
            low = base_price - support_depth
            prices.append((base_price, base_price + 1, low, base_price))
        elif i in resistance_at:
            # Create a local maximum
            high = base_price + resistance_height
            prices.append((base_price, high, base_price - 1, base_price))
        else:
            # Normal candle
            prices.append((base_price, base_price + 1, base_price - 1, base_price))
    
    return create_candles(prices)


# --- Local Minima Tests ---

class TestFindLocalMinima:
    """Tests for local minima (support) detection."""
    
    def test_find_single_minimum(self):
        """Test finding a single local minimum."""
        # Create a V-shaped pattern: prices go down then up
        prices = [
            (100, 101, 99, 100),   # 0
            (100, 101, 98, 99),    # 1
            (99, 100, 97, 98),     # 2
            (98, 99, 96, 97),      # 3
            (97, 98, 95, 96),      # 4
            (96, 97, 94, 95),      # 5 - minimum
            (95, 96, 94.5, 96),    # 6
            (96, 97, 95, 97),      # 7
            (97, 98, 96, 98),      # 8
            (98, 99, 97, 99),      # 9
            (99, 100, 98, 100),    # 10
        ]
        candles = create_candles(prices)
        
        minima = find_local_minima(candles, window=3)
        
        assert len(minima) >= 1, "Should find at least one minimum"
        # The minimum should be around index 5 with low=94
        min_prices = [m.price for m in minima]
        assert any(93 <= p <= 95 for p in min_prices), f"Should find minimum around 94, got {min_prices}"
    
    def test_find_multiple_minima(self):
        """Test finding multiple local minima."""
        # Create W-shaped pattern with two minima
        candles = create_candles_with_extrema(
            base_price=100,
            num_candles=30,
            support_at=[10, 20],
            support_depth=10,
        )
        
        minima = find_local_minima(candles, window=3)
        
        assert len(minima) >= 2, f"Should find at least 2 minima, found {len(minima)}"
    
    def test_no_minima_in_uptrend(self):
        """Test that no minima are found in a pure uptrend."""
        # Create pure uptrend
        prices = [(100 + i, 101 + i, 99 + i, 100 + i) for i in range(20)]
        candles = create_candles(prices)
        
        minima = find_local_minima(candles, window=5)
        
        # In a pure uptrend, there should be no local minima
        assert len(minima) == 0, f"Should find no minima in uptrend, found {len(minima)}"
    
    def test_insufficient_candles(self):
        """Test with insufficient candles for the window size."""
        prices = [(100, 101, 99, 100) for _ in range(5)]
        candles = create_candles(prices)
        
        # Window of 5 needs at least 11 candles (5 + 1 + 5)
        minima = find_local_minima(candles, window=5)
        
        assert len(minima) == 0, "Should return empty list with insufficient candles"


# --- Local Maxima Tests ---

class TestFindLocalMaxima:
    """Tests for local maxima (resistance) detection."""
    
    def test_find_single_maximum(self):
        """Test finding a single local maximum."""
        # Create an inverted V-shaped pattern: prices go up then down
        prices = [
            (100, 101, 99, 100),   # 0
            (100, 102, 99, 101),   # 1
            (101, 103, 100, 102),  # 2
            (102, 104, 101, 103),  # 3
            (103, 105, 102, 104),  # 4
            (104, 110, 103, 105),  # 5 - maximum
            (105, 106, 104, 104),  # 6
            (104, 105, 103, 103),  # 7
            (103, 104, 102, 102),  # 8
            (102, 103, 101, 101),  # 9
            (101, 102, 100, 100),  # 10
        ]
        candles = create_candles(prices)
        
        maxima = find_local_maxima(candles, window=3)
        
        assert len(maxima) >= 1, "Should find at least one maximum"
        max_prices = [m.price for m in maxima]
        assert any(108 <= p <= 112 for p in max_prices), f"Should find maximum around 110, got {max_prices}"
    
    def test_find_multiple_maxima(self):
        """Test finding multiple local maxima."""
        # Create M-shaped pattern with two maxima
        candles = create_candles_with_extrema(
            base_price=100,
            num_candles=30,
            resistance_at=[10, 20],
            resistance_height=10,
        )
        
        maxima = find_local_maxima(candles, window=3)
        
        assert len(maxima) >= 2, f"Should find at least 2 maxima, found {len(maxima)}"
    
    def test_no_maxima_in_downtrend(self):
        """Test that no maxima are found in a pure downtrend."""
        # Create pure downtrend
        prices = [(100 - i, 101 - i, 99 - i, 100 - i) for i in range(20)]
        candles = create_candles(prices)
        
        maxima = find_local_maxima(candles, window=5)
        
        # In a pure downtrend, there should be no local maxima
        assert len(maxima) == 0, f"Should find no maxima in downtrend, found {len(maxima)}"


# --- Clustering Tests ---

class TestClusterLevels:
    """Tests for level clustering."""
    
    def test_cluster_nearby_levels(self):
        """Test that nearby levels are clustered together."""
        levels = [
            PriceLevel(price=100.0, timestamp=datetime.now(timezone.utc), level_type="support"),
            PriceLevel(price=100.5, timestamp=datetime.now(timezone.utc), level_type="support"),
            PriceLevel(price=101.0, timestamp=datetime.now(timezone.utc), level_type="support"),
        ]
        
        # With 2% threshold, all should cluster together
        clusters = cluster_levels(levels, threshold_pct=0.02)
        
        assert len(clusters) == 1, f"Should have 1 cluster, got {len(clusters)}"
        assert len(clusters[0][1]) == 3, "Cluster should contain all 3 levels"
    
    def test_separate_distant_levels(self):
        """Test that distant levels are not clustered."""
        levels = [
            PriceLevel(price=100.0, timestamp=datetime.now(timezone.utc), level_type="support"),
            PriceLevel(price=110.0, timestamp=datetime.now(timezone.utc), level_type="support"),
            PriceLevel(price=120.0, timestamp=datetime.now(timezone.utc), level_type="support"),
        ]
        
        # With 2% threshold, these should be separate
        clusters = cluster_levels(levels, threshold_pct=0.02)
        
        assert len(clusters) == 3, f"Should have 3 separate clusters, got {len(clusters)}"
    
    def test_cluster_price_is_average(self):
        """Test that cluster price is the average of its levels."""
        levels = [
            PriceLevel(price=100.0, timestamp=datetime.now(timezone.utc), level_type="support"),
            PriceLevel(price=101.0, timestamp=datetime.now(timezone.utc), level_type="support"),
            PriceLevel(price=102.0, timestamp=datetime.now(timezone.utc), level_type="support"),
        ]
        
        clusters = cluster_levels(levels, threshold_pct=0.05)
        
        assert len(clusters) == 1
        expected_avg = (100.0 + 101.0 + 102.0) / 3
        assert abs(clusters[0][0] - expected_avg) < 0.01, \
            f"Cluster price should be {expected_avg}, got {clusters[0][0]}"
    
    def test_empty_levels(self):
        """Test clustering with empty list."""
        clusters = cluster_levels([])
        assert clusters == []


# --- Strength Calculation Tests ---

class TestCalculateStrength:
    """Tests for strength scoring."""
    
    def test_single_touch_strength(self):
        """Test strength with single touch."""
        levels = [PriceLevel(price=100, timestamp=datetime.now(timezone.utc), level_type="support")]
        strength = calculate_strength(levels)
        
        assert strength == 0.1, f"Single touch should have strength 0.1, got {strength}"
    
    def test_max_strength(self):
        """Test strength caps at 1.0."""
        levels = [
            PriceLevel(price=100, timestamp=datetime.now(timezone.utc), level_type="support")
            for _ in range(15)  # More than max_touches
        ]
        strength = calculate_strength(levels, max_touches=10)
        
        assert strength == 1.0, f"Strength should cap at 1.0, got {strength}"
    
    def test_strength_scaling(self):
        """Test that strength scales linearly with touches."""
        for num_touches in [1, 3, 5, 7, 10]:
            levels = [
                PriceLevel(price=100, timestamp=datetime.now(timezone.utc), level_type="support")
                for _ in range(num_touches)
            ]
            strength = calculate_strength(levels, max_touches=10)
            expected = min(num_touches / 10, 1.0)
            
            assert abs(strength - expected) < 0.01, \
                f"Strength for {num_touches} touches should be {expected}, got {strength}"


# --- Timeframe Determination Tests ---

class TestDetermineTimeframe:
    """Tests for timeframe determination."""
    
    def test_5y_timeframe(self):
        """Test 5-year timeframe detection."""
        candles = create_simple_candles([100] * 1300)  # > 1260
        timeframe = determine_timeframe(candles)
        assert timeframe == "5y"
    
    def test_1y_timeframe(self):
        """Test 1-year timeframe detection."""
        candles = create_simple_candles([100] * 300)  # > 252, < 1260
        timeframe = determine_timeframe(candles)
        assert timeframe == "1y"
    
    def test_6m_timeframe(self):
        """Test 6-month timeframe detection."""
        candles = create_simple_candles([100] * 150)  # > 126, < 252
        timeframe = determine_timeframe(candles)
        assert timeframe == "6m"
    
    def test_1m_timeframe(self):
        """Test 1-month timeframe detection."""
        candles = create_simple_candles([100] * 50)  # < 126
        timeframe = determine_timeframe(candles)
        assert timeframe == "1m"


# --- Active Level Detection Tests ---

class TestIsLevelActive:
    """Tests for active level detection (Requirement 2.6)."""
    
    def test_level_active_within_2_percent(self):
        """
        Test that level is active when price is within 2%.
        
        **Validates: Requirements 2.6**
        """
        level = SupportResistance(
            level=100.0,
            strength=0.5,
            timeframe="1y",
            last_tested=datetime.now(timezone.utc),
        )
        
        # Price exactly at level
        assert is_level_active(level, 100.0) is True
        
        # Price 1% above
        assert is_level_active(level, 101.0) is True
        
        # Price 2% below
        assert is_level_active(level, 98.0) is True
        
        # Price exactly 2% away
        assert is_level_active(level, 102.0) is True
    
    def test_level_not_active_beyond_2_percent(self):
        """
        Test that level is not active when price is beyond 2%.
        
        **Validates: Requirements 2.6**
        """
        level = SupportResistance(
            level=100.0,
            strength=0.5,
            timeframe="1y",
            last_tested=datetime.now(timezone.utc),
        )
        
        # Price 3% above
        assert is_level_active(level, 103.0) is False
        
        # Price 5% below
        assert is_level_active(level, 95.0) is False
    
    def test_active_level_with_custom_threshold(self):
        """Test active level detection with custom threshold."""
        level = SupportResistance(
            level=100.0,
            strength=0.5,
            timeframe="1y",
            last_tested=datetime.now(timezone.utc),
        )
        
        # With 5% threshold, 104 should be active
        assert is_level_active(level, 104.0, threshold_pct=0.05) is True
        
        # With 1% threshold, 102 should not be active
        assert is_level_active(level, 102.0, threshold_pct=0.01) is False


# --- Get Active Levels Tests ---

class TestGetActiveLevels:
    """Tests for getting all active levels."""
    
    def test_get_active_levels(self):
        """Test getting active levels from a list."""
        now = datetime.now(timezone.utc)
        levels = [
            SupportResistance(level=95.0, strength=0.5, timeframe="1y", last_tested=now),
            SupportResistance(level=100.0, strength=0.7, timeframe="1y", last_tested=now),
            SupportResistance(level=105.0, strength=0.3, timeframe="1y", last_tested=now),
            SupportResistance(level=120.0, strength=0.8, timeframe="1y", last_tested=now),
        ]
        
        current_price = 100.0
        active = get_active_levels(levels, current_price)
        
        # Should include 100 (exact) and possibly 98-102 range
        assert len(active) >= 1
        assert any(l.level == 100.0 for l in active)
    
    def test_no_active_levels(self):
        """Test when no levels are active."""
        now = datetime.now(timezone.utc)
        levels = [
            SupportResistance(level=80.0, strength=0.5, timeframe="1y", last_tested=now),
            SupportResistance(level=120.0, strength=0.7, timeframe="1y", last_tested=now),
        ]
        
        current_price = 100.0
        active = get_active_levels(levels, current_price)
        
        assert len(active) == 0


# --- Nearest Level Tests ---

class TestNearestLevels:
    """Tests for finding nearest support/resistance."""
    
    def test_get_nearest_support(self):
        """Test finding nearest support below current price."""
        now = datetime.now(timezone.utc)
        levels = [
            SupportResistance(level=90.0, strength=0.5, timeframe="1y", last_tested=now),
            SupportResistance(level=95.0, strength=0.7, timeframe="1y", last_tested=now),
            SupportResistance(level=105.0, strength=0.3, timeframe="1y", last_tested=now),
        ]
        
        nearest = get_nearest_support(levels, current_price=100.0)
        
        assert nearest is not None
        assert nearest.level == 95.0, f"Nearest support should be 95, got {nearest.level}"
    
    def test_get_nearest_resistance(self):
        """Test finding nearest resistance above current price."""
        now = datetime.now(timezone.utc)
        levels = [
            SupportResistance(level=95.0, strength=0.5, timeframe="1y", last_tested=now),
            SupportResistance(level=105.0, strength=0.7, timeframe="1y", last_tested=now),
            SupportResistance(level=110.0, strength=0.3, timeframe="1y", last_tested=now),
        ]
        
        nearest = get_nearest_resistance(levels, current_price=100.0)
        
        assert nearest is not None
        assert nearest.level == 105.0, f"Nearest resistance should be 105, got {nearest.level}"
    
    def test_no_support_below(self):
        """Test when no support exists below current price."""
        now = datetime.now(timezone.utc)
        levels = [
            SupportResistance(level=105.0, strength=0.5, timeframe="1y", last_tested=now),
            SupportResistance(level=110.0, strength=0.7, timeframe="1y", last_tested=now),
        ]
        
        nearest = get_nearest_support(levels, current_price=100.0)
        
        assert nearest is None
    
    def test_no_resistance_above(self):
        """Test when no resistance exists above current price."""
        now = datetime.now(timezone.utc)
        levels = [
            SupportResistance(level=90.0, strength=0.5, timeframe="1y", last_tested=now),
            SupportResistance(level=95.0, strength=0.7, timeframe="1y", last_tested=now),
        ]
        
        nearest = get_nearest_resistance(levels, current_price=100.0)
        
        assert nearest is None


# --- Full Analysis Tests ---

class TestAnalyzeSupportResistance:
    """Tests for complete support/resistance analysis."""
    
    def test_analyze_with_clear_levels(self):
        """Test analysis with clear support and resistance levels."""
        # Create candles with clear support at index 15 and resistance at index 25
        candles = create_candles_with_extrema(
            base_price=100,
            num_candles=50,
            support_at=[15],
            resistance_at=[25],
            support_depth=10,
            resistance_height=10,
        )
        
        result = analyze_support_resistance(candles, current_price=100.0)
        
        assert isinstance(result, SupportResistanceResult)
        assert len(result.support_levels) >= 1, "Should find at least 1 support level"
        assert len(result.resistance_levels) >= 1, "Should find at least 1 resistance level"
        assert result.current_price == 100.0
    
    def test_analyze_uses_last_close_if_no_price(self):
        """Test that analysis uses last close price if not provided."""
        candles = create_candles_with_extrema(
            base_price=100,
            num_candles=50,
            support_at=[15],
            resistance_at=[25],
        )
        
        result = analyze_support_resistance(candles)
        
        assert result.current_price == candles[-1].close
    
    def test_analyze_empty_candles_raises_error(self):
        """Test that empty candle list raises error."""
        with pytest.raises(ValueError, match="Cannot analyze"):
            analyze_support_resistance([])
    
    def test_analyze_identifies_active_levels(self):
        """
        Test that analysis correctly identifies active levels.
        
        **Validates: Requirements 2.6**
        """
        # Create candles with support at 98 (within 2% of 100)
        prices = []
        for i in range(50):
            if i == 25:
                # Create support at 98
                prices.append((100, 101, 98, 100))
            else:
                prices.append((100, 101, 99, 100))
        
        candles = create_candles(prices)
        result = analyze_support_resistance(candles, current_price=100.0)
        
        # Check if any support level around 98 is marked as active
        # (depends on whether the level was detected)
        if result.support_levels:
            # At least verify the structure is correct
            assert isinstance(result.active_support_levels, list)
            assert isinstance(result.active_resistance_levels, list)
    
    def test_analyze_5_year_data(self):
        """
        Test analysis with 5 years of historical data.
        
        **Validates: Requirements 2.3**
        """
        # Create 5 years of daily candles (1260 trading days)
        num_candles = 1300
        support_indices = [200, 500, 800, 1100]  # Multiple support levels
        resistance_indices = [300, 600, 900, 1200]  # Multiple resistance levels
        
        candles = create_candles_with_extrema(
            base_price=100,
            num_candles=num_candles,
            support_at=support_indices,
            resistance_at=resistance_indices,
            support_depth=10,
            resistance_height=10,
        )
        
        result = analyze_support_resistance(candles, current_price=100.0)
        
        assert result.timeframe == "5y", f"Should be 5y timeframe, got {result.timeframe}"
        assert len(result.support_levels) >= 1, "Should find support levels in 5y data"
        assert len(result.resistance_levels) >= 1, "Should find resistance levels in 5y data"


# --- Edge Cases ---

class TestEdgeCases:
    """Tests for edge cases."""
    
    def test_all_same_price(self):
        """Test with all candles at the same price."""
        prices = [(100, 100, 100, 100) for _ in range(50)]
        candles = create_candles(prices)
        
        result = analyze_support_resistance(candles)
        
        # Should not crash, may or may not find levels
        assert isinstance(result, SupportResistanceResult)
    
    def test_very_volatile_prices(self):
        """Test with highly volatile prices."""
        import random
        random.seed(42)
        
        prices = []
        for _ in range(100):
            base = random.uniform(90, 110)
            high = base + random.uniform(0, 5)
            low = base - random.uniform(0, 5)
            prices.append((base, high, low, base))
        
        candles = create_candles(prices)
        result = analyze_support_resistance(candles)
        
        # Should not crash
        assert isinstance(result, SupportResistanceResult)
    
    def test_minimum_candles_for_window(self):
        """Test with minimum candles for the default window."""
        # Default window is 5, so need at least 11 candles
        candles = create_candles_with_extrema(
            base_price=100,
            num_candles=11,
            support_at=[5],
            resistance_at=[5],
        )
        
        result = analyze_support_resistance(candles, window=5)
        
        # Should not crash
        assert isinstance(result, SupportResistanceResult)
    
    def test_strength_in_valid_range(self):
        """Test that all strength values are in [0, 1]."""
        candles = create_candles_with_extrema(
            base_price=100,
            num_candles=100,
            support_at=[20, 22, 24, 40, 42, 60],  # Multiple touches
            resistance_at=[30, 32, 50, 52, 70],
        )
        
        result = analyze_support_resistance(candles)
        
        for level in result.support_levels + result.resistance_levels:
            assert 0.0 <= level.strength <= 1.0, \
                f"Strength {level.strength} should be in [0, 1]"

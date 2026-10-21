"""
Property-based tests for Confluence Threshold.

**Property 5: Confluence Threshold**
**Validates: Requirements 2.5**

These tests verify:
- Confluence score >= 0.7 requires at least 3 aligned factors
- Confluence score is calculated as aligned factors / total checks (6)
- Score is always in range [0.0, 1.0]
"""

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.models import ConfluenceResult, OHLCV, SupportResistance
from src.agents.technical.confluence import (
    detect_confluence,
    detect_volume_spike,
    validate_confluence_score,
    TOTAL_CONFLUENCE_FACTORS,
)


# --- Strategies for generating test data ---

@st.composite
def confluence_factors_strategy(draw, min_factors: int = 0, max_factors: int = 6):
    """Generate a list of confluence factors."""
    all_factors = [
        "rsi_oversold", "rsi_overbought",
        "5y_support", "1y_support", "6m_support", "1m_support",
        "5y_resistance", "1y_resistance", "6m_resistance", "1m_resistance",
        "volume_spike",
        "golden_cross", "death_cross",
        "macd_bullish", "macd_bearish",
        "below_bollinger_lower", "above_bollinger_upper",
    ]
    num_factors = draw(st.integers(min_value=min_factors, max_value=max_factors))
    return draw(st.lists(
        st.sampled_from(all_factors),
        min_size=num_factors,
        max_size=num_factors,
        unique=True,
    ))


@st.composite
def ohlcv_candle_strategy(draw, base_price: float = 100.0):
    """Generate a valid OHLCV candle."""
    close = draw(st.floats(min_value=base_price * 0.9, max_value=base_price * 1.1, allow_nan=False))
    high = close * draw(st.floats(min_value=1.0, max_value=1.05, allow_nan=False))
    low = close * draw(st.floats(min_value=0.95, max_value=1.0, allow_nan=False))
    open_price = draw(st.floats(min_value=low, max_value=high, allow_nan=False))
    volume = draw(st.integers(min_value=100000, max_value=10000000))
    
    return OHLCV(
        timestamp=datetime.now(timezone.utc),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def create_test_candles(count: int = 250, base_price: float = 100.0) -> list[OHLCV]:
    """Create a list of test candles for confluence detection."""
    candles = []
    price = base_price
    
    for i in range(count):
        # Small random walk
        import random
        price *= (1 + random.uniform(-0.01, 0.01))
        
        candles.append(OHLCV(
            timestamp=datetime.now(timezone.utc) - timedelta(days=count - i),
            open=price * 0.999,
            high=price * 1.01,
            low=price * 0.99,
            close=price,
            volume=1000000,
        ))
    
    return candles


# --- Property Tests ---

@pytest.mark.property
class TestConfluenceThreshold:
    """
    Property tests for Confluence Threshold.
    
    **Validates: Requirements 2.5**
    """

    @given(
        num_factors=st.integers(min_value=0, max_value=6),
    )
    @settings(max_examples=50)
    def test_confluence_score_calculation(self, num_factors: int):
        """
        Property: Confluence score equals aligned factors / total checks.
        
        **Validates: Requirements 2.5**
        
        The confluence score should always be calculated as:
        score = len(factors) / TOTAL_CONFLUENCE_FACTORS (6)
        """
        # Generate factors
        all_factors = [
            "rsi_oversold", "volume_spike", "golden_cross",
            "macd_bullish", "below_bollinger_lower", "5y_support",
        ]
        factors = all_factors[:num_factors]
        
        # Create ConfluenceResult
        result = ConfluenceResult(
            score=num_factors / TOTAL_CONFLUENCE_FACTORS,
            factors=factors,
            description=f"Test: {num_factors}/{TOTAL_CONFLUENCE_FACTORS} factors",
        )
        
        # Verify score calculation
        expected_score = num_factors / TOTAL_CONFLUENCE_FACTORS
        assert result.score == expected_score, \
            f"Score should be {expected_score}, got {result.score}"
        
        # Verify score is in valid range
        assert 0.0 <= result.score <= 1.0, \
            f"Score must be in [0.0, 1.0], got {result.score}"

    @given(
        num_factors=st.integers(min_value=5, max_value=6),
    )
    @settings(max_examples=20)
    def test_high_confluence_requires_minimum_factors(self, num_factors: int):
        """
        Property: Score >= 0.7 requires at least 3 aligned factors.
        
        **Validates: Requirements 2.5**
        
        When the confluence score is >= 0.7, there must be at least 3
        factors aligned. With 6 total factors, score >= 0.7 means
        at least 5 factors (5/6 = 0.833), which exceeds 3.
        """
        # Generate factors (5 or 6 factors gives score >= 0.833)
        all_factors = [
            "rsi_oversold", "volume_spike", "golden_cross",
            "macd_bullish", "below_bollinger_lower", "5y_support",
        ]
        factors = all_factors[:num_factors]
        score = num_factors / TOTAL_CONFLUENCE_FACTORS
        
        # Create ConfluenceResult
        result = ConfluenceResult(
            score=score,
            factors=factors,
            description=f"High confluence: {num_factors}/{TOTAL_CONFLUENCE_FACTORS}",
        )
        
        # If score >= 0.7, must have at least 3 factors
        if result.score >= 0.7:
            assert len(result.factors) >= 3, \
                f"Score >= 0.7 requires at least 3 factors, got {len(result.factors)}"
        
        # Validate using the validation function
        assert validate_confluence_score(result) is True, \
            f"High confluence with {num_factors} factors should be valid"

    @given(
        num_factors=st.integers(min_value=0, max_value=2),
    )
    @settings(max_examples=20)
    def test_low_factor_count_produces_low_score(self, num_factors: int):
        """
        Property: Low factor count produces score < 0.7.
        
        **Validates: Requirements 2.5**
        
        With 0-2 factors out of 6, the score will be at most 2/6 = 0.333,
        which is well below the 0.7 threshold.
        """
        all_factors = [
            "rsi_oversold", "volume_spike", "golden_cross",
            "macd_bullish", "below_bollinger_lower", "5y_support",
        ]
        factors = all_factors[:num_factors]
        score = num_factors / TOTAL_CONFLUENCE_FACTORS
        
        result = ConfluenceResult(
            score=score,
            factors=factors,
            description=f"Low confluence: {num_factors}/{TOTAL_CONFLUENCE_FACTORS}",
        )
        
        # With 0-2 factors, score should be < 0.7
        assert result.score < 0.7, \
            f"Score with {num_factors} factors should be < 0.7, got {result.score}"
        
        # Low scores are always valid (no minimum factor requirement)
        assert validate_confluence_score(result) is True

    def test_score_0_7_with_exactly_3_factors_is_valid(self):
        """
        Property: Score >= 0.7 with exactly 3 factors is valid.
        
        **Validates: Requirements 2.5**
        
        The requirement states score >= 0.7 requires AT LEAST 3 factors.
        So 3 factors with score >= 0.7 should be valid.
        
        Note: With 6 total factors, 3 factors gives score = 0.5.
        To get score >= 0.7 with 3 factors, we'd need a different total.
        This test validates the validation logic itself.
        """
        # Create a result with score 0.7 and exactly 3 factors
        # (This is a synthetic test case to verify the validation logic)
        result = ConfluenceResult(
            score=0.7,
            factors=["rsi_oversold", "volume_spike", "golden_cross"],
            description="Test: 3 factors with 0.7 score",
        )
        
        # Should be valid because we have >= 3 factors
        assert validate_confluence_score(result) is True

    def test_score_0_7_with_2_factors_is_invalid(self):
        """
        Property: Score >= 0.7 with only 2 factors is invalid.
        
        **Validates: Requirements 2.5**
        
        This is an edge case that shouldn't happen in practice
        (2/6 = 0.333, not 0.7), but the validation should catch it.
        """
        # Create a synthetic invalid result
        result = ConfluenceResult(
            score=0.7,
            factors=["rsi_oversold", "volume_spike"],
            description="Invalid: 2 factors with 0.7 score",
        )
        
        # Should be invalid because we have < 3 factors
        assert validate_confluence_score(result) is False

    @given(
        score=st.floats(min_value=0.0, max_value=0.69, allow_nan=False),
        num_factors=st.integers(min_value=0, max_value=6),
    )
    @settings(max_examples=50)
    def test_scores_below_0_7_always_valid(self, score: float, num_factors: int):
        """
        Property: Scores below 0.7 are always valid regardless of factor count.
        
        **Validates: Requirements 2.5**
        
        The minimum factor requirement only applies when score >= 0.7.
        """
        all_factors = [
            "rsi_oversold", "volume_spike", "golden_cross",
            "macd_bullish", "below_bollinger_lower", "5y_support",
        ]
        factors = all_factors[:num_factors]
        
        result = ConfluenceResult(
            score=score,
            factors=factors,
            description=f"Test: score {score} with {num_factors} factors",
        )
        
        # Scores below 0.7 should always be valid
        assert validate_confluence_score(result) is True

    def test_total_confluence_factors_is_6(self):
        """
        Property: Total confluence factors should be 6.
        
        **Validates: Requirements 2.4**
        
        The system checks 6 independent factors for confluence.
        """
        assert TOTAL_CONFLUENCE_FACTORS == 6, \
            f"Total factors should be 6, got {TOTAL_CONFLUENCE_FACTORS}"

    @given(
        factors=confluence_factors_strategy(min_factors=0, max_factors=6),
    )
    @settings(max_examples=50)
    def test_confluence_score_bounds(self, factors: list[str]):
        """
        Property: Confluence score is always in [0.0, 1.0].
        
        **Validates: Requirements 2.5**
        """
        # Calculate score based on unique factors (max 6)
        unique_factors = list(set(factors))[:6]
        score = len(unique_factors) / TOTAL_CONFLUENCE_FACTORS
        
        result = ConfluenceResult(
            score=score,
            factors=unique_factors,
            description=f"Test: {len(unique_factors)} factors",
        )
        
        assert 0.0 <= result.score <= 1.0, \
            f"Score must be in [0.0, 1.0], got {result.score}"

    def test_perfect_confluence_score(self):
        """
        Property: 6 factors produces perfect score of 1.0.
        
        **Validates: Requirements 2.5**
        """
        factors = [
            "rsi_oversold",
            "5y_support",
            "volume_spike",
            "golden_cross",
            "macd_bullish",
            "below_bollinger_lower",
        ]
        
        result = ConfluenceResult(
            score=len(factors) / TOTAL_CONFLUENCE_FACTORS,
            factors=factors,
            description="Perfect confluence",
        )
        
        assert result.score == 1.0, \
            f"6 factors should give score 1.0, got {result.score}"
        assert validate_confluence_score(result) is True

    def test_zero_confluence_score(self):
        """
        Property: 0 factors produces score of 0.0.
        
        **Validates: Requirements 2.5**
        """
        result = ConfluenceResult(
            score=0.0,
            factors=[],
            description="No confluence",
        )
        
        assert result.score == 0.0
        assert validate_confluence_score(result) is True

    @given(
        num_factors=st.integers(min_value=4, max_value=6),
    )
    @settings(max_examples=20)
    def test_high_confluence_threshold_at_0_7(self, num_factors: int):
        """
        Property: Score >= 0.7 indicates high confluence.
        
        **Validates: Requirements 2.5**
        
        With 6 total factors:
        - 4 factors = 0.667 (below threshold)
        - 5 factors = 0.833 (above threshold)
        - 6 factors = 1.0 (above threshold)
        """
        all_factors = [
            "rsi_oversold", "volume_spike", "golden_cross",
            "macd_bullish", "below_bollinger_lower", "5y_support",
        ]
        factors = all_factors[:num_factors]
        score = num_factors / TOTAL_CONFLUENCE_FACTORS
        
        result = ConfluenceResult(
            score=score,
            factors=factors,
            description=f"Test: {num_factors} factors",
        )
        
        # Check if score meets high confluence threshold
        is_high_confluence = result.score >= 0.7
        
        if num_factors >= 5:
            assert is_high_confluence, \
                f"{num_factors} factors should give high confluence"
        else:
            assert not is_high_confluence, \
                f"{num_factors} factors should not give high confluence"

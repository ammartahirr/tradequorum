"""
Property-based tests for RSI Bounds.

**Property 8: RSI Bounds**
**Validates: Requirements 2.2**

These tests verify:
- RSI values are always in the range [0, 100]
- TechnicalSignal model rejects RSI values outside this range
- Any RSI calculation function (when implemented) produces values in [0, 100]
"""

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from pydantic import ValidationError

from src.models.enums import MarketCondition, TrendDirection
from src.models.signals import (
    ConfluenceResult,
    SupportResistance,
    TechnicalSignal,
)


# --- Strategies for generating test data ---

@st.composite
def valid_rsi_strategy(draw):
    """Generate valid RSI values in [0, 100]."""
    return draw(st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False))


@st.composite
def invalid_rsi_below_strategy(draw):
    """Generate invalid RSI values below 0."""
    return draw(st.floats(max_value=-0.001, allow_nan=False, allow_infinity=False))


@st.composite
def invalid_rsi_above_strategy(draw):
    """Generate invalid RSI values above 100."""
    return draw(st.floats(min_value=100.001, max_value=1000.0, allow_nan=False, allow_infinity=False))


@st.composite
def support_resistance_strategy(draw, base_price: float = None):
    """Generate valid SupportResistance instances."""
    now = datetime.now(timezone.utc)
    price = base_price or draw(st.floats(min_value=0.01, max_value=10000.0, allow_nan=False))
    return SupportResistance(
        level=price,
        strength=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        timeframe=draw(st.sampled_from(["5y", "1y", "6m", "1m"])),
        last_tested=now - timedelta(days=draw(st.integers(min_value=1, max_value=365))),
    )


@st.composite
def confluence_result_strategy(draw):
    """Generate valid ConfluenceResult instances."""
    return ConfluenceResult(
        score=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        factors=draw(st.lists(
            st.sampled_from([
                "rsi_oversold", "rsi_overbought", "5y_support", "1y_support",
                "volume_spike", "golden_cross", "death_cross", "macd_bullish",
                "macd_bearish", "below_bollinger_lower", "above_bollinger_upper"
            ]),
            min_size=0,
            max_size=6,
            unique=True
        )),
        description=draw(st.text(min_size=1, max_size=100)),
    )


# --- Property Tests ---

@pytest.mark.property
class TestRSIBounds:
    """
    Property tests for RSI Bounds.
    
    **Validates: Requirements 2.2**
    """

    @given(
        rsi=valid_rsi_strategy(),
        current_price=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False),
        trend=st.sampled_from(list(TrendDirection)),
        condition=st.sampled_from(list(MarketCondition)),
    )
    @settings(max_examples=100)
    def test_valid_rsi_values_accepted(
        self,
        rsi: float,
        current_price: float,
        trend: TrendDirection,
        condition: MarketCondition,
    ):
        """
        Property: RSI values in [0, 100] must be accepted by TechnicalSignal.
        
        **Validates: Requirements 2.2**
        
        For any RSI value in the valid range [0, 100], the TechnicalSignal
        model should accept it without raising a validation error.
        """
        now = datetime.now(timezone.utc)
        symbol = "AAPL"
        
        # Create TechnicalSignal with valid RSI
        signal = TechnicalSignal(
            symbol=symbol,
            trend=trend,
            condition=condition,
            rsi=rsi,
            current_price=current_price,
            support_levels=[
                SupportResistance(
                    level=current_price * 0.95,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=current_price * 1.05,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=0.5,
                factors=["rsi_oversold"] if rsi <= 30 else (["rsi_overbought"] if rsi >= 70 else []),
                description="Test confluence",
            ),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=now,
        )
        
        # Verify the RSI is stored correctly and within bounds
        assert 0 <= signal.rsi <= 100, \
            f"RSI ({signal.rsi}) must be in range [0, 100]"
        assert signal.rsi == rsi, \
            f"RSI should be stored as provided: expected {rsi}, got {signal.rsi}"

    @given(
        invalid_rsi=invalid_rsi_below_strategy(),
        current_price=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_rsi_below_zero_rejected(
        self,
        invalid_rsi: float,
        current_price: float,
    ):
        """
        Property: RSI values below 0 must be rejected by TechnicalSignal.
        
        **Validates: Requirements 2.2**
        
        The TechnicalSignal model should reject any RSI value below 0
        with a validation error.
        """
        now = datetime.now(timezone.utc)
        symbol = "AAPL"
        
        with pytest.raises(ValidationError) as exc_info:
            TechnicalSignal(
                symbol=symbol,
                trend=TrendDirection.SIDEWAYS,
                condition=MarketCondition.NEUTRAL,
                rsi=invalid_rsi,
                current_price=current_price,
                support_levels=[
                    SupportResistance(
                        level=current_price * 0.95,
                        strength=0.8,
                        timeframe="1y",
                        last_tested=now - timedelta(days=30),
                    )
                ],
                resistance_levels=[
                    SupportResistance(
                        level=current_price * 1.05,
                        strength=0.7,
                        timeframe="1y",
                        last_tested=now - timedelta(days=30),
                    )
                ],
                confluence=ConfluenceResult(
                    score=0.5,
                    factors=[],
                    description="Test confluence",
                ),
                volume_trend="stable",
                interest_rate_impact=0.0,
                timestamp=now,
            )
        
        # Verify the error is related to RSI validation
        error_str = str(exc_info.value).lower()
        assert "rsi" in error_str or "greater than or equal" in error_str, \
            f"Validation error should mention RSI constraint: {exc_info.value}"

    @given(
        invalid_rsi=invalid_rsi_above_strategy(),
        current_price=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_rsi_above_100_rejected(
        self,
        invalid_rsi: float,
        current_price: float,
    ):
        """
        Property: RSI values above 100 must be rejected by TechnicalSignal.
        
        **Validates: Requirements 2.2**
        
        The TechnicalSignal model should reject any RSI value above 100
        with a validation error.
        """
        now = datetime.now(timezone.utc)
        symbol = "AAPL"
        
        with pytest.raises(ValidationError) as exc_info:
            TechnicalSignal(
                symbol=symbol,
                trend=TrendDirection.SIDEWAYS,
                condition=MarketCondition.NEUTRAL,
                rsi=invalid_rsi,
                current_price=current_price,
                support_levels=[
                    SupportResistance(
                        level=current_price * 0.95,
                        strength=0.8,
                        timeframe="1y",
                        last_tested=now - timedelta(days=30),
                    )
                ],
                resistance_levels=[
                    SupportResistance(
                        level=current_price * 1.05,
                        strength=0.7,
                        timeframe="1y",
                        last_tested=now - timedelta(days=30),
                    )
                ],
                confluence=ConfluenceResult(
                    score=0.5,
                    factors=[],
                    description="Test confluence",
                ),
                volume_trend="stable",
                interest_rate_impact=0.0,
                timestamp=now,
            )
        
        # Verify the error is related to RSI validation
        error_str = str(exc_info.value).lower()
        assert "rsi" in error_str or "less than or equal" in error_str, \
            f"Validation error should mention RSI constraint: {exc_info.value}"

    @given(
        rsi=valid_rsi_strategy(),
    )
    @settings(max_examples=100)
    def test_rsi_boundary_values(
        self,
        rsi: float,
    ):
        """
        Property: RSI boundary values (0 and 100) must be valid.
        
        **Validates: Requirements 2.2**
        
        The RSI range is inclusive: [0, 100], so both 0 and 100 are valid values.
        """
        now = datetime.now(timezone.utc)
        current_price = 100.0
        
        # Test with the generated RSI value
        signal = TechnicalSignal(
            symbol="TEST",
            trend=TrendDirection.SIDEWAYS,
            condition=MarketCondition.NEUTRAL,
            rsi=rsi,
            current_price=current_price,
            support_levels=[
                SupportResistance(
                    level=current_price * 0.95,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=current_price * 1.05,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=0.5,
                factors=[],
                description="Test confluence",
            ),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=now,
        )
        
        assert 0 <= signal.rsi <= 100

    def test_rsi_exact_boundary_zero(self):
        """
        Test that RSI value of exactly 0 is accepted.
        
        **Validates: Requirements 2.2**
        """
        now = datetime.now(timezone.utc)
        current_price = 100.0
        
        signal = TechnicalSignal(
            symbol="TEST",
            trend=TrendDirection.STRONG_DOWNTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=0.0,
            current_price=current_price,
            support_levels=[
                SupportResistance(
                    level=current_price * 0.95,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=current_price * 1.05,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=0.9,
                factors=["rsi_oversold"],
                description="Extreme oversold",
            ),
            volume_trend="increasing",
            interest_rate_impact=0.0,
            timestamp=now,
        )
        
        assert signal.rsi == 0.0

    def test_rsi_exact_boundary_100(self):
        """
        Test that RSI value of exactly 100 is accepted.
        
        **Validates: Requirements 2.2**
        """
        now = datetime.now(timezone.utc)
        current_price = 100.0
        
        signal = TechnicalSignal(
            symbol="TEST",
            trend=TrendDirection.STRONG_UPTREND,
            condition=MarketCondition.OVERBOUGHT,
            rsi=100.0,
            current_price=current_price,
            support_levels=[
                SupportResistance(
                    level=current_price * 0.95,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=current_price * 1.05,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=0.9,
                factors=["rsi_overbought"],
                description="Extreme overbought",
            ),
            volume_trend="increasing",
            interest_rate_impact=0.0,
            timestamp=now,
        )
        
        assert signal.rsi == 100.0

    @given(
        rsi=valid_rsi_strategy(),
        trend=st.sampled_from(list(TrendDirection)),
        condition=st.sampled_from(list(MarketCondition)),
        confluence_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_rsi_preserved_in_technical_signal(
        self,
        rsi: float,
        trend: TrendDirection,
        condition: MarketCondition,
        confluence_score: float,
    ):
        """
        Property: RSI value must be preserved exactly in TechnicalSignal.
        
        **Validates: Requirements 2.2**
        
        When a valid RSI value is provided to TechnicalSignal, it should be
        stored and retrievable without modification.
        """
        now = datetime.now(timezone.utc)
        current_price = 150.0
        
        signal = TechnicalSignal(
            symbol="MSFT",
            trend=trend,
            condition=condition,
            rsi=rsi,
            current_price=current_price,
            support_levels=[
                SupportResistance(
                    level=current_price * 0.9,
                    strength=0.75,
                    timeframe="6m",
                    last_tested=now - timedelta(days=15),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=current_price * 1.1,
                    strength=0.65,
                    timeframe="6m",
                    last_tested=now - timedelta(days=20),
                )
            ],
            confluence=ConfluenceResult(
                score=confluence_score,
                factors=[],
                description="Test",
            ),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=now,
        )
        
        # RSI should be exactly preserved
        assert signal.rsi == rsi, \
            f"RSI should be preserved exactly: expected {rsi}, got {signal.rsi}"
        
        # And still within bounds
        assert 0 <= signal.rsi <= 100, \
            f"RSI ({signal.rsi}) must remain in range [0, 100]"

    @given(
        nan_or_inf=st.sampled_from([float('nan'), float('inf'), float('-inf')]),
    )
    @settings(max_examples=10)
    def test_rsi_rejects_nan_and_infinity(
        self,
        nan_or_inf: float,
    ):
        """
        Property: RSI must reject NaN and infinity values.
        
        **Validates: Requirements 2.2**
        
        NaN and infinity are not valid RSI values and should be rejected.
        """
        now = datetime.now(timezone.utc)
        current_price = 100.0
        
        with pytest.raises(ValidationError):
            TechnicalSignal(
                symbol="TEST",
                trend=TrendDirection.SIDEWAYS,
                condition=MarketCondition.NEUTRAL,
                rsi=nan_or_inf,
                current_price=current_price,
                support_levels=[
                    SupportResistance(
                        level=current_price * 0.95,
                        strength=0.8,
                        timeframe="1y",
                        last_tested=now - timedelta(days=30),
                    )
                ],
                resistance_levels=[
                    SupportResistance(
                        level=current_price * 1.05,
                        strength=0.7,
                        timeframe="1y",
                        last_tested=now - timedelta(days=30),
                    )
                ],
                confluence=ConfluenceResult(
                    score=0.5,
                    factors=[],
                    description="Test confluence",
                ),
                volume_trend="stable",
                interest_rate_impact=0.0,
                timestamp=now,
            )

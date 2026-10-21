"""
Property-based tests for Signal Freshness.

**Property 4: Signal Freshness**
**Validates: Requirements 3.8, 3.9**

These tests verify that:
- NewsSignals with expires_at <= current time are discarded
- TechnicalSignals with timestamp > 1 hour old are discarded
- Fresh signals are correctly identified
- Stale signals are never used for trade decisions
"""

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.models.enums import (
    ImpactType,
    MarketCondition,
    Sentiment,
    TrendDirection,
)
from src.models.signals import (
    ConfluenceResult,
    NewsSignal,
    SupportResistance,
    TechnicalSignal,
)

from src.agents.strategy.signal_freshness import (
    SignalFreshnessValidator,
    is_news_signal_fresh,
    is_technical_signal_fresh,
)
from src.agents.strategy.config import SignalFreshnessConfig


# --- Strategies for generating test data ---

@st.composite
def news_signal_with_expiry_strategy(draw, expires_in_hours: int = None):
    """Generate NewsSignal with configurable expiry."""
    now = datetime.now(timezone.utc)
    
    if expires_in_hours is None:
        expires_in_hours = draw(st.integers(min_value=-48, max_value=168))
    
    return NewsSignal(
        symbol="AAPL",
        sentiment=draw(st.sampled_from(list(Sentiment))),
        impact_type=draw(st.sampled_from(list(ImpactType))),
        impact_score=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        confidence=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        reasoning="Test news",
        source_items=["item1"],
        timestamp=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=expires_in_hours),
    )


@st.composite
def technical_signal_with_age_strategy(draw, age_minutes: int = None):
    """Generate TechnicalSignal with configurable age."""
    now = datetime.now(timezone.utc)
    
    if age_minutes is None:
        age_minutes = draw(st.integers(min_value=0, max_value=180))
    
    signal_time = now - timedelta(minutes=age_minutes)
    
    return TechnicalSignal(
        symbol="AAPL",
        trend=draw(st.sampled_from(list(TrendDirection))),
        condition=draw(st.sampled_from(list(MarketCondition))),
        rsi=draw(st.floats(min_value=0.0, max_value=100.0, allow_nan=False)),
        current_price=draw(st.floats(min_value=1.0, max_value=10000.0, allow_nan=False)),
        support_levels=[
            SupportResistance(
                level=50.0,
                strength=0.8,
                timeframe="1y",
                last_tested=now - timedelta(days=30),
            )
        ],
        resistance_levels=[
            SupportResistance(
                level=150.0,
                strength=0.7,
                timeframe="1y",
                last_tested=now - timedelta(days=30),
            )
        ],
        confluence=ConfluenceResult(
            score=0.7,
            factors=["rsi_oversold"],
            description="Test confluence",
        ),
        volume_trend="stable",
        interest_rate_impact=0.0,
        timestamp=signal_time,
    )


# --- Property Tests ---

@pytest.mark.property
class TestSignalFreshness:
    """
    Property tests for Signal Freshness.
    
    **Validates: Requirements 3.8, 3.9**
    """

    @given(
        hours_until_expiry=st.integers(min_value=1, max_value=168),
    )
    @settings(max_examples=100)
    def test_news_signal_fresh_before_expiry(
        self,
        hours_until_expiry: int,
    ):
        """
        Property: NewsSignals with expires_at > current time are fresh.
        
        **Validates: Requirement 3.8**
        
        A news signal should be considered fresh if its expiry time
        is in the future.
        """
        now = datetime.now(timezone.utc)
        
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.8,
            confidence=0.9,
            reasoning="Test news",
            source_items=["item1"],
            timestamp=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=hours_until_expiry),
        )
        
        is_fresh = is_news_signal_fresh(news_signal, now)
        
        assert is_fresh is True, (
            f"NewsSignal with {hours_until_expiry}h until expiry should be fresh"
        )

    @given(
        hours_since_expiry=st.integers(min_value=0, max_value=168),
    )
    @settings(max_examples=100)
    def test_news_signal_stale_after_expiry(
        self,
        hours_since_expiry: int,
    ):
        """
        Property: NewsSignals with expires_at <= current time are stale.
        
        **Validates: Requirement 3.8**
        
        A news signal should be considered stale if its expiry time
        is at or before the current time.
        """
        now = datetime.now(timezone.utc)
        
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.8,
            confidence=0.9,
            reasoning="Test news",
            source_items=["item1"],
            timestamp=now - timedelta(hours=24),
            expires_at=now - timedelta(hours=hours_since_expiry),
        )
        
        is_fresh = is_news_signal_fresh(news_signal, now)
        
        assert is_fresh is False, (
            f"NewsSignal expired {hours_since_expiry}h ago should be stale"
        )

    @given(
        age_minutes=st.integers(min_value=0, max_value=59),
    )
    @settings(max_examples=100)
    def test_technical_signal_fresh_within_one_hour(
        self,
        age_minutes: int,
    ):
        """
        Property: TechnicalSignals with timestamp within 1 hour are fresh.
        
        **Validates: Requirement 3.9**
        
        A technical signal should be considered fresh if its timestamp
        is within 1 hour of the current time.
        """
        now = datetime.now(timezone.utc)
        signal_time = now - timedelta(minutes=age_minutes)
        
        technical_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.NEUTRAL,
            rsi=50.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(
                    level=95.0,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=105.0,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=0.7,
                factors=["ma_alignment"],
                description="Test confluence",
            ),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=signal_time,
        )
        
        is_fresh = is_technical_signal_fresh(technical_signal, now)
        
        assert is_fresh is True, (
            f"TechnicalSignal {age_minutes}min old should be fresh"
        )

    @given(
        age_minutes=st.integers(min_value=61, max_value=1440),
    )
    @settings(max_examples=100)
    def test_technical_signal_stale_after_one_hour(
        self,
        age_minutes: int,
    ):
        """
        Property: TechnicalSignals with timestamp > 1 hour old are stale.
        
        **Validates: Requirement 3.9**
        
        A technical signal should be considered stale if its timestamp
        is more than 1 hour before the current time.
        """
        now = datetime.now(timezone.utc)
        signal_time = now - timedelta(minutes=age_minutes)
        
        technical_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.NEUTRAL,
            rsi=50.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(
                    level=95.0,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=105.0,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=0.7,
                factors=["ma_alignment"],
                description="Test confluence",
            ),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=signal_time,
        )
        
        is_fresh = is_technical_signal_fresh(technical_signal, now)
        
        assert is_fresh is False, (
            f"TechnicalSignal {age_minutes}min old should be stale"
        )

    @given(
        news_hours_until_expiry=st.integers(min_value=1, max_value=168),
        tech_age_minutes=st.integers(min_value=0, max_value=59),
    )
    @settings(max_examples=100)
    def test_validator_accepts_fresh_signals(
        self,
        news_hours_until_expiry: int,
        tech_age_minutes: int,
    ):
        """
        Property: Validator accepts when both signals are fresh.
        
        **Validates: Requirements 3.8, 3.9**
        
        The SignalFreshnessValidator should return is_valid=True when
        both news and technical signals are fresh.
        """
        now = datetime.now(timezone.utc)
        
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.8,
            confidence=0.9,
            reasoning="Test news",
            source_items=["item1"],
            timestamp=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=news_hours_until_expiry),
        )
        
        technical_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.NEUTRAL,
            rsi=50.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(
                    level=95.0,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=105.0,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=0.7,
                factors=["ma_alignment"],
                description="Test confluence",
            ),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=now - timedelta(minutes=tech_age_minutes),
        )
        
        validator = SignalFreshnessValidator()
        result = validator.validate(news_signal, technical_signal, now)
        
        assert result.is_valid is True, (
            f"Validator should accept fresh signals: "
            f"news_fresh={result.news_fresh}, tech_fresh={result.technical_fresh}"
        )
        assert result.news_fresh is True
        assert result.technical_fresh is True
        assert result.rejection_reason is None

    @given(
        news_hours_since_expiry=st.integers(min_value=1, max_value=168),
        tech_age_minutes=st.integers(min_value=0, max_value=59),
    )
    @settings(max_examples=100)
    def test_validator_rejects_expired_news_signal(
        self,
        news_hours_since_expiry: int,
        tech_age_minutes: int,
    ):
        """
        Property: Validator rejects when news signal is expired.
        
        **Validates: Requirement 3.8**
        
        The SignalFreshnessValidator should return is_valid=False when
        the news signal is expired, even if technical signal is fresh.
        """
        now = datetime.now(timezone.utc)
        
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.8,
            confidence=0.9,
            reasoning="Test news",
            source_items=["item1"],
            timestamp=now - timedelta(hours=24),
            expires_at=now - timedelta(hours=news_hours_since_expiry),
        )
        
        technical_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.NEUTRAL,
            rsi=50.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(
                    level=95.0,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=105.0,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=0.7,
                factors=["ma_alignment"],
                description="Test confluence",
            ),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=now - timedelta(minutes=tech_age_minutes),
        )
        
        validator = SignalFreshnessValidator()
        result = validator.validate(news_signal, technical_signal, now)
        
        assert result.is_valid is False, (
            f"Validator should reject expired news signal"
        )
        assert result.news_fresh is False
        assert result.rejection_reason is not None

    @given(
        news_hours_until_expiry=st.integers(min_value=1, max_value=168),
        tech_age_minutes=st.integers(min_value=61, max_value=1440),
    )
    @settings(max_examples=100)
    def test_validator_rejects_stale_technical_signal(
        self,
        news_hours_until_expiry: int,
        tech_age_minutes: int,
    ):
        """
        Property: Validator rejects when technical signal is stale.
        
        **Validates: Requirement 3.9**
        
        The SignalFreshnessValidator should return is_valid=False when
        the technical signal is stale, even if news signal is fresh.
        """
        now = datetime.now(timezone.utc)
        
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.8,
            confidence=0.9,
            reasoning="Test news",
            source_items=["item1"],
            timestamp=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=news_hours_until_expiry),
        )
        
        technical_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.NEUTRAL,
            rsi=50.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(
                    level=95.0,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=105.0,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=0.7,
                factors=["ma_alignment"],
                description="Test confluence",
            ),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=now - timedelta(minutes=tech_age_minutes),
        )
        
        validator = SignalFreshnessValidator()
        result = validator.validate(news_signal, technical_signal, now)
        
        assert result.is_valid is False, (
            f"Validator should reject stale technical signal"
        )
        assert result.technical_fresh is False
        assert result.rejection_reason is not None

    @given(
        news_hours_since_expiry=st.integers(min_value=1, max_value=168),
        tech_age_minutes=st.integers(min_value=61, max_value=1440),
    )
    @settings(max_examples=50)
    def test_validator_rejects_both_stale_signals(
        self,
        news_hours_since_expiry: int,
        tech_age_minutes: int,
    ):
        """
        Property: Validator rejects when both signals are stale.
        
        **Validates: Requirements 3.8, 3.9**
        
        The SignalFreshnessValidator should return is_valid=False and
        include both rejection reasons when both signals are stale.
        """
        now = datetime.now(timezone.utc)
        
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.8,
            confidence=0.9,
            reasoning="Test news",
            source_items=["item1"],
            timestamp=now - timedelta(hours=24),
            expires_at=now - timedelta(hours=news_hours_since_expiry),
        )
        
        technical_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.NEUTRAL,
            rsi=50.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(
                    level=95.0,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=105.0,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=0.7,
                factors=["ma_alignment"],
                description="Test confluence",
            ),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=now - timedelta(minutes=tech_age_minutes),
        )
        
        validator = SignalFreshnessValidator()
        result = validator.validate(news_signal, technical_signal, now)
        
        assert result.is_valid is False, (
            f"Validator should reject both stale signals"
        )
        assert result.news_fresh is False
        assert result.technical_fresh is False
        assert result.rejection_reason is not None
        # Both reasons should be in the rejection message
        assert "NewsSignal" in result.rejection_reason
        assert "TechnicalSignal" in result.rejection_reason

    @given(
        age_seconds=st.integers(min_value=0, max_value=3600),
    )
    @settings(max_examples=50)
    def test_technical_signal_exactly_one_hour_is_fresh(
        self,
        age_seconds: int,
    ):
        """
        Property: TechnicalSignal exactly 1 hour old is still fresh.
        
        **Validates: Requirement 3.9**
        
        The boundary condition: a signal exactly 1 hour old (3600 seconds)
        should still be considered fresh.
        """
        now = datetime.now(timezone.utc)
        signal_time = now - timedelta(seconds=age_seconds)
        
        technical_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.NEUTRAL,
            rsi=50.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(
                    level=95.0,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=105.0,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=0.7,
                factors=["ma_alignment"],
                description="Test confluence",
            ),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=signal_time,
        )
        
        is_fresh = is_technical_signal_fresh(technical_signal, now)
        
        # Signal should be fresh if age <= 3600 seconds (1 hour)
        expected_fresh = age_seconds <= 3600
        assert is_fresh == expected_fresh, (
            f"TechnicalSignal {age_seconds}s old should be "
            f"{'fresh' if expected_fresh else 'stale'}"
        )

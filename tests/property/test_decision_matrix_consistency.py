"""
Property-based tests for Decision Matrix Consistency.

**Property 6: Decision Matrix Consistency**
**Validates: Requirements 3.2, 3.3, 3.4, 3.5**

These tests verify that:
- VERY_BULLISH + OVERSOLD → STRONG_BUY or BUY
- VERY_BEARISH + OVERBOUGHT → STRONG_SELL
- BULLISH + OVERBOUGHT → WAIT_PULLBACK
- Conflicting signals (bearish news + oversold) → NO_TRADE
- Decision matrix produces consistent outputs for identical inputs
"""

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.models.enums import (
    Conviction,
    ImpactType,
    MarketCondition,
    Sentiment,
    TradeAction,
    TrendDirection,
)
from src.models.signals import (
    ConfluenceResult,
    NewsSignal,
    SupportResistance,
    TechnicalSignal,
)

from src.agents.strategy.decision_matrix import (
    DecisionMatrixEvaluator,
    map_sentiment_score,
    map_technical_score,
)


# --- Strategies for generating test data ---

@st.composite
def news_signal_strategy(draw, sentiment: Sentiment = None, symbol: str = "AAPL"):
    """Generate valid NewsSignal instances."""
    now = datetime.now(timezone.utc)
    return NewsSignal(
        symbol=symbol,
        sentiment=sentiment or draw(st.sampled_from(list(Sentiment))),
        impact_type=draw(st.sampled_from(list(ImpactType))),
        impact_score=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        confidence=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        reasoning=draw(st.text(min_size=1, max_size=100)),
        source_items=["item1"],
        timestamp=now,
        expires_at=now + timedelta(hours=72),
    )


@st.composite
def technical_signal_strategy(draw, condition: MarketCondition = None, symbol: str = "AAPL"):
    """Generate valid TechnicalSignal instances."""
    now = datetime.now(timezone.utc)
    
    return TechnicalSignal(
        symbol=symbol,
        trend=draw(st.sampled_from(list(TrendDirection))),
        condition=condition or draw(st.sampled_from(list(MarketCondition))),
        rsi=draw(st.floats(min_value=0.0, max_value=100.0, allow_nan=False)),
        current_price=draw(st.floats(min_value=1.0, max_value=10000.0, allow_nan=False)),
        support_levels=[
            SupportResistance(
                level=draw(st.floats(min_value=0.5, max_value=9999.0, allow_nan=False)),
                strength=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
                timeframe="1y",
                last_tested=now - timedelta(days=30),
            )
        ],
        resistance_levels=[
            SupportResistance(
                level=draw(st.floats(min_value=1.0, max_value=10000.0, allow_nan=False)),
                strength=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
                timeframe="1y",
                last_tested=now - timedelta(days=30),
            )
        ],
        confluence=ConfluenceResult(
            score=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
            factors=["rsi_oversold"],
            description="Test confluence",
        ),
        volume_trend=draw(st.sampled_from(["increasing", "decreasing", "stable"])),
        interest_rate_impact=draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False)),
        timestamp=now,
    )


# --- Property Tests ---

@pytest.mark.property
class TestDecisionMatrixConsistency:
    """
    Property tests for Decision Matrix Consistency.
    
    **Validates: Requirements 3.2, 3.3, 3.4, 3.5**
    """

    @given(
        impact_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        confluence_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_very_bullish_oversold_produces_strong_buy(
        self,
        impact_score: float,
        confluence_score: float,
    ):
        """
        Property: VERY_BULLISH + OVERSOLD → STRONG_BUY with HIGH conviction.
        
        **Validates: Requirement 3.2**
        
        When news sentiment is VERY_BULLISH and technical condition is OVERSOLD,
        the decision matrix must produce a STRONG_BUY action with HIGH conviction.
        """
        now = datetime.now(timezone.utc)
        
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.VERY_BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=impact_score,
            confidence=0.9,
            reasoning="Very bullish news",
            source_items=["item1"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        technical_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.DOWNTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=25.0,
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
                    level=110.0,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=confluence_score,
                factors=["rsi_oversold", "support_level"],
                description="Strong confluence",
            ),
            volume_trend="increasing",
            interest_rate_impact=0.1,
            timestamp=now,
        )
        
        evaluator = DecisionMatrixEvaluator()
        result = evaluator.evaluate(news_signal, technical_signal)
        
        # Verify the property
        assert result.action == TradeAction.STRONG_BUY, (
            f"VERY_BULLISH + OVERSOLD should produce STRONG_BUY, got {result.action.value}"
        )
        assert result.conviction == Conviction.HIGH, (
            f"STRONG_BUY should have HIGH conviction, got {result.conviction.value}"
        )

    @given(
        impact_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        confluence_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_very_bearish_overbought_produces_strong_sell(
        self,
        impact_score: float,
        confluence_score: float,
    ):
        """
        Property: VERY_BEARISH + OVERBOUGHT → STRONG_SELL with HIGH conviction.
        
        **Validates: Requirement 3.3**
        
        When news sentiment is VERY_BEARISH and technical condition is OVERBOUGHT,
        the decision matrix must produce a STRONG_SELL action with HIGH conviction.
        """
        now = datetime.now(timezone.utc)
        
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.VERY_BEARISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=impact_score,
            confidence=0.9,
            reasoning="Very bearish news",
            source_items=["item1"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        technical_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.OVERBOUGHT,
            rsi=75.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(
                    level=90.0,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=105.0,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=confluence_score,
                factors=["rsi_overbought", "resistance_level"],
                description="Strong confluence",
            ),
            volume_trend="increasing",
            interest_rate_impact=-0.1,
            timestamp=now,
        )
        
        evaluator = DecisionMatrixEvaluator()
        result = evaluator.evaluate(news_signal, technical_signal)
        
        # Verify the property
        assert result.action == TradeAction.STRONG_SELL, (
            f"VERY_BEARISH + OVERBOUGHT should produce STRONG_SELL, got {result.action.value}"
        )
        assert result.conviction == Conviction.HIGH, (
            f"STRONG_SELL should have HIGH conviction, got {result.conviction.value}"
        )

    @given(
        impact_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        confluence_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_bullish_overbought_produces_wait_pullback(
        self,
        impact_score: float,
        confluence_score: float,
    ):
        """
        Property: BULLISH + OVERBOUGHT → WAIT_PULLBACK with MEDIUM conviction.
        
        **Validates: Requirement 3.4**
        
        When news sentiment is BULLISH and technical condition is OVERBOUGHT,
        the decision matrix must produce a WAIT_PULLBACK action.
        """
        now = datetime.now(timezone.utc)
        
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=impact_score,
            confidence=0.8,
            reasoning="Bullish news",
            source_items=["item1"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        technical_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.OVERBOUGHT,
            rsi=75.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(
                    level=90.0,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=105.0,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=confluence_score,
                factors=["rsi_overbought"],
                description="Overbought confluence",
            ),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=now,
        )
        
        evaluator = DecisionMatrixEvaluator()
        result = evaluator.evaluate(news_signal, technical_signal)
        
        # Verify the property
        assert result.action == TradeAction.WAIT_PULLBACK, (
            f"BULLISH + OVERBOUGHT should produce WAIT_PULLBACK, got {result.action.value}"
        )
        assert result.conviction == Conviction.MEDIUM, (
            f"WAIT_PULLBACK should have MEDIUM conviction, got {result.conviction.value}"
        )

    @given(
        sentiment=st.sampled_from([Sentiment.BEARISH, Sentiment.VERY_BEARISH]),
        impact_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        confluence_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_bearish_oversold_produces_no_trade(
        self,
        sentiment: Sentiment,
        impact_score: float,
        confluence_score: float,
    ):
        """
        Property: Bearish news + OVERSOLD → NO_TRADE (conflicting signals).
        
        **Validates: Requirement 3.5**
        
        When news sentiment is BEARISH or VERY_BEARISH and technical condition
        is OVERSOLD, the decision matrix must produce a NO_TRADE action due to
        conflicting signals.
        """
        now = datetime.now(timezone.utc)
        
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=sentiment,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=impact_score,
            confidence=0.8,
            reasoning="Bearish news",
            source_items=["item1"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        technical_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.DOWNTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=25.0,
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
                    level=110.0,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=confluence_score,
                factors=["rsi_oversold"],
                description="Oversold confluence",
            ),
            volume_trend="decreasing",
            interest_rate_impact=-0.1,
            timestamp=now,
        )
        
        evaluator = DecisionMatrixEvaluator()
        result = evaluator.evaluate(news_signal, technical_signal)
        
        # Verify the property
        assert result.action == TradeAction.NO_TRADE, (
            f"Bearish ({sentiment.value}) + OVERSOLD should produce NO_TRADE, "
            f"got {result.action.value}"
        )

    @given(
        impact_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        confluence_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_decision_matrix_is_deterministic(
        self,
        impact_score: float,
        confluence_score: float,
    ):
        """
        Property: Decision matrix produces consistent outputs for identical inputs.
        
        **Validates: Requirements 3.2, 3.3, 3.4, 3.5**
        
        For the same input signals, the decision matrix should always produce
        the same output action and conviction.
        """
        now = datetime.now(timezone.utc)
        
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=impact_score,
            confidence=0.8,
            reasoning="Test news",
            source_items=["item1"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
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
                score=confluence_score,
                factors=["ma_alignment"],
                description="Neutral confluence",
            ),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=now,
        )
        
        evaluator = DecisionMatrixEvaluator()
        
        # Evaluate multiple times
        result1 = evaluator.evaluate(news_signal, technical_signal)
        result2 = evaluator.evaluate(news_signal, technical_signal)
        result3 = evaluator.evaluate(news_signal, technical_signal)
        
        # Verify consistency
        assert result1.action == result2.action == result3.action, (
            f"Decision matrix should be deterministic: "
            f"{result1.action.value}, {result2.action.value}, {result3.action.value}"
        )
        assert result1.conviction == result2.conviction == result3.conviction, (
            f"Conviction should be deterministic: "
            f"{result1.conviction.value}, {result2.conviction.value}, {result3.conviction.value}"
        )

    @given(
        sentiment=st.sampled_from(list(Sentiment)),
        impact_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_sentiment_score_mapping_is_bounded(
        self,
        sentiment: Sentiment,
        impact_score: float,
    ):
        """
        Property: Sentiment score mapping produces values in [-1.0, 1.0].
        
        **Validates: Requirement 3.1**
        
        The map_sentiment_score function should always produce values
        within the valid range.
        """
        score = map_sentiment_score(sentiment, impact_score)
        
        assert -1.0 <= score <= 1.0, (
            f"Sentiment score ({score}) should be in [-1.0, 1.0] "
            f"for sentiment={sentiment.value}, impact_score={impact_score}"
        )

    @given(
        condition=st.sampled_from(list(MarketCondition)),
        confluence_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_technical_score_mapping_is_bounded(
        self,
        condition: MarketCondition,
        confluence_score: float,
    ):
        """
        Property: Technical score mapping produces values in [-1.0, 1.0].
        
        **Validates: Requirement 3.1**
        
        The map_technical_score function should always produce values
        within the valid range.
        """
        score = map_technical_score(condition, confluence_score)
        
        assert -1.0 <= score <= 1.0, (
            f"Technical score ({score}) should be in [-1.0, 1.0] "
            f"for condition={condition.value}, confluence_score={confluence_score}"
        )

    @given(
        impact_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        confluence_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_strong_actions_require_high_conviction(
        self,
        impact_score: float,
        confluence_score: float,
    ):
        """
        Property: STRONG_BUY and STRONG_SELL always have HIGH conviction.
        
        **Validates: Requirement 3.6**
        
        When the decision matrix produces a STRONG_BUY or STRONG_SELL action,
        the conviction must always be HIGH.
        """
        now = datetime.now(timezone.utc)
        
        # Test STRONG_BUY case
        news_signal_bullish = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.VERY_BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=impact_score,
            confidence=0.9,
            reasoning="Very bullish news",
            source_items=["item1"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        technical_signal_oversold = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.DOWNTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=25.0,
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
                    level=110.0,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=confluence_score,
                factors=["rsi_oversold"],
                description="Oversold confluence",
            ),
            volume_trend="increasing",
            interest_rate_impact=0.1,
            timestamp=now,
        )
        
        evaluator = DecisionMatrixEvaluator()
        result = evaluator.evaluate(news_signal_bullish, technical_signal_oversold)
        
        if result.action == TradeAction.STRONG_BUY:
            assert result.conviction == Conviction.HIGH, (
                f"STRONG_BUY must have HIGH conviction, got {result.conviction.value}"
            )
        
        # Test STRONG_SELL case
        news_signal_bearish = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.VERY_BEARISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=impact_score,
            confidence=0.9,
            reasoning="Very bearish news",
            source_items=["item1"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        technical_signal_overbought = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.OVERBOUGHT,
            rsi=75.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(
                    level=90.0,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=105.0,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=confluence_score,
                factors=["rsi_overbought"],
                description="Overbought confluence",
            ),
            volume_trend="increasing",
            interest_rate_impact=-0.1,
            timestamp=now,
        )
        
        result = evaluator.evaluate(news_signal_bearish, technical_signal_overbought)
        
        if result.action == TradeAction.STRONG_SELL:
            assert result.conviction == Conviction.HIGH, (
                f"STRONG_SELL must have HIGH conviction, got {result.conviction.value}"
            )

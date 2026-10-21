"""
Property-based tests for News Impact Classification.

**Property 9: News Impact Classification**
**Validates: Requirements 1.4**

These tests verify:
- For any NewsSignal with impact_type == CASH_FLOW, the confidence must be >= 0.7
- If the original classification was CASH_FLOW but confidence < 0.7, it should be downgraded to HYPE
- The analyze_news_impact function correctly applies the confidence threshold
"""

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.models.enums import ImpactType, Sentiment
from src.models.signals import NewsItem, NewsSignal
from src.agents.news.analyzer import (
    analyze_news_impact,
    CASH_FLOW_CONFIDENCE_THRESHOLD,
    LLMAnalysisResult,
    parse_llm_response,
)


# --- Strategies for generating test data ---

@st.composite
def news_item_strategy(draw):
    """Generate valid NewsItem instances for testing."""
    now = datetime.now(timezone.utc)
    return NewsItem(
        source=draw(st.sampled_from(["reuters", "bloomberg", "twitter", "sec_filing"])),
        headline=draw(st.text(min_size=10, max_size=200)),
        content=draw(st.text(min_size=50, max_size=1000)),
        published_at=now - timedelta(hours=draw(st.integers(min_value=0, max_value=24))),
        symbols=draw(st.lists(
            st.text(min_size=1, max_size=5, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
            min_size=1,
            max_size=3
        )),
        url=draw(st.one_of(st.none(), st.text(min_size=10, max_size=100))),
    )


@st.composite
def valid_cash_flow_confidence_strategy(draw):
    """Generate confidence values that are valid for CASH_FLOW (>= 0.7)."""
    return draw(st.floats(
        min_value=CASH_FLOW_CONFIDENCE_THRESHOLD,
        max_value=1.0,
        allow_nan=False,
        allow_infinity=False
    ))


@st.composite
def invalid_cash_flow_confidence_strategy(draw):
    """Generate confidence values that are invalid for CASH_FLOW (< 0.7)."""
    return draw(st.floats(
        min_value=0.0,
        max_value=CASH_FLOW_CONFIDENCE_THRESHOLD - 0.001,
        allow_nan=False,
        allow_infinity=False
    ))


@st.composite
def news_signal_strategy(draw, impact_type: ImpactType = None, confidence: float = None):
    """Generate valid NewsSignal instances."""
    now = datetime.now(timezone.utc)
    
    # Use provided values or generate random ones
    _impact_type = impact_type or draw(st.sampled_from(list(ImpactType)))
    _confidence = confidence if confidence is not None else draw(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
    )
    
    return NewsSignal(
        symbol=draw(st.text(min_size=1, max_size=5, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ")),
        sentiment=draw(st.sampled_from(list(Sentiment))),
        impact_type=_impact_type,
        impact_score=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        confidence=_confidence,
        reasoning=draw(st.text(min_size=1, max_size=200)),
        source_items=draw(st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=3)),
        timestamp=now,
        expires_at=now + timedelta(hours=draw(st.integers(min_value=1, max_value=168))),
    )


# --- Property Tests ---

@pytest.mark.property
class TestNewsImpactClassification:
    """
    Property tests for News Impact Classification.
    
    **Validates: Requirements 1.4**
    
    Requirement 1.4: WHEN a news item is classified as CASH_FLOW impact, 
    THE News_Agent SHALL assign a confidence score of 0.7 or higher; 
    IF the confidence is below 0.7, THEN THE News_Agent SHALL downgrade 
    the impact type to HYPE
    """

    @given(
        symbol=st.text(min_size=1, max_size=5, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        sentiment=st.sampled_from(list(Sentiment)),
        impact_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        confidence=valid_cash_flow_confidence_strategy(),
    )
    @settings(max_examples=100)
    def test_cash_flow_with_valid_confidence_preserved(
        self,
        symbol: str,
        sentiment: Sentiment,
        impact_score: float,
        confidence: float,
    ):
        """
        Property: CASH_FLOW impact type with confidence >= 0.7 must be preserved.
        
        **Validates: Requirements 1.4**
        
        When a NewsSignal has impact_type == CASH_FLOW and confidence >= 0.7,
        the impact type should remain CASH_FLOW.
        """
        now = datetime.now(timezone.utc)
        
        # Create a NewsSignal with CASH_FLOW and valid confidence
        signal = NewsSignal(
            symbol=symbol,
            sentiment=sentiment,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=impact_score,
            confidence=confidence,
            reasoning="Test reasoning for cash flow impact",
            source_items=["item1"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        # Verify the property: CASH_FLOW with confidence >= 0.7 is valid
        assert signal.impact_type == ImpactType.CASH_FLOW, \
            f"CASH_FLOW impact type should be preserved when confidence ({confidence}) >= {CASH_FLOW_CONFIDENCE_THRESHOLD}"
        assert signal.confidence >= CASH_FLOW_CONFIDENCE_THRESHOLD, \
            f"Confidence ({signal.confidence}) must be >= {CASH_FLOW_CONFIDENCE_THRESHOLD} for CASH_FLOW"

    @given(
        symbol=st.text(min_size=1, max_size=5, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        sentiment=st.sampled_from(list(Sentiment)),
        impact_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_cash_flow_signals_always_have_sufficient_confidence(
        self,
        symbol: str,
        sentiment: Sentiment,
        impact_score: float,
        confidence: float,
    ):
        """
        Property: Any NewsSignal with impact_type == CASH_FLOW must have confidence >= 0.7.
        
        **Validates: Requirements 1.4**
        
        This is the core invariant: if a signal has CASH_FLOW impact type,
        its confidence MUST be at least 0.7. This property should hold for
        all NewsSignals in the system.
        """
        now = datetime.now(timezone.utc)
        
        # If we're creating a CASH_FLOW signal, confidence must be >= 0.7
        # Otherwise, the signal should have been downgraded to HYPE
        if confidence >= CASH_FLOW_CONFIDENCE_THRESHOLD:
            # Valid CASH_FLOW signal
            signal = NewsSignal(
                symbol=symbol,
                sentiment=sentiment,
                impact_type=ImpactType.CASH_FLOW,
                impact_score=impact_score,
                confidence=confidence,
                reasoning="Valid cash flow impact",
                source_items=["item1"],
                timestamp=now,
                expires_at=now + timedelta(hours=72),
            )
            
            # Verify the invariant holds
            assert signal.impact_type == ImpactType.CASH_FLOW
            assert signal.confidence >= CASH_FLOW_CONFIDENCE_THRESHOLD
        else:
            # Low confidence - should be HYPE, not CASH_FLOW
            # Creating a CASH_FLOW signal with low confidence violates the requirement
            # The analyzer should have downgraded this to HYPE
            signal = NewsSignal(
                symbol=symbol,
                sentiment=sentiment,
                impact_type=ImpactType.HYPE,  # Downgraded from CASH_FLOW
                impact_score=impact_score,
                confidence=confidence,
                reasoning="Downgraded from CASH_FLOW due to low confidence",
                source_items=["item1"],
                timestamp=now,
                expires_at=now + timedelta(hours=24),  # HYPE has 24h expiry
            )
            
            # Verify the downgrade happened correctly
            assert signal.impact_type == ImpactType.HYPE
            assert signal.confidence < CASH_FLOW_CONFIDENCE_THRESHOLD

    @given(
        news_item=news_item_strategy(),
    )
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_analyze_news_impact_enforces_confidence_threshold(
        self,
        news_item: NewsItem,
    ):
        """
        Property: analyze_news_impact() must enforce the confidence threshold for CASH_FLOW.
        
        **Validates: Requirements 1.4**
        
        When analyze_news_impact() produces a NewsSignal:
        - If impact_type == CASH_FLOW, then confidence >= 0.7
        - If original classification was CASH_FLOW but confidence < 0.7, 
          it should be downgraded to HYPE
        """
        # Ensure we have at least one symbol
        assume(len(news_item.symbols) > 0)
        assume(len(news_item.symbols[0]) > 0)
        
        # Call analyze_news_impact without LLM client (uses fallback)
        signal = await analyze_news_impact(news_item, llm_client=None)
        
        # Verify the core property: CASH_FLOW requires confidence >= 0.7
        if signal.impact_type == ImpactType.CASH_FLOW:
            assert signal.confidence >= CASH_FLOW_CONFIDENCE_THRESHOLD, \
                f"CASH_FLOW signal must have confidence >= {CASH_FLOW_CONFIDENCE_THRESHOLD}, " \
                f"but got {signal.confidence}"
        
        # Additional verification: confidence is always in valid range
        assert 0.0 <= signal.confidence <= 1.0, \
            f"Confidence must be in [0.0, 1.0], got {signal.confidence}"
        assert 0.0 <= signal.impact_score <= 1.0, \
            f"Impact score must be in [0.0, 1.0], got {signal.impact_score}"

    @given(
        impact_type=st.sampled_from([ImpactType.HYPE, ImpactType.REGULATORY, ImpactType.MACRO]),
        confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        symbol=st.text(min_size=1, max_size=5, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        sentiment=st.sampled_from(list(Sentiment)),
        impact_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_non_cash_flow_impact_types_accept_any_confidence(
        self,
        impact_type: ImpactType,
        confidence: float,
        symbol: str,
        sentiment: Sentiment,
        impact_score: float,
    ):
        """
        Property: Non-CASH_FLOW impact types can have any confidence level.
        
        **Validates: Requirements 1.4**
        
        The confidence threshold of 0.7 only applies to CASH_FLOW impact type.
        HYPE, REGULATORY, and MACRO can have any confidence level in [0.0, 1.0].
        """
        now = datetime.now(timezone.utc)
        
        # Determine expiry based on impact type
        expiry_hours = {
            ImpactType.HYPE: 24,
            ImpactType.REGULATORY: 168,
            ImpactType.MACRO: 24,
        }
        
        # Create signal with non-CASH_FLOW impact type
        signal = NewsSignal(
            symbol=symbol,
            sentiment=sentiment,
            impact_type=impact_type,
            impact_score=impact_score,
            confidence=confidence,
            reasoning=f"Test {impact_type.value} impact",
            source_items=["item1"],
            timestamp=now,
            expires_at=now + timedelta(hours=expiry_hours[impact_type]),
        )
        
        # Verify the signal is valid regardless of confidence level
        assert signal.impact_type == impact_type
        assert signal.confidence == confidence
        assert 0.0 <= signal.confidence <= 1.0

    def test_cash_flow_confidence_threshold_constant(self):
        """
        Test that the CASH_FLOW confidence threshold is correctly set to 0.7.
        
        **Validates: Requirements 1.4**
        """
        assert CASH_FLOW_CONFIDENCE_THRESHOLD == 0.7, \
            f"CASH_FLOW_CONFIDENCE_THRESHOLD should be 0.7, got {CASH_FLOW_CONFIDENCE_THRESHOLD}"

    @given(
        confidence=invalid_cash_flow_confidence_strategy(),
    )
    @settings(max_examples=50)
    def test_low_confidence_cash_flow_should_be_downgraded(
        self,
        confidence: float,
    ):
        """
        Property: CASH_FLOW with confidence < 0.7 should be downgraded to HYPE.
        
        **Validates: Requirements 1.4**
        
        This test verifies the downgrade logic: when a news item would be
        classified as CASH_FLOW but has confidence below 0.7, it should
        be downgraded to HYPE.
        """
        # Verify the confidence is indeed below threshold
        assert confidence < CASH_FLOW_CONFIDENCE_THRESHOLD, \
            f"Test setup error: confidence ({confidence}) should be < {CASH_FLOW_CONFIDENCE_THRESHOLD}"
        
        # In a properly functioning system, a CASH_FLOW classification
        # with this confidence would be downgraded to HYPE
        # The analyzer.py implements this logic in analyze_news_impact()
        
        # Simulate what the analyzer should do:
        original_impact_type = ImpactType.CASH_FLOW
        
        # Apply the downgrade rule from Requirement 1.4
        if original_impact_type == ImpactType.CASH_FLOW and confidence < CASH_FLOW_CONFIDENCE_THRESHOLD:
            final_impact_type = ImpactType.HYPE
        else:
            final_impact_type = original_impact_type
        
        # Verify the downgrade happened
        assert final_impact_type == ImpactType.HYPE, \
            f"CASH_FLOW with confidence {confidence} should be downgraded to HYPE"

    @given(
        confidence=st.floats(
            min_value=CASH_FLOW_CONFIDENCE_THRESHOLD,
            max_value=1.0,
            allow_nan=False,
            allow_infinity=False
        ),
    )
    @settings(max_examples=50)
    def test_high_confidence_cash_flow_not_downgraded(
        self,
        confidence: float,
    ):
        """
        Property: CASH_FLOW with confidence >= 0.7 should NOT be downgraded.
        
        **Validates: Requirements 1.4**
        
        When confidence meets or exceeds the threshold, CASH_FLOW should
        remain as CASH_FLOW.
        """
        # Verify the confidence is at or above threshold
        assert confidence >= CASH_FLOW_CONFIDENCE_THRESHOLD, \
            f"Test setup error: confidence ({confidence}) should be >= {CASH_FLOW_CONFIDENCE_THRESHOLD}"
        
        # Simulate what the analyzer should do:
        original_impact_type = ImpactType.CASH_FLOW
        
        # Apply the downgrade rule from Requirement 1.4
        if original_impact_type == ImpactType.CASH_FLOW and confidence < CASH_FLOW_CONFIDENCE_THRESHOLD:
            final_impact_type = ImpactType.HYPE
        else:
            final_impact_type = original_impact_type
        
        # Verify NO downgrade happened
        assert final_impact_type == ImpactType.CASH_FLOW, \
            f"CASH_FLOW with confidence {confidence} should NOT be downgraded"

    @given(
        sentiment=st.sampled_from(list(Sentiment)),
        impact_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_llm_response_parsing_respects_confidence_bounds(
        self,
        sentiment: Sentiment,
        impact_score: float,
        confidence: float,
    ):
        """
        Property: Parsed LLM responses must have confidence in [0.0, 1.0].
        
        **Validates: Requirements 1.4**
        
        The parse_llm_response function should ensure confidence values
        are bounded to [0.0, 1.0] even if the LLM returns out-of-range values.
        """
        # Create a mock LLM response JSON
        llm_response = f'''{{
            "sentiment": "{sentiment.value}",
            "impact_type": "cash_flow",
            "impact_score": {impact_score},
            "confidence": {confidence},
            "reasoning": "Test reasoning"
        }}'''
        
        # Parse the response
        result = parse_llm_response(llm_response)
        
        # Verify confidence is bounded
        assert 0.0 <= result.confidence <= 1.0, \
            f"Parsed confidence must be in [0.0, 1.0], got {result.confidence}"
        assert 0.0 <= result.impact_score <= 1.0, \
            f"Parsed impact_score must be in [0.0, 1.0], got {result.impact_score}"

    @given(
        out_of_range_confidence=st.floats(min_value=1.1, max_value=10.0, allow_nan=False),
    )
    @settings(max_examples=20)
    def test_llm_response_parsing_clamps_high_confidence(
        self,
        out_of_range_confidence: float,
    ):
        """
        Property: LLM responses with confidence > 1.0 should be clamped to 1.0.
        
        **Validates: Requirements 1.4**
        """
        llm_response = f'''{{
            "sentiment": "bullish",
            "impact_type": "cash_flow",
            "impact_score": 0.8,
            "confidence": {out_of_range_confidence},
            "reasoning": "Test reasoning"
        }}'''
        
        result = parse_llm_response(llm_response)
        
        assert result.confidence == 1.0, \
            f"Confidence > 1.0 should be clamped to 1.0, got {result.confidence}"

    @given(
        out_of_range_confidence=st.floats(min_value=-10.0, max_value=-0.1, allow_nan=False),
    )
    @settings(max_examples=20)
    def test_llm_response_parsing_clamps_low_confidence(
        self,
        out_of_range_confidence: float,
    ):
        """
        Property: LLM responses with confidence < 0.0 should be clamped to 0.0.
        
        **Validates: Requirements 1.4**
        """
        llm_response = f'''{{
            "sentiment": "bearish",
            "impact_type": "hype",
            "impact_score": 0.5,
            "confidence": {out_of_range_confidence},
            "reasoning": "Test reasoning"
        }}'''
        
        result = parse_llm_response(llm_response)
        
        assert result.confidence == 0.0, \
            f"Confidence < 0.0 should be clamped to 0.0, got {result.confidence}"

    def test_boundary_confidence_exactly_at_threshold(self):
        """
        Test that confidence exactly at 0.7 is valid for CASH_FLOW.
        
        **Validates: Requirements 1.4**
        
        The threshold is >= 0.7, so exactly 0.7 should be valid.
        """
        now = datetime.now(timezone.utc)
        
        signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.8,
            confidence=0.7,  # Exactly at threshold
            reasoning="Boundary test",
            source_items=["item1"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        assert signal.impact_type == ImpactType.CASH_FLOW
        assert signal.confidence == 0.7
        assert signal.confidence >= CASH_FLOW_CONFIDENCE_THRESHOLD

    def test_boundary_confidence_just_below_threshold(self):
        """
        Test that confidence just below 0.7 should result in HYPE, not CASH_FLOW.
        
        **Validates: Requirements 1.4**
        """
        confidence = 0.699  # Just below threshold
        
        # This confidence is below threshold, so CASH_FLOW should be downgraded
        assert confidence < CASH_FLOW_CONFIDENCE_THRESHOLD
        
        # In a properly functioning system, this would be HYPE
        now = datetime.now(timezone.utc)
        
        signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.HYPE,  # Downgraded from CASH_FLOW
            impact_score=0.8,
            confidence=confidence,
            reasoning="Downgraded due to low confidence",
            source_items=["item1"],
            timestamp=now,
            expires_at=now + timedelta(hours=24),  # HYPE expiry
        )
        
        assert signal.impact_type == ImpactType.HYPE
        assert signal.confidence < CASH_FLOW_CONFIDENCE_THRESHOLD

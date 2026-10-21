"""
Property-based tests for Portfolio Exposure.

**Property 10: Portfolio Exposure**
**Validates: Requirements 5.3, 5.5**

These tests verify:
- Correlated exposure does not exceed 20% (Requirement 5.3)
- Open positions do not exceed 10 (Requirement 5.5)
- Position is rejected or reduced when limits would be exceeded
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
    TradingHorizon,
    TrendDirection,
)
from src.models.signals import (
    ConfluenceResult,
    NewsSignal,
    SupportResistance,
    TechnicalSignal,
)
from src.models.trading import TradeDecision
from src.agents.risk.config import ExposureConfig
from src.agents.risk.exposure_tracker import ExposureTracker, OpenPosition


# --- Helper functions ---

def create_trade_decision(symbol: str, position_size_pct: float) -> TradeDecision:
    """Create a valid trade decision for testing."""
    now = datetime.now(timezone.utc)
    entry_price = 100.0
    stop_loss = 95.0
    take_profit = 110.0
    
    news_signal = NewsSignal(
        symbol=symbol,
        sentiment=Sentiment.BULLISH,
        impact_type=ImpactType.CASH_FLOW,
        impact_score=0.8,
        confidence=0.85,
        reasoning="Test",
        source_items=["item1"],
        timestamp=now,
        expires_at=now + timedelta(hours=72),
    )
    
    tech_signal = TechnicalSignal(
        symbol=symbol,
        trend=TrendDirection.UPTREND,
        condition=MarketCondition.OVERSOLD,
        rsi=30.0,
        current_price=entry_price,
        support_levels=[SupportResistance(level=90.0, strength=0.8, timeframe="1y", last_tested=now - timedelta(days=30))],
        resistance_levels=[SupportResistance(level=115.0, strength=0.7, timeframe="1y", last_tested=now - timedelta(days=30))],
        confluence=ConfluenceResult(score=0.8, factors=["rsi_oversold"], description="Test"),
        volume_trend="increasing",
        interest_rate_impact=0.1,
        timestamp=now,
    )
    
    return TradeDecision(
        symbol=symbol,
        action=TradeAction.BUY,
        conviction=Conviction.MEDIUM,
        horizon=TradingHorizon.SHORT_TERM,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_size_pct=position_size_pct,
        risk_reward_ratio=2.0,
        reasoning="Test",
        news_signal=news_signal,
        technical_signal=tech_signal,
        timestamp=now,
        expires_at=now + timedelta(hours=4),
    )


# --- Property Tests ---

@pytest.mark.property
class TestPortfolioExposure:
    """
    Property tests for Portfolio Exposure.
    
    **Validates: Requirements 5.3, 5.5**
    """

    @given(
        num_positions=st.integers(min_value=0, max_value=15),
        max_open_positions=st.integers(min_value=5, max_value=15),
    )
    @settings(max_examples=100)
    def test_open_position_limit_enforced(
        self,
        num_positions: int,
        max_open_positions: int,
    ):
        """
        Property: New trades are rejected when max open positions reached.
        
        **Validates: Requirement 5.5**
        
        When open_positions >= max_open_positions:
        - New trades for different symbols are rejected
        - Trades for existing symbols are allowed (modification)
        """
        config = ExposureConfig(
            max_open_positions=max_open_positions,
            max_correlated_exposure_pct=1.0,  # High to not interfere
        )
        tracker = ExposureTracker(config)
        
        # Add existing positions
        symbols = [f"SYM{i}" for i in range(num_positions)]
        for symbol in symbols:
            tracker.add_position(OpenPosition(
                symbol=symbol,
                position_size_pct=0.02,
                entry_price=100.0,
            ))
        
        # Try to add a new position
        new_symbol = "NEWSYM"
        decision = create_trade_decision(new_symbol, 0.05)
        result = tracker.validate(decision)
        
        # Property: Rejected if at limit, allowed if under
        if num_positions >= max_open_positions:
            assert not result.is_valid, \
                f"Should reject new position when {num_positions} >= {max_open_positions}"
            assert result.rejection_reason is not None, \
                "Rejection reason must be provided"
            assert "position" in result.rejection_reason.lower(), \
                "Rejection reason should mention positions"
        else:
            assert result.is_valid, \
                f"Should allow new position when {num_positions} < {max_open_positions}"

    @given(
        num_positions=st.integers(min_value=10, max_value=15),
    )
    @settings(max_examples=50)
    def test_existing_symbol_allowed_at_limit(
        self,
        num_positions: int,
    ):
        """
        Property: Trades for existing symbols are allowed even at position limit.
        
        **Validates: Requirement 5.5**
        
        When modifying an existing position, the limit check should pass.
        """
        max_open_positions = 10
        config = ExposureConfig(
            max_open_positions=max_open_positions,
            max_correlated_exposure_pct=1.0,  # High to not interfere
        )
        tracker = ExposureTracker(config)
        
        # Add positions up to the limit
        symbols = [f"SYM{i}" for i in range(max_open_positions)]
        for symbol in symbols:
            tracker.add_position(OpenPosition(
                symbol=symbol,
                position_size_pct=0.02,
                entry_price=100.0,
            ))
        
        # Try to modify an existing position
        existing_symbol = symbols[0]
        decision = create_trade_decision(existing_symbol, 0.05)
        result = tracker.validate(decision)
        
        # Property: Modification of existing position is allowed
        assert result.is_valid, \
            f"Should allow modification of existing position even at limit"

    @given(
        existing_exposure=st.floats(min_value=0.0, max_value=0.25, allow_nan=False),
        new_position_size=st.floats(min_value=0.01, max_value=0.15, allow_nan=False),
        max_correlated_exposure=st.floats(min_value=0.10, max_value=0.30, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_correlated_exposure_limit_enforced(
        self,
        existing_exposure: float,
        new_position_size: float,
        max_correlated_exposure: float,
    ):
        """
        Property: Correlated exposure does not exceed max_correlated_exposure_pct.
        
        **Validates: Requirement 5.3**
        
        When adding a position in a correlated asset:
        - If total exposure would exceed limit, position is rejected or reduced
        - If total exposure is within limit, position is approved
        """
        config = ExposureConfig(
            max_open_positions=100,  # High to not interfere
            max_correlated_exposure_pct=max_correlated_exposure,
            correlation_groups={"tech": ["AAPL", "MSFT", "GOOGL"]},
        )
        tracker = ExposureTracker(config)
        
        # Add existing correlated position
        if existing_exposure > 0:
            tracker.add_position(OpenPosition(
                symbol="MSFT",
                position_size_pct=existing_exposure,
                entry_price=100.0,
            ))
        
        # Try to add a new correlated position
        decision = create_trade_decision("AAPL", new_position_size)
        result = tracker.validate(decision)
        
        total_exposure = existing_exposure + new_position_size
        
        # Property: If total would exceed limit, must be rejected or reduced
        if total_exposure > max_correlated_exposure:
            if result.is_valid:
                # If approved, must have been reduced
                assert result.adjusted_size_pct is not None, \
                    f"Position should be reduced when exposure {total_exposure:.4f} > limit {max_correlated_exposure:.4f}"
                final_exposure = existing_exposure + result.adjusted_size_pct
                assert final_exposure <= max_correlated_exposure + 0.001, \
                    f"Final exposure {final_exposure:.4f} exceeds limit {max_correlated_exposure:.4f}"
            # else: rejected is also valid
        else:
            # Under limit, should be approved without adjustment
            assert result.is_valid, \
                f"Should approve when exposure {total_exposure:.4f} <= limit {max_correlated_exposure:.4f}"

    @given(
        num_correlated=st.integers(min_value=1, max_value=5),
        position_size=st.floats(min_value=0.01, max_value=0.05, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_correlated_exposure_sums_correctly(
        self,
        num_correlated: int,
        position_size: float,
    ):
        """
        Property: Correlated exposure is the sum of all positions in the same group.
        
        **Validates: Requirement 5.3**
        """
        config = ExposureConfig(
            max_open_positions=100,
            max_correlated_exposure_pct=1.0,  # High to not interfere
            correlation_groups={"tech": ["AAPL", "MSFT", "GOOGL", "META", "AMZN"]},
        )
        tracker = ExposureTracker(config)
        
        # Add correlated positions
        tech_symbols = ["AAPL", "MSFT", "GOOGL", "META", "AMZN"][:num_correlated]
        for symbol in tech_symbols:
            tracker.add_position(OpenPosition(
                symbol=symbol,
                position_size_pct=position_size,
                entry_price=100.0,
            ))
        
        # Check correlated exposure for any tech symbol
        exposure = tracker.get_correlated_exposure("AAPL")
        expected_exposure = num_correlated * position_size
        
        # Property: Correlated exposure equals sum of all positions in group
        assert abs(exposure - expected_exposure) < 0.0001, \
            f"Correlated exposure incorrect: expected {expected_exposure:.4f}, got {exposure:.4f}"

    @given(
        tech_positions=st.integers(min_value=0, max_value=3),
        finance_positions=st.integers(min_value=0, max_value=3),
        position_size=st.floats(min_value=0.02, max_value=0.05, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_uncorrelated_positions_tracked_separately(
        self,
        tech_positions: int,
        finance_positions: int,
        position_size: float,
    ):
        """
        Property: Positions in different correlation groups are tracked separately.
        
        **Validates: Requirement 5.3**
        
        Adding positions in one group should not affect exposure in another group.
        """
        config = ExposureConfig(
            max_open_positions=100,
            max_correlated_exposure_pct=0.20,
            correlation_groups={
                "tech": ["AAPL", "MSFT", "GOOGL"],
                "finance": ["JPM", "BAC", "GS"],
            },
        )
        tracker = ExposureTracker(config)
        
        # Add tech positions
        tech_symbols = ["AAPL", "MSFT", "GOOGL"][:tech_positions]
        for symbol in tech_symbols:
            tracker.add_position(OpenPosition(
                symbol=symbol,
                position_size_pct=position_size,
                entry_price=100.0,
            ))
        
        # Add finance positions
        finance_symbols = ["JPM", "BAC", "GS"][:finance_positions]
        for symbol in finance_symbols:
            tracker.add_position(OpenPosition(
                symbol=symbol,
                position_size_pct=position_size,
                entry_price=100.0,
            ))
        
        # Check exposures
        tech_exposure = tracker.get_correlated_exposure("AAPL")
        finance_exposure = tracker.get_correlated_exposure("JPM")
        
        expected_tech = tech_positions * position_size
        expected_finance = finance_positions * position_size
        
        # Property: Each group's exposure is independent
        assert abs(tech_exposure - expected_tech) < 0.0001, \
            f"Tech exposure incorrect: expected {expected_tech:.4f}, got {tech_exposure:.4f}"
        assert abs(finance_exposure - expected_finance) < 0.0001, \
            f"Finance exposure incorrect: expected {expected_finance:.4f}, got {finance_exposure:.4f}"

    @given(
        position_size=st.floats(min_value=0.01, max_value=0.10, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_uncorrelated_symbol_only_counts_itself(
        self,
        position_size: float,
    ):
        """
        Property: Symbols not in any correlation group only count their own exposure.
        
        **Validates: Requirement 5.3**
        """
        config = ExposureConfig(
            max_open_positions=100,
            max_correlated_exposure_pct=0.20,
            correlation_groups={"tech": ["AAPL", "MSFT"]},
        )
        tracker = ExposureTracker(config)
        
        # Add a position for an uncorrelated symbol
        tracker.add_position(OpenPosition(
            symbol="UNKNOWN",
            position_size_pct=position_size,
            entry_price=100.0,
        ))
        
        # Add a tech position
        tracker.add_position(OpenPosition(
            symbol="AAPL",
            position_size_pct=position_size,
            entry_price=100.0,
        ))
        
        # Check exposure for uncorrelated symbol
        unknown_exposure = tracker.get_correlated_exposure("UNKNOWN")
        
        # Property: Uncorrelated symbol only counts itself
        assert abs(unknown_exposure - position_size) < 0.0001, \
            f"Uncorrelated exposure should be {position_size:.4f}, got {unknown_exposure:.4f}"

    @given(
        existing_size=st.floats(min_value=0.05, max_value=0.15, allow_nan=False),
        new_size=st.floats(min_value=0.05, max_value=0.15, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_position_reduced_to_fit_exposure_limit(
        self,
        existing_size: float,
        new_size: float,
    ):
        """
        Property: Position is reduced (not rejected) when it can fit within limit.
        
        **Validates: Requirement 5.3**
        
        When there's room for a smaller position, it should be adjusted down.
        """
        max_exposure = 0.20
        assume(existing_size < max_exposure)  # Must have some room
        assume(existing_size + new_size > max_exposure)  # Must exceed limit
        
        config = ExposureConfig(
            max_open_positions=100,
            max_correlated_exposure_pct=max_exposure,
            correlation_groups={"tech": ["AAPL", "MSFT"]},
        )
        tracker = ExposureTracker(config)
        
        # Add existing position
        tracker.add_position(OpenPosition(
            symbol="MSFT",
            position_size_pct=existing_size,
            entry_price=100.0,
        ))
        
        # Try to add new position that would exceed limit
        decision = create_trade_decision("AAPL", new_size)
        result = tracker.validate(decision)
        
        available_room = max_exposure - existing_size
        
        # Property: If there's room, position should be reduced, not rejected
        if available_room > 0.001:  # Small threshold for floating point
            assert result.is_valid, \
                f"Should approve reduced position when room available ({available_room:.4f})"
            assert result.adjusted_size_pct is not None, \
                "Should have adjusted size"
            assert result.adjusted_size_pct <= available_room + 0.001, \
                f"Adjusted size {result.adjusted_size_pct:.4f} exceeds available room {available_room:.4f}"

    @given(
        num_positions=st.integers(min_value=0, max_value=12),
    )
    @settings(max_examples=50)
    def test_position_count_accurate(
        self,
        num_positions: int,
    ):
        """
        Property: Open position count is always accurate.
        
        **Validates: Requirement 5.5**
        """
        config = ExposureConfig(max_open_positions=15)
        tracker = ExposureTracker(config)
        
        # Add positions
        for i in range(num_positions):
            tracker.add_position(OpenPosition(
                symbol=f"SYM{i}",
                position_size_pct=0.02,
                entry_price=100.0,
            ))
        
        # Property: Count matches number of added positions
        assert tracker.get_open_position_count() == num_positions, \
            f"Position count incorrect: expected {num_positions}, got {tracker.get_open_position_count()}"
        
        # Remove some positions
        positions_to_remove = num_positions // 2
        for i in range(positions_to_remove):
            tracker.remove_position(f"SYM{i}")
        
        expected_remaining = num_positions - positions_to_remove
        
        # Property: Count updated after removals
        assert tracker.get_open_position_count() == expected_remaining, \
            f"Position count after removal incorrect: expected {expected_remaining}, got {tracker.get_open_position_count()}"

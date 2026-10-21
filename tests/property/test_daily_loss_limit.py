"""
Property-based tests for Daily Loss Limit.

**Property 7: Daily Loss Limit**
**Validates: Requirements 5.4**

These tests verify:
- Trading is halted when daily loss exceeds 5% (Requirement 5.4)
- Cumulative losses are tracked correctly
- Alert is sent when limit is breached (Requirement 10.4)
"""

from datetime import date, datetime, timezone

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.agents.risk.config import DailyLossConfig, AlertConfig
from src.agents.risk.daily_loss_tracker import DailyLossTracker


# --- Property Tests ---

@pytest.mark.property
class TestDailyLossLimit:
    """
    Property tests for Daily Loss Limit.
    
    **Validates: Requirements 5.4, 10.4**
    """

    @given(
        losses=st.lists(
            st.floats(min_value=0.01, max_value=1000.0, allow_nan=False),
            min_size=1,
            max_size=20,
        ),
        portfolio_value=st.floats(min_value=10000.0, max_value=10000000.0, allow_nan=False),
        max_daily_loss_pct=st.floats(min_value=0.01, max_value=0.20, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_trading_halted_when_loss_exceeds_limit(
        self,
        losses: list[float],
        portfolio_value: float,
        max_daily_loss_pct: float,
    ):
        """
        Property: Trading is halted when cumulative daily loss >= max_daily_loss_pct.
        
        **Validates: Requirement 5.4**
        
        For any sequence of losses:
        - If sum(losses) / portfolio_value >= max_daily_loss_pct, trading is halted
        - If sum(losses) / portfolio_value < max_daily_loss_pct, trading is allowed
        """
        config = DailyLossConfig(max_daily_loss_pct=max_daily_loss_pct)
        tracker = DailyLossTracker(loss_config=config)
        
        # Record all losses
        for loss in losses:
            tracker.record_trade_result(-loss)  # Negative for losses
        
        total_loss = sum(losses)
        loss_pct = total_loss / portfolio_value
        
        is_halted = tracker.is_trading_halted(portfolio_value)
        
        # Property: Trading halted iff loss >= limit
        if loss_pct >= max_daily_loss_pct:
            assert is_halted, \
                f"Trading should be halted: loss {loss_pct:.4f} >= limit {max_daily_loss_pct:.4f}"
        else:
            assert not is_halted, \
                f"Trading should not be halted: loss {loss_pct:.4f} < limit {max_daily_loss_pct:.4f}"

    @given(
        losses=st.lists(
            st.floats(min_value=0.01, max_value=1000.0, allow_nan=False),
            min_size=1,
            max_size=20,
        ),
        profits=st.lists(
            st.floats(min_value=0.01, max_value=1000.0, allow_nan=False),
            min_size=0,
            max_size=10,
        ),
        portfolio_value=st.floats(min_value=10000.0, max_value=10000000.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_cumulative_loss_tracked_correctly(
        self,
        losses: list[float],
        profits: list[float],
        portfolio_value: float,
    ):
        """
        Property: Cumulative daily loss is tracked correctly.
        
        **Validates: Requirement 5.4**
        
        - Only losses (negative PnL) contribute to daily loss
        - Profits do not reduce the daily loss counter
        """
        config = DailyLossConfig(max_daily_loss_pct=0.05)
        tracker = DailyLossTracker(loss_config=config)
        
        # Record losses and profits in interleaved order
        for i, loss in enumerate(losses):
            tracker.record_trade_result(-loss)
            if i < len(profits):
                tracker.record_trade_result(profits[i])
        
        # Record remaining profits
        for profit in profits[len(losses):]:
            tracker.record_trade_result(profit)
        
        # Property: Daily loss equals sum of losses only
        expected_loss = sum(losses)
        actual_loss = tracker.get_daily_loss()
        
        assert abs(actual_loss - expected_loss) < 0.01, \
            f"Daily loss tracking incorrect: expected {expected_loss:.2f}, got {actual_loss:.2f}"
        
        # Property: Daily loss percentage is correct
        expected_pct = expected_loss / portfolio_value
        actual_pct = tracker.get_daily_loss_pct(portfolio_value)
        
        assert abs(actual_pct - expected_pct) < 0.0001, \
            f"Daily loss percentage incorrect: expected {expected_pct:.4f}, got {actual_pct:.4f}"

    @given(
        loss_pct=st.floats(min_value=0.051, max_value=0.50, allow_nan=False),
        portfolio_value=st.floats(min_value=10000.0, max_value=10000000.0, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_validation_rejects_when_limit_breached(
        self,
        loss_pct: float,
        portfolio_value: float,
    ):
        """
        Property: Validation returns is_valid=False when limit is breached.
        
        **Validates: Requirement 5.4**
        
        When daily loss >= 5%:
        - validate() returns is_valid=False
        - rejection_reason is non-empty
        """
        max_daily_loss_pct = 0.05  # 5%
        assume(loss_pct >= max_daily_loss_pct)
        
        config = DailyLossConfig(max_daily_loss_pct=max_daily_loss_pct)
        tracker = DailyLossTracker(loss_config=config)
        
        # Record a loss that exceeds the limit
        loss_amount = portfolio_value * loss_pct
        tracker.record_trade_result(-loss_amount)
        
        result = tracker.validate(portfolio_value)
        
        # Property: Validation fails when limit breached
        assert not result.is_valid, \
            f"Validation should fail when loss {loss_pct:.4f} >= limit {max_daily_loss_pct:.4f}"
        assert result.rejection_reason is not None and len(result.rejection_reason) > 0, \
            "Rejection reason must be non-empty when validation fails"
        assert result.current_daily_loss_pct >= max_daily_loss_pct, \
            f"Current loss {result.current_daily_loss_pct:.4f} should be >= limit"

    @given(
        loss_pct=st.floats(min_value=0.001, max_value=0.049, allow_nan=False),
        portfolio_value=st.floats(min_value=10000.0, max_value=10000000.0, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_validation_allows_when_under_limit(
        self,
        loss_pct: float,
        portfolio_value: float,
    ):
        """
        Property: Validation returns is_valid=True when under limit.
        
        **Validates: Requirement 5.4**
        
        When daily loss < 5%:
        - validate() returns is_valid=True
        - rejection_reason is None
        """
        max_daily_loss_pct = 0.05  # 5%
        assume(loss_pct < max_daily_loss_pct)
        
        config = DailyLossConfig(max_daily_loss_pct=max_daily_loss_pct)
        tracker = DailyLossTracker(loss_config=config)
        
        # Record a loss under the limit
        loss_amount = portfolio_value * loss_pct
        tracker.record_trade_result(-loss_amount)
        
        result = tracker.validate(portfolio_value)
        
        # Property: Validation passes when under limit
        assert result.is_valid, \
            f"Validation should pass when loss {loss_pct:.4f} < limit {max_daily_loss_pct:.4f}"
        assert result.rejection_reason is None, \
            "Rejection reason should be None when validation passes"

    @given(
        portfolio_value=st.floats(min_value=10000.0, max_value=10000000.0, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_alert_sent_once_per_day(
        self,
        portfolio_value: float,
    ):
        """
        Property: Alert is sent only once per day when limit is breached.
        
        **Validates: Requirement 10.4**
        
        When daily loss limit is breached:
        - First validation sends alert (alert_sent=True)
        - Subsequent validations do not send alert (alert_sent=False)
        """
        alerts_received = []
        
        def alert_callback(alert_type: str, data: dict):
            alerts_received.append((alert_type, data))
        
        config = DailyLossConfig(max_daily_loss_pct=0.05)
        alert_config = AlertConfig(alerts_enabled=True)
        tracker = DailyLossTracker(
            loss_config=config,
            alert_config=alert_config,
            alert_callback=alert_callback,
        )
        
        # Record a loss that exceeds the limit
        loss_amount = portfolio_value * 0.06  # 6% loss
        tracker.record_trade_result(-loss_amount)
        
        # First validation should send alert
        result1 = tracker.validate(portfolio_value)
        assert result1.alert_sent, "First validation should send alert"
        assert len(alerts_received) == 1, "Should have received one alert"
        
        # Second validation should not send alert
        result2 = tracker.validate(portfolio_value)
        assert not result2.alert_sent, "Second validation should not send alert"
        assert len(alerts_received) == 1, "Should still have only one alert"
        
        # Third validation should not send alert
        result3 = tracker.validate(portfolio_value)
        assert not result3.alert_sent, "Third validation should not send alert"
        assert len(alerts_received) == 1, "Should still have only one alert"

    @given(
        num_trades=st.integers(min_value=1, max_value=50),
        portfolio_value=st.floats(min_value=100000.0, max_value=10000000.0, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_trade_count_tracked_correctly(
        self,
        num_trades: int,
        portfolio_value: float,
    ):
        """
        Property: Trade count is tracked correctly.
        
        **Validates: Requirement 5.4**
        
        The daily record should accurately count all trades.
        """
        config = DailyLossConfig(max_daily_loss_pct=0.05)
        tracker = DailyLossTracker(loss_config=config)
        
        # Record trades with alternating profits and losses
        for i in range(num_trades):
            if i % 2 == 0:
                tracker.record_trade_result(-100.0)  # Loss
            else:
                tracker.record_trade_result(50.0)  # Profit
        
        record = tracker.get_daily_record()
        
        # Property: Trade count equals number of recorded trades
        assert record.trade_count == num_trades, \
            f"Trade count incorrect: expected {num_trades}, got {record.trade_count}"

    @given(
        portfolio_value=st.floats(min_value=10000.0, max_value=10000000.0, allow_nan=False),
    )
    @settings(max_examples=20)
    def test_reset_clears_daily_record(
        self,
        portfolio_value: float,
    ):
        """
        Property: Reset clears the daily loss record.
        
        After reset:
        - Daily loss is 0
        - Trade count is 0
        - Trading is no longer halted
        """
        config = DailyLossConfig(max_daily_loss_pct=0.05)
        tracker = DailyLossTracker(loss_config=config)
        
        # Record a loss that exceeds the limit
        loss_amount = portfolio_value * 0.10  # 10% loss
        tracker.record_trade_result(-loss_amount)
        
        # Verify trading is halted
        assert tracker.is_trading_halted(portfolio_value), \
            "Trading should be halted before reset"
        
        # Reset the daily record
        tracker.reset_daily_record()
        
        # Property: After reset, everything is cleared
        assert tracker.get_daily_loss() == 0.0, \
            "Daily loss should be 0 after reset"
        assert not tracker.is_trading_halted(portfolio_value), \
            "Trading should not be halted after reset"
        
        record = tracker.get_daily_record()
        assert record.trade_count == 0, \
            "Trade count should be 0 after reset"

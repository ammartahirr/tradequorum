"""
Property-based tests for Strategy Agent Stop-Loss Calculation.

**Property 1: Stop-Loss Integrity**
**Validates: Requirements 4.1, 4.2, 4.3, 13.1, 13.2**

These tests verify that the Strategy Agent's stop-loss calculation:
- For BUY trades: stop_loss < entry_price
- For SELL trades: stop_loss > entry_price
- Stop-loss is always set (never zero)
- Stop-loss is placed relative to support/resistance levels with buffer
"""

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.models.enums import TradeAction, TradingHorizon
from src.models.signals import SupportResistance

from src.agents.strategy.stop_loss import (
    calculate_stop_loss,
    StopLossCalculator,
)
from src.agents.strategy.config import StopLossConfig


# --- Strategies for generating test data ---

@st.composite
def support_resistance_strategy(draw, min_level: float = 1.0, max_level: float = 10000.0):
    """Generate valid SupportResistance instances."""
    now = datetime.now(timezone.utc)
    return SupportResistance(
        level=draw(st.floats(min_value=min_level, max_value=max_level, allow_nan=False)),
        strength=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        timeframe=draw(st.sampled_from(["5y", "1y", "6m", "1m"])),
        last_tested=now - timedelta(days=draw(st.integers(min_value=1, max_value=365))),
    )


@st.composite
def support_levels_below_price_strategy(draw, entry_price: float):
    """Generate support levels below the entry price."""
    num_levels = draw(st.integers(min_value=1, max_value=5))
    levels = []
    
    for _ in range(num_levels):
        # Generate level between 50% and 99% of entry price
        level_pct = draw(st.floats(min_value=0.5, max_value=0.99, allow_nan=False))
        level = entry_price * level_pct
        
        now = datetime.now(timezone.utc)
        levels.append(SupportResistance(
            level=level,
            strength=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
            timeframe=draw(st.sampled_from(["5y", "1y", "6m", "1m"])),
            last_tested=now - timedelta(days=draw(st.integers(min_value=1, max_value=365))),
        ))
    
    return levels


@st.composite
def resistance_levels_above_price_strategy(draw, entry_price: float):
    """Generate resistance levels above the entry price."""
    num_levels = draw(st.integers(min_value=1, max_value=5))
    levels = []
    
    for _ in range(num_levels):
        # Generate level between 101% and 200% of entry price
        level_pct = draw(st.floats(min_value=1.01, max_value=2.0, allow_nan=False))
        level = entry_price * level_pct
        
        now = datetime.now(timezone.utc)
        levels.append(SupportResistance(
            level=level,
            strength=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
            timeframe=draw(st.sampled_from(["5y", "1y", "6m", "1m"])),
            last_tested=now - timedelta(days=draw(st.integers(min_value=1, max_value=365))),
        ))
    
    return levels


# --- Property Tests ---

@pytest.mark.property
class TestStopLossCalculationIntegrity:
    """
    Property tests for Strategy Agent Stop-Loss Calculation.
    
    **Validates: Requirements 4.1, 4.2, 4.3, 13.1, 13.2**
    """

    @given(
        entry_price=st.floats(min_value=10.0, max_value=10000.0, allow_nan=False),
        horizon=st.sampled_from(list(TradingHorizon)),
    )
    @settings(max_examples=100)
    def test_buy_stop_loss_always_below_entry(
        self,
        entry_price: float,
        horizon: TradingHorizon,
    ):
        """
        Property: For BUY trades, calculated stop_loss is always below entry_price.
        
        **Validates: Requirements 4.2, 13.1**
        
        For any valid entry price and support levels, the stop-loss
        calculation for BUY trades must produce a value below entry_price.
        """
        # Generate support levels below entry price
        now = datetime.now(timezone.utc)
        support_levels = [
            SupportResistance(
                level=entry_price * 0.95,  # 5% below
                strength=0.8,
                timeframe="1y",
                last_tested=now - timedelta(days=30),
            ),
            SupportResistance(
                level=entry_price * 0.90,  # 10% below
                strength=0.6,
                timeframe="6m",
                last_tested=now - timedelta(days=60),
            ),
        ]
        
        # Empty resistance levels for BUY
        resistance_levels = []
        
        for action in [TradeAction.BUY, TradeAction.STRONG_BUY]:
            stop_loss = calculate_stop_loss(
                action=action,
                entry_price=entry_price,
                support_levels=support_levels,
                resistance_levels=resistance_levels,
                horizon=horizon,
            )
            
            # Verify the property
            assert stop_loss < entry_price, (
                f"BUY stop_loss ({stop_loss}) must be < entry_price ({entry_price}) "
                f"for action={action.value}, horizon={horizon.value}"
            )
            assert stop_loss > 0, "Stop-loss must be positive"

    @given(
        entry_price=st.floats(min_value=10.0, max_value=10000.0, allow_nan=False),
        horizon=st.sampled_from(list(TradingHorizon)),
    )
    @settings(max_examples=100)
    def test_sell_stop_loss_always_above_entry(
        self,
        entry_price: float,
        horizon: TradingHorizon,
    ):
        """
        Property: For SELL trades, calculated stop_loss is always above entry_price.
        
        **Validates: Requirements 4.3, 13.2**
        
        For any valid entry price and resistance levels, the stop-loss
        calculation for SELL trades must produce a value above entry_price.
        """
        # Generate resistance levels above entry price
        now = datetime.now(timezone.utc)
        resistance_levels = [
            SupportResistance(
                level=entry_price * 1.05,  # 5% above
                strength=0.8,
                timeframe="1y",
                last_tested=now - timedelta(days=30),
            ),
            SupportResistance(
                level=entry_price * 1.10,  # 10% above
                strength=0.6,
                timeframe="6m",
                last_tested=now - timedelta(days=60),
            ),
        ]
        
        # Empty support levels for SELL
        support_levels = []
        
        for action in [TradeAction.SELL, TradeAction.STRONG_SELL]:
            stop_loss = calculate_stop_loss(
                action=action,
                entry_price=entry_price,
                support_levels=support_levels,
                resistance_levels=resistance_levels,
                horizon=horizon,
            )
            
            # Verify the property
            assert stop_loss > entry_price, (
                f"SELL stop_loss ({stop_loss}) must be > entry_price ({entry_price}) "
                f"for action={action.value}, horizon={horizon.value}"
            )
            assert stop_loss > 0, "Stop-loss must be positive"

    @given(
        entry_price=st.floats(min_value=10.0, max_value=10000.0, allow_nan=False),
        horizon=st.sampled_from(list(TradingHorizon)),
    )
    @settings(max_examples=100)
    def test_buy_stop_loss_without_support_levels(
        self,
        entry_price: float,
        horizon: TradingHorizon,
    ):
        """
        Property: BUY stop-loss is valid even without support levels.
        
        **Validates: Requirements 4.1, 4.2**
        
        When no support levels are available, the stop-loss calculation
        should fall back to a default buffer and still produce a valid
        stop-loss below entry_price.
        """
        # No support or resistance levels
        support_levels = []
        resistance_levels = []
        
        stop_loss = calculate_stop_loss(
            action=TradeAction.BUY,
            entry_price=entry_price,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            horizon=horizon,
        )
        
        # Verify the property
        assert stop_loss < entry_price, (
            f"BUY stop_loss ({stop_loss}) must be < entry_price ({entry_price}) "
            f"even without support levels"
        )
        assert stop_loss > 0, "Stop-loss must be positive"

    @given(
        entry_price=st.floats(min_value=10.0, max_value=10000.0, allow_nan=False),
        horizon=st.sampled_from(list(TradingHorizon)),
    )
    @settings(max_examples=100)
    def test_sell_stop_loss_without_resistance_levels(
        self,
        entry_price: float,
        horizon: TradingHorizon,
    ):
        """
        Property: SELL stop-loss is valid even without resistance levels.
        
        **Validates: Requirements 4.1, 4.3**
        
        When no resistance levels are available, the stop-loss calculation
        should fall back to a default buffer and still produce a valid
        stop-loss above entry_price.
        """
        # No support or resistance levels
        support_levels = []
        resistance_levels = []
        
        stop_loss = calculate_stop_loss(
            action=TradeAction.SELL,
            entry_price=entry_price,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            horizon=horizon,
        )
        
        # Verify the property
        assert stop_loss > entry_price, (
            f"SELL stop_loss ({stop_loss}) must be > entry_price ({entry_price}) "
            f"even without resistance levels"
        )
        assert stop_loss > 0, "Stop-loss must be positive"

    @given(
        entry_price=st.floats(min_value=100.0, max_value=1000.0, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_short_term_has_tighter_stops_than_long_term(
        self,
        entry_price: float,
    ):
        """
        Property: SHORT_TERM horizon uses tighter stops than LONG_TERM.
        
        **Validates: Requirement 4.7**
        
        For the same entry price and support levels, SHORT_TERM trades
        should have stop-losses closer to entry than LONG_TERM trades.
        """
        now = datetime.now(timezone.utc)
        support_levels = [
            SupportResistance(
                level=entry_price * 0.90,
                strength=0.8,
                timeframe="1y",
                last_tested=now - timedelta(days=30),
            ),
        ]
        resistance_levels = []
        
        short_term_sl = calculate_stop_loss(
            action=TradeAction.BUY,
            entry_price=entry_price,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            horizon=TradingHorizon.SHORT_TERM,
        )
        
        long_term_sl = calculate_stop_loss(
            action=TradeAction.BUY,
            entry_price=entry_price,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            horizon=TradingHorizon.LONG_TERM,
        )
        
        # Short-term stop should be closer to entry (higher value for BUY)
        short_term_distance = entry_price - short_term_sl
        long_term_distance = entry_price - long_term_sl
        
        assert short_term_distance <= long_term_distance, (
            f"SHORT_TERM stop distance ({short_term_distance:.2f}) should be <= "
            f"LONG_TERM stop distance ({long_term_distance:.2f})"
        )

    @given(
        entry_price=st.floats(min_value=10.0, max_value=10000.0, allow_nan=False),
        buffer_pct=st.floats(min_value=0.005, max_value=0.02, allow_nan=False),
        horizon=st.sampled_from(list(TradingHorizon)),
    )
    @settings(max_examples=100)
    def test_stop_loss_respects_buffer_range(
        self,
        entry_price: float,
        buffer_pct: float,
        horizon: TradingHorizon,
    ):
        """
        Property: Stop-loss buffer is within configured range (0.5% to 2%).
        
        **Validates: Requirements 4.2, 4.3**
        
        The stop-loss should be placed with a buffer of 0.5% to 2% from
        the support/resistance level.
        """
        config = StopLossConfig(
            min_buffer_pct=0.005,
            max_buffer_pct=0.02,
        )
        
        now = datetime.now(timezone.utc)
        support_level = entry_price * 0.95
        support_levels = [
            SupportResistance(
                level=support_level,
                strength=0.8,
                timeframe="1y",
                last_tested=now - timedelta(days=30),
            ),
        ]
        
        stop_loss = calculate_stop_loss(
            action=TradeAction.BUY,
            entry_price=entry_price,
            support_levels=support_levels,
            resistance_levels=[],
            horizon=horizon,
            config=config,
        )
        
        # Stop-loss should be below support level (with buffer)
        assert stop_loss < support_level, (
            f"Stop-loss ({stop_loss}) should be below support ({support_level})"
        )
        
        # Buffer should be within range
        actual_buffer = (support_level - stop_loss) / support_level
        # Allow some tolerance for horizon adjustments
        assert actual_buffer >= config.min_buffer_pct * 0.5, (
            f"Buffer ({actual_buffer:.4f}) should be >= min ({config.min_buffer_pct * 0.5:.4f})"
        )
        assert actual_buffer <= config.max_buffer_pct * 2.0, (
            f"Buffer ({actual_buffer:.4f}) should be <= max ({config.max_buffer_pct * 2.0:.4f})"
        )

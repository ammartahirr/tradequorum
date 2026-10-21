"""
Property-based tests for Risk-Reward Minimum.

**Property 2: Risk-Reward Minimum**
**Validates: Requirements 4.6, 13.4**

These tests verify that:
- Risk-reward ratio is always >= 1.5 for actionable trades
- Take-profit calculation ensures minimum risk-reward is met
- The system never enters a trade where potential loss exceeds 2/3 of potential gain
"""

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.models.enums import TradeAction, TradingHorizon
from src.models.signals import SupportResistance

from src.agents.strategy.take_profit import (
    calculate_take_profit,
    calculate_risk_reward_ratio,
    TakeProfitCalculator,
)
from src.agents.strategy.stop_loss import calculate_stop_loss
from src.agents.strategy.config import TakeProfitConfig, StopLossConfig


# --- Strategies for generating test data ---

@st.composite
def support_resistance_levels_strategy(draw, entry_price: float):
    """Generate support and resistance levels around entry price."""
    now = datetime.now(timezone.utc)
    
    # Generate support levels below entry
    num_supports = draw(st.integers(min_value=1, max_value=3))
    support_levels = []
    for i in range(num_supports):
        level_pct = draw(st.floats(min_value=0.7, max_value=0.98, allow_nan=False))
        support_levels.append(SupportResistance(
            level=entry_price * level_pct,
            strength=draw(st.floats(min_value=0.3, max_value=1.0, allow_nan=False)),
            timeframe=draw(st.sampled_from(["5y", "1y", "6m", "1m"])),
            last_tested=now - timedelta(days=draw(st.integers(min_value=1, max_value=365))),
        ))
    
    # Generate resistance levels above entry
    num_resistances = draw(st.integers(min_value=1, max_value=3))
    resistance_levels = []
    for i in range(num_resistances):
        level_pct = draw(st.floats(min_value=1.02, max_value=1.5, allow_nan=False))
        resistance_levels.append(SupportResistance(
            level=entry_price * level_pct,
            strength=draw(st.floats(min_value=0.3, max_value=1.0, allow_nan=False)),
            timeframe=draw(st.sampled_from(["5y", "1y", "6m", "1m"])),
            last_tested=now - timedelta(days=draw(st.integers(min_value=1, max_value=365))),
        ))
    
    return support_levels, resistance_levels


# --- Property Tests ---

@pytest.mark.property
class TestRiskRewardMinimum:
    """
    Property tests for Risk-Reward Minimum.
    
    **Validates: Requirements 4.6, 13.4**
    """

    @given(
        entry_price=st.floats(min_value=10.0, max_value=10000.0, allow_nan=False),
        stop_loss_offset=st.floats(min_value=0.01, max_value=0.1, allow_nan=False),
        horizon=st.sampled_from(list(TradingHorizon)),
    )
    @settings(max_examples=100)
    def test_buy_take_profit_ensures_minimum_risk_reward(
        self,
        entry_price: float,
        stop_loss_offset: float,
        horizon: TradingHorizon,
    ):
        """
        Property: BUY take-profit ensures risk-reward ratio >= 1.5.
        
        **Validates: Requirements 4.6, 13.4**
        
        For any valid entry price and stop-loss, the take-profit calculation
        must produce a value that ensures risk-reward ratio >= 1.5.
        """
        stop_loss = entry_price * (1 - stop_loss_offset)
        
        now = datetime.now(timezone.utc)
        resistance_levels = [
            SupportResistance(
                level=entry_price * 1.10,
                strength=0.8,
                timeframe="1y",
                last_tested=now - timedelta(days=30),
            ),
        ]
        support_levels = []
        
        take_profit = calculate_take_profit(
            action=TradeAction.BUY,
            entry_price=entry_price,
            stop_loss=stop_loss,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            horizon=horizon,
        )
        
        # Calculate risk-reward ratio
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
        rr_ratio = reward / risk if risk > 0 else 0
        
        # Verify the property (use small epsilon for floating-point comparison)
        epsilon = 1e-9
        assert rr_ratio >= 1.5 - epsilon, (
            f"BUY risk-reward ratio ({rr_ratio:.6f}) must be >= 1.5. "
            f"entry={entry_price:.2f}, sl={stop_loss:.2f}, tp={take_profit:.2f}"
        )
        assert take_profit > entry_price, (
            f"BUY take_profit ({take_profit}) must be > entry_price ({entry_price})"
        )

    @given(
        entry_price=st.floats(min_value=10.0, max_value=10000.0, allow_nan=False),
        stop_loss_offset=st.floats(min_value=0.01, max_value=0.1, allow_nan=False),
        horizon=st.sampled_from(list(TradingHorizon)),
    )
    @settings(max_examples=100)
    def test_sell_take_profit_ensures_minimum_risk_reward(
        self,
        entry_price: float,
        stop_loss_offset: float,
        horizon: TradingHorizon,
    ):
        """
        Property: SELL take-profit ensures risk-reward ratio >= 1.5.
        
        **Validates: Requirements 4.6, 13.4**
        
        For any valid entry price and stop-loss, the take-profit calculation
        must produce a value that ensures risk-reward ratio >= 1.5.
        """
        stop_loss = entry_price * (1 + stop_loss_offset)
        
        now = datetime.now(timezone.utc)
        support_levels = [
            SupportResistance(
                level=entry_price * 0.85,
                strength=0.8,
                timeframe="1y",
                last_tested=now - timedelta(days=30),
            ),
        ]
        resistance_levels = []
        
        take_profit = calculate_take_profit(
            action=TradeAction.SELL,
            entry_price=entry_price,
            stop_loss=stop_loss,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            horizon=horizon,
        )
        
        # Ensure take_profit is positive
        assume(take_profit > 0)
        
        # Calculate risk-reward ratio
        risk = stop_loss - entry_price
        reward = entry_price - take_profit
        rr_ratio = reward / risk if risk > 0 else 0
        
        # Verify the property (use small epsilon for floating-point comparison)
        epsilon = 1e-9
        assert rr_ratio >= 1.5 - epsilon, (
            f"SELL risk-reward ratio ({rr_ratio:.6f}) must be >= 1.5. "
            f"entry={entry_price:.2f}, sl={stop_loss:.2f}, tp={take_profit:.2f}"
        )
        assert take_profit < entry_price, (
            f"SELL take_profit ({take_profit}) must be < entry_price ({entry_price})"
        )

    @given(
        entry_price=st.floats(min_value=10.0, max_value=10000.0, allow_nan=False),
        horizon=st.sampled_from(list(TradingHorizon)),
    )
    @settings(max_examples=100)
    def test_buy_take_profit_without_resistance_levels(
        self,
        entry_price: float,
        horizon: TradingHorizon,
    ):
        """
        Property: BUY take-profit is valid even without resistance levels.
        
        **Validates: Requirements 4.4, 4.6**
        
        When no resistance levels are available, the take-profit calculation
        should fall back to a default multiplier and still ensure minimum
        risk-reward ratio.
        """
        stop_loss = entry_price * 0.95  # 5% below
        
        take_profit = calculate_take_profit(
            action=TradeAction.BUY,
            entry_price=entry_price,
            stop_loss=stop_loss,
            support_levels=[],
            resistance_levels=[],
            horizon=horizon,
        )
        
        # Calculate risk-reward ratio
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
        rr_ratio = reward / risk if risk > 0 else 0
        
        # Verify the property
        assert rr_ratio >= 1.5, (
            f"BUY risk-reward ratio ({rr_ratio:.2f}) must be >= 1.5 "
            f"even without resistance levels"
        )
        assert take_profit > entry_price, (
            f"BUY take_profit ({take_profit}) must be > entry_price ({entry_price})"
        )

    @given(
        entry_price=st.floats(min_value=10.0, max_value=10000.0, allow_nan=False),
        horizon=st.sampled_from(list(TradingHorizon)),
    )
    @settings(max_examples=100)
    def test_sell_take_profit_without_support_levels(
        self,
        entry_price: float,
        horizon: TradingHorizon,
    ):
        """
        Property: SELL take-profit is valid even without support levels.
        
        **Validates: Requirements 4.5, 4.6**
        
        When no support levels are available, the take-profit calculation
        should fall back to a default multiplier and still ensure minimum
        risk-reward ratio.
        """
        stop_loss = entry_price * 1.05  # 5% above
        
        take_profit = calculate_take_profit(
            action=TradeAction.SELL,
            entry_price=entry_price,
            stop_loss=stop_loss,
            support_levels=[],
            resistance_levels=[],
            horizon=horizon,
        )
        
        # Ensure take_profit is positive
        assume(take_profit > 0)
        
        # Calculate risk-reward ratio
        risk = stop_loss - entry_price
        reward = entry_price - take_profit
        rr_ratio = reward / risk if risk > 0 else 0
        
        # Verify the property
        assert rr_ratio >= 1.5, (
            f"SELL risk-reward ratio ({rr_ratio:.2f}) must be >= 1.5 "
            f"even without support levels"
        )
        assert take_profit < entry_price, (
            f"SELL take_profit ({take_profit}) must be < entry_price ({entry_price})"
        )

    @given(
        entry_price=st.floats(min_value=100.0, max_value=1000.0, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_long_term_targets_higher_levels(
        self,
        entry_price: float,
    ):
        """
        Property: LONG_TERM horizon targets higher resistance levels.
        
        **Validates: Requirement 4.8**
        
        For the same entry price and resistance levels, LONG_TERM trades
        should target higher take-profit levels than SHORT_TERM trades.
        """
        stop_loss = entry_price * 0.95
        
        now = datetime.now(timezone.utc)
        resistance_levels = [
            SupportResistance(
                level=entry_price * 1.05,  # First resistance
                strength=0.8,
                timeframe="1m",
                last_tested=now - timedelta(days=10),
            ),
            SupportResistance(
                level=entry_price * 1.15,  # Second resistance
                strength=0.7,
                timeframe="6m",
                last_tested=now - timedelta(days=60),
            ),
            SupportResistance(
                level=entry_price * 1.25,  # Third resistance
                strength=0.6,
                timeframe="1y",
                last_tested=now - timedelta(days=180),
            ),
        ]
        
        short_term_tp = calculate_take_profit(
            action=TradeAction.BUY,
            entry_price=entry_price,
            stop_loss=stop_loss,
            support_levels=[],
            resistance_levels=resistance_levels,
            horizon=TradingHorizon.SHORT_TERM,
        )
        
        long_term_tp = calculate_take_profit(
            action=TradeAction.BUY,
            entry_price=entry_price,
            stop_loss=stop_loss,
            support_levels=[],
            resistance_levels=resistance_levels,
            horizon=TradingHorizon.LONG_TERM,
        )
        
        # Long-term should target higher or equal levels
        assert long_term_tp >= short_term_tp, (
            f"LONG_TERM take-profit ({long_term_tp:.2f}) should be >= "
            f"SHORT_TERM take-profit ({short_term_tp:.2f})"
        )

    @given(
        entry_price=st.floats(min_value=10.0, max_value=10000.0, allow_nan=False),
        stop_loss_offset=st.floats(min_value=0.01, max_value=0.1, allow_nan=False),
        take_profit_offset=st.floats(min_value=0.02, max_value=0.3, allow_nan=False),
        action=st.sampled_from([TradeAction.BUY, TradeAction.STRONG_BUY]),
    )
    @settings(max_examples=100)
    def test_risk_reward_ratio_calculation_buy(
        self,
        entry_price: float,
        stop_loss_offset: float,
        take_profit_offset: float,
        action: TradeAction,
    ):
        """
        Property: Risk-reward ratio calculation is correct for BUY trades.
        
        **Validates: Requirements 4.6, 13.4**
        
        The calculate_risk_reward_ratio function should correctly compute
        the ratio of potential reward to potential risk.
        """
        stop_loss = entry_price * (1 - stop_loss_offset)
        take_profit = entry_price * (1 + take_profit_offset)
        
        rr_ratio = calculate_risk_reward_ratio(
            action=action,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        
        # Calculate expected ratio
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
        expected_ratio = reward / risk
        
        # Verify calculation is correct
        assert abs(rr_ratio - expected_ratio) < 0.001, (
            f"Risk-reward ratio ({rr_ratio:.4f}) should equal "
            f"expected ({expected_ratio:.4f})"
        )

    @given(
        entry_price=st.floats(min_value=10.0, max_value=10000.0, allow_nan=False),
        stop_loss_offset=st.floats(min_value=0.01, max_value=0.1, allow_nan=False),
        take_profit_offset=st.floats(min_value=0.02, max_value=0.3, allow_nan=False),
        action=st.sampled_from([TradeAction.SELL, TradeAction.STRONG_SELL]),
    )
    @settings(max_examples=100)
    def test_risk_reward_ratio_calculation_sell(
        self,
        entry_price: float,
        stop_loss_offset: float,
        take_profit_offset: float,
        action: TradeAction,
    ):
        """
        Property: Risk-reward ratio calculation is correct for SELL trades.
        
        **Validates: Requirements 4.6, 13.4**
        
        The calculate_risk_reward_ratio function should correctly compute
        the ratio of potential reward to potential risk.
        """
        stop_loss = entry_price * (1 + stop_loss_offset)
        take_profit = entry_price * (1 - take_profit_offset)
        
        # Ensure take_profit is positive
        assume(take_profit > 0)
        
        rr_ratio = calculate_risk_reward_ratio(
            action=action,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        
        # Calculate expected ratio
        risk = stop_loss - entry_price
        reward = entry_price - take_profit
        expected_ratio = reward / risk
        
        # Verify calculation is correct
        assert abs(rr_ratio - expected_ratio) < 0.001, (
            f"Risk-reward ratio ({rr_ratio:.4f}) should equal "
            f"expected ({expected_ratio:.4f})"
        )

"""
Property-based tests for Position Size Limits.

**Property 3: Position Size Limits**
**Validates: Requirements 5.1, 5.2, 13.3**

These tests verify:
- Position size does not exceed 5% of portfolio (Requirement 5.1)
- Portfolio risk per trade does not exceed 2% (Requirement 5.2)
- Position size is adjusted downward when limits exceeded (Requirement 5.6)
- Trade records validate position size (Requirement 13.3)
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
from src.agents.risk.config import PositionLimitsConfig
from src.agents.risk.position_validator import PositionValidator


# --- Strategies for generating test data ---

@st.composite
def trade_decision_strategy(draw, action: TradeAction = None):
    """Generate valid TradeDecision instances for testing."""
    now = datetime.now(timezone.utc)
    
    # Generate action if not provided
    if action is None:
        action = draw(st.sampled_from([
            TradeAction.BUY, TradeAction.STRONG_BUY,
            TradeAction.SELL, TradeAction.STRONG_SELL,
        ]))
    
    # Determine conviction based on action
    if action in {TradeAction.STRONG_BUY, TradeAction.STRONG_SELL}:
        conviction = Conviction.HIGH
    else:
        conviction = draw(st.sampled_from([Conviction.HIGH, Conviction.MEDIUM]))
    
    # Generate prices
    entry_price = draw(st.floats(min_value=10.0, max_value=1000.0, allow_nan=False))
    
    # Calculate stop-loss and take-profit based on action
    if action in {TradeAction.BUY, TradeAction.STRONG_BUY}:
        stop_loss_offset = draw(st.floats(min_value=0.02, max_value=0.10, allow_nan=False))
        take_profit_offset = draw(st.floats(min_value=0.05, max_value=0.30, allow_nan=False))
        stop_loss = entry_price * (1 - stop_loss_offset)
        take_profit = entry_price * (1 + take_profit_offset)
    else:
        stop_loss_offset = draw(st.floats(min_value=0.02, max_value=0.10, allow_nan=False))
        take_profit_offset = draw(st.floats(min_value=0.05, max_value=0.30, allow_nan=False))
        stop_loss = entry_price * (1 + stop_loss_offset)
        take_profit = entry_price * (1 - take_profit_offset)
        assume(take_profit > 0)
    
    # Calculate risk-reward ratio
    if action in {TradeAction.BUY, TradeAction.STRONG_BUY}:
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
    else:
        risk = stop_loss - entry_price
        reward = entry_price - take_profit
    
    assume(risk > 0)
    rr_ratio = reward / risk
    assume(rr_ratio >= 1.5)
    
    # Generate position size
    position_size_pct = draw(st.floats(min_value=0.01, max_value=0.20, allow_nan=False))
    
    symbol = "AAPL"
    
    # Create signals
    news_signal = NewsSignal(
        symbol=symbol,
        sentiment=Sentiment.BULLISH if action in {TradeAction.BUY, TradeAction.STRONG_BUY} else Sentiment.BEARISH,
        impact_type=ImpactType.CASH_FLOW,
        impact_score=0.8,
        confidence=0.85,
        reasoning="Test reasoning",
        source_items=["item1"],
        timestamp=now,
        expires_at=now + timedelta(hours=72),
    )
    
    tech_signal = TechnicalSignal(
        symbol=symbol,
        trend=TrendDirection.UPTREND if action in {TradeAction.BUY, TradeAction.STRONG_BUY} else TrendDirection.DOWNTREND,
        condition=MarketCondition.OVERSOLD if action in {TradeAction.BUY, TradeAction.STRONG_BUY} else MarketCondition.OVERBOUGHT,
        rsi=30.0 if action in {TradeAction.BUY, TradeAction.STRONG_BUY} else 70.0,
        current_price=entry_price,
        support_levels=[
            SupportResistance(
                level=entry_price * 0.9,
                strength=0.8,
                timeframe="1y",
                last_tested=now - timedelta(days=30),
            )
        ],
        resistance_levels=[
            SupportResistance(
                level=entry_price * 1.1,
                strength=0.7,
                timeframe="1y",
                last_tested=now - timedelta(days=30),
            )
        ],
        confluence=ConfluenceResult(
            score=0.8,
            factors=["rsi_condition", "support_level"],
            description="Strong confluence",
        ),
        volume_trend="increasing",
        interest_rate_impact=0.1,
        timestamp=now,
    )
    
    return TradeDecision(
        symbol=symbol,
        action=action,
        conviction=conviction,
        horizon=draw(st.sampled_from(list(TradingHorizon))),
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_size_pct=position_size_pct,
        risk_reward_ratio=rr_ratio,
        reasoning="Test trade",
        news_signal=news_signal,
        technical_signal=tech_signal,
        timestamp=now,
        expires_at=now + timedelta(hours=4),
    )


# --- Property Tests ---

@pytest.mark.property
class TestPositionSizeLimits:
    """
    Property tests for Position Size Limits.
    
    **Validates: Requirements 5.1, 5.2, 13.3**
    """

    @given(
        position_size_pct=st.floats(min_value=0.01, max_value=0.20, allow_nan=False),
        portfolio_value=st.floats(min_value=10000.0, max_value=10000000.0, allow_nan=False),
        max_position_pct=st.floats(min_value=0.01, max_value=0.10, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_position_size_never_exceeds_max(
        self,
        position_size_pct: float,
        portfolio_value: float,
        max_position_pct: float,
    ):
        """
        Property: Approved position size never exceeds max_position_pct.
        
        **Validates: Requirement 5.1**
        
        For any trade decision with any position size:
        - If approved, adjusted_size <= max_position_pct
        - If position_size > max_position_pct, it must be adjusted down
        """
        config = PositionLimitsConfig(
            max_position_pct=max_position_pct,
            max_portfolio_risk_pct=0.10,  # High to not interfere
        )
        validator = PositionValidator(config)
        
        # Create a simple decision for testing
        now = datetime.now(timezone.utc)
        entry_price = 100.0
        stop_loss = 95.0  # 5% below entry
        take_profit = 110.0  # 10% above entry
        
        news_signal = NewsSignal(
            symbol="AAPL",
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
            symbol="AAPL",
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
        
        decision = TradeDecision(
            symbol="AAPL",
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
        
        result = validator.validate(decision, portfolio_value)
        
        # Property: If approved, final size <= max
        if result.is_valid:
            final_size = result.adjusted_size_pct if result.adjusted_size_pct else position_size_pct
            assert final_size <= max_position_pct, \
                f"Approved position size {final_size:.4f} exceeds max {max_position_pct:.4f}"
        
        # Property: If original > max, must be adjusted
        if position_size_pct > max_position_pct and result.is_valid:
            assert result.adjusted_size_pct is not None, \
                f"Position size {position_size_pct:.4f} > max {max_position_pct:.4f} but not adjusted"
            assert result.adjusted_size_pct <= max_position_pct, \
                f"Adjusted size {result.adjusted_size_pct:.4f} still exceeds max {max_position_pct:.4f}"

    @given(
        entry_price=st.floats(min_value=10.0, max_value=1000.0, allow_nan=False),
        stop_loss_pct=st.floats(min_value=0.01, max_value=0.20, allow_nan=False),
        position_size_pct=st.floats(min_value=0.01, max_value=0.20, allow_nan=False),
        portfolio_value=st.floats(min_value=10000.0, max_value=10000000.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_portfolio_risk_never_exceeds_max(
        self,
        entry_price: float,
        stop_loss_pct: float,
        position_size_pct: float,
        portfolio_value: float,
    ):
        """
        Property: Portfolio risk per trade never exceeds max_portfolio_risk_pct.
        
        **Validates: Requirement 5.2**
        
        For any trade decision:
        - Portfolio risk = (position_value / entry_price) * (entry_price - stop_loss)
        - If approved, portfolio_risk / portfolio_value <= max_portfolio_risk_pct
        """
        max_portfolio_risk_pct = 0.02  # 2%
        
        config = PositionLimitsConfig(
            max_position_pct=0.50,  # High to not interfere
            max_portfolio_risk_pct=max_portfolio_risk_pct,
        )
        validator = PositionValidator(config)
        
        # Calculate stop-loss
        stop_loss = entry_price * (1 - stop_loss_pct)
        take_profit = entry_price * 1.15  # 15% above entry
        
        now = datetime.now(timezone.utc)
        
        news_signal = NewsSignal(
            symbol="AAPL",
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
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=30.0,
            current_price=entry_price,
            support_levels=[SupportResistance(level=stop_loss * 0.95, strength=0.8, timeframe="1y", last_tested=now - timedelta(days=30))],
            resistance_levels=[SupportResistance(level=take_profit * 1.05, strength=0.7, timeframe="1y", last_tested=now - timedelta(days=30))],
            confluence=ConfluenceResult(score=0.8, factors=["rsi_oversold"], description="Test"),
            volume_trend="increasing",
            interest_rate_impact=0.1,
            timestamp=now,
        )
        
        # Calculate risk-reward ratio
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
        assume(risk > 0)
        rr_ratio = reward / risk
        assume(rr_ratio >= 1.5)
        
        decision = TradeDecision(
            symbol="AAPL",
            action=TradeAction.BUY,
            conviction=Conviction.MEDIUM,
            horizon=TradingHorizon.SHORT_TERM,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_pct=position_size_pct,
            risk_reward_ratio=rr_ratio,
            reasoning="Test",
            news_signal=news_signal,
            technical_signal=tech_signal,
            timestamp=now,
            expires_at=now + timedelta(hours=4),
        )
        
        result = validator.validate(decision, portfolio_value)
        
        # Property: If approved, portfolio risk <= max
        if result.is_valid:
            final_size = result.adjusted_size_pct if result.adjusted_size_pct else position_size_pct
            position_value = portfolio_value * final_size
            num_shares = position_value / entry_price
            risk_per_share = entry_price - stop_loss
            total_risk = num_shares * risk_per_share
            portfolio_risk_pct = total_risk / portfolio_value
            
            assert portfolio_risk_pct <= max_portfolio_risk_pct + 0.001, \
                f"Portfolio risk {portfolio_risk_pct:.4f} exceeds max {max_portfolio_risk_pct:.4f}"

    @given(
        position_size_pct=st.floats(min_value=0.06, max_value=0.20, allow_nan=False),
        portfolio_value=st.floats(min_value=10000.0, max_value=10000000.0, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_oversized_position_is_adjusted_down(
        self,
        position_size_pct: float,
        portfolio_value: float,
    ):
        """
        Property: Positions exceeding limits are adjusted downward, not rejected.
        
        **Validates: Requirement 5.6**
        
        When position_size > max_position_pct:
        - Trade should still be approved (if otherwise valid)
        - adjusted_size should be set to a valid value
        - adjusted_size <= max_position_pct
        """
        max_position_pct = 0.05  # 5%
        assume(position_size_pct > max_position_pct)
        
        config = PositionLimitsConfig(
            max_position_pct=max_position_pct,
            max_portfolio_risk_pct=0.10,  # High to not interfere
        )
        validator = PositionValidator(config)
        
        now = datetime.now(timezone.utc)
        entry_price = 100.0
        stop_loss = 98.0  # Small risk
        take_profit = 105.0
        
        news_signal = NewsSignal(
            symbol="AAPL",
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
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=30.0,
            current_price=entry_price,
            support_levels=[SupportResistance(level=95.0, strength=0.8, timeframe="1y", last_tested=now - timedelta(days=30))],
            resistance_levels=[SupportResistance(level=110.0, strength=0.7, timeframe="1y", last_tested=now - timedelta(days=30))],
            confluence=ConfluenceResult(score=0.8, factors=["rsi_oversold"], description="Test"),
            volume_trend="increasing",
            interest_rate_impact=0.1,
            timestamp=now,
        )
        
        decision = TradeDecision(
            symbol="AAPL",
            action=TradeAction.BUY,
            conviction=Conviction.MEDIUM,
            horizon=TradingHorizon.SHORT_TERM,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_pct=position_size_pct,
            risk_reward_ratio=2.5,
            reasoning="Test",
            news_signal=news_signal,
            technical_signal=tech_signal,
            timestamp=now,
            expires_at=now + timedelta(hours=4),
        )
        
        result = validator.validate(decision, portfolio_value)
        
        # Property: Oversized position should be adjusted, not rejected
        assert result.is_valid, \
            f"Oversized position should be adjusted, not rejected: {result.rejection_reason}"
        assert result.adjusted_size_pct is not None, \
            "Oversized position should have adjusted_size_pct set"
        assert result.adjusted_size_pct <= max_position_pct, \
            f"Adjusted size {result.adjusted_size_pct:.4f} exceeds max {max_position_pct:.4f}"
        assert len(result.warnings) > 0, \
            "Adjustment should generate a warning"

    @given(
        action=st.sampled_from([TradeAction.BUY, TradeAction.STRONG_BUY, TradeAction.SELL, TradeAction.STRONG_SELL]),
        entry_price=st.floats(min_value=10.0, max_value=1000.0, allow_nan=False),
        stop_loss_pct=st.floats(min_value=0.02, max_value=0.10, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_risk_calculation_correct_for_buy_and_sell(
        self,
        action: TradeAction,
        entry_price: float,
        stop_loss_pct: float,
    ):
        """
        Property: Risk per share is calculated correctly for both BUY and SELL.
        
        **Validates: Requirements 5.2, 13.3**
        
        For BUY: risk = entry_price - stop_loss
        For SELL: risk = stop_loss - entry_price
        """
        config = PositionLimitsConfig()
        validator = PositionValidator(config)
        
        now = datetime.now(timezone.utc)
        
        # Calculate prices based on action
        if action in {TradeAction.BUY, TradeAction.STRONG_BUY}:
            stop_loss = entry_price * (1 - stop_loss_pct)
            take_profit = entry_price * 1.15
            expected_risk = entry_price - stop_loss
            sentiment = Sentiment.BULLISH
            trend = TrendDirection.UPTREND
            condition = MarketCondition.OVERSOLD
            rsi = 30.0
        else:
            stop_loss = entry_price * (1 + stop_loss_pct)
            take_profit = entry_price * 0.85
            expected_risk = stop_loss - entry_price
            sentiment = Sentiment.BEARISH
            trend = TrendDirection.DOWNTREND
            condition = MarketCondition.OVERBOUGHT
            rsi = 70.0
        
        # Ensure valid risk-reward
        if action in {TradeAction.BUY, TradeAction.STRONG_BUY}:
            risk = entry_price - stop_loss
            reward = take_profit - entry_price
        else:
            risk = stop_loss - entry_price
            reward = entry_price - take_profit
        
        assume(risk > 0 and reward > 0)
        rr_ratio = reward / risk
        assume(rr_ratio >= 1.5)
        
        # Determine conviction
        conviction = Conviction.HIGH if action in {TradeAction.STRONG_BUY, TradeAction.STRONG_SELL} else Conviction.MEDIUM
        
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=sentiment,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.8,
            confidence=0.85,
            reasoning="Test",
            source_items=["item1"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        tech_signal = TechnicalSignal(
            symbol="AAPL",
            trend=trend,
            condition=condition,
            rsi=rsi,
            current_price=entry_price,
            support_levels=[SupportResistance(level=entry_price * 0.9, strength=0.8, timeframe="1y", last_tested=now - timedelta(days=30))],
            resistance_levels=[SupportResistance(level=entry_price * 1.1, strength=0.7, timeframe="1y", last_tested=now - timedelta(days=30))],
            confluence=ConfluenceResult(score=0.8, factors=["indicator"], description="Test"),
            volume_trend="increasing",
            interest_rate_impact=0.1,
            timestamp=now,
        )
        
        decision = TradeDecision(
            symbol="AAPL",
            action=action,
            conviction=conviction,
            horizon=TradingHorizon.SHORT_TERM,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_pct=0.05,
            risk_reward_ratio=rr_ratio,
            reasoning="Test",
            news_signal=news_signal,
            technical_signal=tech_signal,
            timestamp=now,
            expires_at=now + timedelta(hours=4),
        )
        
        # Verify risk calculation
        calculated_risk = validator._calculate_risk_per_share(decision)
        
        assert abs(calculated_risk - expected_risk) < 0.01, \
            f"Risk calculation incorrect: expected {expected_risk:.4f}, got {calculated_risk:.4f}"

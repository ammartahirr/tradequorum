"""
Property-based tests for Stop-Loss Integrity.

**Property 1: Stop-Loss Integrity**
**Validates: Requirements 4.1, 4.2, 4.3, 13.1, 13.2**

These tests verify:
- For BUY trades: stop_loss < entry_price
- For SELL trades: stop_loss > entry_price
- Stop-loss is always set (never zero)
- Take-profit position is correct relative to entry
"""

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from pydantic import ValidationError

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
from src.models.trading import TradeDecision, TradeRecord


# --- Strategies for generating test data ---

@st.composite
def news_signal_strategy(draw):
    """Generate valid NewsSignal instances."""
    now = datetime.now(timezone.utc)
    return NewsSignal(
        symbol=draw(st.text(min_size=1, max_size=5, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ")),
        sentiment=draw(st.sampled_from(list(Sentiment))),
        impact_type=draw(st.sampled_from(list(ImpactType))),
        impact_score=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        confidence=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        reasoning=draw(st.text(min_size=1, max_size=100)),
        source_items=draw(st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=3)),
        timestamp=now,
        expires_at=now + timedelta(hours=draw(st.integers(min_value=1, max_value=168))),
    )


@st.composite
def technical_signal_strategy(draw, symbol: str = None):
    """Generate valid TechnicalSignal instances."""
    now = datetime.now(timezone.utc)
    sym = symbol or draw(st.text(min_size=1, max_size=5, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
    
    return TechnicalSignal(
        symbol=sym,
        trend=draw(st.sampled_from(list(TrendDirection))),
        condition=draw(st.sampled_from(list(MarketCondition))),
        rsi=draw(st.floats(min_value=0.0, max_value=100.0, allow_nan=False)),
        current_price=draw(st.floats(min_value=0.01, max_value=10000.0, allow_nan=False)),
        support_levels=[
            SupportResistance(
                level=draw(st.floats(min_value=0.01, max_value=10000.0, allow_nan=False)),
                strength=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
                timeframe=draw(st.sampled_from(["5y", "1y", "6m", "1m"])),
                last_tested=now - timedelta(days=draw(st.integers(min_value=1, max_value=365))),
            )
        ],
        resistance_levels=[
            SupportResistance(
                level=draw(st.floats(min_value=0.01, max_value=10000.0, allow_nan=False)),
                strength=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
                timeframe=draw(st.sampled_from(["5y", "1y", "6m", "1m"])),
                last_tested=now - timedelta(days=draw(st.integers(min_value=1, max_value=365))),
            )
        ],
        confluence=ConfluenceResult(
            score=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
            factors=draw(st.lists(st.text(min_size=1, max_size=20), min_size=0, max_size=6)),
            description=draw(st.text(min_size=1, max_size=100)),
        ),
        volume_trend=draw(st.sampled_from(["increasing", "decreasing", "stable"])),
        interest_rate_impact=draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False)),
        timestamp=now,
    )


# --- Property Tests ---

@pytest.mark.property
class TestStopLossIntegrity:
    """
    Property tests for Stop-Loss Integrity.
    
    **Validates: Requirements 4.1, 4.2, 4.3, 13.1, 13.2**
    """

    @given(
        entry_price=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False),
        stop_loss_offset=st.floats(min_value=0.01, max_value=0.5, allow_nan=False),
        take_profit_offset=st.floats(min_value=0.02, max_value=1.0, allow_nan=False),
        action=st.sampled_from([TradeAction.BUY, TradeAction.STRONG_BUY]),
        conviction=st.sampled_from([Conviction.HIGH, Conviction.MEDIUM]),
        horizon=st.sampled_from(list(TradingHorizon)),
    )
    @settings(max_examples=100)
    def test_buy_trade_stop_loss_below_entry(
        self,
        entry_price: float,
        stop_loss_offset: float,
        take_profit_offset: float,
        action: TradeAction,
        conviction: Conviction,
        horizon: TradingHorizon,
    ):
        """
        Property: For BUY trades, stop_loss must be below entry_price.
        
        **Validates: Requirements 4.2, 13.1**
        
        For any valid BUY or STRONG_BUY trade:
        - stop_loss < entry_price (always)
        - take_profit > entry_price (always)
        """
        # STRONG_BUY requires HIGH conviction
        if action == TradeAction.STRONG_BUY:
            conviction = Conviction.HIGH
        
        # Calculate valid stop-loss and take-profit
        stop_loss = entry_price * (1 - stop_loss_offset)
        take_profit = entry_price * (1 + take_profit_offset)
        
        # Ensure risk-reward ratio >= 1.5
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
        assume(risk > 0)
        rr_ratio = reward / risk
        assume(rr_ratio >= 1.5)
        
        now = datetime.now(timezone.utc)
        symbol = "AAPL"
        
        # Create valid signals
        news_signal = NewsSignal(
            symbol=symbol,
            sentiment=Sentiment.BULLISH,
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
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=30.0,
            current_price=entry_price,
            support_levels=[
                SupportResistance(
                    level=stop_loss * 0.99,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=take_profit * 1.01,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=0.8,
                factors=["rsi_oversold", "support_level"],
                description="Strong confluence",
            ),
            volume_trend="increasing",
            interest_rate_impact=0.1,
            timestamp=now,
        )
        
        # Create trade decision - should succeed with valid stop-loss
        decision = TradeDecision(
            symbol=symbol,
            action=action,
            conviction=conviction,
            horizon=horizon,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_pct=0.05,
            risk_reward_ratio=rr_ratio,
            reasoning="Test trade",
            news_signal=news_signal,
            technical_signal=tech_signal,
            timestamp=now,
            expires_at=now + timedelta(hours=4),
        )
        
        # Verify the property holds
        assert decision.stop_loss < decision.entry_price, \
            f"BUY trade stop_loss ({decision.stop_loss}) must be < entry_price ({decision.entry_price})"
        assert decision.take_profit > decision.entry_price, \
            f"BUY trade take_profit ({decision.take_profit}) must be > entry_price ({decision.entry_price})"
        assert decision.stop_loss > 0, "Stop-loss must never be zero"

    @given(
        entry_price=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False),
        stop_loss_offset=st.floats(min_value=0.01, max_value=0.5, allow_nan=False),
        take_profit_offset=st.floats(min_value=0.02, max_value=0.5, allow_nan=False),
        action=st.sampled_from([TradeAction.SELL, TradeAction.STRONG_SELL]),
        conviction=st.sampled_from([Conviction.HIGH, Conviction.MEDIUM]),
        horizon=st.sampled_from(list(TradingHorizon)),
    )
    @settings(max_examples=100)
    def test_sell_trade_stop_loss_above_entry(
        self,
        entry_price: float,
        stop_loss_offset: float,
        take_profit_offset: float,
        action: TradeAction,
        conviction: Conviction,
        horizon: TradingHorizon,
    ):
        """
        Property: For SELL trades, stop_loss must be above entry_price.
        
        **Validates: Requirements 4.3, 13.2**
        
        For any valid SELL or STRONG_SELL trade:
        - stop_loss > entry_price (always)
        - take_profit < entry_price (always)
        """
        # STRONG_SELL requires HIGH conviction
        if action == TradeAction.STRONG_SELL:
            conviction = Conviction.HIGH
        
        # Calculate valid stop-loss and take-profit for SELL
        stop_loss = entry_price * (1 + stop_loss_offset)
        take_profit = entry_price * (1 - take_profit_offset)
        
        # Ensure take_profit is positive
        assume(take_profit > 0)
        
        # Ensure risk-reward ratio >= 1.5
        risk = stop_loss - entry_price
        reward = entry_price - take_profit
        assume(risk > 0 and reward > 0)
        rr_ratio = reward / risk
        assume(rr_ratio >= 1.5)
        
        now = datetime.now(timezone.utc)
        symbol = "AAPL"
        
        # Create valid signals
        news_signal = NewsSignal(
            symbol=symbol,
            sentiment=Sentiment.BEARISH,
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
            trend=TrendDirection.DOWNTREND,
            condition=MarketCondition.OVERBOUGHT,
            rsi=75.0,
            current_price=entry_price,
            support_levels=[
                SupportResistance(
                    level=take_profit * 0.99,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=stop_loss * 1.01,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=0.8,
                factors=["rsi_overbought", "resistance_level"],
                description="Strong confluence",
            ),
            volume_trend="increasing",
            interest_rate_impact=-0.1,
            timestamp=now,
        )
        
        # Create trade decision - should succeed with valid stop-loss
        decision = TradeDecision(
            symbol=symbol,
            action=action,
            conviction=conviction,
            horizon=horizon,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_pct=0.05,
            risk_reward_ratio=rr_ratio,
            reasoning="Test trade",
            news_signal=news_signal,
            technical_signal=tech_signal,
            timestamp=now,
            expires_at=now + timedelta(hours=4),
        )
        
        # Verify the property holds
        assert decision.stop_loss > decision.entry_price, \
            f"SELL trade stop_loss ({decision.stop_loss}) must be > entry_price ({decision.entry_price})"
        assert decision.take_profit < decision.entry_price, \
            f"SELL trade take_profit ({decision.take_profit}) must be < entry_price ({decision.entry_price})"
        assert decision.stop_loss > 0, "Stop-loss must never be zero"

    @given(
        entry_price=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False),
        invalid_stop_loss_offset=st.floats(min_value=0.01, max_value=0.5, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_buy_trade_rejects_invalid_stop_loss(
        self,
        entry_price: float,
        invalid_stop_loss_offset: float,
    ):
        """
        Property: BUY trades with stop_loss >= entry_price must be rejected.
        
        **Validates: Requirements 4.2, 13.1**
        
        The model validation should reject any BUY trade where stop_loss is
        not below entry_price.
        """
        # Invalid stop-loss: at or above entry price
        invalid_stop_loss = entry_price * (1 + invalid_stop_loss_offset)
        take_profit = entry_price * 1.5  # Valid take-profit
        
        now = datetime.now(timezone.utc)
        symbol = "AAPL"
        
        news_signal = NewsSignal(
            symbol=symbol,
            sentiment=Sentiment.BULLISH,
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
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=30.0,
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
                    level=take_profit * 1.01,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=0.8,
                factors=["rsi_oversold"],
                description="Strong confluence",
            ),
            volume_trend="increasing",
            interest_rate_impact=0.1,
            timestamp=now,
        )
        
        # Attempting to create a BUY trade with invalid stop-loss should raise ValidationError
        with pytest.raises(ValidationError) as exc_info:
            TradeDecision(
                symbol=symbol,
                action=TradeAction.BUY,
                conviction=Conviction.MEDIUM,
                horizon=TradingHorizon.SHORT_TERM,
                entry_price=entry_price,
                stop_loss=invalid_stop_loss,
                take_profit=take_profit,
                position_size_pct=0.05,
                risk_reward_ratio=2.0,
                reasoning="Test trade",
                news_signal=news_signal,
                technical_signal=tech_signal,
                timestamp=now,
                expires_at=now + timedelta(hours=4),
            )
        
        assert "stop_loss" in str(exc_info.value).lower()

    @given(
        entry_price=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False),
        invalid_stop_loss_offset=st.floats(min_value=0.01, max_value=0.5, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_sell_trade_rejects_invalid_stop_loss(
        self,
        entry_price: float,
        invalid_stop_loss_offset: float,
    ):
        """
        Property: SELL trades with stop_loss <= entry_price must be rejected.
        
        **Validates: Requirements 4.3, 13.2**
        
        The model validation should reject any SELL trade where stop_loss is
        not above entry_price.
        """
        # Invalid stop-loss: at or below entry price
        invalid_stop_loss = entry_price * (1 - invalid_stop_loss_offset)
        take_profit = entry_price * 0.8  # Valid take-profit for SELL
        
        now = datetime.now(timezone.utc)
        symbol = "AAPL"
        
        news_signal = NewsSignal(
            symbol=symbol,
            sentiment=Sentiment.BEARISH,
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
            trend=TrendDirection.DOWNTREND,
            condition=MarketCondition.OVERBOUGHT,
            rsi=75.0,
            current_price=entry_price,
            support_levels=[
                SupportResistance(
                    level=take_profit * 0.99,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=entry_price * 1.1,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=now - timedelta(days=30),
                )
            ],
            confluence=ConfluenceResult(
                score=0.8,
                factors=["rsi_overbought"],
                description="Strong confluence",
            ),
            volume_trend="increasing",
            interest_rate_impact=-0.1,
            timestamp=now,
        )
        
        # Attempting to create a SELL trade with invalid stop-loss should raise ValidationError
        with pytest.raises(ValidationError) as exc_info:
            TradeDecision(
                symbol=symbol,
                action=TradeAction.SELL,
                conviction=Conviction.MEDIUM,
                horizon=TradingHorizon.SHORT_TERM,
                entry_price=entry_price,
                stop_loss=invalid_stop_loss,
                take_profit=take_profit,
                position_size_pct=0.05,
                risk_reward_ratio=2.0,
                reasoning="Test trade",
                news_signal=news_signal,
                technical_signal=tech_signal,
                timestamp=now,
                expires_at=now + timedelta(hours=4),
            )
        
        assert "stop_loss" in str(exc_info.value).lower()

    @given(
        entry_price=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False),
        stop_loss_offset=st.floats(min_value=0.01, max_value=0.3, allow_nan=False),
        take_profit_offset=st.floats(min_value=0.02, max_value=0.5, allow_nan=False),
        action=st.sampled_from([TradeAction.BUY, TradeAction.STRONG_BUY]),
        horizon=st.sampled_from(list(TradingHorizon)),
    )
    @settings(max_examples=100)
    def test_trade_record_buy_stop_loss_integrity(
        self,
        entry_price: float,
        stop_loss_offset: float,
        take_profit_offset: float,
        action: TradeAction,
        horizon: TradingHorizon,
    ):
        """
        Property: TradeRecord for BUY trades must have stop_loss < entry_price.
        
        **Validates: Requirements 13.1, 13.2**
        
        Trade records must maintain the same stop-loss integrity as trade decisions.
        """
        # Calculate valid stop-loss and take-profit
        stop_loss = entry_price * (1 - stop_loss_offset)
        take_profit = entry_price * (1 + take_profit_offset)
        
        now = datetime.now(timezone.utc)
        
        # Determine conviction based on action
        conviction = Conviction.HIGH if action == TradeAction.STRONG_BUY else Conviction.MEDIUM
        
        # Create trade record
        record = TradeRecord(
            trade_id="trade-001",
            symbol="AAPL",
            action=action,
            horizon=horizon,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=1000.0,
            status="open",
            conviction=conviction,
            news_signal_id="news-001",
            technical_signal_id="tech-001",
            decision_reasoning="Test trade",
            opened_at=now,
            exness_order_id="exness-001",
        )
        
        # Verify the property holds
        assert record.stop_loss < record.entry_price, \
            f"BUY TradeRecord stop_loss ({record.stop_loss}) must be < entry_price ({record.entry_price})"
        assert record.take_profit > record.entry_price, \
            f"BUY TradeRecord take_profit ({record.take_profit}) must be > entry_price ({record.entry_price})"
        assert record.stop_loss > 0, "Stop-loss must never be zero"

    @given(
        entry_price=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False),
        stop_loss_offset=st.floats(min_value=0.01, max_value=0.3, allow_nan=False),
        take_profit_offset=st.floats(min_value=0.02, max_value=0.5, allow_nan=False),
        action=st.sampled_from([TradeAction.SELL, TradeAction.STRONG_SELL]),
        horizon=st.sampled_from(list(TradingHorizon)),
    )
    @settings(max_examples=100)
    def test_trade_record_sell_stop_loss_integrity(
        self,
        entry_price: float,
        stop_loss_offset: float,
        take_profit_offset: float,
        action: TradeAction,
        horizon: TradingHorizon,
    ):
        """
        Property: TradeRecord for SELL trades must have stop_loss > entry_price.
        
        **Validates: Requirements 13.1, 13.2**
        
        Trade records must maintain the same stop-loss integrity as trade decisions.
        """
        # Calculate valid stop-loss and take-profit for SELL
        stop_loss = entry_price * (1 + stop_loss_offset)
        take_profit = entry_price * (1 - take_profit_offset)
        
        # Ensure take_profit is positive
        assume(take_profit > 0)
        
        now = datetime.now(timezone.utc)
        
        # Determine conviction based on action
        conviction = Conviction.HIGH if action == TradeAction.STRONG_SELL else Conviction.MEDIUM
        
        # Create trade record
        record = TradeRecord(
            trade_id="trade-001",
            symbol="AAPL",
            action=action,
            horizon=horizon,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=1000.0,
            status="open",
            conviction=conviction,
            news_signal_id="news-001",
            technical_signal_id="tech-001",
            decision_reasoning="Test trade",
            opened_at=now,
            exness_order_id="exness-001",
        )
        
        # Verify the property holds
        assert record.stop_loss > record.entry_price, \
            f"SELL TradeRecord stop_loss ({record.stop_loss}) must be > entry_price ({record.entry_price})"
        assert record.take_profit < record.entry_price, \
            f"SELL TradeRecord take_profit ({record.take_profit}) must be < entry_price ({record.entry_price})"
        assert record.stop_loss > 0, "Stop-loss must never be zero"

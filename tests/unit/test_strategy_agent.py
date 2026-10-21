"""
Unit tests for the Strategy Agent.

Tests all decision matrix combinations, stop-loss and take-profit calculations,
and signal freshness validation.

Requirements:
- 3.1-3.9: Strategy decision making
- 4.1-4.8: Stop-loss and take-profit calculation
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

from src.agents.strategy.decision_matrix import (
    DecisionMatrixEvaluator,
    map_sentiment_score,
    map_technical_score,
)
from src.agents.strategy.signal_freshness import (
    SignalFreshnessValidator,
    is_news_signal_fresh,
    is_technical_signal_fresh,
)
from src.agents.strategy.stop_loss import (
    StopLossCalculator,
    calculate_stop_loss,
)
from src.agents.strategy.take_profit import (
    TakeProfitCalculator,
    calculate_take_profit,
    calculate_risk_reward_ratio,
)
from src.agents.strategy.strategy_agent import StrategyAgent


# --- Test Fixtures ---

@pytest.fixture
def now():
    """Current time fixture."""
    return datetime.now(timezone.utc)


@pytest.fixture
def fresh_news_signal(now):
    """Fresh news signal fixture."""
    return NewsSignal(
        symbol="AAPL",
        sentiment=Sentiment.BULLISH,
        impact_type=ImpactType.CASH_FLOW,
        impact_score=0.8,
        confidence=0.85,
        reasoning="Strong earnings report",
        source_items=["news-001"],
        timestamp=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=71),
    )


@pytest.fixture
def fresh_technical_signal(now):
    """Fresh technical signal fixture."""
    return TechnicalSignal(
        symbol="AAPL",
        trend=TrendDirection.UPTREND,
        condition=MarketCondition.OVERSOLD,
        rsi=28.0,
        current_price=150.0,
        support_levels=[
            SupportResistance(
                level=145.0,
                strength=0.8,
                timeframe="1y",
                last_tested=now - timedelta(days=30),
            ),
            SupportResistance(
                level=140.0,
                strength=0.6,
                timeframe="6m",
                last_tested=now - timedelta(days=60),
            ),
        ],
        resistance_levels=[
            SupportResistance(
                level=160.0,
                strength=0.7,
                timeframe="1y",
                last_tested=now - timedelta(days=45),
            ),
            SupportResistance(
                level=170.0,
                strength=0.5,
                timeframe="6m",
                last_tested=now - timedelta(days=90),
            ),
        ],
        confluence=ConfluenceResult(
            score=0.75,
            factors=["rsi_oversold", "support_level", "volume_spike"],
            description="Strong confluence",
        ),
        volume_trend="increasing",
        interest_rate_impact=0.1,
        timestamp=now - timedelta(minutes=30),
    )


# --- Decision Matrix Tests ---

class TestDecisionMatrixEvaluator:
    """Tests for DecisionMatrixEvaluator."""

    def test_very_bullish_oversold_produces_strong_buy(self, now):
        """Test VERY_BULLISH + OVERSOLD → STRONG_BUY."""
        news = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.VERY_BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.9,
            confidence=0.9,
            reasoning="Major acquisition",
            source_items=["news-001"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        tech = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.DOWNTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=25.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(level=95.0, strength=0.8, timeframe="1y",
                                  last_tested=now - timedelta(days=30))
            ],
            resistance_levels=[
                SupportResistance(level=110.0, strength=0.7, timeframe="1y",
                                  last_tested=now - timedelta(days=30))
            ],
            confluence=ConfluenceResult(score=0.8, factors=["rsi_oversold"],
                                        description="Oversold"),
            volume_trend="increasing",
            interest_rate_impact=0.1,
            timestamp=now,
        )
        
        evaluator = DecisionMatrixEvaluator()
        result = evaluator.evaluate(news, tech)
        
        assert result.action == TradeAction.STRONG_BUY
        assert result.conviction == Conviction.HIGH


    def test_very_bearish_overbought_produces_strong_sell(self, now):
        """Test VERY_BEARISH + OVERBOUGHT → STRONG_SELL."""
        news = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.VERY_BEARISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.9,
            confidence=0.9,
            reasoning="Major lawsuit",
            source_items=["news-001"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        tech = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.OVERBOUGHT,
            rsi=75.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(level=90.0, strength=0.7, timeframe="1y",
                                  last_tested=now - timedelta(days=30))
            ],
            resistance_levels=[
                SupportResistance(level=105.0, strength=0.8, timeframe="1y",
                                  last_tested=now - timedelta(days=30))
            ],
            confluence=ConfluenceResult(score=0.8, factors=["rsi_overbought"],
                                        description="Overbought"),
            volume_trend="increasing",
            interest_rate_impact=-0.1,
            timestamp=now,
        )
        
        evaluator = DecisionMatrixEvaluator()
        result = evaluator.evaluate(news, tech)
        
        assert result.action == TradeAction.STRONG_SELL
        assert result.conviction == Conviction.HIGH

    def test_bullish_overbought_produces_wait_pullback(self, now):
        """Test BULLISH + OVERBOUGHT → WAIT_PULLBACK."""
        news = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.7,
            confidence=0.8,
            reasoning="Good earnings",
            source_items=["news-001"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        tech = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.OVERBOUGHT,
            rsi=75.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(level=90.0, strength=0.7, timeframe="1y",
                                  last_tested=now - timedelta(days=30))
            ],
            resistance_levels=[
                SupportResistance(level=105.0, strength=0.8, timeframe="1y",
                                  last_tested=now - timedelta(days=30))
            ],
            confluence=ConfluenceResult(score=0.6, factors=["rsi_overbought"],
                                        description="Overbought"),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=now,
        )
        
        evaluator = DecisionMatrixEvaluator()
        result = evaluator.evaluate(news, tech)
        
        assert result.action == TradeAction.WAIT_PULLBACK
        assert result.conviction == Conviction.MEDIUM

    def test_bearish_oversold_produces_no_trade(self, now):
        """Test BEARISH + OVERSOLD → NO_TRADE (conflicting signals)."""
        news = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BEARISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.7,
            confidence=0.8,
            reasoning="Bad earnings",
            source_items=["news-001"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        tech = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.DOWNTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=25.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(level=95.0, strength=0.8, timeframe="1y",
                                  last_tested=now - timedelta(days=30))
            ],
            resistance_levels=[
                SupportResistance(level=110.0, strength=0.7, timeframe="1y",
                                  last_tested=now - timedelta(days=30))
            ],
            confluence=ConfluenceResult(score=0.7, factors=["rsi_oversold"],
                                        description="Oversold"),
            volume_trend="decreasing",
            interest_rate_impact=-0.1,
            timestamp=now,
        )
        
        evaluator = DecisionMatrixEvaluator()
        result = evaluator.evaluate(news, tech)
        
        assert result.action == TradeAction.NO_TRADE

    def test_very_bearish_oversold_produces_no_trade(self, now):
        """Test VERY_BEARISH + OVERSOLD → NO_TRADE (conflicting signals)."""
        news = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.VERY_BEARISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.9,
            confidence=0.9,
            reasoning="Major scandal",
            source_items=["news-001"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        tech = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.DOWNTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=20.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(level=95.0, strength=0.8, timeframe="1y",
                                  last_tested=now - timedelta(days=30))
            ],
            resistance_levels=[
                SupportResistance(level=110.0, strength=0.7, timeframe="1y",
                                  last_tested=now - timedelta(days=30))
            ],
            confluence=ConfluenceResult(score=0.8, factors=["rsi_oversold"],
                                        description="Oversold"),
            volume_trend="increasing",
            interest_rate_impact=-0.2,
            timestamp=now,
        )
        
        evaluator = DecisionMatrixEvaluator()
        result = evaluator.evaluate(news, tech)
        
        assert result.action == TradeAction.NO_TRADE


# --- Sentiment and Technical Score Mapping Tests ---

class TestScoreMapping:
    """Tests for sentiment and technical score mapping."""

    def test_sentiment_score_very_bullish(self):
        """Test VERY_BULLISH sentiment produces positive score."""
        score = map_sentiment_score(Sentiment.VERY_BULLISH, 1.0)
        assert score > 0
        assert score <= 1.0

    def test_sentiment_score_very_bearish(self):
        """Test VERY_BEARISH sentiment produces negative score."""
        score = map_sentiment_score(Sentiment.VERY_BEARISH, 1.0)
        assert score < 0
        assert score >= -1.0

    def test_sentiment_score_neutral(self):
        """Test NEUTRAL sentiment produces zero score."""
        score = map_sentiment_score(Sentiment.NEUTRAL, 0.5)
        assert score == 0.0

    def test_technical_score_oversold(self):
        """Test OVERSOLD condition produces positive score (buying opportunity)."""
        score = map_technical_score(MarketCondition.OVERSOLD, 1.0)
        assert score > 0
        assert score <= 1.0

    def test_technical_score_overbought(self):
        """Test OVERBOUGHT condition produces negative score (selling opportunity)."""
        score = map_technical_score(MarketCondition.OVERBOUGHT, 1.0)
        assert score < 0
        assert score >= -1.0

    def test_technical_score_neutral(self):
        """Test NEUTRAL condition produces zero score."""
        score = map_technical_score(MarketCondition.NEUTRAL, 0.5)
        assert score == 0.0


# --- Signal Freshness Tests ---

class TestSignalFreshness:
    """Tests for signal freshness validation."""

    def test_fresh_news_signal(self, now):
        """Test news signal with future expiry is fresh."""
        signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.8,
            confidence=0.9,
            reasoning="Test",
            source_items=["item1"],
            timestamp=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=71),
        )
        
        assert is_news_signal_fresh(signal, now) is True

    def test_expired_news_signal(self, now):
        """Test news signal with past expiry is stale."""
        signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.8,
            confidence=0.9,
            reasoning="Test",
            source_items=["item1"],
            timestamp=now - timedelta(hours=25),
            expires_at=now - timedelta(hours=1),
        )
        
        assert is_news_signal_fresh(signal, now) is False

    def test_fresh_technical_signal(self, now):
        """Test technical signal within 1 hour is fresh."""
        signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.NEUTRAL,
            rsi=50.0,
            current_price=100.0,
            support_levels=[],
            resistance_levels=[],
            confluence=ConfluenceResult(score=0.5, factors=[], description="Test"),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=now - timedelta(minutes=30),
        )
        
        assert is_technical_signal_fresh(signal, now) is True

    def test_stale_technical_signal(self, now):
        """Test technical signal older than 1 hour is stale."""
        signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.NEUTRAL,
            rsi=50.0,
            current_price=100.0,
            support_levels=[],
            resistance_levels=[],
            confluence=ConfluenceResult(score=0.5, factors=[], description="Test"),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=now - timedelta(hours=2),
        )
        
        assert is_technical_signal_fresh(signal, now) is False

    def test_validator_accepts_fresh_signals(self, fresh_news_signal, fresh_technical_signal, now):
        """Test validator accepts when both signals are fresh."""
        validator = SignalFreshnessValidator()
        result = validator.validate(fresh_news_signal, fresh_technical_signal, now)
        
        assert result.is_valid is True
        assert result.news_fresh is True
        assert result.technical_fresh is True
        assert result.rejection_reason is None


# --- Stop-Loss Calculation Tests ---

class TestStopLossCalculation:
    """Tests for stop-loss calculation."""

    def test_buy_stop_loss_below_entry(self, now):
        """Test BUY stop-loss is below entry price."""
        support_levels = [
            SupportResistance(level=95.0, strength=0.8, timeframe="1y",
                              last_tested=now - timedelta(days=30)),
        ]
        
        stop_loss = calculate_stop_loss(
            action=TradeAction.BUY,
            entry_price=100.0,
            support_levels=support_levels,
            resistance_levels=[],
            horizon=TradingHorizon.SHORT_TERM,
        )
        
        assert stop_loss < 100.0
        assert stop_loss > 0

    def test_sell_stop_loss_above_entry(self, now):
        """Test SELL stop-loss is above entry price."""
        resistance_levels = [
            SupportResistance(level=105.0, strength=0.8, timeframe="1y",
                              last_tested=now - timedelta(days=30)),
        ]
        
        stop_loss = calculate_stop_loss(
            action=TradeAction.SELL,
            entry_price=100.0,
            support_levels=[],
            resistance_levels=resistance_levels,
            horizon=TradingHorizon.SHORT_TERM,
        )
        
        assert stop_loss > 100.0

    def test_buy_stop_loss_without_support(self):
        """Test BUY stop-loss uses default buffer without support levels."""
        stop_loss = calculate_stop_loss(
            action=TradeAction.BUY,
            entry_price=100.0,
            support_levels=[],
            resistance_levels=[],
            horizon=TradingHorizon.SHORT_TERM,
        )
        
        assert stop_loss < 100.0
        assert stop_loss > 0

    def test_sell_stop_loss_without_resistance(self):
        """Test SELL stop-loss uses default buffer without resistance levels."""
        stop_loss = calculate_stop_loss(
            action=TradeAction.SELL,
            entry_price=100.0,
            support_levels=[],
            resistance_levels=[],
            horizon=TradingHorizon.SHORT_TERM,
        )
        
        assert stop_loss > 100.0

    def test_short_term_tighter_stops(self, now):
        """Test SHORT_TERM has tighter stops than LONG_TERM."""
        support_levels = [
            SupportResistance(level=90.0, strength=0.8, timeframe="1y",
                              last_tested=now - timedelta(days=30)),
        ]
        
        short_term_sl = calculate_stop_loss(
            action=TradeAction.BUY,
            entry_price=100.0,
            support_levels=support_levels,
            resistance_levels=[],
            horizon=TradingHorizon.SHORT_TERM,
        )
        
        long_term_sl = calculate_stop_loss(
            action=TradeAction.BUY,
            entry_price=100.0,
            support_levels=support_levels,
            resistance_levels=[],
            horizon=TradingHorizon.LONG_TERM,
        )
        
        # Short-term stop should be closer to entry (higher value for BUY)
        assert short_term_sl >= long_term_sl


# --- Take-Profit Calculation Tests ---

class TestTakeProfitCalculation:
    """Tests for take-profit calculation."""

    def test_buy_take_profit_above_entry(self, now):
        """Test BUY take-profit is above entry price."""
        resistance_levels = [
            SupportResistance(level=110.0, strength=0.7, timeframe="1y",
                              last_tested=now - timedelta(days=30)),
        ]
        
        take_profit = calculate_take_profit(
            action=TradeAction.BUY,
            entry_price=100.0,
            stop_loss=95.0,
            support_levels=[],
            resistance_levels=resistance_levels,
            horizon=TradingHorizon.SHORT_TERM,
        )
        
        assert take_profit > 100.0

    def test_sell_take_profit_below_entry(self, now):
        """Test SELL take-profit is below entry price."""
        support_levels = [
            SupportResistance(level=85.0, strength=0.7, timeframe="1y",
                              last_tested=now - timedelta(days=30)),
        ]
        
        take_profit = calculate_take_profit(
            action=TradeAction.SELL,
            entry_price=100.0,
            stop_loss=105.0,
            support_levels=support_levels,
            resistance_levels=[],
            horizon=TradingHorizon.SHORT_TERM,
        )
        
        assert take_profit < 100.0

    def test_minimum_risk_reward_ratio(self, now):
        """Test take-profit ensures minimum 1.5 risk-reward ratio."""
        take_profit = calculate_take_profit(
            action=TradeAction.BUY,
            entry_price=100.0,
            stop_loss=95.0,  # 5% risk
            support_levels=[],
            resistance_levels=[],
            horizon=TradingHorizon.SHORT_TERM,
        )
        
        risk = 100.0 - 95.0  # 5
        reward = take_profit - 100.0
        rr_ratio = reward / risk
        
        assert rr_ratio >= 1.5

    def test_long_term_targets_higher_levels(self, now):
        """Test LONG_TERM targets higher resistance levels."""
        resistance_levels = [
            SupportResistance(level=105.0, strength=0.8, timeframe="1m",
                              last_tested=now - timedelta(days=10)),
            SupportResistance(level=115.0, strength=0.7, timeframe="6m",
                              last_tested=now - timedelta(days=60)),
            SupportResistance(level=125.0, strength=0.6, timeframe="1y",
                              last_tested=now - timedelta(days=180)),
        ]
        
        short_term_tp = calculate_take_profit(
            action=TradeAction.BUY,
            entry_price=100.0,
            stop_loss=95.0,
            support_levels=[],
            resistance_levels=resistance_levels,
            horizon=TradingHorizon.SHORT_TERM,
        )
        
        long_term_tp = calculate_take_profit(
            action=TradeAction.BUY,
            entry_price=100.0,
            stop_loss=95.0,
            support_levels=[],
            resistance_levels=resistance_levels,
            horizon=TradingHorizon.LONG_TERM,
        )
        
        assert long_term_tp >= short_term_tp


# --- Risk-Reward Ratio Tests ---

class TestRiskRewardRatio:
    """Tests for risk-reward ratio calculation."""

    def test_buy_risk_reward_calculation(self):
        """Test risk-reward calculation for BUY trades."""
        rr = calculate_risk_reward_ratio(
            action=TradeAction.BUY,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
        )
        
        # Risk = 100 - 95 = 5
        # Reward = 110 - 100 = 10
        # RR = 10 / 5 = 2.0
        assert abs(rr - 2.0) < 0.001

    def test_sell_risk_reward_calculation(self):
        """Test risk-reward calculation for SELL trades."""
        rr = calculate_risk_reward_ratio(
            action=TradeAction.SELL,
            entry_price=100.0,
            stop_loss=105.0,
            take_profit=90.0,
        )
        
        # Risk = 105 - 100 = 5
        # Reward = 100 - 90 = 10
        # RR = 10 / 5 = 2.0
        assert abs(rr - 2.0) < 0.001

    def test_zero_risk_returns_zero(self):
        """Test zero risk returns zero ratio."""
        rr = calculate_risk_reward_ratio(
            action=TradeAction.BUY,
            entry_price=100.0,
            stop_loss=100.0,  # No risk
            take_profit=110.0,
        )
        
        assert rr == 0.0


# --- Strategy Agent Integration Tests ---

class TestStrategyAgent:
    """Integration tests for StrategyAgent."""

    @pytest.mark.asyncio
    async def test_evaluate_fresh_signals_produces_decision(
        self, fresh_news_signal, fresh_technical_signal, now
    ):
        """Test evaluation with fresh signals produces a decision."""
        # Mock the persistence layer
        mock_persistence = MagicMock()
        mock_persistence.persist_decision = AsyncMock(return_value="decision-001")
        
        agent = StrategyAgent(persistence=mock_persistence)
        
        result = await agent.evaluate(
            news_signal=fresh_news_signal,
            technical_signal=fresh_technical_signal,
            horizon=TradingHorizon.SHORT_TERM,
            news_signal_id="news-001",
            technical_signal_id="tech-001",
            current_time=now,
        )
        
        assert result.success is True
        assert result.decision is not None
        assert result.freshness_result.is_valid is True

    @pytest.mark.asyncio
    async def test_evaluate_expired_news_signal_fails(
        self, fresh_technical_signal, now
    ):
        """Test evaluation with expired news signal fails."""
        expired_news = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.8,
            confidence=0.9,
            reasoning="Old news",
            source_items=["news-001"],
            timestamp=now - timedelta(hours=25),
            expires_at=now - timedelta(hours=1),
        )
        
        mock_persistence = MagicMock()
        agent = StrategyAgent(persistence=mock_persistence)
        
        result = await agent.evaluate(
            news_signal=expired_news,
            technical_signal=fresh_technical_signal,
            horizon=TradingHorizon.SHORT_TERM,
            current_time=now,
        )
        
        assert result.success is False
        assert result.decision is None
        assert result.freshness_result.is_valid is False
        assert result.freshness_result.news_fresh is False

    @pytest.mark.asyncio
    async def test_evaluate_stale_technical_signal_fails(
        self, fresh_news_signal, now
    ):
        """Test evaluation with stale technical signal fails."""
        stale_tech = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=28.0,
            current_price=150.0,
            support_levels=[],
            resistance_levels=[],
            confluence=ConfluenceResult(score=0.7, factors=[], description="Test"),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=now - timedelta(hours=2),  # 2 hours old
        )
        
        mock_persistence = MagicMock()
        agent = StrategyAgent(persistence=mock_persistence)
        
        result = await agent.evaluate(
            news_signal=fresh_news_signal,
            technical_signal=stale_tech,
            horizon=TradingHorizon.SHORT_TERM,
            current_time=now,
        )
        
        assert result.success is False
        assert result.decision is None
        assert result.freshness_result.is_valid is False
        assert result.freshness_result.technical_fresh is False

    @pytest.mark.asyncio
    async def test_strong_buy_decision_has_valid_levels(
        self, now
    ):
        """Test STRONG_BUY decision has valid stop-loss and take-profit."""
        news = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.VERY_BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.9,
            confidence=0.9,
            reasoning="Major acquisition",
            source_items=["news-001"],
            timestamp=now - timedelta(minutes=30),
            expires_at=now + timedelta(hours=71),
        )
        
        tech = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.DOWNTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=25.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(level=95.0, strength=0.8, timeframe="1y",
                                  last_tested=now - timedelta(days=30)),
            ],
            resistance_levels=[
                SupportResistance(level=110.0, strength=0.7, timeframe="1y",
                                  last_tested=now - timedelta(days=30)),
            ],
            confluence=ConfluenceResult(score=0.8, factors=["rsi_oversold"],
                                        description="Oversold"),
            volume_trend="increasing",
            interest_rate_impact=0.1,
            timestamp=now - timedelta(minutes=15),
        )
        
        mock_persistence = MagicMock()
        mock_persistence.persist_decision = AsyncMock(return_value="decision-001")
        
        agent = StrategyAgent(persistence=mock_persistence)
        
        result = await agent.evaluate(
            news_signal=news,
            technical_signal=tech,
            horizon=TradingHorizon.SHORT_TERM,
            current_time=now,
        )
        
        assert result.success is True
        assert result.decision is not None
        assert result.decision.action == TradeAction.STRONG_BUY
        assert result.decision.conviction == Conviction.HIGH
        assert result.decision.stop_loss < result.decision.entry_price
        assert result.decision.take_profit > result.decision.entry_price
        assert result.decision.risk_reward_ratio >= 1.5

    @pytest.mark.asyncio
    async def test_no_trade_decision_for_conflicting_signals(
        self, now
    ):
        """Test NO_TRADE decision for conflicting signals."""
        news = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BEARISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.8,
            confidence=0.9,
            reasoning="Bad earnings",
            source_items=["news-001"],
            timestamp=now - timedelta(minutes=30),
            expires_at=now + timedelta(hours=71),
        )
        
        tech = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.DOWNTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=25.0,
            current_price=100.0,
            support_levels=[
                SupportResistance(level=95.0, strength=0.8, timeframe="1y",
                                  last_tested=now - timedelta(days=30)),
            ],
            resistance_levels=[
                SupportResistance(level=110.0, strength=0.7, timeframe="1y",
                                  last_tested=now - timedelta(days=30)),
            ],
            confluence=ConfluenceResult(score=0.7, factors=["rsi_oversold"],
                                        description="Oversold"),
            volume_trend="decreasing",
            interest_rate_impact=-0.1,
            timestamp=now - timedelta(minutes=15),
        )
        
        mock_persistence = MagicMock()
        mock_persistence.persist_decision = AsyncMock(return_value="decision-001")
        
        agent = StrategyAgent(persistence=mock_persistence)
        
        result = await agent.evaluate(
            news_signal=news,
            technical_signal=tech,
            horizon=TradingHorizon.SHORT_TERM,
            current_time=now,
        )
        
        assert result.success is True
        assert result.decision is not None
        assert result.decision.action == TradeAction.NO_TRADE

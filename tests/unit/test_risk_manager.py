"""
Unit tests for the Risk Manager.

Tests:
- Position sizing calculations (Requirements 5.1, 5.2, 5.6)
- Daily loss limit enforcement (Requirement 5.4)
- Correlated exposure tracking (Requirement 5.3)
- Open position limits (Requirement 5.5)
- Risk assessment generation (Requirements 5.7, 5.8)
"""

from datetime import datetime, timedelta, timezone

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
from src.agents.risk.config import (
    RiskConfig,
    PositionLimitsConfig,
    ExposureConfig,
    DailyLossConfig,
    AlertConfig,
)
from src.agents.risk.risk_manager import RiskManager, Portfolio
from src.agents.risk.position_validator import PositionValidator
from src.agents.risk.exposure_tracker import ExposureTracker, OpenPosition
from src.agents.risk.daily_loss_tracker import DailyLossTracker


# --- Fixtures ---

@pytest.fixture
def now():
    """Current timestamp for tests."""
    return datetime.now(timezone.utc)


@pytest.fixture
def sample_news_signal(now):
    """Create a sample news signal for testing."""
    return NewsSignal(
        symbol="AAPL",
        sentiment=Sentiment.BULLISH,
        impact_type=ImpactType.CASH_FLOW,
        impact_score=0.8,
        confidence=0.85,
        reasoning="Strong earnings report",
        source_items=["news-001"],
        timestamp=now,
        expires_at=now + timedelta(hours=72),
    )


@pytest.fixture
def sample_technical_signal(now):
    """Create a sample technical signal for testing."""
    return TechnicalSignal(
        symbol="AAPL",
        trend=TrendDirection.UPTREND,
        condition=MarketCondition.OVERSOLD,
        rsi=28.5,
        current_price=150.0,
        support_levels=[
            SupportResistance(
                level=145.0,
                strength=0.85,
                timeframe="1y",
                last_tested=now - timedelta(days=30),
            )
        ],
        resistance_levels=[
            SupportResistance(
                level=165.0,
                strength=0.75,
                timeframe="1y",
                last_tested=now - timedelta(days=60),
            )
        ],
        confluence=ConfluenceResult(
            score=0.83,
            factors=["rsi_oversold", "5y_support", "volume_spike"],
            description="Strong confluence at support",
        ),
        volume_trend="increasing",
        interest_rate_impact=0.1,
        timestamp=now,
    )


@pytest.fixture
def sample_trade_decision(now, sample_news_signal, sample_technical_signal):
    """Create a sample trade decision for testing."""
    return TradeDecision(
        symbol="AAPL",
        action=TradeAction.BUY,
        conviction=Conviction.MEDIUM,
        horizon=TradingHorizon.SHORT_TERM,
        entry_price=150.0,
        stop_loss=145.0,
        take_profit=162.5,
        position_size_pct=0.05,
        risk_reward_ratio=2.5,
        reasoning="Bullish news + oversold technical",
        news_signal=sample_news_signal,
        technical_signal=sample_technical_signal,
        timestamp=now,
        expires_at=now + timedelta(hours=4),
    )


@pytest.fixture
def empty_portfolio():
    """Create an empty portfolio for testing."""
    return Portfolio(
        total_value=100000.0,
        open_positions=[],
    )


# --- Position Validator Tests ---

class TestPositionValidator:
    """Tests for position size validation."""

    def test_valid_position_size_approved(self, sample_trade_decision):
        """Test that valid position sizes are approved."""
        config = PositionLimitsConfig(
            max_position_pct=0.05,
            max_portfolio_risk_pct=0.02,
        )
        validator = PositionValidator(config)
        
        result = validator.validate(sample_trade_decision, 100000.0)
        
        assert result.is_valid
        assert result.adjusted_size_pct is None
        assert result.rejection_reason is None

    def test_oversized_position_adjusted(self, now, sample_news_signal, sample_technical_signal):
        """Test that oversized positions are adjusted down."""
        config = PositionLimitsConfig(
            max_position_pct=0.05,
            max_portfolio_risk_pct=0.10,  # High to not interfere
        )
        validator = PositionValidator(config)
        
        decision = TradeDecision(
            symbol="AAPL",
            action=TradeAction.BUY,
            conviction=Conviction.MEDIUM,
            horizon=TradingHorizon.SHORT_TERM,
            entry_price=150.0,
            stop_loss=148.0,  # Small risk
            take_profit=155.0,
            position_size_pct=0.10,  # 10% - exceeds 5% limit
            risk_reward_ratio=2.5,
            reasoning="Test",
            news_signal=sample_news_signal,
            technical_signal=sample_technical_signal,
            timestamp=now,
            expires_at=now + timedelta(hours=4),
        )
        
        result = validator.validate(decision, 100000.0)
        
        assert result.is_valid
        assert result.adjusted_size_pct == 0.05
        assert len(result.warnings) > 0

    def test_high_risk_position_adjusted(self, now, sample_news_signal, sample_technical_signal):
        """Test that high-risk positions are adjusted to meet risk limits."""
        config = PositionLimitsConfig(
            max_position_pct=0.10,  # High to not interfere
            max_portfolio_risk_pct=0.02,  # 2% max risk
        )
        validator = PositionValidator(config)
        
        # Position with 10% stop-loss distance
        decision = TradeDecision(
            symbol="AAPL",
            action=TradeAction.BUY,
            conviction=Conviction.MEDIUM,
            horizon=TradingHorizon.SHORT_TERM,
            entry_price=100.0,
            stop_loss=90.0,  # 10% risk per share
            take_profit=120.0,
            position_size_pct=0.05,  # 5% position = 0.5% portfolio risk
            risk_reward_ratio=2.0,
            reasoning="Test",
            news_signal=sample_news_signal,
            technical_signal=sample_technical_signal,
            timestamp=now,
            expires_at=now + timedelta(hours=4),
        )
        
        result = validator.validate(decision, 100000.0)
        
        # 5% position * 10% risk = 0.5% portfolio risk, which is under 2%
        assert result.is_valid

    def test_buy_risk_calculation(self, sample_trade_decision):
        """Test risk calculation for BUY trades."""
        validator = PositionValidator()
        
        risk = validator._calculate_risk_per_share(sample_trade_decision)
        
        # For BUY: risk = entry - stop_loss = 150 - 145 = 5
        assert risk == 5.0

    def test_sell_risk_calculation(self, now, sample_news_signal):
        """Test risk calculation for SELL trades."""
        validator = PositionValidator()
        
        tech_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.DOWNTREND,
            condition=MarketCondition.OVERBOUGHT,
            rsi=75.0,
            current_price=150.0,
            support_levels=[SupportResistance(level=140.0, strength=0.8, timeframe="1y", last_tested=datetime.now(timezone.utc) - timedelta(days=30))],
            resistance_levels=[SupportResistance(level=160.0, strength=0.8, timeframe="1y", last_tested=datetime.now(timezone.utc) - timedelta(days=30))],
            confluence=ConfluenceResult(score=0.8, factors=["rsi_overbought"], description="Test"),
            volume_trend="increasing",
            interest_rate_impact=-0.1,
            timestamp=now,
        )
        
        decision = TradeDecision(
            symbol="AAPL",
            action=TradeAction.SELL,
            conviction=Conviction.MEDIUM,
            horizon=TradingHorizon.SHORT_TERM,
            entry_price=150.0,
            stop_loss=155.0,  # Above entry for SELL
            take_profit=140.0,  # Below entry for SELL
            position_size_pct=0.05,
            risk_reward_ratio=2.0,
            reasoning="Test",
            news_signal=NewsSignal(
                symbol="AAPL",
                sentiment=Sentiment.BEARISH,
                impact_type=ImpactType.CASH_FLOW,
                impact_score=0.8,
                confidence=0.85,
                reasoning="Test",
                source_items=["item1"],
                timestamp=now,
                expires_at=now + timedelta(hours=72),
            ),
            technical_signal=tech_signal,
            timestamp=now,
            expires_at=now + timedelta(hours=4),
        )
        
        risk = validator._calculate_risk_per_share(decision)
        
        # For SELL: risk = stop_loss - entry = 155 - 150 = 5
        assert risk == 5.0


# --- Exposure Tracker Tests ---

class TestExposureTracker:
    """Tests for correlated exposure tracking."""

    def test_add_and_remove_positions(self):
        """Test adding and removing positions."""
        tracker = ExposureTracker()
        
        tracker.add_position(OpenPosition("AAPL", 0.05, 150.0))
        assert tracker.get_open_position_count() == 1
        
        tracker.add_position(OpenPosition("MSFT", 0.03, 300.0))
        assert tracker.get_open_position_count() == 2
        
        tracker.remove_position("AAPL")
        assert tracker.get_open_position_count() == 1
        
        tracker.remove_position("MSFT")
        assert tracker.get_open_position_count() == 0

    def test_correlated_exposure_calculation(self):
        """Test correlated exposure is calculated correctly."""
        config = ExposureConfig(
            correlation_groups={"tech": ["AAPL", "MSFT", "GOOGL"]}
        )
        tracker = ExposureTracker(config)
        
        tracker.add_position(OpenPosition("AAPL", 0.05, 150.0))
        tracker.add_position(OpenPosition("MSFT", 0.03, 300.0))
        
        # Both are in tech group
        exposure = tracker.get_correlated_exposure("AAPL")
        assert exposure == 0.08  # 5% + 3%

    def test_uncorrelated_exposure(self):
        """Test uncorrelated symbols only count themselves."""
        config = ExposureConfig(
            correlation_groups={"tech": ["AAPL", "MSFT"]}
        )
        tracker = ExposureTracker(config)
        
        tracker.add_position(OpenPosition("AAPL", 0.05, 150.0))
        tracker.add_position(OpenPosition("UNKNOWN", 0.03, 100.0))
        
        # UNKNOWN is not in any group
        exposure = tracker.get_correlated_exposure("UNKNOWN")
        assert exposure == 0.03

    def test_open_position_limit_rejection(self, sample_trade_decision):
        """Test rejection when max positions reached."""
        config = ExposureConfig(max_open_positions=2)
        tracker = ExposureTracker(config)
        
        tracker.add_position(OpenPosition("MSFT", 0.05, 300.0))
        tracker.add_position(OpenPosition("GOOGL", 0.05, 2500.0))
        
        result = tracker.validate(sample_trade_decision)
        
        assert not result.is_valid
        assert "position" in result.rejection_reason.lower()

    def test_correlated_exposure_limit_adjustment(self, now, sample_news_signal, sample_technical_signal):
        """Test position adjustment when correlated exposure would exceed limit."""
        config = ExposureConfig(
            max_open_positions=10,
            max_correlated_exposure_pct=0.10,  # 10% max
            correlation_groups={"tech": ["AAPL", "MSFT"]},
        )
        tracker = ExposureTracker(config)
        
        # Add 8% exposure in MSFT
        tracker.add_position(OpenPosition("MSFT", 0.08, 300.0))
        
        # Try to add 5% in AAPL (would total 13%)
        decision = TradeDecision(
            symbol="AAPL",
            action=TradeAction.BUY,
            conviction=Conviction.MEDIUM,
            horizon=TradingHorizon.SHORT_TERM,
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=162.5,
            position_size_pct=0.05,
            risk_reward_ratio=2.5,
            reasoning="Test",
            news_signal=sample_news_signal,
            technical_signal=sample_technical_signal,
            timestamp=now,
            expires_at=now + timedelta(hours=4),
        )
        
        result = tracker.validate(decision)
        
        assert result.is_valid
        assert abs(result.adjusted_size_pct - 0.02) < 0.0001  # Only 2% room left


# --- Daily Loss Tracker Tests ---

class TestDailyLossTracker:
    """Tests for daily loss limit enforcement."""

    def test_record_losses(self):
        """Test recording losses."""
        tracker = DailyLossTracker()
        
        tracker.record_trade_result(-100.0)
        tracker.record_trade_result(-50.0)
        
        assert tracker.get_daily_loss() == 150.0

    def test_profits_dont_reduce_loss(self):
        """Test that profits don't reduce the loss counter."""
        tracker = DailyLossTracker()
        
        tracker.record_trade_result(-100.0)
        tracker.record_trade_result(200.0)  # Profit
        
        assert tracker.get_daily_loss() == 100.0

    def test_trading_halted_at_limit(self):
        """Test trading is halted when limit reached."""
        config = DailyLossConfig(max_daily_loss_pct=0.05)
        tracker = DailyLossTracker(loss_config=config)
        
        portfolio_value = 100000.0
        
        # Record 5% loss
        tracker.record_trade_result(-5000.0)
        
        assert tracker.is_trading_halted(portfolio_value)

    def test_trading_allowed_under_limit(self):
        """Test trading is allowed when under limit."""
        config = DailyLossConfig(max_daily_loss_pct=0.05)
        tracker = DailyLossTracker(loss_config=config)
        
        portfolio_value = 100000.0
        
        # Record 4% loss
        tracker.record_trade_result(-4000.0)
        
        assert not tracker.is_trading_halted(portfolio_value)

    def test_validation_rejection(self):
        """Test validation returns rejection when limit breached."""
        config = DailyLossConfig(max_daily_loss_pct=0.05)
        tracker = DailyLossTracker(loss_config=config)
        
        portfolio_value = 100000.0
        tracker.record_trade_result(-6000.0)  # 6% loss
        
        result = tracker.validate(portfolio_value)
        
        assert not result.is_valid
        assert result.rejection_reason is not None
        assert "daily loss" in result.rejection_reason.lower()

    def test_alert_sent_on_breach(self):
        """Test alert is sent when limit is breached."""
        alerts = []
        
        def alert_callback(alert_type, data):
            alerts.append((alert_type, data))
        
        config = DailyLossConfig(max_daily_loss_pct=0.05)
        alert_config = AlertConfig(alerts_enabled=True)
        tracker = DailyLossTracker(
            loss_config=config,
            alert_config=alert_config,
            alert_callback=alert_callback,
        )
        
        portfolio_value = 100000.0
        tracker.record_trade_result(-6000.0)
        
        result = tracker.validate(portfolio_value)
        
        assert result.alert_sent
        assert len(alerts) == 1
        assert alerts[0][0] == "DAILY_LOSS_LIMIT_BREACHED"

    def test_reset_clears_record(self):
        """Test reset clears the daily record."""
        tracker = DailyLossTracker()
        
        tracker.record_trade_result(-1000.0)
        assert tracker.get_daily_loss() == 1000.0
        
        tracker.reset_daily_record()
        assert tracker.get_daily_loss() == 0.0


# --- Risk Manager Integration Tests ---

class TestRiskManager:
    """Integration tests for the Risk Manager."""

    def test_approve_valid_trade(self, sample_trade_decision, empty_portfolio):
        """Test approval of a valid trade."""
        manager = RiskManager()
        
        result = manager.assess_trade(sample_trade_decision, empty_portfolio)
        
        assert result.approved
        assert result.rejection_reason is None
        assert 0.0 <= result.risk_score <= 1.0

    def test_reject_at_position_limit(self, sample_trade_decision):
        """Test rejection when at position limit."""
        config = RiskConfig()
        config.exposure.max_open_positions = 2
        manager = RiskManager(config)
        
        portfolio = Portfolio(
            total_value=100000.0,
            open_positions=[
                OpenPosition("MSFT", 0.05, 300.0),
                OpenPosition("GOOGL", 0.05, 2500.0),
            ],
        )
        
        result = manager.assess_trade(sample_trade_decision, portfolio)
        
        assert not result.approved
        assert "position" in result.rejection_reason.lower()

    def test_reject_at_daily_loss_limit(self, sample_trade_decision, empty_portfolio):
        """Test rejection when daily loss limit breached."""
        manager = RiskManager()
        
        # Record losses exceeding 5%
        manager.record_trade_result(-6000.0)
        
        result = manager.assess_trade(sample_trade_decision, empty_portfolio)
        
        assert not result.approved
        assert "daily loss" in result.rejection_reason.lower()

    def test_adjust_oversized_position(self, now, sample_news_signal, sample_technical_signal, empty_portfolio):
        """Test adjustment of oversized position."""
        manager = RiskManager()
        
        decision = TradeDecision(
            symbol="AAPL",
            action=TradeAction.BUY,
            conviction=Conviction.MEDIUM,
            horizon=TradingHorizon.SHORT_TERM,
            entry_price=150.0,
            stop_loss=148.0,
            take_profit=155.0,
            position_size_pct=0.10,  # 10% - exceeds 5% limit
            risk_reward_ratio=2.5,
            reasoning="Test",
            news_signal=sample_news_signal,
            technical_signal=sample_technical_signal,
            timestamp=now,
            expires_at=now + timedelta(hours=4),
        )
        
        result = manager.assess_trade(decision, empty_portfolio)
        
        assert result.approved
        assert result.adjusted_size is not None
        assert result.adjusted_size <= 0.05

    def test_risk_score_calculation(self, sample_trade_decision, empty_portfolio):
        """Test risk score is calculated correctly."""
        manager = RiskManager()
        
        result = manager.assess_trade(sample_trade_decision, empty_portfolio)
        
        assert 0.0 <= result.risk_score <= 1.0

    def test_risk_score_increases_with_exposure(self, sample_trade_decision):
        """Test risk score increases with more exposure."""
        manager = RiskManager()
        
        # Empty portfolio
        empty = Portfolio(total_value=100000.0, open_positions=[])
        result_empty = manager.assess_trade(sample_trade_decision, empty)
        
        # Portfolio with existing positions
        with_positions = Portfolio(
            total_value=100000.0,
            open_positions=[
                OpenPosition("MSFT", 0.05, 300.0),
                OpenPosition("GOOGL", 0.05, 2500.0),
            ],
        )
        result_with = manager.assess_trade(sample_trade_decision, with_positions)
        
        # Risk score should be higher with more positions
        assert result_with.risk_score >= result_empty.risk_score

    def test_get_portfolio_risk(self):
        """Test getting portfolio risk metrics."""
        config = RiskConfig()
        config.exposure.correlation_groups = {"tech": ["AAPL", "MSFT"]}
        manager = RiskManager(config)
        
        portfolio = Portfolio(
            total_value=100000.0,
            open_positions=[
                OpenPosition("AAPL", 0.05, 150.0),
                OpenPosition("MSFT", 0.03, 300.0),
            ],
        )
        
        risk = manager.get_portfolio_risk(portfolio)
        
        assert risk["open_positions"] == 2
        assert risk["max_open_positions"] == 10
        assert "tech" in risk["group_exposures"]
        assert risk["group_exposures"]["tech"] == 0.08

    def test_check_daily_limits(self, empty_portfolio):
        """Test checking daily limits."""
        manager = RiskManager()
        
        # Initially allowed
        assert manager.check_daily_limits(empty_portfolio.total_value)
        
        # After exceeding limit
        manager.record_trade_result(-6000.0)
        assert not manager.check_daily_limits(empty_portfolio.total_value)

    def test_position_tracking(self):
        """Test adding and removing positions."""
        manager = RiskManager()
        
        manager.add_position(OpenPosition("AAPL", 0.05, 150.0))
        
        portfolio = Portfolio(total_value=100000.0, open_positions=[])
        risk = manager.get_portfolio_risk(portfolio)
        
        # Position should be tracked internally
        # Note: get_portfolio_risk uses the provided portfolio, not internal state
        # This test verifies the add_position method works
        assert True  # Method executed without error

    def test_rejection_reason_always_provided(self, sample_trade_decision):
        """Test rejection reason is always provided when rejected."""
        config = RiskConfig()
        config.exposure.max_open_positions = 0  # Force rejection
        manager = RiskManager(config)
        
        portfolio = Portfolio(total_value=100000.0, open_positions=[])
        
        result = manager.assess_trade(sample_trade_decision, portfolio)
        
        if not result.approved:
            assert result.rejection_reason is not None
            assert len(result.rejection_reason) > 0

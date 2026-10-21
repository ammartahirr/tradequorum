"""
Unit tests for the Order Executor.

Tests:
- Order placement with mocked MT5 API (Requirement 6.1)
- Retry logic with simulated failures (Requirements 6.4, 6.5)
- Trade record validation (Requirements 13.1, 13.2, 13.4)
- Partial fill handling (Requirement 6.3)
- WebSocket broadcast on execution (Requirement 6.6)
"""

import asyncio
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
from src.models.trading import TradeDecision, OrderResult
from src.execution.config import ExecutionConfig, OrderExecutionConfig
from src.execution.order_executor import (
    OrderExecutor,
    OrderExecutionError,
    OrderValidationError,
    PartialFillError,
)
from src.execution.websocket_broadcaster import MockWebSocketBroadcaster
from src.execution.trade_persistence import TradePersistence


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
def sample_buy_decision(now, sample_news_signal, sample_technical_signal):
    """Create a sample BUY trade decision for testing."""
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
def sample_sell_decision(now):
    """Create a sample SELL trade decision for testing."""
    news_signal = NewsSignal(
        symbol="AAPL",
        sentiment=Sentiment.BEARISH,
        impact_type=ImpactType.CASH_FLOW,
        impact_score=0.8,
        confidence=0.85,
        reasoning="Weak guidance",
        source_items=["news-002"],
        timestamp=now,
        expires_at=now + timedelta(hours=72),
    )
    
    technical_signal = TechnicalSignal(
        symbol="AAPL",
        trend=TrendDirection.DOWNTREND,
        condition=MarketCondition.OVERBOUGHT,
        rsi=75.0,
        current_price=150.0,
        support_levels=[
            SupportResistance(
                level=140.0,
                strength=0.8,
                timeframe="1y",
                last_tested=now - timedelta(days=30),
            )
        ],
        resistance_levels=[
            SupportResistance(
                level=155.0,
                strength=0.8,
                timeframe="1y",
                last_tested=now - timedelta(days=30),
            )
        ],
        confluence=ConfluenceResult(
            score=0.8,
            factors=["rsi_overbought", "resistance"],
            description="Overbought at resistance",
        ),
        volume_trend="decreasing",
        interest_rate_impact=-0.1,
        timestamp=now,
    )
    
    return TradeDecision(
        symbol="AAPL",
        action=TradeAction.SELL,
        conviction=Conviction.MEDIUM,
        horizon=TradingHorizon.SHORT_TERM,
        entry_price=150.0,
        stop_loss=155.0,  # Above entry for SELL
        take_profit=140.0,  # Below entry for SELL
        position_size_pct=0.05,
        risk_reward_ratio=2.0,
        reasoning="Bearish news + overbought technical",
        news_signal=news_signal,
        technical_signal=technical_signal,
        timestamp=now,
        expires_at=now + timedelta(hours=4),
    )


@pytest.fixture
def mock_broadcaster():
    """Create a mock WebSocket broadcaster."""
    return MockWebSocketBroadcaster()


@pytest.fixture
def mock_persistence():
    """Create a mock trade persistence."""
    persistence = MagicMock(spec=TradePersistence)
    persistence.save_trade_record = AsyncMock()
    return persistence


# --- Order Placement Tests ---

class TestOrderPlacement:
    """Tests for order placement (Requirement 6.1)."""

    @pytest.mark.asyncio
    async def test_place_buy_order_success(self, sample_buy_decision, mock_broadcaster, mock_persistence):
        """Test successful BUY order placement."""
        executor = OrderExecutor(
            websocket_broadcaster=mock_broadcaster,
            trade_persistence=mock_persistence,
        )
        
        result = await executor.place_order(sample_buy_decision, 100.0)
        
        assert result.symbol == "AAPL"
        assert result.status == "filled"
        assert result.filled_price == sample_buy_decision.entry_price
        assert result.filled_quantity == 100.0
        assert result.order_id is not None

    @pytest.mark.asyncio
    async def test_place_sell_order_success(self, sample_sell_decision, mock_broadcaster, mock_persistence):
        """Test successful SELL order placement."""
        executor = OrderExecutor(
            websocket_broadcaster=mock_broadcaster,
            trade_persistence=mock_persistence,
        )
        
        result = await executor.place_order(sample_sell_decision, 100.0)
        
        assert result.symbol == "AAPL"
        assert result.status == "filled"
        assert result.filled_price == sample_sell_decision.entry_price

    @pytest.mark.asyncio
    async def test_order_broadcasts_result(self, sample_buy_decision, mock_broadcaster, mock_persistence):
        """Test that order execution broadcasts result (Requirement 6.6)."""
        executor = OrderExecutor(
            websocket_broadcaster=mock_broadcaster,
            trade_persistence=mock_persistence,
        )
        
        await executor.place_order(sample_buy_decision, 100.0)
        
        # Check broadcast was made
        trade_broadcasts = mock_broadcaster.get_broadcasts_of_type("trade_execution")
        assert len(trade_broadcasts) == 1
        assert trade_broadcasts[0]["data"]["symbol"] == "AAPL"
        assert trade_broadcasts[0]["data"]["action"] == "buy"

    @pytest.mark.asyncio
    async def test_order_persists_trade_record(self, sample_buy_decision, mock_broadcaster, mock_persistence):
        """Test that order execution persists trade record (Requirement 6.2)."""
        executor = OrderExecutor(
            websocket_broadcaster=mock_broadcaster,
            trade_persistence=mock_persistence,
        )
        
        await executor.place_order(sample_buy_decision, 100.0)
        
        # Check persistence was called
        mock_persistence.save_trade_record.assert_called_once()


# --- Trade Validation Tests ---

class TestTradeValidation:
    """Tests for trade record validation (Requirements 13.1, 13.2, 13.4).
    
    Note: The TradeDecision model validates stop-loss and risk-reward at the Pydantic level,
    so we test that the model correctly rejects invalid inputs. The OrderExecutor's validation
    is a secondary check that would catch any bypassed model validation.
    """

    def test_buy_invalid_stop_loss_above_entry(self, now, sample_news_signal, sample_technical_signal):
        """Test BUY trade rejected when stop_loss >= entry_price (Requirement 13.1).
        
        The TradeDecision model validates this at construction time.
        """
        from pydantic import ValidationError
        
        # Attempt to create invalid decision with stop_loss above entry
        with pytest.raises(ValidationError) as exc_info:
            TradeDecision(
                symbol="AAPL",
                action=TradeAction.BUY,
                conviction=Conviction.MEDIUM,
                horizon=TradingHorizon.SHORT_TERM,
                entry_price=150.0,
                stop_loss=155.0,  # Invalid: above entry for BUY
                take_profit=165.0,
                position_size_pct=0.05,
                risk_reward_ratio=3.0,
                reasoning="Test",
                news_signal=sample_news_signal,
                technical_signal=sample_technical_signal,
                timestamp=now,
                expires_at=now + timedelta(hours=4),
            )
        
        assert "stop_loss" in str(exc_info.value).lower()
        assert "below" in str(exc_info.value).lower()

    def test_sell_invalid_stop_loss_below_entry(self, now):
        """Test SELL trade rejected when stop_loss <= entry_price (Requirement 13.2).
        
        The TradeDecision model validates this at construction time.
        """
        from pydantic import ValidationError
        
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BEARISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.8,
            confidence=0.85,
            reasoning="Test",
            source_items=["item1"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        technical_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.DOWNTREND,
            condition=MarketCondition.OVERBOUGHT,
            rsi=75.0,
            current_price=150.0,
            support_levels=[SupportResistance(level=140.0, strength=0.8, timeframe="1y", last_tested=now - timedelta(days=30))],
            resistance_levels=[SupportResistance(level=160.0, strength=0.8, timeframe="1y", last_tested=now - timedelta(days=30))],
            confluence=ConfluenceResult(score=0.8, factors=["rsi_overbought"], description="Test"),
            volume_trend="decreasing",
            interest_rate_impact=-0.1,
            timestamp=now,
        )
        
        # Attempt to create invalid decision with stop_loss below entry for SELL
        with pytest.raises(ValidationError) as exc_info:
            TradeDecision(
                symbol="AAPL",
                action=TradeAction.SELL,
                conviction=Conviction.MEDIUM,
                horizon=TradingHorizon.SHORT_TERM,
                entry_price=150.0,
                stop_loss=145.0,  # Invalid: below entry for SELL
                take_profit=140.0,
                position_size_pct=0.05,
                risk_reward_ratio=2.0,
                reasoning="Test",
                news_signal=news_signal,
                technical_signal=technical_signal,
                timestamp=now,
                expires_at=now + timedelta(hours=4),
            )
        
        assert "stop_loss" in str(exc_info.value).lower()
        assert "above" in str(exc_info.value).lower()

    def test_invalid_risk_reward_ratio(self, now, sample_news_signal, sample_technical_signal):
        """Test trade rejected when risk_reward_ratio < 1.5 (Requirement 13.4).
        
        The TradeDecision model validates this at construction time.
        """
        from pydantic import ValidationError
        
        # Attempt to create decision with low risk-reward ratio
        with pytest.raises(ValidationError) as exc_info:
            TradeDecision(
                symbol="AAPL",
                action=TradeAction.BUY,
                conviction=Conviction.MEDIUM,
                horizon=TradingHorizon.SHORT_TERM,
                entry_price=150.0,
                stop_loss=145.0,
                take_profit=152.0,  # Only 2 points profit vs 5 points risk = 0.4 RR
                position_size_pct=0.05,
                risk_reward_ratio=0.4,  # Below 1.5 minimum
                reasoning="Test",
                news_signal=sample_news_signal,
                technical_signal=sample_technical_signal,
                timestamp=now,
                expires_at=now + timedelta(hours=4),
            )
        
        assert "risk-reward" in str(exc_info.value).lower()
        assert "1.5" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invalid_position_size(self, sample_buy_decision):
        """Test trade rejected when position size is invalid."""
        executor = OrderExecutor()
        
        with pytest.raises(OrderValidationError) as exc_info:
            await executor.place_order(sample_buy_decision, 0.0)
        
        assert "size" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_negative_position_size(self, sample_buy_decision):
        """Test trade rejected when position size is negative."""
        executor = OrderExecutor()
        
        with pytest.raises(OrderValidationError) as exc_info:
            await executor.place_order(sample_buy_decision, -100.0)
        
        assert "size" in str(exc_info.value).lower()


# --- Retry Logic Tests ---

class TestRetryLogic:
    """Tests for retry logic (Requirements 6.4, 6.5)."""

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, sample_buy_decision):
        """Test retry with exponential backoff on failure (Requirement 6.4)."""
        # Create executor with short retry delays for testing
        config = ExecutionConfig()
        config.order_execution.retry_delays_seconds = [0.01, 0.02, 0.04]
        
        executor = OrderExecutor(config=config)
        
        # Mock MT5 client that fails twice then succeeds
        mock_mt5 = MagicMock()
        mock_mt5.get_open_positions = AsyncMock(return_value=[])
        
        call_count = 0
        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Connection failed")
            return OrderResult(
                order_id="123",
                symbol="AAPL",
                status="filled",
                filled_price=150.0,
                filled_quantity=100.0,
                timestamp=datetime.now(timezone.utc),
            )
        
        executor._execute_order_mt5 = mock_execute
        executor._mt5_client = mock_mt5
        
        result = await executor.place_order(sample_buy_decision, 100.0)
        
        assert result.status == "filled"
        assert call_count == 3  # Failed twice, succeeded on third

    @pytest.mark.asyncio
    async def test_check_existing_position_before_retry(self, sample_buy_decision):
        """Test that existing positions are checked before retry (Requirement 6.5)."""
        config = ExecutionConfig()
        config.order_execution.retry_delays_seconds = [0.01, 0.02, 0.04]
        
        executor = OrderExecutor(config=config)
        
        # Mock MT5 client that returns an existing position
        mock_mt5 = MagicMock()
        mock_mt5.get_open_positions = AsyncMock(return_value=[
            {"symbol": "AAPL", "ticket": 12345, "volume": 50.0}
        ])
        
        executor._mt5_client = mock_mt5
        
        # Mock execute that always fails
        async def mock_execute(*args, **kwargs):
            raise Exception("Connection failed")
        
        executor._execute_order_mt5 = mock_execute
        
        # Should raise PartialFillError because position exists
        with pytest.raises(PartialFillError) as exc_info:
            await executor.place_order(sample_buy_decision, 100.0)
        
        assert "partially filled" in str(exc_info.value).lower()
        assert exc_info.value.partial_fill_info is not None

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self, sample_buy_decision):
        """Test error raised when all retries are exhausted."""
        config = ExecutionConfig()
        config.order_execution.retry_delays_seconds = [0.01, 0.02, 0.04]
        
        executor = OrderExecutor(config=config)
        
        # Mock MT5 client with no existing positions
        mock_mt5 = MagicMock()
        mock_mt5.get_open_positions = AsyncMock(return_value=[])
        
        executor._mt5_client = mock_mt5
        
        # Mock execute that always fails
        async def mock_execute(*args, **kwargs):
            raise Exception("Connection failed")
        
        executor._execute_order_mt5 = mock_execute
        
        with pytest.raises(OrderExecutionError) as exc_info:
            await executor.place_order(sample_buy_decision, 100.0)
        
        assert "3 attempts" in str(exc_info.value)


# --- Partial Fill Tests ---

class TestPartialFill:
    """Tests for partial fill handling (Requirement 6.3)."""

    @pytest.mark.asyncio
    async def test_partial_fill_logged(self, sample_buy_decision, mock_broadcaster, mock_persistence):
        """Test that partial fills are handled correctly."""
        executor = OrderExecutor(
            websocket_broadcaster=mock_broadcaster,
            trade_persistence=mock_persistence,
        )
        
        # Mock execute that returns partial fill
        async def mock_execute(*args, **kwargs):
            return OrderResult(
                order_id="123",
                symbol="AAPL",
                status="partial",
                filled_price=150.0,
                filled_quantity=50.0,  # Only half filled
                timestamp=datetime.now(timezone.utc),
            )
        
        executor._execute_order_mt5 = mock_execute
        
        result = await executor.place_order(sample_buy_decision, 100.0)
        
        assert result.status == "partial"
        assert result.filled_quantity == 50.0


# --- Account Info Tests ---

class TestAccountInfo:
    """Tests for account information retrieval."""

    @pytest.mark.asyncio
    async def test_get_account_info_no_client(self):
        """Test account info returns defaults when no MT5 client."""
        executor = OrderExecutor()
        
        info = await executor.get_account_info()
        
        assert info["balance"] == 100000.0
        assert info["equity"] == 100000.0

    @pytest.mark.asyncio
    async def test_get_open_positions_no_client(self):
        """Test open positions returns empty when no MT5 client."""
        executor = OrderExecutor()
        
        positions = await executor.get_open_positions()
        
        assert positions == []


# --- Order Modification Tests ---

class TestOrderModification:
    """Tests for order modification."""

    @pytest.mark.asyncio
    async def test_modify_order_no_client(self):
        """Test modify order returns success when no MT5 client."""
        executor = OrderExecutor()
        
        result = await executor.modify_order("123", stop_loss=144.0)
        
        assert result is True

    @pytest.mark.asyncio
    async def test_close_position_no_client(self):
        """Test close position returns result when no MT5 client."""
        executor = OrderExecutor()
        
        result = await executor.close_position("123")
        
        assert result.order_id == "123"
        assert result.status == "filled"

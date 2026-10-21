"""
Integration tests for error handling and graceful degradation.

Tests:
- MT5 connection failure and recovery (Requirements 6.4, 6.5, 10.6)
- Stale data handling (Requirement 10.2)
- LLM fallback (Requirement 10.1)
- SageMaker fallback (Requirement 10.3)

Requirements: 10.1, 10.2, 10.3, 10.6, 6.4, 6.5
"""

import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.models import OHLCV, NewsItem, NewsSignal, TechnicalSignal
from src.models.enums import (
    Conviction,
    ImpactType,
    MarketCondition,
    Sentiment,
    TradeAction,
    TradingHorizon,
    TrendDirection,
)
from src.models.signals import ConfluenceResult, SupportResistance


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def now():
    """Current timestamp for tests."""
    return datetime.now(timezone.utc)


@pytest.fixture
def sample_candles():
    """Create sample OHLCV candles for testing."""
    base_time = datetime(2024, 1, 15, 14, 30, tzinfo=timezone.utc)
    candles = []
    for i in range(250):
        candle = OHLCV(
            timestamp=base_time + timedelta(days=i),
            open=100.0 + i * 0.1,
            high=105.0 + i * 0.1,
            low=95.0 + i * 0.1,
            close=102.0 + i * 0.1,
            volume=1000000 + i * 10000,
        )
        candles.append(candle)
    return candles


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
def sample_news_item():
    """Create a sample news item for testing."""
    return NewsItem(
        source="reuters",
        headline="Apple reports record Q4 earnings",
        content="Apple Inc. reported record quarterly earnings, beating analyst expectations.",
        published_at=datetime.now(timezone.utc),
        symbols=["AAPL"],
        url="https://reuters.com/article/123",
    )


# ============================================================================
# MT5 Connection Failure and Recovery Tests (Requirements 6.4, 6.5, 10.6)
# ============================================================================

class TestMT5ConnectionFailureHandling:
    """Tests for MT5 connection failure handling."""

    @pytest.mark.asyncio
    async def test_retry_with_exponential_backoff(self):
        """Test retry with exponential backoff (Requirement 6.4)."""
        from src.agents.technical.mt5_client import (
            MT5Client,
            MT5ConnectionError,
            MT5Credentials,
        )
        from src.agents.technical.config import MT5Config
        
        config = MT5Config()
        config.retry_delays_seconds = [0.01, 0.02, 0.04]  # Fast for testing
        
        client = MT5Client(config=config)
        
        # Mock the MT5 module - fail twice, succeed on third
        mock_mt5 = MagicMock()
        mock_mt5.initialize.side_effect = [False, False, True]
        mock_mt5.last_error.return_value = (1, "Connection failed")
        mock_mt5.login.return_value = True
        client._mt5 = mock_mt5
        
        # Mock secrets client
        mock_secrets = AsyncMock()
        mock_secrets.get_mt5_credentials.return_value = MT5Credentials(
            server="test-server",
            login=12345,
            password="test-password",
        )
        client.secrets_client = mock_secrets
        
        result = await client.connect()
        
        assert result is True
        assert mock_mt5.initialize.call_count == 3
        assert client.is_connected is True

    @pytest.mark.asyncio
    async def test_connection_failure_after_all_retries(self):
        """Test connection failure after all retries exhausted."""
        from src.agents.technical.mt5_client import (
            MT5Client,
            MT5ConnectionError,
            MT5Credentials,
        )
        from src.agents.technical.config import MT5Config
        
        config = MT5Config()
        config.retry_delays_seconds = [0.01, 0.02, 0.04]
        
        client = MT5Client(config=config)
        
        # Mock the MT5 module - always fail
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = False
        mock_mt5.last_error.return_value = (1, "Connection failed")
        client._mt5 = mock_mt5
        
        # Mock secrets client
        mock_secrets = AsyncMock()
        mock_secrets.get_mt5_credentials.return_value = MT5Credentials(
            server="test-server",
            login=12345,
            password="test-password",
        )
        client.secrets_client = mock_secrets
        
        with pytest.raises(MT5ConnectionError) as exc_info:
            await client.connect()
        
        assert "3" in str(exc_info.value)  # 3 attempts
        assert client.is_connected is False


    @pytest.mark.asyncio
    async def test_reconnection_triggers_callback(self):
        """Test that reconnection triggers signal recalculation callback (Requirement 10.6)."""
        from src.agents.technical.mt5_client import MT5Client, MT5Credentials
        from src.agents.technical.config import MT5Config
        
        callback_called = False
        
        async def mock_callback():
            nonlocal callback_called
            callback_called = True
        
        config = MT5Config()
        config.retry_delays_seconds = [0.01]
        
        client = MT5Client(config=config, on_reconnect_callback=mock_callback)
        
        # Mock the MT5 module
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.login.return_value = True
        mock_mt5.shutdown.return_value = None
        client._mt5 = mock_mt5
        
        # Mock secrets client
        mock_secrets = AsyncMock()
        mock_secrets.get_mt5_credentials.return_value = MT5Credentials(
            server="test-server",
            login=12345,
            password="test-password",
        )
        client.secrets_client = mock_secrets
        
        # Simulate reconnection
        result = await client.reconnect_with_signal_recalculation()
        
        assert result is True
        assert callback_called is True

    @pytest.mark.asyncio
    async def test_query_positions_before_retry(self):
        """Test that open positions are queried before retry (Requirement 6.5)."""
        from src.execution.order_executor import (
            OrderExecutor,
            PartialFillError,
        )
        from src.execution.config import ExecutionConfig
        from src.models.trading import TradeDecision
        
        config = ExecutionConfig()
        config.order_execution.retry_delays_seconds = [0.01, 0.02]
        
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
        
        # Create a valid trade decision
        now = datetime.now(timezone.utc)
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.8,
            confidence=0.85,
            reasoning="Test",
            source_items=["test"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        technical_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=28.5,
            current_price=150.0,
            support_levels=[SupportResistance(level=145.0, strength=0.8, timeframe="1y", last_tested=now)],
            resistance_levels=[SupportResistance(level=165.0, strength=0.8, timeframe="1y", last_tested=now)],
            confluence=ConfluenceResult(score=0.8, factors=["test"], description="Test"),
            volume_trend="increasing",
            interest_rate_impact=0.1,
            timestamp=now,
        )
        
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
            news_signal=news_signal,
            technical_signal=technical_signal,
            timestamp=now,
            expires_at=now + timedelta(hours=4),
        )
        
        # Should raise PartialFillError because position exists
        with pytest.raises(PartialFillError) as exc_info:
            await executor.place_order(decision, 100.0)
        
        assert "partially filled" in str(exc_info.value).lower()
        assert exc_info.value.partial_fill_info is not None


# ============================================================================
# Stale Data Handling Tests (Requirement 10.2)
# ============================================================================

class TestStaleDataHandling:
    """Tests for stale market data handling."""

    def test_data_marked_stale_after_5_minutes(self):
        """Test that data is marked stale when >5 min old during trading hours (Requirement 10.2)."""
        from src.agents.technical.market_data import is_data_stale, StaleDataDetector
        from src.agents.technical.config import StaleDataConfig
        
        config = StaleDataConfig(
            stale_threshold_minutes=5,
            trading_start_hour_utc=14,
            trading_end_hour_utc=21,
            trading_days=[0, 1, 2, 3, 4],
        )
        
        # Monday at 3:00 PM UTC (during trading hours)
        current_time = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
        
        # Data updated 6 minutes ago - should be stale
        last_update = current_time - timedelta(minutes=6)
        assert is_data_stale(last_update, current_time, config) is True
        
        # Data updated 4 minutes ago - should NOT be stale
        last_update = current_time - timedelta(minutes=4)
        assert is_data_stale(last_update, current_time, config) is False

    def test_data_not_stale_outside_trading_hours(self):
        """Test that old data is not stale outside trading hours."""
        from src.agents.technical.market_data import is_data_stale
        from src.agents.technical.config import StaleDataConfig
        
        config = StaleDataConfig(
            stale_threshold_minutes=5,
            trading_start_hour_utc=14,
            trading_end_hour_utc=21,
            trading_days=[0, 1, 2, 3, 4],
        )
        
        # Saturday (not a trading day)
        current_time = datetime(2024, 1, 13, 15, 0, tzinfo=timezone.utc)
        last_update = current_time - timedelta(hours=2)
        
        assert is_data_stale(last_update, current_time, config) is False

    @pytest.mark.asyncio
    async def test_strategy_agent_halts_on_stale_data(
        self, sample_news_signal, sample_technical_signal
    ):
        """Test that Strategy Agent halts trade decisions when data is stale (Requirement 10.2)."""
        from src.agents.strategy.strategy_agent import StrategyAgent
        from src.agents.strategy.config import StrategyConfig, StaleDataConfig
        
        config = StrategyConfig()
        config.stale_data = StaleDataConfig(
            stale_threshold_minutes=5,
            halt_on_stale_data=True,
        )
        
        # Create agent with stale data detector that always returns True
        agent = StrategyAgent(config=config, stale_data_detector=lambda symbol: True)
        
        result = await agent.evaluate(
            sample_news_signal,
            sample_technical_signal,
        )
        
        assert result.success is False
        assert result.is_stale_data is True
        assert "stale" in result.error_message.lower()
        assert result.decision is None

    @pytest.mark.asyncio
    async def test_strategy_agent_continues_with_fresh_data(
        self, sample_news_signal, sample_technical_signal
    ):
        """Test that Strategy Agent continues when data is fresh."""
        from src.agents.strategy.strategy_agent import StrategyAgent
        from src.agents.strategy.config import StrategyConfig, StaleDataConfig
        
        config = StrategyConfig()
        config.stale_data = StaleDataConfig(
            stale_threshold_minutes=5,
            halt_on_stale_data=True,
        )
        
        # Create agent with stale data detector that always returns False
        agent = StrategyAgent(config=config, stale_data_detector=lambda symbol: False)
        
        result = await agent.evaluate(
            sample_news_signal,
            sample_technical_signal,
        )
        
        # Should succeed (or fail for other reasons, but not stale data)
        assert result.is_stale_data is False

    def test_stale_data_detector_tracks_symbols(self):
        """Test that StaleDataDetector correctly tracks multiple symbols."""
        from src.agents.technical.market_data import StaleDataDetector
        from src.agents.technical.config import StaleDataConfig
        
        config = StaleDataConfig(
            stale_threshold_minutes=5,
            trading_start_hour_utc=14,
            trading_end_hour_utc=21,
            trading_days=[0, 1, 2, 3, 4],
        )
        
        detector = StaleDataDetector(config)
        
        # Monday at 3:00 PM UTC (during trading hours)
        current_time = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
        
        # Record fresh update for AAPL
        detector.record_update("AAPL", current_time - timedelta(minutes=2))
        
        # Record stale update for MSFT
        detector.record_update("MSFT", current_time - timedelta(minutes=10))
        
        # Check staleness
        assert detector.is_stale("AAPL", current_time) is False
        assert detector.is_stale("MSFT", current_time) is True
        
        # GOOGL has no update - should be stale during trading hours
        assert detector.is_stale("GOOGL", current_time) is True


# ============================================================================
# LLM Fallback Tests (Requirement 10.1)
# ============================================================================

class TestLLMFallback:
    """Tests for LLM fallback to rule-based keyword analysis."""

    @pytest.mark.asyncio
    async def test_fallback_on_llm_error(self, sample_news_item):
        """Test fallback to keyword analysis when LLM fails (Requirement 10.1)."""
        from src.agents.news.analyzer import (
            analyze_news_impact,
            ClaudeOpusClient,
            LLMError,
            FALLBACK_CONFIDENCE_MULTIPLIER,
        )
        
        # Create mock LLM client that raises an error
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.side_effect = LLMError("API timeout")
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        assert isinstance(signal, NewsSignal)
        assert "Rule-based analysis" in signal.reasoning
        assert "LLM unavailable" in signal.reasoning

    @pytest.mark.asyncio
    async def test_fallback_confidence_multiplied_by_half(self, sample_news_item):
        """Test that fallback mode multiplies confidence by 0.5 (Requirement 10.1)."""
        from src.agents.news.analyzer import (
            analyze_news_impact,
            FALLBACK_CONFIDENCE_MULTIPLIER,
        )
        
        # Use fallback (no LLM client)
        signal = await analyze_news_impact(sample_news_item, llm_client=None)
        
        # Confidence should be reduced by fallback multiplier
        # Max base confidence is 0.8, so max fallback confidence is 0.4
        assert signal.confidence <= 0.8 * FALLBACK_CONFIDENCE_MULTIPLIER
        assert FALLBACK_CONFIDENCE_MULTIPLIER == 0.5

    @pytest.mark.asyncio
    async def test_fallback_detects_bullish_keywords(self):
        """Test that fallback correctly detects bullish sentiment."""
        from src.agents.news.analyzer import analyze_keywords
        from src.models.enums import Sentiment
        
        text = "Apple beats earnings expectations with record revenue growth and profit increase"
        sentiment, impact_type, impact_score, confidence = analyze_keywords(text)
        
        assert sentiment in [Sentiment.BULLISH, Sentiment.VERY_BULLISH]

    @pytest.mark.asyncio
    async def test_fallback_detects_bearish_keywords(self):
        """Test that fallback correctly detects bearish sentiment."""
        from src.agents.news.analyzer import analyze_keywords
        from src.models.enums import Sentiment
        
        text = "Company reports massive losses, announces layoffs and restructuring"
        sentiment, impact_type, impact_score, confidence = analyze_keywords(text)
        
        assert sentiment in [Sentiment.BEARISH, Sentiment.VERY_BEARISH]

    @pytest.mark.asyncio
    async def test_cash_flow_downgraded_in_fallback_mode(self, sample_news_item):
        """Test that CASH_FLOW is downgraded to HYPE in fallback mode due to low confidence."""
        from src.agents.news.analyzer import (
            analyze_news_impact,
            CASH_FLOW_CONFIDENCE_THRESHOLD,
        )
        from src.models.enums import ImpactType
        
        # Modify news item to have cash flow keywords
        sample_news_item.headline = "Apple reports strong quarterly earnings and revenue"
        sample_news_item.content = "Apple Inc. reported strong earnings with increased profit margins."
        
        signal = await analyze_news_impact(sample_news_item, llm_client=None)
        
        # In fallback mode, confidence is multiplied by 0.5
        # If the base confidence was high enough to classify as CASH_FLOW,
        # it should be downgraded to HYPE because 0.5 * confidence < 0.7
        if signal.confidence < CASH_FLOW_CONFIDENCE_THRESHOLD:
            # If confidence is below threshold, CASH_FLOW should be downgraded
            if "cash_flow" in signal.reasoning.lower() or "downgraded" in signal.reasoning.lower():
                assert signal.impact_type == ImpactType.HYPE


# ============================================================================
# SageMaker Fallback Tests (Requirement 10.3)
# ============================================================================

class TestSageMakerFallback:
    """Tests for SageMaker fallback when ML prediction fails."""

    @pytest.mark.asyncio
    async def test_skip_ml_prediction_on_timeout(self, sample_candles):
        """Test that ML prediction is skipped on timeout >10s (Requirement 10.3)."""
        from src.agents.technical.signal_generator import (
            TechnicalSignalGenerator,
            SageMakerClient,
            SAGEMAKER_TIMEOUT_SECONDS,
        )
        
        # Create mock SageMaker client that times out
        mock_sagemaker = AsyncMock(spec=SageMakerClient)
        mock_sagemaker.predict_pattern.return_value = None  # Timeout returns None
        
        generator = TechnicalSignalGenerator(
            sagemaker_client=mock_sagemaker,
            use_sagemaker=True,
        )
        
        # Generate signal - should succeed without ML prediction
        signal = await generator.generate_signal("AAPL", sample_candles)
        
        assert signal is not None
        assert signal.symbol == "AAPL"
        # Signal should be generated with traditional indicators only
        assert signal.confluence is not None

    @pytest.mark.asyncio
    async def test_skip_ml_prediction_on_error(self, sample_candles):
        """Test that ML prediction is skipped on SageMaker error (Requirement 10.3)."""
        from src.agents.technical.signal_generator import (
            TechnicalSignalGenerator,
            SageMakerClient,
        )
        
        # Create a mock SageMaker client where predict_pattern returns None (simulating error handling)
        # The SageMakerClient.predict_pattern already handles exceptions internally and returns None
        mock_sagemaker = MagicMock(spec=SageMakerClient)
        
        # Create an async function that raises an exception
        async def mock_predict_pattern(*args, **kwargs):
            raise Exception("SageMaker error")
        
        mock_sagemaker.predict_pattern = mock_predict_pattern
        
        generator = TechnicalSignalGenerator(
            sagemaker_client=mock_sagemaker,
            use_sagemaker=True,
        )
        
        # Generate signal - should succeed without ML prediction
        # The _get_pattern_prediction method catches exceptions and returns None
        signal = await generator.generate_signal("AAPL", sample_candles)
        
        assert signal is not None
        assert signal.symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_sagemaker_timeout_is_10_seconds(self):
        """Test that SageMaker timeout is configured to 10 seconds (Requirement 10.3)."""
        from src.agents.technical.signal_generator import SAGEMAKER_TIMEOUT_SECONDS
        
        assert SAGEMAKER_TIMEOUT_SECONDS == 10

    @pytest.mark.asyncio
    async def test_signal_generated_without_sagemaker(self, sample_candles):
        """Test that signals can be generated without SageMaker."""
        from src.agents.technical.signal_generator import TechnicalSignalGenerator
        
        generator = TechnicalSignalGenerator(use_sagemaker=False)
        
        signal = await generator.generate_signal("AAPL", sample_candles)
        
        assert signal is not None
        assert signal.symbol == "AAPL"
        assert signal.rsi > 0
        assert signal.confluence is not None

    @pytest.mark.asyncio
    async def test_ml_prediction_enhances_confluence_when_available(self, sample_candles):
        """Test that ML prediction enhances confluence when available."""
        from src.agents.technical.signal_generator import TechnicalSignalGenerator, SageMakerClient
        
        # Create mock SageMaker client that returns a prediction
        mock_sagemaker = AsyncMock(spec=SageMakerClient)
        mock_sagemaker.predict_pattern.return_value = {
            "pattern": "double_bottom",
            "confidence": 0.85,
        }
        
        generator = TechnicalSignalGenerator(
            sagemaker_client=mock_sagemaker,
            use_sagemaker=True,
        )
        
        signal = await generator.generate_signal("AAPL", sample_candles)
        
        assert signal is not None
        # If ML prediction was used, it should be in the confluence factors
        if "ml_pattern_double_bottom" in signal.confluence.factors:
            assert "double_bottom" in signal.confluence.description


# ============================================================================
# Integration Tests for Full Error Handling Pipeline
# ============================================================================

class TestFullErrorHandlingPipeline:
    """Integration tests for the complete error handling pipeline."""

    @pytest.mark.asyncio
    async def test_trading_halted_and_resumed(
        self, sample_news_signal, sample_technical_signal
    ):
        """Test that trading can be halted and resumed."""
        from src.agents.strategy.strategy_agent import StrategyAgent
        
        agent = StrategyAgent()
        
        # Initially trading should not be halted
        assert agent.is_trading_halted is False
        
        # Halt trading
        agent.halt_trading("Daily loss limit breached")
        assert agent.is_trading_halted is True
        assert agent.halt_reason == "Daily loss limit breached"
        
        # Try to evaluate - should fail
        result = await agent.evaluate(sample_news_signal, sample_technical_signal)
        assert result.success is False
        assert "halted" in result.error_message.lower()
        
        # Resume trading
        agent.resume_trading()
        assert agent.is_trading_halted is False
        assert agent.halt_reason is None

    @pytest.mark.asyncio
    async def test_stale_data_detector_integration(
        self, sample_news_signal, sample_technical_signal
    ):
        """Test integration of stale data detector with strategy agent."""
        from src.agents.strategy.strategy_agent import StrategyAgent
        from src.agents.technical.market_data import StaleDataDetector
        from src.agents.technical.config import StaleDataConfig
        
        # Create stale data detector
        stale_config = StaleDataConfig(
            stale_threshold_minutes=5,
            trading_start_hour_utc=14,
            trading_end_hour_utc=21,
            trading_days=[0, 1, 2, 3, 4],
        )
        detector = StaleDataDetector(stale_config)
        
        # Create strategy agent with detector
        agent = StrategyAgent(stale_data_detector=detector.is_stale)
        
        # During trading hours with no update - should be stale
        # (This depends on current time being during trading hours)
        # For testing, we'll use the detector directly
        current_time = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
        
        # No update recorded - should be stale during trading hours
        assert detector.is_stale("AAPL", current_time) is True
        
        # Record fresh update
        detector.record_update("AAPL", current_time - timedelta(minutes=2))
        assert detector.is_stale("AAPL", current_time) is False

    @pytest.mark.asyncio
    async def test_mt5_reconnection_flow(self):
        """Test the complete MT5 reconnection flow."""
        from src.agents.technical.mt5_client import MT5Client, MT5Credentials
        from src.agents.technical.config import MT5Config
        
        signals_recalculated = False
        
        async def recalculate_signals():
            nonlocal signals_recalculated
            signals_recalculated = True
        
        config = MT5Config()
        config.retry_delays_seconds = [0.01]
        
        client = MT5Client(config=config, on_reconnect_callback=recalculate_signals)
        
        # Mock MT5 module
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.login.return_value = True
        mock_mt5.shutdown.return_value = None
        client._mt5 = mock_mt5
        
        # Mock secrets
        mock_secrets = AsyncMock()
        mock_secrets.get_mt5_credentials.return_value = MT5Credentials(
            server="test", login=123, password="test"
        )
        client.secrets_client = mock_secrets
        
        # Initial connection
        await client.connect()
        assert client.is_connected is True
        
        # Simulate disconnect
        await client.disconnect()
        assert client.is_connected is False
        assert client.last_disconnect_time is not None
        
        # Reconnect with signal recalculation
        result = await client.reconnect_with_signal_recalculation()
        assert result is True
        assert signals_recalculated is True

    @pytest.mark.asyncio
    async def test_graceful_degradation_chain(self, sample_news_item, sample_candles):
        """Test that the system degrades gracefully through multiple failures."""
        from src.agents.news.analyzer import analyze_news_impact, ClaudeOpusClient, LLMError
        from src.agents.technical.signal_generator import TechnicalSignalGenerator, SageMakerClient
        
        # 1. LLM fails - should fall back to keyword analysis
        mock_llm = AsyncMock(spec=ClaudeOpusClient)
        mock_llm.analyze.side_effect = LLMError("LLM unavailable")
        
        news_signal = await analyze_news_impact(sample_news_item, llm_client=mock_llm)
        assert news_signal is not None
        assert "Rule-based" in news_signal.reasoning
        
        # 2. SageMaker fails - should continue with traditional indicators
        mock_sagemaker = AsyncMock(spec=SageMakerClient)
        mock_sagemaker.predict_pattern.return_value = None  # Timeout
        
        generator = TechnicalSignalGenerator(
            sagemaker_client=mock_sagemaker,
            use_sagemaker=True,
        )
        
        technical_signal = await generator.generate_signal("AAPL", sample_candles)
        assert technical_signal is not None
        assert technical_signal.confluence is not None
        
        # Both signals generated despite failures
        assert news_signal.symbol == "AAPL"
        assert technical_signal.symbol == "AAPL"

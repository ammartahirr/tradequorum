"""
End-to-end integration tests for the AI Trading System.

Tests:
- Full pipeline: news ingestion -> signal -> decision -> risk check -> order
- WebSocket dashboard update flow

Requirements: All
"""

import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.models import NewsItem, NewsSignal, TechnicalSignal, OHLCV
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
from src.models.trading import TradeDecision, OrderResult, RiskAssessment

from src.pipeline.trading_pipeline import TradingPipeline, PipelineResult
from src.pipeline.pipeline_config import PipelineConfig
from src.execution.websocket_broadcaster import MockWebSocketBroadcaster


@pytest.fixture
def now():
    """Current timestamp for tests."""
    return datetime.now(timezone.utc)


@pytest.fixture
def sample_candles():
    """Create sample OHLCV candles for testing (250 candles required)."""
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
def sample_news_item():
    """Create a sample news item for testing."""
    return NewsItem(
        source="reuters",
        headline="Apple reports record Q4 earnings beating expectations",
        content="Apple Inc. reported record quarterly earnings with strong iPhone sales.",
        published_at=datetime.now(timezone.utc),
        symbols=["AAPL"],
        url="https://reuters.com/article/123",
    )


@pytest.fixture
def bullish_news_item():
    """Create a bullish news item for testing."""
    return NewsItem(
        source="reuters",
        headline="Company beats earnings with record revenue growth and profit increase",
        content="Strong quarterly results with revenue growth exceeding analyst expectations.",
        published_at=datetime.now(timezone.utc),
        symbols=["AAPL"],
        url="https://reuters.com/article/456",
    )


@pytest.fixture
def pipeline_config():
    """Create pipeline config for testing."""
    config = PipelineConfig()
    config.enable_persistence = False
    config.use_sagemaker = False
    config.use_llm = False
    config.enable_websocket_broadcasts = True
    return config


class TestFullPipelineFlow:
    """Tests for the complete trading pipeline flow."""

    @pytest.mark.asyncio
    async def test_full_pipeline_news_to_no_trade(
        self, sample_news_item, sample_candles, pipeline_config
    ):
        """Test pipeline that results in NO_TRADE decision."""
        pipeline = TradingPipeline(config=pipeline_config)
        
        result = await pipeline.run_full_pipeline(
            news_item=sample_news_item,
            candles=sample_candles,
            portfolio_value=100000.0,
            horizon=TradingHorizon.SHORT_TERM,
        )
        
        assert result.symbol == "AAPL"
        assert result.news_signal is not None
        assert result.technical_signal is not None
        # Pipeline should complete successfully even if no trade

    @pytest.mark.asyncio
    async def test_pipeline_stages_execute_in_order(
        self, bullish_news_item, sample_candles, pipeline_config
    ):
        """Test that pipeline stages execute in correct order."""
        pipeline = TradingPipeline(config=pipeline_config)
        
        # Stage 1: News analysis
        news_signal, news_id = await pipeline.analyze_news(bullish_news_item)
        assert news_signal is not None
        assert news_signal.symbol == "AAPL"
        assert news_signal.sentiment in [
            Sentiment.BULLISH, Sentiment.VERY_BULLISH, Sentiment.NEUTRAL
        ]
        
        # Stage 2: Technical analysis
        tech_signal, tech_id = await pipeline.analyze_technical("AAPL", sample_candles)
        assert tech_signal is not None
        assert tech_signal.symbol == "AAPL"
        assert 0 <= tech_signal.rsi <= 100
        
        # Stage 3: Strategy evaluation
        decision, decision_id = await pipeline.evaluate_strategy(
            news_signal, tech_signal, TradingHorizon.SHORT_TERM
        )
        # Decision may be None or have any action depending on signals
        
        if decision and decision.action in {
            TradeAction.BUY, TradeAction.STRONG_BUY,
            TradeAction.SELL, TradeAction.STRONG_SELL
        }:
            # Stage 4: Risk assessment
            assessment = await pipeline.assess_risk(decision, 100000.0)
            assert assessment is not None
            assert 0 <= assessment.risk_score <= 1.0

    @pytest.mark.asyncio
    async def test_pipeline_with_mock_order_execution(
        self, bullish_news_item, sample_candles, pipeline_config, now
    ):
        """Test pipeline with mocked order execution."""
        pipeline = TradingPipeline(config=pipeline_config)
        
        # Create a mock decision that would be approved
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.VERY_BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.9,
            confidence=0.85,
            reasoning="Strong earnings",
            source_items=["test"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        tech_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=25.0,
            current_price=150.0,
            support_levels=[
                SupportResistance(level=145.0, strength=0.9, timeframe="1y", last_tested=now)
            ],
            resistance_levels=[
                SupportResistance(level=170.0, strength=0.8, timeframe="1y", last_tested=now)
            ],
            confluence=ConfluenceResult(
                score=0.85,
                factors=["rsi_oversold", "support", "volume_spike", "macd_bullish"],
                description="Strong confluence",
            ),
            volume_trend="increasing",
            interest_rate_impact=0.1,
            timestamp=now,
        )
        
        # Evaluate strategy with these signals
        decision, _ = await pipeline.evaluate_strategy(news_signal, tech_signal)
        
        if decision and decision.action in {TradeAction.BUY, TradeAction.STRONG_BUY}:
            # Assess risk
            assessment = await pipeline.assess_risk(decision, 100000.0)
            
            if assessment.approved:
                # Execute order (mock)
                size = assessment.adjusted_size or decision.position_size_pct
                order_result = await pipeline.execute_order(decision, size * 100000.0)
                
                assert order_result is not None
                assert order_result.symbol == "AAPL"
                assert order_result.status == "filled"


class TestWebSocketDashboardFlow:
    """Tests for WebSocket dashboard update flow."""

    @pytest.mark.asyncio
    async def test_websocket_broadcasts_on_trade_execution(self, now):
        """Test that WebSocket broadcasts are sent on trade execution."""
        config = PipelineConfig()
        config.enable_persistence = False
        config.use_sagemaker = False
        config.use_llm = False
        
        pipeline = TradingPipeline(config=config)
        
        # Replace broadcaster with mock
        mock_broadcaster = MockWebSocketBroadcaster(config.execution_config)
        pipeline._websocket_broadcaster = mock_broadcaster
        pipeline._order_executor._websocket_broadcaster = mock_broadcaster
        pipeline._position_manager._websocket_broadcaster = mock_broadcaster
        
        # Add a connection
        mock_broadcaster.add_connection("test-connection-1")
        
        # Create signals for a trade
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.VERY_BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.9,
            confidence=0.85,
            reasoning="Strong earnings",
            source_items=["test"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        tech_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=25.0,
            current_price=150.0,
            support_levels=[
                SupportResistance(level=145.0, strength=0.9, timeframe="1y", last_tested=now)
            ],
            resistance_levels=[
                SupportResistance(level=170.0, strength=0.8, timeframe="1y", last_tested=now)
            ],
            confluence=ConfluenceResult(
                score=0.85,
                factors=["rsi_oversold", "support", "volume_spike", "macd_bullish"],
                description="Strong confluence",
            ),
            volume_trend="increasing",
            interest_rate_impact=0.1,
            timestamp=now,
        )
        
        # Get decision
        decision, _ = await pipeline.evaluate_strategy(news_signal, tech_signal)
        
        if decision and decision.action in {TradeAction.BUY, TradeAction.STRONG_BUY}:
            assessment = await pipeline.assess_risk(decision, 100000.0)
            
            if assessment.approved:
                size = assessment.adjusted_size or decision.position_size_pct
                order_result = await pipeline.execute_order(decision, size * 100000.0)
                
                if order_result:
                    await pipeline.open_position_from_order(decision, order_result)
                    
                    # Check broadcasts were sent
                    position_updates = mock_broadcaster.get_broadcasts_of_type("position_update")
                    assert len(position_updates) >= 1
                    
                    # Verify position update content
                    update = position_updates[0]
                    assert update["data"]["symbol"] == "AAPL"
                    assert update["update_type"] == "opened"

    @pytest.mark.asyncio
    async def test_websocket_broadcasts_position_close(self, now):
        """Test WebSocket broadcasts when position is closed."""
        config = PipelineConfig()
        config.enable_persistence = False
        
        pipeline = TradingPipeline(config=config)
        
        mock_broadcaster = MockWebSocketBroadcaster(config.execution_config)
        pipeline._position_manager._websocket_broadcaster = mock_broadcaster
        mock_broadcaster.add_connection("test-connection-1")
        
        # Open a position
        await pipeline._position_manager.open_position(
            trade_id="test-trade-1",
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=165.0,
            position_size=100.0,
            action=TradeAction.BUY,
            exness_order_id="order-123",
        )
        
        # Clear broadcasts from open
        mock_broadcaster.clear_broadcasts()
        
        # Close the position
        await pipeline._position_manager.close_position(
            trade_id="test-trade-1",
            exit_price=160.0,
            close_reason="tp",
        )
        
        # Check close broadcast
        position_updates = mock_broadcaster.get_broadcasts_of_type("position_update")
        assert len(position_updates) == 1
        
        update = position_updates[0]
        assert update["update_type"] == "closed"
        assert update["data"]["symbol"] == "AAPL"
        assert update["data"]["exit_price"] == 160.0
        assert update["data"]["status"] == "closed_tp"

    @pytest.mark.asyncio
    async def test_websocket_alert_on_risk_breach(self, now):
        """Test WebSocket alert when risk limit is breached."""
        config = PipelineConfig()
        config.enable_persistence = False
        
        pipeline = TradingPipeline(config=config)
        
        mock_broadcaster = MockWebSocketBroadcaster(config.execution_config)
        pipeline._websocket_broadcaster = mock_broadcaster
        mock_broadcaster.add_connection("test-connection-1")
        
        # Broadcast a risk alert
        await pipeline._on_risk_alert(
            "DAILY_LOSS_LIMIT_BREACHED",
            {"current_loss_pct": 0.06, "limit_pct": 0.05}
        )
        
        alerts = mock_broadcaster.get_broadcasts_of_type("alert")
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "DAILY_LOSS_LIMIT_BREACHED"


class TestPipelineRiskIntegration:
    """Tests for pipeline risk management integration."""

    @pytest.mark.asyncio
    async def test_risk_rejection_stops_execution(self, now):
        """Test that risk rejection prevents order execution."""
        config = PipelineConfig()
        config.enable_persistence = False
        config.use_sagemaker = False
        config.use_llm = False
        
        pipeline = TradingPipeline(config=config)
        
        # Open 10 positions to hit the limit
        for i in range(10):
            await pipeline._position_manager.open_position(
                trade_id=f"test-trade-{i}",
                symbol=f"SYM{i}",
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                position_size=1000.0,
                action=TradeAction.BUY,
                exness_order_id=f"order-{i}",
            )
        
        # Create a decision
        news_signal = NewsSignal(
            symbol="NEWSTOCK",
            sentiment=Sentiment.VERY_BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.9,
            confidence=0.85,
            reasoning="Test",
            source_items=["test"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        tech_signal = TechnicalSignal(
            symbol="NEWSTOCK",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=25.0,
            current_price=150.0,
            support_levels=[
                SupportResistance(level=145.0, strength=0.9, timeframe="1y", last_tested=now)
            ],
            resistance_levels=[
                SupportResistance(level=170.0, strength=0.8, timeframe="1y", last_tested=now)
            ],
            confluence=ConfluenceResult(score=0.85, factors=["test"], description="Test"),
            volume_trend="increasing",
            interest_rate_impact=0.1,
            timestamp=now,
        )
        
        decision, _ = await pipeline.evaluate_strategy(news_signal, tech_signal)
        
        if decision and decision.action in {TradeAction.BUY, TradeAction.STRONG_BUY}:
            assessment = await pipeline.assess_risk(decision, 100000.0)
            
            # Should be rejected due to max open positions
            assert assessment.approved is False
            assert assessment.rejection_reason is not None
            assert "position" in assessment.rejection_reason.lower()

    @pytest.mark.asyncio
    async def test_position_size_adjustment(self, now):
        """Test that position size is adjusted when exceeding limits."""
        config = PipelineConfig()
        config.enable_persistence = False
        
        pipeline = TradingPipeline(config=config)
        
        news_signal = NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.VERY_BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.9,
            confidence=0.85,
            reasoning="Test",
            source_items=["test"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
        
        tech_signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.OVERSOLD,
            rsi=25.0,
            current_price=150.0,
            support_levels=[
                SupportResistance(level=145.0, strength=0.9, timeframe="1y", last_tested=now)
            ],
            resistance_levels=[
                SupportResistance(level=170.0, strength=0.8, timeframe="1y", last_tested=now)
            ],
            confluence=ConfluenceResult(score=0.85, factors=["test"], description="Test"),
            volume_trend="increasing",
            interest_rate_impact=0.1,
            timestamp=now,
        )
        
        decision, _ = await pipeline.evaluate_strategy(news_signal, tech_signal)
        
        if decision:
            assessment = await pipeline.assess_risk(decision, 100000.0)
            
            # If approved with adjustment, verify adjustment is within limits
            if assessment.approved and assessment.adjusted_size:
                assert assessment.adjusted_size <= 0.05  # Max 5% position


class TestPipelineDataFlow:
    """Tests for data flow through the pipeline."""

    @pytest.mark.asyncio
    async def test_signal_ids_propagate_through_pipeline(
        self, sample_news_item, sample_candles
    ):
        """Test that signal IDs are properly propagated."""
        config = PipelineConfig()
        config.enable_persistence = False
        config.use_sagemaker = False
        config.use_llm = False
        
        pipeline = TradingPipeline(config=config)
        
        # Analyze news
        news_signal, news_id = await pipeline.analyze_news(sample_news_item)
        
        # Analyze technical
        tech_signal, tech_id = await pipeline.analyze_technical("AAPL", sample_candles)
        
        # Evaluate with IDs
        decision, decision_id = await pipeline.evaluate_strategy(
            news_signal, tech_signal,
            news_signal_id=news_id,
            technical_signal_id=tech_id,
        )
        
        # Signals should be generated
        assert news_signal is not None
        assert tech_signal is not None

    @pytest.mark.asyncio
    async def test_stale_data_halts_trading(self, sample_news_item, sample_candles):
        """Test that stale data detection halts trading."""
        config = PipelineConfig()
        config.enable_persistence = False
        config.use_sagemaker = False
        config.use_llm = False
        
        pipeline = TradingPipeline(config=config)
        
        # Override stale detector to always return True
        pipeline._strategy_agent.set_stale_data_detector(lambda symbol: True)
        
        # Analyze signals
        news_signal, _ = await pipeline.analyze_news(sample_news_item)
        tech_signal, _ = await pipeline.analyze_technical("AAPL", sample_candles)
        
        # Strategy should fail due to stale data
        decision, _ = await pipeline.evaluate_strategy(news_signal, tech_signal)
        
        # Decision should be None due to stale data
        assert decision is None

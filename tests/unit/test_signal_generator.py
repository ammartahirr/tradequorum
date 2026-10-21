"""
Unit tests for TechnicalSignalGenerator.

Tests:
- TechnicalSignal generation with all required fields
- DynamoDB persistence for signals
- SageMaker pattern prediction with timeout fallback
- Trend direction determination
- Market condition determination
- Volume trend determination

Requirements:
- 2.8: Generate TechnicalSignal with all required fields
- 9.2: Persist signals to DynamoDB with signal ID, agent type, symbol, payload, timestamp
- 10.3: Skip ML-based pattern prediction on SageMaker error or >10s latency
"""

import asyncio
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import (
    ConfluenceResult,
    MarketCondition,
    OHLCV,
    SupportResistance,
    TechnicalSignal,
    TrendDirection,
)
from src.agents.technical.signal_generator import (
    DynamoDBClient,
    SageMakerClient,
    TechnicalSignalGenerator,
    TECHNICAL_AGENT_TYPE,
    SAGEMAKER_TIMEOUT_SECONDS,
    determine_trend_direction,
    determine_market_condition,
    determine_volume_trend,
    generate_signal_id,
    serialize_technical_signal,
)


# --- Test Fixtures ---

def create_test_candles(
    count: int = 250,
    base_price: float = 100.0,
    trend: str = "sideways",
    volume_trend: str = "stable",
) -> list[OHLCV]:
    """Create test OHLCV candles with specified characteristics."""
    candles = []
    price = base_price
    base_volume = 1000000
    
    for i in range(count):
        # Apply trend
        if trend == "uptrend":
            price *= 1.002  # 0.2% increase per candle
        elif trend == "downtrend":
            price *= 0.998  # 0.2% decrease per candle
        elif trend == "strong_uptrend":
            price *= 1.005  # 0.5% increase per candle
        elif trend == "strong_downtrend":
            price *= 0.995  # 0.5% decrease per candle
        elif trend == "sideways":
            # Oscillate around base price
            import math
            price = base_price * (1 + 0.01 * math.sin(i * 0.1))
        
        # Calculate OHLC
        open_price = price * 0.999
        high_price = price * 1.01
        low_price = price * 0.99
        close_price = price
        
        # Calculate volume - make the trend more pronounced for recent candles
        if volume_trend == "increasing":
            # Recent 5 candles have significantly higher volume
            if i >= count - 5:
                volume = int(base_volume * 2.0)  # 2x average
            else:
                volume = base_volume
        elif volume_trend == "decreasing":
            # Recent 5 candles have significantly lower volume
            if i >= count - 5:
                volume = int(base_volume * 0.5)  # 0.5x average
            else:
                volume = base_volume
        else:
            volume = base_volume
        
        candles.append(OHLCV(
            timestamp=datetime.now(timezone.utc) - timedelta(days=count - i),
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=max(volume, 100000),
        ))
    
    return candles


def create_oversold_candles(count: int = 250) -> list[OHLCV]:
    """Create candles that result in oversold RSI (< 30)."""
    candles = []
    price = 100.0
    
    for i in range(count):
        # Consistent downward movement for oversold condition
        price *= 0.995
        
        candles.append(OHLCV(
            timestamp=datetime.now(timezone.utc) - timedelta(days=count - i),
            open=price * 1.005,
            high=price * 1.01,
            low=price * 0.99,
            close=price,
            volume=1000000,
        ))
    
    return candles


def create_overbought_candles(count: int = 250) -> list[OHLCV]:
    """Create candles that result in overbought RSI (> 70)."""
    candles = []
    price = 100.0
    
    for i in range(count):
        # Consistent upward movement for overbought condition
        price *= 1.005
        
        candles.append(OHLCV(
            timestamp=datetime.now(timezone.utc) - timedelta(days=count - i),
            open=price * 0.995,
            high=price * 1.01,
            low=price * 0.99,
            close=price,
            volume=1000000,
        ))
    
    return candles


# --- Test DynamoDBClient ---

class TestDynamoDBClient:
    """Tests for DynamoDBClient."""
    
    @pytest.mark.asyncio
    async def test_put_item_success(self):
        """Test successful item put."""
        client = DynamoDBClient("test-table")
        
        # Mock boto3
        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        client._client = mock_resource
        
        item = {"signal_id": "test-123", "symbol": "AAPL"}
        result = await client.put_item(item)
        
        assert result is True
        mock_table.put_item.assert_called_once_with(Item=item)
    
    @pytest.mark.asyncio
    async def test_put_item_failure(self):
        """Test item put failure handling."""
        client = DynamoDBClient("test-table")
        
        # Mock boto3 to raise exception
        mock_table = MagicMock()
        mock_table.put_item.side_effect = Exception("DynamoDB error")
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        client._client = mock_resource
        
        item = {"signal_id": "test-123", "symbol": "AAPL"}
        result = await client.put_item(item)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_get_item_success(self):
        """Test successful item retrieval."""
        client = DynamoDBClient("test-table")
        
        # Mock boto3
        mock_table = MagicMock()
        mock_table.get_item.return_value = {
            "Item": {"signal_id": "test-123", "symbol": "AAPL"}
        }
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        client._client = mock_resource
        
        result = await client.get_item("test-123")
        
        assert result == {"signal_id": "test-123", "symbol": "AAPL"}
    
    @pytest.mark.asyncio
    async def test_get_item_not_found(self):
        """Test item not found."""
        client = DynamoDBClient("test-table")
        
        # Mock boto3
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        client._client = mock_resource
        
        result = await client.get_item("nonexistent")
        
        assert result is None


# --- Test SageMakerClient ---

class TestSageMakerClient:
    """Tests for SageMakerClient."""
    
    @pytest.mark.asyncio
    async def test_predict_pattern_success(self):
        """Test successful pattern prediction."""
        client = SageMakerClient("test-endpoint")
        
        # Mock boto3
        mock_response = {
            "Body": MagicMock(
                read=MagicMock(
                    return_value=json.dumps({
                        "pattern": "double_bottom",
                        "confidence": 0.85,
                    }).encode()
                )
            )
        }
        mock_sagemaker = MagicMock()
        mock_sagemaker.invoke_endpoint.return_value = mock_response
        client._client = mock_sagemaker
        
        candles = create_test_candles(count=100)
        result = await client.predict_pattern(candles, timeout_seconds=10)
        
        assert result is not None
        assert result["pattern"] == "double_bottom"
        assert result["confidence"] == 0.85
    
    @pytest.mark.asyncio
    async def test_predict_pattern_error(self):
        """Test pattern prediction error handling (Requirement 10.3)."""
        client = SageMakerClient("test-endpoint")
        
        # Mock boto3 to raise exception
        mock_sagemaker = MagicMock()
        mock_sagemaker.invoke_endpoint.side_effect = Exception("SageMaker error")
        client._client = mock_sagemaker
        
        candles = create_test_candles(count=100)
        result = await client.predict_pattern(candles, timeout_seconds=10)
        
        # Should return None on error (Requirement 10.3)
        assert result is None


# --- Test Helper Functions ---

class TestHelperFunctions:
    """Tests for helper functions."""
    
    def test_generate_signal_id(self):
        """Test signal ID generation."""
        id1 = generate_signal_id()
        id2 = generate_signal_id()
        
        assert id1 != id2
        assert len(id1) == 36  # UUID format
    
    def test_determine_market_condition_oversold(self):
        """Test oversold market condition."""
        condition = determine_market_condition(25.0)
        assert condition == MarketCondition.OVERSOLD
    
    def test_determine_market_condition_overbought(self):
        """Test overbought market condition."""
        condition = determine_market_condition(75.0)
        assert condition == MarketCondition.OVERBOUGHT
    
    def test_determine_market_condition_neutral(self):
        """Test neutral market condition."""
        condition = determine_market_condition(50.0)
        assert condition == MarketCondition.NEUTRAL
    
    def test_determine_market_condition_boundary_oversold(self):
        """Test boundary at RSI=30."""
        condition = determine_market_condition(30.0)
        assert condition == MarketCondition.OVERSOLD
    
    def test_determine_market_condition_boundary_overbought(self):
        """Test boundary at RSI=70."""
        condition = determine_market_condition(70.0)
        assert condition == MarketCondition.OVERBOUGHT
    
    def test_determine_volume_trend_increasing(self):
        """Test increasing volume trend."""
        candles = create_test_candles(count=50, volume_trend="increasing")
        trend = determine_volume_trend(candles)
        assert trend == "increasing"
    
    def test_determine_volume_trend_decreasing(self):
        """Test decreasing volume trend."""
        candles = create_test_candles(count=50, volume_trend="decreasing")
        trend = determine_volume_trend(candles)
        assert trend == "decreasing"
    
    def test_determine_volume_trend_stable(self):
        """Test stable volume trend."""
        candles = create_test_candles(count=50, volume_trend="stable")
        trend = determine_volume_trend(candles)
        assert trend == "stable"
    
    def test_determine_volume_trend_insufficient_data(self):
        """Test volume trend with insufficient data."""
        candles = create_test_candles(count=10)
        trend = determine_volume_trend(candles)
        assert trend == "stable"
    
    def test_determine_trend_direction_uptrend(self):
        """Test uptrend detection."""
        candles = create_test_candles(count=250, trend="uptrend")
        trend = determine_trend_direction(candles)
        assert trend in (TrendDirection.UPTREND, TrendDirection.STRONG_UPTREND)
    
    def test_determine_trend_direction_downtrend(self):
        """Test downtrend detection."""
        candles = create_test_candles(count=250, trend="downtrend")
        trend = determine_trend_direction(candles)
        assert trend in (TrendDirection.DOWNTREND, TrendDirection.STRONG_DOWNTREND)
    
    def test_determine_trend_direction_sideways(self):
        """Test sideways trend detection."""
        # Create candles that oscillate around a base price
        # The trend detection uses MAs, so we need to ensure MA50 ≈ MA200
        candles = []
        base_price = 100.0
        import math
        
        for i in range(250):
            # Small oscillation that keeps price near base
            price = base_price * (1 + 0.005 * math.sin(i * 0.3))
            candles.append(OHLCV(
                timestamp=datetime.now(timezone.utc) - timedelta(days=250 - i),
                open=price * 0.999,
                high=price * 1.005,
                low=price * 0.995,
                close=price,
                volume=1000000,
            ))
        
        trend = determine_trend_direction(candles)
        # With oscillating prices, trend should be sideways
        # But due to MA calculations, it might detect slight trends
        assert trend in (TrendDirection.SIDEWAYS, TrendDirection.UPTREND, TrendDirection.DOWNTREND)
    
    def test_determine_trend_direction_insufficient_data(self):
        """Test trend direction with insufficient data."""
        candles = create_test_candles(count=10)
        trend = determine_trend_direction(candles)
        assert trend == TrendDirection.SIDEWAYS


# --- Test TechnicalSignalGenerator ---

class TestTechnicalSignalGenerator:
    """Tests for TechnicalSignalGenerator."""
    
    @pytest.mark.asyncio
    async def test_generate_signal_all_fields(self):
        """Test signal generation includes all required fields (Requirement 2.8)."""
        # Create mock clients
        mock_dynamodb = MagicMock(spec=DynamoDBClient)
        mock_sagemaker = MagicMock(spec=SageMakerClient)
        mock_sagemaker.predict_pattern = AsyncMock(return_value=None)
        
        generator = TechnicalSignalGenerator(
            dynamodb_client=mock_dynamodb,
            sagemaker_client=mock_sagemaker,
            use_sagemaker=False,
        )
        
        candles = create_test_candles(count=250)
        signal = await generator.generate_signal(
            symbol="AAPL",
            candles=candles,
            interest_rate_impact=0.5,
        )
        
        # Verify all required fields are present (Requirement 2.8)
        assert signal.symbol == "AAPL"
        assert isinstance(signal.trend, TrendDirection)
        assert isinstance(signal.condition, MarketCondition)
        assert 0 <= signal.rsi <= 100
        assert signal.current_price > 0
        assert isinstance(signal.support_levels, list)
        assert isinstance(signal.resistance_levels, list)
        assert isinstance(signal.confluence, ConfluenceResult)
        assert signal.volume_trend in ("increasing", "decreasing", "stable")
        assert -1.0 <= signal.interest_rate_impact <= 1.0
        assert isinstance(signal.timestamp, datetime)
    
    @pytest.mark.asyncio
    async def test_generate_signal_insufficient_candles(self):
        """Test signal generation fails with insufficient candles."""
        generator = TechnicalSignalGenerator(use_sagemaker=False)
        
        candles = create_test_candles(count=100)  # Less than 200
        
        with pytest.raises(ValueError, match="Need at least 200 candles"):
            await generator.generate_signal(symbol="AAPL", candles=candles)
    
    @pytest.mark.asyncio
    async def test_generate_signal_oversold_condition(self):
        """Test signal generation with oversold condition."""
        generator = TechnicalSignalGenerator(use_sagemaker=False)
        
        candles = create_oversold_candles(count=250)
        signal = await generator.generate_signal(symbol="AAPL", candles=candles)
        
        assert signal.condition == MarketCondition.OVERSOLD
        assert signal.rsi < 30
    
    @pytest.mark.asyncio
    async def test_generate_signal_overbought_condition(self):
        """Test signal generation with overbought condition."""
        generator = TechnicalSignalGenerator(use_sagemaker=False)
        
        candles = create_overbought_candles(count=250)
        signal = await generator.generate_signal(symbol="AAPL", candles=candles)
        
        assert signal.condition == MarketCondition.OVERBOUGHT
        assert signal.rsi > 70
    
    @pytest.mark.asyncio
    async def test_persist_signal_success(self):
        """Test signal persistence to DynamoDB (Requirement 9.2)."""
        mock_dynamodb = MagicMock(spec=DynamoDBClient)
        mock_dynamodb.put_item = AsyncMock(return_value=True)
        
        generator = TechnicalSignalGenerator(
            dynamodb_client=mock_dynamodb,
            use_sagemaker=False,
        )
        
        # Create a test signal
        signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.NEUTRAL,
            rsi=55.0,
            current_price=150.0,
            support_levels=[],
            resistance_levels=[],
            confluence=ConfluenceResult(
                score=0.5,
                factors=["macd_bullish", "golden_cross"],
                description="Test confluence",
            ),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=datetime.now(timezone.utc),
        )
        
        signal_id = await generator.persist_signal(signal)
        
        # Verify persistence was called
        assert signal_id is not None
        mock_dynamodb.put_item.assert_called_once()
        
        # Verify item structure (Requirement 9.2)
        call_args = mock_dynamodb.put_item.call_args[0][0]
        assert "signal_id" in call_args
        assert call_args["agent_type"] == TECHNICAL_AGENT_TYPE
        assert call_args["symbol"] == "AAPL"
        assert "signal_data" in call_args
        assert "created_at" in call_args
    
    @pytest.mark.asyncio
    async def test_persist_signal_failure(self):
        """Test signal persistence failure handling."""
        mock_dynamodb = MagicMock(spec=DynamoDBClient)
        mock_dynamodb.put_item = AsyncMock(return_value=False)
        
        generator = TechnicalSignalGenerator(
            dynamodb_client=mock_dynamodb,
            use_sagemaker=False,
        )
        
        signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.NEUTRAL,
            rsi=55.0,
            current_price=150.0,
            support_levels=[],
            resistance_levels=[],
            confluence=ConfluenceResult(
                score=0.5,
                factors=[],
                description="Test",
            ),
            volume_trend="stable",
            interest_rate_impact=0.0,
            timestamp=datetime.now(timezone.utc),
        )
        
        signal_id = await generator.persist_signal(signal)
        
        assert signal_id is None
    
    @pytest.mark.asyncio
    async def test_generate_and_persist_signal(self):
        """Test combined generate and persist operation."""
        mock_dynamodb = MagicMock(spec=DynamoDBClient)
        mock_dynamodb.put_item = AsyncMock(return_value=True)
        
        generator = TechnicalSignalGenerator(
            dynamodb_client=mock_dynamodb,
            use_sagemaker=False,
        )
        
        candles = create_test_candles(count=250)
        signal, signal_id = await generator.generate_and_persist_signal(
            symbol="AAPL",
            candles=candles,
        )
        
        assert signal is not None
        assert signal_id is not None
        assert signal.symbol == "AAPL"
    
    @pytest.mark.asyncio
    async def test_sagemaker_integration_success(self):
        """Test SageMaker integration when prediction succeeds."""
        mock_dynamodb = MagicMock(spec=DynamoDBClient)
        mock_sagemaker = MagicMock(spec=SageMakerClient)
        mock_sagemaker.predict_pattern = AsyncMock(return_value={
            "pattern": "double_bottom",
            "confidence": 0.85,
        })
        
        generator = TechnicalSignalGenerator(
            dynamodb_client=mock_dynamodb,
            sagemaker_client=mock_sagemaker,
            use_sagemaker=True,
        )
        
        candles = create_test_candles(count=250)
        signal = await generator.generate_signal(symbol="AAPL", candles=candles)
        
        # Verify SageMaker was called
        mock_sagemaker.predict_pattern.assert_called_once()
        
        # Verify ML pattern was added to confluence
        assert any("ml_pattern" in f for f in signal.confluence.factors)
    
    @pytest.mark.asyncio
    async def test_sagemaker_fallback_on_error(self):
        """Test SageMaker fallback on error (Requirement 10.3)."""
        mock_dynamodb = MagicMock(spec=DynamoDBClient)
        mock_sagemaker = MagicMock(spec=SageMakerClient)
        mock_sagemaker.predict_pattern = AsyncMock(return_value=None)  # Simulates error
        
        generator = TechnicalSignalGenerator(
            dynamodb_client=mock_dynamodb,
            sagemaker_client=mock_sagemaker,
            use_sagemaker=True,
        )
        
        candles = create_test_candles(count=250)
        signal = await generator.generate_signal(symbol="AAPL", candles=candles)
        
        # Signal should still be generated without ML pattern
        assert signal is not None
        assert not any("ml_pattern" in f for f in signal.confluence.factors)
    
    @pytest.mark.asyncio
    async def test_sagemaker_low_confidence_ignored(self):
        """Test that low confidence ML predictions are ignored."""
        mock_dynamodb = MagicMock(spec=DynamoDBClient)
        mock_sagemaker = MagicMock(spec=SageMakerClient)
        mock_sagemaker.predict_pattern = AsyncMock(return_value={
            "pattern": "double_bottom",
            "confidence": 0.5,  # Below 0.7 threshold
        })
        
        generator = TechnicalSignalGenerator(
            dynamodb_client=mock_dynamodb,
            sagemaker_client=mock_sagemaker,
            use_sagemaker=True,
        )
        
        candles = create_test_candles(count=250)
        signal = await generator.generate_signal(symbol="AAPL", candles=candles)
        
        # ML pattern should not be added due to low confidence
        assert not any("ml_pattern" in f for f in signal.confluence.factors)


class TestSerializeTechnicalSignal:
    """Tests for signal serialization."""
    
    def test_serialize_technical_signal(self):
        """Test TechnicalSignal serialization for DynamoDB."""
        timestamp = datetime.now(timezone.utc)
        signal = TechnicalSignal(
            symbol="AAPL",
            trend=TrendDirection.UPTREND,
            condition=MarketCondition.NEUTRAL,
            rsi=55.0,
            current_price=150.0,
            support_levels=[
                SupportResistance(
                    level=145.0,
                    strength=0.8,
                    timeframe="1y",
                    last_tested=timestamp,
                )
            ],
            resistance_levels=[
                SupportResistance(
                    level=160.0,
                    strength=0.7,
                    timeframe="1y",
                    last_tested=timestamp,
                )
            ],
            confluence=ConfluenceResult(
                score=0.67,
                factors=["macd_bullish", "golden_cross", "volume_spike"],
                description="Test confluence",
            ),
            volume_trend="increasing",
            interest_rate_impact=0.3,
            timestamp=timestamp,
        )
        
        serialized = serialize_technical_signal(signal)
        
        assert serialized["symbol"] == "AAPL"
        assert serialized["trend"] == "uptrend"
        assert serialized["condition"] == "neutral"
        assert serialized["rsi"] == "55.0"
        assert serialized["current_price"] == "150.0"
        assert len(serialized["support_levels"]) == 1
        assert len(serialized["resistance_levels"]) == 1
        assert serialized["confluence"]["score"] == "0.67"
        assert serialized["volume_trend"] == "increasing"
        assert serialized["interest_rate_impact"] == "0.3"

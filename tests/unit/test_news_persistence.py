"""
Unit tests for the News Agent persistence module.

Tests the DynamoDB persistence layer for NewsSignals including:
- Signal serialization
- SignalLog creation
- DynamoDB item conversion
- Persistence operations

Requirements: 9.1
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.news.persistence import (
    SignalPersistence,
    DynamoDBClient,
    generate_signal_id,
    serialize_news_signal,
    create_signal_log,
    signal_log_to_dynamodb_item,
    NEWS_AGENT_TYPE,
    DEFAULT_SIGNALS_TABLE,
)
from src.models import NewsSignal, SignalLog
from src.models.enums import ImpactType, Sentiment


class TestGenerateSignalId:
    """Tests for generate_signal_id function."""
    
    def test_generates_uuid_string(self):
        """Should generate a valid UUID string."""
        signal_id = generate_signal_id()
        assert isinstance(signal_id, str)
        assert len(signal_id) == 36  # UUID format: 8-4-4-4-12
        assert signal_id.count("-") == 4
    
    def test_generates_unique_ids(self):
        """Should generate unique IDs on each call."""
        ids = [generate_signal_id() for _ in range(100)]
        assert len(set(ids)) == 100  # All unique


class TestSerializeNewsSignal:
    """Tests for serialize_news_signal function."""
    
    @pytest.fixture
    def sample_signal(self):
        """Create a sample NewsSignal for testing."""
        now = datetime.now(timezone.utc)
        return NewsSignal(
            symbol="AAPL",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.85,
            confidence=0.9,
            reasoning="Strong earnings beat",
            source_items=["reuters:123"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
    
    def test_serializes_all_fields(self, sample_signal):
        """Should serialize all NewsSignal fields."""
        result = serialize_news_signal(sample_signal)
        
        assert result["symbol"] == "AAPL"
        assert result["sentiment"] == "bullish"
        assert result["impact_type"] == "cash_flow"
        assert result["impact_score"] == "0.85"
        assert result["confidence"] == "0.9"
        assert result["reasoning"] == "Strong earnings beat"
        assert result["source_items"] == ["reuters:123"]
        assert "timestamp" in result
        assert "expires_at" in result
    
    def test_converts_enums_to_values(self, sample_signal):
        """Should convert enum values to strings."""
        result = serialize_news_signal(sample_signal)
        
        assert result["sentiment"] == sample_signal.sentiment.value
        assert result["impact_type"] == sample_signal.impact_type.value
    
    def test_converts_floats_to_strings(self, sample_signal):
        """Should convert floats to strings for DynamoDB compatibility."""
        result = serialize_news_signal(sample_signal)
        
        assert isinstance(result["impact_score"], str)
        assert isinstance(result["confidence"], str)
    
    def test_converts_datetimes_to_iso(self, sample_signal):
        """Should convert datetimes to ISO format strings."""
        result = serialize_news_signal(sample_signal)
        
        # Should be parseable as ISO format
        datetime.fromisoformat(result["timestamp"])
        datetime.fromisoformat(result["expires_at"])


class TestCreateSignalLog:
    """Tests for create_signal_log function."""
    
    @pytest.fixture
    def sample_signal(self):
        """Create a sample NewsSignal for testing."""
        now = datetime.now(timezone.utc)
        return NewsSignal(
            symbol="TSLA",
            sentiment=Sentiment.VERY_BULLISH,
            impact_type=ImpactType.HYPE,
            impact_score=0.6,
            confidence=0.7,
            reasoning="Social media buzz",
            source_items=["twitter:456"],
            timestamp=now,
            expires_at=now + timedelta(hours=24),
        )
    
    def test_creates_signal_log_with_generated_id(self, sample_signal):
        """Should create SignalLog with generated ID when not provided."""
        log = create_signal_log(sample_signal)
        
        assert isinstance(log, SignalLog)
        assert len(log.signal_id) == 36  # UUID format
        assert log.agent_type == NEWS_AGENT_TYPE
        assert log.symbol == "TSLA"
    
    def test_creates_signal_log_with_provided_id(self, sample_signal):
        """Should use provided signal ID."""
        custom_id = "custom-signal-id-123"
        log = create_signal_log(sample_signal, signal_id=custom_id)
        
        assert log.signal_id == custom_id
    
    def test_sets_agent_type_to_news(self, sample_signal):
        """Should set agent_type to 'news'."""
        log = create_signal_log(sample_signal)
        
        assert log.agent_type == "news"
    
    def test_includes_serialized_signal_data(self, sample_signal):
        """Should include serialized signal data."""
        log = create_signal_log(sample_signal)
        
        assert log.signal_data["symbol"] == "TSLA"
        assert log.signal_data["sentiment"] == "very_bullish"
        assert log.signal_data["impact_type"] == "hype"
    
    def test_sets_created_at_from_signal_timestamp(self, sample_signal):
        """Should use signal timestamp as created_at."""
        log = create_signal_log(sample_signal)
        
        assert log.created_at == sample_signal.timestamp
    
    def test_initializes_tracking_fields(self, sample_signal):
        """Should initialize consumed_by, resulted_in_trade, trade_id."""
        log = create_signal_log(sample_signal)
        
        assert log.consumed_by is None
        assert log.resulted_in_trade is False
        assert log.trade_id is None


class TestSignalLogToDynamoDBItem:
    """Tests for signal_log_to_dynamodb_item function."""
    
    @pytest.fixture
    def sample_log(self):
        """Create a sample SignalLog for testing."""
        return SignalLog(
            signal_id="test-signal-123",
            agent_type="news",
            symbol="GOOGL",
            signal_data={"sentiment": "bullish", "impact_type": "cash_flow"},
            created_at=datetime.now(timezone.utc),
            consumed_by=None,
            resulted_in_trade=False,
            trade_id=None,
        )
    
    def test_converts_required_fields(self, sample_log):
        """Should convert all required fields."""
        item = signal_log_to_dynamodb_item(sample_log)
        
        assert item["signal_id"] == "test-signal-123"
        assert item["agent_type"] == "news"
        assert item["symbol"] == "GOOGL"
        assert "signal_data" in item
        assert "created_at" in item
        assert item["resulted_in_trade"] is False
    
    def test_serializes_signal_data_as_json(self, sample_log):
        """Should serialize signal_data as JSON string."""
        item = signal_log_to_dynamodb_item(sample_log)
        
        # Should be valid JSON
        parsed = json.loads(item["signal_data"])
        assert parsed["sentiment"] == "bullish"
    
    def test_excludes_none_optional_fields(self, sample_log):
        """Should not include None optional fields."""
        item = signal_log_to_dynamodb_item(sample_log)
        
        assert "consumed_by" not in item
        assert "trade_id" not in item
    
    def test_includes_optional_fields_when_set(self):
        """Should include optional fields when they have values."""
        log = SignalLog(
            signal_id="test-signal-456",
            agent_type="news",
            symbol="MSFT",
            signal_data={"test": "data"},
            created_at=datetime.now(timezone.utc),
            consumed_by="strategy_agent",
            resulted_in_trade=True,
            trade_id="trade-789",
        )
        
        item = signal_log_to_dynamodb_item(log)
        
        assert item["consumed_by"] == "strategy_agent"
        assert item["trade_id"] == "trade-789"
        assert item["resulted_in_trade"] is True


class TestDynamoDBClient:
    """Tests for DynamoDBClient class."""
    
    def test_init_with_default_table(self):
        """Should use default table name."""
        client = DynamoDBClient()
        assert client.table_name == DEFAULT_SIGNALS_TABLE
    
    def test_init_with_custom_table(self):
        """Should accept custom table name."""
        client = DynamoDBClient(table_name="custom-signals")
        assert client.table_name == "custom-signals"


class TestSignalPersistence:
    """Tests for SignalPersistence class."""
    
    @pytest.fixture
    def mock_dynamodb_client(self):
        """Create a mock DynamoDB client."""
        client = MagicMock(spec=DynamoDBClient)
        client.put_item = AsyncMock(return_value=True)
        client.get_item = AsyncMock(return_value=None)
        return client
    
    @pytest.fixture
    def sample_signal(self):
        """Create a sample NewsSignal for testing."""
        now = datetime.now(timezone.utc)
        return NewsSignal(
            symbol="NVDA",
            sentiment=Sentiment.BULLISH,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=0.8,
            confidence=0.85,
            reasoning="Strong GPU demand",
            source_items=["bloomberg:789"],
            timestamp=now,
            expires_at=now + timedelta(hours=72),
        )
    
    @pytest.mark.asyncio
    async def test_persist_news_signal_success(self, mock_dynamodb_client, sample_signal):
        """Should persist signal and return signal_id on success."""
        persistence = SignalPersistence(dynamodb_client=mock_dynamodb_client)
        
        signal_id = await persistence.persist_news_signal(sample_signal)
        
        assert signal_id is not None
        assert len(signal_id) == 36  # UUID format
        mock_dynamodb_client.put_item.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_persist_news_signal_with_custom_id(self, mock_dynamodb_client, sample_signal):
        """Should use provided signal_id."""
        persistence = SignalPersistence(dynamodb_client=mock_dynamodb_client)
        custom_id = "custom-id-abc"
        
        signal_id = await persistence.persist_news_signal(sample_signal, signal_id=custom_id)
        
        assert signal_id == custom_id
    
    @pytest.mark.asyncio
    async def test_persist_news_signal_failure(self, mock_dynamodb_client, sample_signal):
        """Should return None on persistence failure."""
        mock_dynamodb_client.put_item = AsyncMock(return_value=False)
        persistence = SignalPersistence(dynamodb_client=mock_dynamodb_client)
        
        signal_id = await persistence.persist_news_signal(sample_signal)
        
        assert signal_id is None
    
    @pytest.mark.asyncio
    async def test_persist_includes_required_fields(self, mock_dynamodb_client, sample_signal):
        """Should include all required fields in persisted item (Requirement 9.1)."""
        persistence = SignalPersistence(dynamodb_client=mock_dynamodb_client)
        
        await persistence.persist_news_signal(sample_signal)
        
        # Get the item that was passed to put_item
        call_args = mock_dynamodb_client.put_item.call_args
        item = call_args[0][0]  # First positional argument
        
        # Verify required fields per Requirement 9.1
        assert "signal_id" in item
        assert item["agent_type"] == "news"
        assert item["symbol"] == "NVDA"
        assert "signal_data" in item
        assert "created_at" in item
    
    @pytest.mark.asyncio
    async def test_get_signal_returns_none_when_not_found(self, mock_dynamodb_client):
        """Should return None when signal not found."""
        persistence = SignalPersistence(dynamodb_client=mock_dynamodb_client)
        
        result = await persistence.get_signal("nonexistent-id")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_signal_returns_signal_log(self, mock_dynamodb_client):
        """Should return SignalLog when found."""
        mock_dynamodb_client.get_item = AsyncMock(return_value={
            "signal_id": "test-id",
            "agent_type": "news",
            "symbol": "AAPL",
            "signal_data": '{"sentiment": "bullish"}',
            "created_at": datetime.now(timezone.utc).isoformat(),
            "resulted_in_trade": False,
        })
        persistence = SignalPersistence(dynamodb_client=mock_dynamodb_client)
        
        result = await persistence.get_signal("test-id")
        
        assert isinstance(result, SignalLog)
        assert result.signal_id == "test-id"
        assert result.symbol == "AAPL"
    
    @pytest.mark.asyncio
    async def test_mark_signal_consumed(self, mock_dynamodb_client):
        """Should update signal with consumed_by and trade_id."""
        mock_dynamodb_client.get_item = AsyncMock(return_value={
            "signal_id": "test-id",
            "agent_type": "news",
            "symbol": "AAPL",
            "signal_data": '{"sentiment": "bullish"}',
            "created_at": datetime.now(timezone.utc).isoformat(),
            "resulted_in_trade": False,
        })
        persistence = SignalPersistence(dynamodb_client=mock_dynamodb_client)
        
        result = await persistence.mark_signal_consumed(
            "test-id",
            consumed_by="strategy_agent",
            trade_id="trade-123"
        )
        
        assert result is True
        # Verify put_item was called with updated fields
        call_args = mock_dynamodb_client.put_item.call_args
        item = call_args[0][0]
        assert item["consumed_by"] == "strategy_agent"
        assert item["trade_id"] == "trade-123"
        assert item["resulted_in_trade"] is True


class TestConstants:
    """Tests for module constants."""
    
    def test_news_agent_type(self):
        """NEWS_AGENT_TYPE should be 'news'."""
        assert NEWS_AGENT_TYPE == "news"
    
    def test_default_signals_table(self):
        """DEFAULT_SIGNALS_TABLE should be set."""
        assert DEFAULT_SIGNALS_TABLE == "trading-signals"

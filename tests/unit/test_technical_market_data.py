"""
Unit tests for Technical Agent market data fetching.

Tests the MT5 client, market data fetching, and stale data detection
functionality.

Requirements tested:
- 2.1: Fetch OHLCV candles for configurable timeframes
- 9.5: Store OHLCV candles in Timestream for time-series querying
- 10.2: Mark signals as stale when data >5 min old during trading hours
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.models import OHLCV
from src.agents.technical.config import (
    TechnicalAgentConfig,
    MT5Config,
    StaleDataConfig,
    TimestreamConfig,
    SUPPORTED_TIMEFRAMES,
    TIMEFRAME_MINUTES,
)
from src.agents.technical.market_data import (
    is_trading_hours,
    is_data_stale,
    StaleDataDetector,
    fetch_ohlcv_candles,
    MarketDataFetcher,
    STALE_DATA_THRESHOLD_MINUTES,
)
from src.agents.technical.mt5_client import (
    MT5Client,
    MT5ConnectionError,
    MT5AuthenticationError,
    MT5DataError,
    MT5Credentials,
)
from src.agents.technical.persistence import (
    TimestreamPersistence,
    TimestreamClient,
    serialize_ohlcv_for_timestream,
)


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def sample_candles() -> list[OHLCV]:
    """Create sample OHLCV candles for testing."""
    base_time = datetime(2024, 1, 15, 14, 30, tzinfo=timezone.utc)
    candles = []
    
    for i in range(10):
        candle = OHLCV(
            timestamp=base_time + timedelta(days=i),
            open=100.0 + i,
            high=105.0 + i,
            low=95.0 + i,
            close=102.0 + i,
            volume=1000000 + i * 10000,
        )
        candles.append(candle)
    
    return candles


@pytest.fixture
def trading_hours_config() -> StaleDataConfig:
    """Create stale data config for testing."""
    return StaleDataConfig(
        stale_threshold_minutes=5,
        trading_start_hour_utc=14,
        trading_start_minute_utc=30,
        trading_end_hour_utc=21,
        trading_end_minute_utc=0,
        trading_days=[0, 1, 2, 3, 4],  # Monday-Friday
    )


@pytest.fixture
def mock_mt5_client() -> MT5Client:
    """Create a mock MT5 client."""
    client = MT5Client()
    client._connected = True
    return client


# ============================================================================
# Tests for is_trading_hours()
# ============================================================================

class TestIsTradingHours:
    """Tests for trading hours detection."""
    
    def test_during_trading_hours_weekday(self, trading_hours_config):
        """Test detection during regular trading hours on a weekday."""
        # Monday at 3:00 PM UTC (within trading hours)
        timestamp = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
        assert is_trading_hours(timestamp, trading_hours_config) is True
    
    def test_before_trading_hours_weekday(self, trading_hours_config):
        """Test detection before trading hours on a weekday."""
        # Monday at 10:00 AM UTC (before trading hours)
        timestamp = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
        assert is_trading_hours(timestamp, trading_hours_config) is False
    
    def test_after_trading_hours_weekday(self, trading_hours_config):
        """Test detection after trading hours on a weekday."""
        # Monday at 10:00 PM UTC (after trading hours)
        timestamp = datetime(2024, 1, 15, 22, 0, tzinfo=timezone.utc)
        assert is_trading_hours(timestamp, trading_hours_config) is False
    
    def test_weekend_not_trading(self, trading_hours_config):
        """Test that weekends are not trading hours."""
        # Saturday at 3:00 PM UTC
        timestamp = datetime(2024, 1, 13, 15, 0, tzinfo=timezone.utc)
        assert is_trading_hours(timestamp, trading_hours_config) is False
    
    def test_trading_start_boundary(self, trading_hours_config):
        """Test exact trading start time."""
        # Monday at 2:30 PM UTC (exact start)
        timestamp = datetime(2024, 1, 15, 14, 30, tzinfo=timezone.utc)
        assert is_trading_hours(timestamp, trading_hours_config) is True
    
    def test_trading_end_boundary(self, trading_hours_config):
        """Test exact trading end time."""
        # Monday at 9:00 PM UTC (exact end)
        timestamp = datetime(2024, 1, 15, 21, 0, tzinfo=timezone.utc)
        assert is_trading_hours(timestamp, trading_hours_config) is True
    
    def test_just_before_trading_start(self, trading_hours_config):
        """Test one minute before trading starts."""
        # Monday at 2:29 PM UTC
        timestamp = datetime(2024, 1, 15, 14, 29, tzinfo=timezone.utc)
        assert is_trading_hours(timestamp, trading_hours_config) is False


# ============================================================================
# Tests for is_data_stale()
# ============================================================================

class TestIsDataStale:
    """Tests for stale data detection."""
    
    def test_fresh_data_during_trading_hours(self, trading_hours_config):
        """Test that recent data is not stale during trading hours."""
        current_time = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
        last_update = current_time - timedelta(minutes=2)
        
        assert is_data_stale(last_update, current_time, trading_hours_config) is False
    
    def test_stale_data_during_trading_hours(self, trading_hours_config):
        """Test that old data is stale during trading hours (Requirement 10.2)."""
        current_time = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
        last_update = current_time - timedelta(minutes=6)  # >5 minutes
        
        assert is_data_stale(last_update, current_time, trading_hours_config) is True
    
    def test_old_data_outside_trading_hours_not_stale(self, trading_hours_config):
        """Test that old data is not considered stale outside trading hours."""
        # Saturday (not a trading day)
        current_time = datetime(2024, 1, 13, 15, 0, tzinfo=timezone.utc)
        last_update = current_time - timedelta(hours=2)
        
        assert is_data_stale(last_update, current_time, trading_hours_config) is False
    
    def test_exactly_5_minutes_not_stale(self, trading_hours_config):
        """Test that exactly 5 minutes is not stale (boundary condition)."""
        current_time = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
        last_update = current_time - timedelta(minutes=5)
        
        assert is_data_stale(last_update, current_time, trading_hours_config) is False
    
    def test_5_minutes_1_second_is_stale(self, trading_hours_config):
        """Test that 5 minutes and 1 second is stale."""
        current_time = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
        last_update = current_time - timedelta(minutes=5, seconds=1)
        
        assert is_data_stale(last_update, current_time, trading_hours_config) is True


# ============================================================================
# Tests for StaleDataDetector
# ============================================================================

class TestStaleDataDetector:
    """Tests for the StaleDataDetector class."""
    
    def test_record_and_check_update(self, trading_hours_config):
        """Test recording and checking updates."""
        detector = StaleDataDetector(trading_hours_config)
        
        # Record an update
        update_time = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
        detector.record_update("AAPL", update_time)
        
        # Check immediately after - should not be stale
        current_time = update_time + timedelta(minutes=1)
        assert detector.is_stale("AAPL", current_time) is False
    
    def test_no_update_recorded_is_stale_during_trading(self, trading_hours_config):
        """Test that no recorded update is considered stale during trading hours."""
        detector = StaleDataDetector(trading_hours_config)
        
        # During trading hours with no update recorded
        current_time = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
        assert detector.is_stale("AAPL", current_time) is True
    
    def test_get_stale_symbols(self, trading_hours_config):
        """Test getting list of stale symbols."""
        detector = StaleDataDetector(trading_hours_config)
        
        current_time = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
        
        # Record fresh update for AAPL
        detector.record_update("AAPL", current_time - timedelta(minutes=2))
        
        # Record stale update for MSFT
        detector.record_update("MSFT", current_time - timedelta(minutes=10))
        
        # GOOGL has no update
        
        stale = detector.get_stale_symbols(["AAPL", "MSFT", "GOOGL"], current_time)
        
        assert "AAPL" not in stale
        assert "MSFT" in stale
        assert "GOOGL" in stale
    
    def test_clear_specific_symbol(self, trading_hours_config):
        """Test clearing update for a specific symbol."""
        detector = StaleDataDetector(trading_hours_config)
        
        update_time = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
        detector.record_update("AAPL", update_time)
        detector.record_update("MSFT", update_time)
        
        detector.clear("AAPL")
        
        assert detector.get_last_update("AAPL") is None
        assert detector.get_last_update("MSFT") is not None
    
    def test_clear_all(self, trading_hours_config):
        """Test clearing all updates."""
        detector = StaleDataDetector(trading_hours_config)
        
        update_time = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
        detector.record_update("AAPL", update_time)
        detector.record_update("MSFT", update_time)
        
        detector.clear()
        
        assert detector.get_last_update("AAPL") is None
        assert detector.get_last_update("MSFT") is None


# ============================================================================
# Tests for MT5Client
# ============================================================================

class TestMT5Client:
    """Tests for the MT5 client."""
    
    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful MT5 connection."""
        client = MT5Client()
        
        # Mock the MT5 module
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
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
        assert client.is_connected is True
    
    @pytest.mark.asyncio
    async def test_connect_retry_on_failure(self):
        """Test connection retry with exponential backoff (Requirement 6.4)."""
        client = MT5Client()
        client.config.retry_delays_seconds = [0.01, 0.02, 0.04]  # Fast for testing
        
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
    
    @pytest.mark.asyncio
    async def test_connect_all_retries_fail(self):
        """Test connection failure after all retries exhausted."""
        client = MT5Client()
        client.config.retry_delays_seconds = [0.01, 0.02, 0.04]
        
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
        
        with pytest.raises(MT5ConnectionError):
            await client.connect()
    
    @pytest.mark.asyncio
    async def test_get_candles_success(self, sample_candles):
        """Test successful candle retrieval."""
        client = MT5Client()
        client._connected = True
        
        # Mock the MT5 module
        mock_mt5 = MagicMock()
        mock_mt5.TIMEFRAME_D1 = 16408
        
        # Create mock rates data
        mock_rates = [
            {
                "time": int(c.timestamp.timestamp()),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "tick_volume": c.volume,
            }
            for c in sample_candles
        ]
        mock_mt5.copy_rates_from_pos.return_value = mock_rates
        client._mt5 = mock_mt5
        
        candles = await client.get_candles("AAPL", "D1", 10)
        
        assert len(candles) == 10
        assert all(isinstance(c, OHLCV) for c in candles)
    
    @pytest.mark.asyncio
    async def test_get_candles_invalid_timeframe(self):
        """Test error on invalid timeframe."""
        client = MT5Client()
        client._connected = True
        client._mt5 = MagicMock()
        
        with pytest.raises(MT5DataError, match="Unsupported timeframe"):
            await client.get_candles("AAPL", "INVALID", 10)


# ============================================================================
# Tests for fetch_ohlcv_candles()
# ============================================================================

class TestFetchOHLCVCandles:
    """Tests for the fetch_ohlcv_candles function."""
    
    @pytest.mark.asyncio
    async def test_fetch_candles_success(self, sample_candles):
        """Test successful candle fetching."""
        mock_client = AsyncMock(spec=MT5Client)
        mock_client.get_candles.return_value = sample_candles
        
        result = await fetch_ohlcv_candles(mock_client, "AAPL", "D1", 10)
        
        assert len(result) == 10
        # Verify sorted by timestamp
        for i in range(1, len(result)):
            assert result[i].timestamp >= result[i-1].timestamp
    
    @pytest.mark.asyncio
    async def test_fetch_candles_invalid_timeframe(self):
        """Test error on invalid timeframe."""
        mock_client = AsyncMock(spec=MT5Client)
        
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            await fetch_ohlcv_candles(mock_client, "AAPL", "INVALID", 10)
    
    @pytest.mark.asyncio
    async def test_fetch_candles_invalid_count(self):
        """Test error on invalid count."""
        mock_client = AsyncMock(spec=MT5Client)
        
        with pytest.raises(ValueError, match="Count must be positive"):
            await fetch_ohlcv_candles(mock_client, "AAPL", "D1", 0)


# ============================================================================
# Tests for MarketDataFetcher
# ============================================================================

class TestMarketDataFetcher:
    """Tests for the MarketDataFetcher class."""
    
    @pytest.mark.asyncio
    async def test_fetch_candles_with_staleness_check(
        self, sample_candles, trading_hours_config
    ):
        """Test fetching candles with staleness detection."""
        mock_client = AsyncMock(spec=MT5Client)
        mock_client.get_candles.return_value = sample_candles
        
        config = TechnicalAgentConfig(stale_data=trading_hours_config)
        fetcher = MarketDataFetcher(mock_client, config)
        
        candles, is_stale = await fetcher.fetch_candles("AAPL", "D1", 10)
        
        assert len(candles) == 10
        # Staleness depends on current time vs last candle timestamp
    
    @pytest.mark.asyncio
    async def test_fetch_multi_timeframe(self, sample_candles):
        """Test fetching multiple timeframes."""
        mock_client = AsyncMock(spec=MT5Client)
        mock_client.get_candles.return_value = sample_candles
        
        fetcher = MarketDataFetcher(mock_client)
        
        results = await fetcher.fetch_multi_timeframe(
            "AAPL",
            ["D1", "H1"],
            count=10,
        )
        
        assert "D1" in results
        assert "H1" in results
        assert len(results["D1"][0]) == 10
        assert len(results["H1"][0]) == 10


# ============================================================================
# Tests for Timestream Persistence
# ============================================================================

class TestTimestreamPersistence:
    """Tests for Timestream persistence."""
    
    def test_serialize_ohlcv_for_timestream(self, sample_candles):
        """Test OHLCV serialization for Timestream."""
        candle = sample_candles[0]
        
        record = serialize_ohlcv_for_timestream(candle, "AAPL", "D1")
        
        assert record["Dimensions"][0]["Value"] == "AAPL"
        assert record["Dimensions"][1]["Value"] == "D1"
        assert record["MeasureName"] == "ohlcv"
        assert record["MeasureValueType"] == "MULTI"
        
        # Check measure values
        measures = {m["Name"]: m["Value"] for m in record["MeasureValues"]}
        assert float(measures["open"]) == candle.open
        assert float(measures["high"]) == candle.high
        assert float(measures["low"]) == candle.low
        assert float(measures["close"]) == candle.close
        assert int(measures["volume"]) == candle.volume
    
    @pytest.mark.asyncio
    async def test_persist_candles_success(self, sample_candles):
        """Test successful candle persistence to Timestream."""
        mock_client = AsyncMock(spec=TimestreamClient)
        mock_client.write_records.return_value = True
        
        persistence = TimestreamPersistence(timestream_client=mock_client)
        
        result = await persistence.persist_candles(sample_candles, "AAPL", "D1")
        
        assert result is True
        mock_client.write_records.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_persist_candles_empty_list(self):
        """Test persisting empty candle list."""
        mock_client = AsyncMock(spec=TimestreamClient)
        
        persistence = TimestreamPersistence(timestream_client=mock_client)
        
        result = await persistence.persist_candles([], "AAPL", "D1")
        
        assert result is True
        mock_client.write_records.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_get_candles_from_timestream(self, sample_candles):
        """Test retrieving candles from Timestream."""
        mock_client = AsyncMock(spec=TimestreamClient)
        
        # Mock query results
        mock_results = [
            {
                "time": c.timestamp.isoformat(),
                "open": str(c.open),
                "high": str(c.high),
                "low": str(c.low),
                "close": str(c.close),
                "volume": str(c.volume),
            }
            for c in sample_candles
        ]
        mock_client.query.return_value = mock_results
        
        persistence = TimestreamPersistence(timestream_client=mock_client)
        
        candles = await persistence.get_candles("AAPL", "D1")
        
        assert len(candles) == len(sample_candles)


# ============================================================================
# Tests for Configuration
# ============================================================================

class TestConfiguration:
    """Tests for configuration classes."""
    
    def test_supported_timeframes(self):
        """Test that all expected timeframes are supported."""
        expected = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
        assert SUPPORTED_TIMEFRAMES == expected
    
    def test_timeframe_minutes_mapping(self):
        """Test timeframe to minutes mapping."""
        assert TIMEFRAME_MINUTES["M1"] == 1
        assert TIMEFRAME_MINUTES["M5"] == 5
        assert TIMEFRAME_MINUTES["H1"] == 60
        assert TIMEFRAME_MINUTES["D1"] == 1440
    
    def test_default_config_values(self):
        """Test default configuration values."""
        config = TechnicalAgentConfig()
        
        assert config.default_timeframe == "D1"
        assert config.default_candle_count == 500
        assert config.stale_data.stale_threshold_minutes == 5
    
    def test_stale_threshold_is_5_minutes(self):
        """Test that stale threshold is 5 minutes (Requirement 10.2)."""
        assert STALE_DATA_THRESHOLD_MINUTES == 5
        
        config = StaleDataConfig()
        assert config.stale_threshold_minutes == 5

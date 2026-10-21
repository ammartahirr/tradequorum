"""
Market data fetching and stale data detection.

Implements OHLCV candle fetching for configurable timeframes with
stale data detection during trading hours.

Requirements:
- 2.1: Fetch OHLCV candles for configurable timeframes
- 10.2: Mark signals as stale when data >5 min old during trading hours
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from src.models import OHLCV

from .config import (
    TechnicalAgentConfig,
    StaleDataConfig,
    DEFAULT_CONFIG,
    SUPPORTED_TIMEFRAMES,
    TIMEFRAME_MINUTES,
)
from .mt5_client import MT5Client, MT5DataError

logger = logging.getLogger(__name__)


# Stale data threshold in minutes (Requirement 10.2)
STALE_DATA_THRESHOLD_MINUTES = 5


def is_trading_hours(
    timestamp: Optional[datetime] = None,
    config: Optional[StaleDataConfig] = None,
) -> bool:
    """
    Check if the given timestamp falls within trading hours.
    
    Args:
        timestamp: Timestamp to check (defaults to current UTC time)
        config: Stale data configuration (uses default if not provided)
        
    Returns:
        True if within trading hours, False otherwise
    """
    if config is None:
        config = DEFAULT_CONFIG.stale_data
    
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    
    # Ensure timestamp is UTC
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    
    # Check if it's a trading day
    if timestamp.weekday() not in config.trading_days:
        return False
    
    # Create time boundaries for today
    trading_start = timestamp.replace(
        hour=config.trading_start_hour_utc,
        minute=config.trading_start_minute_utc,
        second=0,
        microsecond=0,
    )
    trading_end = timestamp.replace(
        hour=config.trading_end_hour_utc,
        minute=config.trading_end_minute_utc,
        second=0,
        microsecond=0,
    )
    
    # Check regular trading hours
    if trading_start <= timestamp <= trading_end:
        return True
    
    # Check extended hours if enabled
    if config.include_extended_hours:
        extended_start = timestamp.replace(
            hour=config.extended_start_hour_utc,
            minute=0,
            second=0,
            microsecond=0,
        )
        extended_end = timestamp.replace(
            hour=config.extended_end_hour_utc,
            minute=0,
            second=0,
            microsecond=0,
        )
        
        # Handle overnight extended hours
        if config.extended_end_hour_utc < config.extended_start_hour_utc:
            # Extended hours span midnight
            if timestamp >= extended_start or timestamp <= extended_end:
                return True
        else:
            if extended_start <= timestamp <= extended_end:
                return True
    
    return False


def is_data_stale(
    last_update: datetime,
    current_time: Optional[datetime] = None,
    config: Optional[StaleDataConfig] = None,
) -> bool:
    """
    Check if market data is stale based on the last update time.
    
    Data is considered stale if:
    - It's during trading hours AND
    - The last update was more than 5 minutes ago
    
    Requirements:
    - 10.2: Mark signals as stale when data >5 min old during trading hours
    
    Args:
        last_update: Timestamp of the last data update
        current_time: Current time (defaults to UTC now)
        config: Stale data configuration
        
    Returns:
        True if data is stale, False otherwise
    """
    if config is None:
        config = DEFAULT_CONFIG.stale_data
    
    if current_time is None:
        current_time = datetime.now(timezone.utc)
    
    # Ensure timestamps are UTC
    if last_update.tzinfo is None:
        last_update = last_update.replace(tzinfo=timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    
    # Only check staleness during trading hours
    if not is_trading_hours(current_time, config):
        return False
    
    # Calculate time since last update
    time_since_update = current_time - last_update
    threshold = timedelta(minutes=config.stale_threshold_minutes)
    
    is_stale = time_since_update > threshold
    
    if is_stale:
        logger.warning(
            f"Data is stale: last update was {time_since_update.total_seconds() / 60:.1f} "
            f"minutes ago (threshold: {config.stale_threshold_minutes} minutes)"
        )
    
    return is_stale


class StaleDataDetector:
    """
    Detector for stale market data.
    
    Tracks the last update time for each symbol and determines
    if data should be considered stale.
    
    Requirements:
    - 10.2: Mark signals as stale when data >5 min old during trading hours
    """
    
    def __init__(self, config: Optional[StaleDataConfig] = None):
        """
        Initialize the stale data detector.
        
        Args:
            config: Stale data configuration
        """
        self.config = config or DEFAULT_CONFIG.stale_data
        self._last_updates: dict[str, datetime] = {}
    
    def record_update(self, symbol: str, timestamp: Optional[datetime] = None) -> None:
        """
        Record a data update for a symbol.
        
        Args:
            symbol: Trading symbol
            timestamp: Update timestamp (defaults to current time)
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        self._last_updates[symbol] = timestamp
        logger.debug(f"Recorded update for {symbol} at {timestamp}")
    
    def is_stale(
        self,
        symbol: str,
        current_time: Optional[datetime] = None,
    ) -> bool:
        """
        Check if data for a symbol is stale.
        
        Args:
            symbol: Trading symbol
            current_time: Current time (defaults to UTC now)
            
        Returns:
            True if data is stale or no update recorded, False otherwise
        """
        last_update = self._last_updates.get(symbol)
        
        if last_update is None:
            # No update recorded - consider stale during trading hours
            if current_time is None:
                current_time = datetime.now(timezone.utc)
            return is_trading_hours(current_time, self.config)
        
        return is_data_stale(last_update, current_time, self.config)
    
    def get_last_update(self, symbol: str) -> Optional[datetime]:
        """
        Get the last update time for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Last update timestamp or None if not recorded
        """
        return self._last_updates.get(symbol)
    
    def get_stale_symbols(
        self,
        symbols: list[str],
        current_time: Optional[datetime] = None,
    ) -> list[str]:
        """
        Get list of symbols with stale data.
        
        Args:
            symbols: List of symbols to check
            current_time: Current time (defaults to UTC now)
            
        Returns:
            List of symbols with stale data
        """
        return [s for s in symbols if self.is_stale(s, current_time)]
    
    def clear(self, symbol: Optional[str] = None) -> None:
        """
        Clear update records.
        
        Args:
            symbol: Specific symbol to clear (clears all if None)
        """
        if symbol:
            self._last_updates.pop(symbol, None)
        else:
            self._last_updates.clear()


async def fetch_ohlcv_candles(
    mt5_client: MT5Client,
    symbol: str,
    timeframe: str = "D1",
    count: int = 500,
    start_time: Optional[datetime] = None,
) -> list[OHLCV]:
    """
    Fetch OHLCV candles from MT5 for a symbol.
    
    Convenience function that wraps MT5Client.get_candles with
    validation and logging.
    
    Requirements:
    - 2.1: Fetch OHLCV candles for configurable timeframes
    
    Args:
        mt5_client: MT5 client instance
        symbol: Trading symbol (e.g., "AAPL", "EURUSD")
        timeframe: Candle timeframe (e.g., "M1", "H1", "D1")
        count: Number of candles to fetch
        start_time: Optional start time for historical data
        
    Returns:
        List of OHLCV candles sorted by timestamp ascending
        
    Raises:
        MT5DataError: If data retrieval fails
        ValueError: If invalid parameters provided
    """
    # Validate timeframe
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(
            f"Unsupported timeframe: {timeframe}. "
            f"Supported: {SUPPORTED_TIMEFRAMES}"
        )
    
    # Validate count
    if count <= 0:
        raise ValueError(f"Count must be positive, got: {count}")
    
    if count > DEFAULT_CONFIG.max_candle_count:
        logger.warning(
            f"Requested {count} candles exceeds max {DEFAULT_CONFIG.max_candle_count}. "
            f"Limiting to max."
        )
        count = DEFAULT_CONFIG.max_candle_count
    
    # Fetch candles
    candles = await mt5_client.get_candles(
        symbol=symbol,
        timeframe=timeframe,
        count=count,
        start_time=start_time,
    )
    
    # Sort by timestamp ascending
    candles.sort(key=lambda c: c.timestamp)
    
    logger.info(
        f"Fetched {len(candles)} {timeframe} candles for {symbol} "
        f"(from {candles[0].timestamp if candles else 'N/A'} "
        f"to {candles[-1].timestamp if candles else 'N/A'})"
    )
    
    return candles


class MarketDataFetcher:
    """
    High-level market data fetcher with caching and stale detection.
    
    Provides a unified interface for fetching market data with:
    - Automatic stale data detection
    - Update tracking
    - Configurable timeframes
    
    Requirements:
    - 2.1: Fetch OHLCV candles for configurable timeframes
    - 10.2: Mark signals as stale when data >5 min old during trading hours
    """
    
    def __init__(
        self,
        mt5_client: MT5Client,
        config: Optional[TechnicalAgentConfig] = None,
    ):
        """
        Initialize the market data fetcher.
        
        Args:
            mt5_client: MT5 client for data retrieval
            config: Technical agent configuration
        """
        self.mt5_client = mt5_client
        self.config = config or DEFAULT_CONFIG
        self.stale_detector = StaleDataDetector(self.config.stale_data)
    
    async def fetch_candles(
        self,
        symbol: str,
        timeframe: Optional[str] = None,
        count: Optional[int] = None,
        start_time: Optional[datetime] = None,
    ) -> tuple[list[OHLCV], bool]:
        """
        Fetch OHLCV candles and check for staleness.
        
        Args:
            symbol: Trading symbol
            timeframe: Candle timeframe (uses default if not provided)
            count: Number of candles (uses default if not provided)
            start_time: Optional start time for historical data
            
        Returns:
            Tuple of (candles, is_stale) where is_stale indicates
            if the data should be considered stale
        """
        timeframe = timeframe or self.config.default_timeframe
        count = count or self.config.default_candle_count
        
        # Fetch candles
        candles = await fetch_ohlcv_candles(
            mt5_client=self.mt5_client,
            symbol=symbol,
            timeframe=timeframe,
            count=count,
            start_time=start_time,
        )
        
        # Record update time
        if candles:
            latest_timestamp = candles[-1].timestamp
            self.stale_detector.record_update(symbol, latest_timestamp)
        
        # Check staleness
        is_stale = self.stale_detector.is_stale(symbol)
        
        return candles, is_stale
    
    async def fetch_multi_timeframe(
        self,
        symbol: str,
        timeframes: list[str],
        count: int = 500,
    ) -> dict[str, tuple[list[OHLCV], bool]]:
        """
        Fetch candles for multiple timeframes.
        
        Args:
            symbol: Trading symbol
            timeframes: List of timeframes to fetch
            count: Number of candles per timeframe
            
        Returns:
            Dictionary mapping timeframe to (candles, is_stale) tuple
        """
        results = {}
        
        for tf in timeframes:
            candles, is_stale = await self.fetch_candles(
                symbol=symbol,
                timeframe=tf,
                count=count,
            )
            results[tf] = (candles, is_stale)
        
        return results
    
    async def get_latest_price(self, symbol: str) -> Optional[dict]:
        """
        Get the latest price for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dictionary with bid, ask, and timestamp
        """
        price_data = await self.mt5_client.get_current_price(symbol)
        
        if price_data:
            self.stale_detector.record_update(symbol, price_data["timestamp"])
        
        return price_data
    
    def is_data_stale(self, symbol: str) -> bool:
        """
        Check if data for a symbol is stale.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            True if data is stale
        """
        return self.stale_detector.is_stale(symbol)
    
    def get_stale_symbols(self, symbols: list[str]) -> list[str]:
        """
        Get list of symbols with stale data.
        
        Args:
            symbols: List of symbols to check
            
        Returns:
            List of symbols with stale data
        """
        return self.stale_detector.get_stale_symbols(symbols)

"""
MT5 API connection handler with authentication.

Implements the MT5 connection handler for fetching market data from Exness
via the MetaTrader 5 API.

Requirements:
- 2.1: Fetch market data for technical indicator calculations
- 6.4: Implement retry with exponential backoff (3 attempts: 1s, 2s, 4s)
- 6.5: Query open positions to verify state before retrying after connection failure
- 10.6: Attempt reconnection and recalculate signals once fresh data resumes
- 11.1: Store MT5 credentials in AWS Secrets Manager with 90-day rotation
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.models import OHLCV

from .config import MT5Config, SUPPORTED_TIMEFRAMES, TIMEFRAME_MINUTES

logger = logging.getLogger(__name__)


class MT5ConnectionError(Exception):
    """Exception raised when MT5 connection fails."""
    pass


class MT5AuthenticationError(Exception):
    """Exception raised when MT5 authentication fails."""
    pass


class MT5DataError(Exception):
    """Exception raised when MT5 data retrieval fails."""
    pass


@dataclass
class MT5Credentials:
    """MT5 login credentials."""
    server: str
    login: int
    password: str


class SecretsManagerClient:
    """
    Client for retrieving secrets from AWS Secrets Manager.
    
    Requirements:
    - 11.1: Store MT5 credentials in AWS Secrets Manager with 90-day rotation
    """
    
    def __init__(self, region: str = "us-east-1"):
        """
        Initialize the Secrets Manager client.
        
        Args:
            region: AWS region for Secrets Manager
        """
        self.region = region
        self._client = None
    
    def _get_client(self):
        """Get or create the boto3 Secrets Manager client."""
        if self._client is None:
            import boto3
            self._client = boto3.client("secretsmanager", region_name=self.region)
        return self._client
    
    async def get_mt5_credentials(self, secret_name: str) -> MT5Credentials:
        """
        Retrieve MT5 credentials from Secrets Manager.
        
        Args:
            secret_name: Name of the secret containing MT5 credentials
            
        Returns:
            MT5Credentials with server, login, and password
            
        Raises:
            MT5AuthenticationError: If credentials cannot be retrieved
        """
        import json
        
        try:
            client = self._get_client()
            response = client.get_secret_value(SecretId=secret_name)
            secret_data = json.loads(response["SecretString"])
            
            return MT5Credentials(
                server=secret_data["server"],
                login=int(secret_data["login"]),
                password=secret_data["password"],
            )
        except Exception as e:
            logger.error(f"Failed to retrieve MT5 credentials: {e}")
            raise MT5AuthenticationError(f"Failed to retrieve credentials: {e}")


class MT5Client:
    """
    Client for interacting with MetaTrader 5 API.
    
    Handles connection management, authentication, and data retrieval
    with retry logic for connection failures.
    
    Requirements:
    - 6.4: Retry with exponential backoff (3 attempts: 1s, 2s, 4s)
    - 6.5: Query open positions to verify state before retrying
    - 10.6: Reconnection and signal recalculation on recovery
    """
    
    def __init__(
        self,
        config: Optional[MT5Config] = None,
        secrets_client: Optional[SecretsManagerClient] = None,
        on_reconnect_callback: Optional[callable] = None,
    ):
        """
        Initialize the MT5 client.
        
        Args:
            config: MT5 configuration (uses default if not provided)
            secrets_client: Secrets Manager client for credential retrieval
            on_reconnect_callback: Optional callback to invoke after successful reconnection
                                   for signal recalculation (Requirement 10.6)
        """
        self.config = config or MT5Config()
        self.secrets_client = secrets_client or SecretsManagerClient()
        self._connected = False
        self._credentials: Optional[MT5Credentials] = None
        self._last_connection_time: Optional[datetime] = None
        self._last_disconnect_time: Optional[datetime] = None
        self._mt5 = None
        self._on_reconnect_callback = on_reconnect_callback
        self._reconnection_in_progress = False
    
    def _get_mt5_module(self):
        """Get the MetaTrader5 module (lazy import)."""
        if self._mt5 is None:
            try:
                import MetaTrader5 as mt5
                self._mt5 = mt5
            except ImportError:
                raise MT5ConnectionError(
                    "MetaTrader5 package not installed. "
                    "Install with: pip install MetaTrader5"
                )
        return self._mt5
    
    @property
    def is_connected(self) -> bool:
        """Check if currently connected to MT5."""
        return self._connected
    
    async def connect(self) -> bool:
        """
        Establish connection to MT5 terminal.
        
        Retrieves credentials from Secrets Manager and initializes
        the MT5 connection with retry logic.
        
        Returns:
            True if connection successful
            
        Raises:
            MT5ConnectionError: If connection fails after all retries
            MT5AuthenticationError: If authentication fails
        """
        mt5 = self._get_mt5_module()
        
        # Retrieve credentials if not already loaded
        if self._credentials is None:
            self._credentials = await self.secrets_client.get_mt5_credentials(
                self.config.credentials_secret_name
            )
        
        # Attempt connection with retry logic (Requirement 6.4)
        last_error = None
        for attempt, delay in enumerate(self.config.retry_delays_seconds):
            try:
                # Initialize MT5 terminal
                if self.config.terminal_path:
                    initialized = mt5.initialize(path=self.config.terminal_path)
                else:
                    initialized = mt5.initialize()
                
                if not initialized:
                    error_code = mt5.last_error()
                    raise MT5ConnectionError(
                        f"MT5 initialization failed: {error_code}"
                    )
                
                # Login to trading account
                authorized = mt5.login(
                    login=self._credentials.login,
                    password=self._credentials.password,
                    server=self._credentials.server,
                    timeout=self.config.connection_timeout_seconds * 1000,
                )
                
                if not authorized:
                    error_code = mt5.last_error()
                    raise MT5AuthenticationError(
                        f"MT5 login failed: {error_code}"
                    )
                
                self._connected = True
                self._last_connection_time = datetime.now(timezone.utc)
                logger.info(
                    f"Connected to MT5 server {self._credentials.server} "
                    f"(login: {self._credentials.login})"
                )
                return True
                
            except (MT5ConnectionError, MT5AuthenticationError) as e:
                last_error = e
                logger.warning(
                    f"MT5 connection attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {delay}s..."
                )
                
                if attempt < len(self.config.retry_delays_seconds) - 1:
                    await asyncio.sleep(delay)
        
        # All retries exhausted
        self._connected = False
        raise MT5ConnectionError(
            f"Failed to connect to MT5 after {len(self.config.retry_delays_seconds)} "
            f"attempts: {last_error}"
        )
    
    async def disconnect(self) -> None:
        """Disconnect from MT5 terminal."""
        if self._connected:
            mt5 = self._get_mt5_module()
            mt5.shutdown()
            self._connected = False
            self._last_disconnect_time = datetime.now(timezone.utc)
            logger.info("Disconnected from MT5")
    
    async def ensure_connected(self) -> None:
        """
        Ensure connection is active, reconnecting if necessary.
        
        Requirements:
        - 10.6: Attempt reconnection when connection is lost
        """
        if not self._connected:
            was_previously_connected = self._last_disconnect_time is not None
            await self.connect()
            
            # If this was a reconnection (not initial connection), trigger callback
            if was_previously_connected and self._on_reconnect_callback:
                await self._trigger_reconnect_callback()
    
    async def reconnect_with_signal_recalculation(self) -> bool:
        """
        Reconnect to MT5 and trigger signal recalculation.
        
        This method should be called when connection is lost and needs to be
        re-established. After successful reconnection, it triggers the callback
        to recalculate all active signals with fresh data.
        
        Requirements:
        - 10.6: Attempt reconnection and recalculate signals once fresh data resumes
        
        Returns:
            True if reconnection successful, False otherwise
        """
        if self._reconnection_in_progress:
            logger.warning("Reconnection already in progress, skipping")
            return False
        
        self._reconnection_in_progress = True
        
        try:
            # Disconnect if still connected (cleanup)
            if self._connected:
                await self.disconnect()
            
            # Attempt reconnection
            await self.connect()
            
            # Trigger signal recalculation callback
            if self._on_reconnect_callback:
                await self._trigger_reconnect_callback()
            
            logger.info("MT5 reconnection successful, signals will be recalculated")
            return True
            
        except MT5ConnectionError as e:
            logger.error(f"MT5 reconnection failed: {e}")
            return False
        finally:
            self._reconnection_in_progress = False
    
    async def _trigger_reconnect_callback(self) -> None:
        """
        Trigger the reconnection callback for signal recalculation.
        
        Requirements:
        - 10.6: Recalculate signals once fresh data resumes
        """
        if self._on_reconnect_callback is None:
            return
        
        try:
            logger.info("Triggering signal recalculation after reconnection")
            if asyncio.iscoroutinefunction(self._on_reconnect_callback):
                await self._on_reconnect_callback()
            else:
                self._on_reconnect_callback()
        except Exception as e:
            logger.error(f"Error in reconnection callback: {e}")
    
    def set_reconnect_callback(self, callback: callable) -> None:
        """
        Set the callback to invoke after successful reconnection.
        
        Args:
            callback: Async or sync function to call after reconnection
        """
        self._on_reconnect_callback = callback
    
    @property
    def last_disconnect_time(self) -> Optional[datetime]:
        """Get the timestamp of the last disconnection."""
        return self._last_disconnect_time
    
    @property
    def is_reconnection_in_progress(self) -> bool:
        """Check if a reconnection attempt is currently in progress."""
        return self._reconnection_in_progress
    
    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int,
        start_time: Optional[datetime] = None,
    ) -> list[OHLCV]:
        """
        Fetch OHLCV candles from MT5.
        
        Args:
            symbol: Trading symbol (e.g., "AAPL", "EURUSD")
            timeframe: Candle timeframe (e.g., "M1", "H1", "D1")
            count: Number of candles to fetch
            start_time: Optional start time for historical data
            
        Returns:
            List of OHLCV candles
            
        Raises:
            MT5DataError: If data retrieval fails
            MT5ConnectionError: If not connected
        """
        await self.ensure_connected()
        
        mt5 = self._get_mt5_module()
        
        # Validate timeframe
        if timeframe not in SUPPORTED_TIMEFRAMES:
            raise MT5DataError(
                f"Unsupported timeframe: {timeframe}. "
                f"Supported: {SUPPORTED_TIMEFRAMES}"
            )
        
        # Map timeframe string to MT5 constant
        timeframe_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
            "W1": mt5.TIMEFRAME_W1,
            "MN1": mt5.TIMEFRAME_MN1,
        }
        mt5_timeframe = timeframe_map[timeframe]
        
        try:
            if start_time:
                # Fetch candles from specific start time
                rates = mt5.copy_rates_from(
                    symbol,
                    mt5_timeframe,
                    start_time,
                    count,
                )
            else:
                # Fetch most recent candles
                rates = mt5.copy_rates_from_pos(
                    symbol,
                    mt5_timeframe,
                    0,  # Start from most recent
                    count,
                )
            
            if rates is None or len(rates) == 0:
                error_code = mt5.last_error()
                raise MT5DataError(
                    f"Failed to fetch candles for {symbol}: {error_code}"
                )
            
            # Convert to OHLCV objects
            candles = []
            for rate in rates:
                candle = OHLCV(
                    timestamp=datetime.fromtimestamp(rate["time"], tz=timezone.utc),
                    open=float(rate["open"]),
                    high=float(rate["high"]),
                    low=float(rate["low"]),
                    close=float(rate["close"]),
                    volume=int(rate["tick_volume"]),
                )
                candles.append(candle)
            
            logger.debug(
                f"Fetched {len(candles)} candles for {symbol} ({timeframe})"
            )
            return candles
            
        except Exception as e:
            if isinstance(e, MT5DataError):
                raise
            raise MT5DataError(f"Error fetching candles: {e}")
    
    async def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """
        Get symbol information from MT5.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dictionary with symbol info or None if not found
        """
        await self.ensure_connected()
        
        mt5 = self._get_mt5_module()
        
        info = mt5.symbol_info(symbol)
        if info is None:
            return None
        
        return {
            "name": info.name,
            "description": info.description,
            "currency_base": info.currency_base,
            "currency_profit": info.currency_profit,
            "digits": info.digits,
            "point": info.point,
            "trade_contract_size": info.trade_contract_size,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "spread": info.spread,
            "bid": info.bid,
            "ask": info.ask,
        }
    
    async def get_current_price(self, symbol: str) -> Optional[dict]:
        """
        Get current bid/ask prices for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dictionary with bid, ask, and timestamp
        """
        await self.ensure_connected()
        
        mt5 = self._get_mt5_module()
        
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        
        return {
            "bid": tick.bid,
            "ask": tick.ask,
            "last": tick.last,
            "volume": tick.volume,
            "timestamp": datetime.fromtimestamp(tick.time, tz=timezone.utc),
        }
    
    async def get_open_positions(self) -> list[dict]:
        """
        Get all open positions.
        
        Used to verify state before retrying after connection failure
        (Requirement 6.5).
        
        Returns:
            List of open position dictionaries
        """
        await self.ensure_connected()
        
        mt5 = self._get_mt5_module()
        
        positions = mt5.positions_get()
        if positions is None:
            return []
        
        return [
            {
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "type": "buy" if pos.type == 0 else "sell",
                "volume": pos.volume,
                "price_open": pos.price_open,
                "price_current": pos.price_current,
                "sl": pos.sl,
                "tp": pos.tp,
                "profit": pos.profit,
                "time": datetime.fromtimestamp(pos.time, tz=timezone.utc),
            }
            for pos in positions
        ]

"""
Timestream persistence layer for Technical Agent market data.

Implements OHLCV candle storage in AWS Timestream for efficient
time-series querying.

Requirements:
- 9.5: Store OHLCV candles in Timestream for time-series querying
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from src.models import OHLCV

from .config import TimestreamConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)

# Agent type constant for technical signals
TECHNICAL_AGENT_TYPE = "technical"

# Default Timestream database and table names
DEFAULT_DATABASE_NAME = "trading-market-data"
DEFAULT_TABLE_NAME = "ohlcv-candles"


def serialize_ohlcv_for_timestream(
    candle: OHLCV,
    symbol: str,
    timeframe: str,
) -> dict:
    """
    Serialize an OHLCV candle for Timestream storage.
    
    Timestream uses a specific format with dimensions, measures, and time.
    
    Args:
        candle: OHLCV candle to serialize
        symbol: Trading symbol
        timeframe: Candle timeframe
        
    Returns:
        Dictionary formatted for Timestream write_records
    """
    # Convert timestamp to milliseconds since epoch
    time_ms = int(candle.timestamp.timestamp() * 1000)
    
    return {
        "Dimensions": [
            {"Name": "symbol", "Value": symbol},
            {"Name": "timeframe", "Value": timeframe},
        ],
        "MeasureName": "ohlcv",
        "MeasureValueType": "MULTI",
        "MeasureValues": [
            {
                "Name": "open",
                "Value": str(candle.open),
                "Type": "DOUBLE",
            },
            {
                "Name": "high",
                "Value": str(candle.high),
                "Type": "DOUBLE",
            },
            {
                "Name": "low",
                "Value": str(candle.low),
                "Type": "DOUBLE",
            },
            {
                "Name": "close",
                "Value": str(candle.close),
                "Type": "DOUBLE",
            },
            {
                "Name": "volume",
                "Value": str(candle.volume),
                "Type": "BIGINT",
            },
        ],
        "Time": str(time_ms),
        "TimeUnit": "MILLISECONDS",
    }


class TimestreamClient:
    """
    Client for interacting with AWS Timestream.
    
    Provides low-level operations for writing and querying
    time-series data.
    """
    
    def __init__(
        self,
        database_name: str = DEFAULT_DATABASE_NAME,
        table_name: str = DEFAULT_TABLE_NAME,
        region: str = "us-east-1",
    ):
        """
        Initialize the Timestream client.
        
        Args:
            database_name: Timestream database name
            table_name: Timestream table name
            region: AWS region
        """
        self.database_name = database_name
        self.table_name = table_name
        self.region = region
        self._write_client = None
        self._query_client = None
    
    def _get_write_client(self):
        """Get or create the boto3 Timestream write client."""
        if self._write_client is None:
            import boto3
            self._write_client = boto3.client(
                "timestream-write",
                region_name=self.region,
            )
        return self._write_client
    
    def _get_query_client(self):
        """Get or create the boto3 Timestream query client."""
        if self._query_client is None:
            import boto3
            self._query_client = boto3.client(
                "timestream-query",
                region_name=self.region,
            )
        return self._query_client
    
    async def write_records(self, records: list[dict]) -> bool:
        """
        Write records to Timestream.
        
        Args:
            records: List of record dictionaries formatted for Timestream
            
        Returns:
            True if successful, False otherwise
        """
        if not records:
            return True
        
        try:
            client = self._get_write_client()
            
            # Timestream has a limit of 100 records per write
            batch_size = 100
            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                
                client.write_records(
                    DatabaseName=self.database_name,
                    TableName=self.table_name,
                    Records=batch,
                    CommonAttributes={},
                )
            
            logger.debug(f"Wrote {len(records)} records to Timestream")
            return True
            
        except Exception as e:
            logger.error(f"Failed to write records to Timestream: {e}")
            return False
    
    async def query(self, query_string: str) -> list[dict]:
        """
        Execute a query against Timestream.
        
        Args:
            query_string: SQL query string
            
        Returns:
            List of result rows as dictionaries
        """
        try:
            client = self._get_query_client()
            
            paginator = client.get_paginator("query")
            results = []
            
            for page in paginator.paginate(QueryString=query_string):
                # Parse column info
                columns = [
                    col["Name"] for col in page["ColumnInfo"]
                ]
                
                # Parse rows
                for row in page["Rows"]:
                    row_dict = {}
                    for i, data in enumerate(row["Data"]):
                        # Handle different data types
                        if "ScalarValue" in data:
                            row_dict[columns[i]] = data["ScalarValue"]
                        elif "NullValue" in data:
                            row_dict[columns[i]] = None
                    results.append(row_dict)
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to query Timestream: {e}")
            return []


class TimestreamPersistence:
    """
    Persistence layer for OHLCV candles in Timestream.
    
    Handles storing and retrieving market data with proper
    formatting and error handling.
    
    Requirements:
    - 9.5: Store OHLCV candles in Timestream for time-series querying
    """
    
    def __init__(
        self,
        timestream_client: Optional[TimestreamClient] = None,
        config: Optional[TimestreamConfig] = None,
    ):
        """
        Initialize the Timestream persistence layer.
        
        Args:
            timestream_client: Optional Timestream client
            config: Timestream configuration
        """
        self.config = config or DEFAULT_CONFIG.timestream
        self.client = timestream_client or TimestreamClient(
            database_name=self.config.database_name,
            table_name=self.config.table_name,
            region=self.config.region,
        )
    
    async def persist_candles(
        self,
        candles: list[OHLCV],
        symbol: str,
        timeframe: str,
    ) -> bool:
        """
        Persist OHLCV candles to Timestream.
        
        Args:
            candles: List of OHLCV candles to persist
            symbol: Trading symbol
            timeframe: Candle timeframe
            
        Returns:
            True if successful, False otherwise
            
        Requirements:
        - 9.5: Store OHLCV candles in Timestream for time-series querying
        """
        if not candles:
            return True
        
        # Serialize candles for Timestream
        records = [
            serialize_ohlcv_for_timestream(candle, symbol, timeframe)
            for candle in candles
        ]
        
        # Write to Timestream
        success = await self.client.write_records(records)
        
        if success:
            logger.info(
                f"Persisted {len(candles)} {timeframe} candles for {symbol} "
                f"to Timestream"
            )
        else:
            logger.error(
                f"Failed to persist candles for {symbol} to Timestream"
            )
        
        return success
    
    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> list[OHLCV]:
        """
        Retrieve OHLCV candles from Timestream.
        
        Args:
            symbol: Trading symbol
            timeframe: Candle timeframe
            start_time: Optional start time filter
            end_time: Optional end time filter
            limit: Maximum number of candles to return
            
        Returns:
            List of OHLCV candles sorted by timestamp ascending
        """
        # Build query
        query = f"""
            SELECT time, open, high, low, close, volume
            FROM "{self.config.database_name}"."{self.config.table_name}"
            WHERE symbol = '{symbol}'
              AND timeframe = '{timeframe}'
        """
        
        if start_time:
            start_ms = int(start_time.timestamp() * 1000)
            query += f" AND time >= from_milliseconds({start_ms})"
        
        if end_time:
            end_ms = int(end_time.timestamp() * 1000)
            query += f" AND time <= from_milliseconds({end_ms})"
        
        query += f" ORDER BY time ASC LIMIT {limit}"
        
        # Execute query
        results = await self.client.query(query)
        
        # Convert to OHLCV objects
        candles = []
        for row in results:
            try:
                candle = OHLCV(
                    timestamp=datetime.fromisoformat(
                        row["time"].replace(" ", "T")
                    ).replace(tzinfo=timezone.utc),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row["volume"]),
                )
                candles.append(candle)
            except (KeyError, ValueError) as e:
                logger.warning(f"Failed to parse candle row: {e}")
                continue
        
        logger.debug(
            f"Retrieved {len(candles)} {timeframe} candles for {symbol} "
            f"from Timestream"
        )
        
        return candles
    
    async def get_latest_candle(
        self,
        symbol: str,
        timeframe: str,
    ) -> Optional[OHLCV]:
        """
        Get the most recent candle for a symbol.
        
        Args:
            symbol: Trading symbol
            timeframe: Candle timeframe
            
        Returns:
            Most recent OHLCV candle or None if not found
        """
        query = f"""
            SELECT time, open, high, low, close, volume
            FROM "{self.config.database_name}"."{self.config.table_name}"
            WHERE symbol = '{symbol}'
              AND timeframe = '{timeframe}'
            ORDER BY time DESC
            LIMIT 1
        """
        
        results = await self.client.query(query)
        
        if not results:
            return None
        
        row = results[0]
        try:
            return OHLCV(
                timestamp=datetime.fromisoformat(
                    row["time"].replace(" ", "T")
                ).replace(tzinfo=timezone.utc),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
            )
        except (KeyError, ValueError) as e:
            logger.warning(f"Failed to parse latest candle: {e}")
            return None
    
    async def get_symbols_with_data(self, timeframe: str) -> list[str]:
        """
        Get list of symbols that have data for a timeframe.
        
        Args:
            timeframe: Candle timeframe
            
        Returns:
            List of symbol names
        """
        query = f"""
            SELECT DISTINCT symbol
            FROM "{self.config.database_name}"."{self.config.table_name}"
            WHERE timeframe = '{timeframe}'
        """
        
        results = await self.client.query(query)
        return [row["symbol"] for row in results if "symbol" in row]
    
    async def delete_old_candles(
        self,
        symbol: str,
        timeframe: str,
        before_time: datetime,
    ) -> bool:
        """
        Delete candles older than a specified time.
        
        Note: Timestream handles data retention automatically based on
        the table's retention policy. This method is provided for
        manual cleanup if needed.
        
        Args:
            symbol: Trading symbol
            timeframe: Candle timeframe
            before_time: Delete candles before this time
            
        Returns:
            True (Timestream doesn't support DELETE, relies on retention)
        """
        # Timestream doesn't support DELETE operations
        # Data is automatically removed based on retention policy
        logger.info(
            f"Timestream retention policy will handle cleanup for {symbol} "
            f"{timeframe} candles older than {before_time}"
        )
        return True

"""
Configuration for the Technical Agent.

This module defines the configuration for:
- MT5 connection settings (authentication, timeouts)
- Timestream database settings for OHLCV storage
- Stale data detection thresholds
- Supported timeframes for candle fetching

Requirements:
- 2.1: Support configurable timeframes for indicator calculations
- 9.5: Configure Timestream for time-series querying
- 10.2: Configure stale data detection threshold (>5 min during trading hours)
"""

from dataclasses import dataclass, field
from typing import Optional


# Supported timeframes for OHLCV candle fetching
SUPPORTED_TIMEFRAMES = [
    "M1",   # 1 minute
    "M5",   # 5 minutes
    "M15",  # 15 minutes
    "M30",  # 30 minutes
    "H1",   # 1 hour
    "H4",   # 4 hours
    "D1",   # 1 day
    "W1",   # 1 week
    "MN1",  # 1 month
]

# Timeframe to minutes mapping
TIMEFRAME_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
    "W1": 10080,
    "MN1": 43200,
}


@dataclass
class MT5Config:
    """
    Configuration for MT5 API connection.
    
    Credentials are stored in AWS Secrets Manager and retrieved at runtime.
    """
    
    # Secrets Manager secret name for MT5 credentials
    credentials_secret_name: str = "exness/mt5/credentials"
    
    # Connection timeout in seconds
    connection_timeout_seconds: int = 30
    
    # Retry configuration for connection failures (Requirement 6.4)
    retry_attempts: int = 3
    retry_delays_seconds: list[int] = field(default_factory=lambda: [1, 2, 4])
    
    # Server configuration (retrieved from Secrets Manager)
    server: Optional[str] = None
    login: Optional[int] = None
    password: Optional[str] = None
    
    # Path to MT5 terminal (for local installations)
    terminal_path: Optional[str] = None


@dataclass
class TimestreamConfig:
    """
    Configuration for AWS Timestream storage.
    
    Requirements:
    - 9.5: Store OHLCV candles in Timestream for time-series querying
    """
    
    # Timestream database name
    database_name: str = "trading-market-data"
    
    # Timestream table name for OHLCV candles
    table_name: str = "ohlcv-candles"
    
    # Memory store retention period (hours)
    memory_store_retention_hours: int = 24
    
    # Magnetic store retention period (days)
    magnetic_store_retention_days: int = 1825  # 5 years for historical analysis
    
    # Batch write size for efficiency
    batch_write_size: int = 100
    
    # AWS region
    region: str = "us-east-1"


@dataclass
class StaleDataConfig:
    """
    Configuration for stale data detection.
    
    Requirements:
    - 10.2: Mark signals as stale when data >5 min old during trading hours
    """
    
    # Threshold in minutes for stale data detection
    stale_threshold_minutes: int = 5
    
    # Trading hours configuration (UTC)
    # Default: NYSE trading hours (9:30 AM - 4:00 PM ET = 14:30 - 21:00 UTC)
    trading_start_hour_utc: int = 14
    trading_start_minute_utc: int = 30
    trading_end_hour_utc: int = 21
    trading_end_minute_utc: int = 0
    
    # Trading days (0=Monday, 6=Sunday)
    trading_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    
    # Whether to consider extended hours
    include_extended_hours: bool = False
    
    # Extended hours configuration (pre-market and after-hours)
    extended_start_hour_utc: int = 9   # 4:00 AM ET
    extended_end_hour_utc: int = 1     # 8:00 PM ET (next day)


@dataclass
class TechnicalAgentConfig:
    """Complete configuration for the Technical Agent."""
    
    # MT5 connection configuration
    mt5: MT5Config = field(default_factory=MT5Config)
    
    # Timestream storage configuration
    timestream: TimestreamConfig = field(default_factory=TimestreamConfig)
    
    # Stale data detection configuration
    stale_data: StaleDataConfig = field(default_factory=StaleDataConfig)
    
    # Default timeframe for analysis
    default_timeframe: str = "D1"
    
    # Number of candles to fetch by default
    default_candle_count: int = 500
    
    # Maximum candles to fetch in a single request
    max_candle_count: int = 5000
    
    # Symbols to monitor (can be overridden via SSM parameter)
    symbols_parameter: str = "/trading/symbols"
    
    # DynamoDB table for signal persistence
    signals_table: str = "trading-signals"


# Default configuration instance
DEFAULT_CONFIG = TechnicalAgentConfig()


def get_timestream_table_definition(config: TechnicalAgentConfig) -> dict:
    """
    Generate Timestream table definition for CloudFormation/CDK.
    
    Args:
        config: TechnicalAgentConfig instance
        
    Returns:
        Dictionary with Timestream table definition
    """
    return {
        "Type": "AWS::Timestream::Table",
        "Properties": {
            "DatabaseName": config.timestream.database_name,
            "TableName": config.timestream.table_name,
            "RetentionProperties": {
                "MemoryStoreRetentionPeriodInHours": str(
                    config.timestream.memory_store_retention_hours
                ),
                "MagneticStoreRetentionPeriodInDays": str(
                    config.timestream.magnetic_store_retention_days
                ),
            },
            "MagneticStoreWriteProperties": {
                "EnableMagneticStoreWrites": True,
            },
        },
    }


def get_timestream_database_definition(config: TechnicalAgentConfig) -> dict:
    """
    Generate Timestream database definition for CloudFormation/CDK.
    
    Args:
        config: TechnicalAgentConfig instance
        
    Returns:
        Dictionary with Timestream database definition
    """
    return {
        "Type": "AWS::Timestream::Database",
        "Properties": {
            "DatabaseName": config.timestream.database_name,
        },
    }

"""
Technical Agent module for the AI Trading System.

The Technical Agent ("The Eye") is responsible for:
- Fetching market data from MT5 API
- Calculating technical indicators (RSI, MACD, Bollinger Bands, moving averages)
- Identifying support and resistance levels
- Detecting confluence patterns
- Generating TechnicalSignals with trend and market condition analysis

Requirements:
- 2.1: Calculate RSI, MACD, Bollinger Bands, 50-day and 200-day moving averages
- 9.5: Store OHLCV candles in Timestream for time-series querying
- 10.2: Mark signals as stale when data >5 min old during trading hours
"""

from .config import (
    TechnicalAgentConfig,
    MT5Config,
    TimestreamConfig,
    StaleDataConfig,
    DEFAULT_CONFIG,
    SUPPORTED_TIMEFRAMES,
    TIMEFRAME_MINUTES,
)
from .mt5_client import (
    MT5Client,
    MT5ConnectionError,
    MT5AuthenticationError,
    MT5DataError,
)
from .market_data import (
    MarketDataFetcher,
    fetch_ohlcv_candles,
    is_data_stale,
    is_trading_hours,
    StaleDataDetector,
    STALE_DATA_THRESHOLD_MINUTES,
)
from .persistence import (
    TimestreamClient,
    TimestreamPersistence,
    serialize_ohlcv_for_timestream,
    TECHNICAL_AGENT_TYPE,
    DEFAULT_DATABASE_NAME,
    DEFAULT_TABLE_NAME,
)
from .indicators import (
    calculate_rsi,
    calculate_macd,
    calculate_bollinger_bands,
    calculate_sma,
    calculate_ema,
    calculate_moving_averages,
    calculate_all_indicators,
    MACDResult,
    BollingerBandsResult,
    MovingAveragesResult,
    TechnicalIndicators,
    IndicatorCalculationError,
)
from .support_resistance import (
    analyze_support_resistance,
    identify_support_levels,
    identify_resistance_levels,
    is_level_active,
    get_active_levels,
    get_nearest_support,
    get_nearest_resistance,
    find_local_minima,
    find_local_maxima,
    cluster_levels,
    SupportResistanceResult,
    ACTIVE_LEVEL_THRESHOLD_PCT,
    DEFAULT_LOOKBACK_WINDOW,
    DEFAULT_CLUSTER_THRESHOLD_PCT,
)
from .confluence import (
    detect_confluence,
    detect_volume_spike,
    validate_confluence_score,
    get_confluence_summary,
    TOTAL_CONFLUENCE_FACTORS,
    RSI_OVERSOLD_THRESHOLD,
    RSI_OVERBOUGHT_THRESHOLD,
    VOLUME_SPIKE_MULTIPLIER,
    VOLUME_AVERAGE_PERIOD,
)
from .signal_generator import (
    TechnicalSignalGenerator,
    DynamoDBClient as SignalDynamoDBClient,
    SageMakerClient,
    generate_signal_id,
    serialize_technical_signal,
    determine_trend_direction,
    determine_market_condition,
    determine_volume_trend,
    SAGEMAKER_TIMEOUT_SECONDS,
)

__all__ = [
    # Configuration
    "TechnicalAgentConfig",
    "MT5Config",
    "TimestreamConfig",
    "StaleDataConfig",
    "DEFAULT_CONFIG",
    "SUPPORTED_TIMEFRAMES",
    "TIMEFRAME_MINUTES",
    # MT5 Client
    "MT5Client",
    "MT5ConnectionError",
    "MT5AuthenticationError",
    "MT5DataError",
    # Market Data
    "MarketDataFetcher",
    "fetch_ohlcv_candles",
    "is_data_stale",
    "is_trading_hours",
    "StaleDataDetector",
    "STALE_DATA_THRESHOLD_MINUTES",
    # Persistence (Timestream)
    "TimestreamClient",
    "TimestreamPersistence",
    "serialize_ohlcv_for_timestream",
    "TECHNICAL_AGENT_TYPE",
    "DEFAULT_DATABASE_NAME",
    "DEFAULT_TABLE_NAME",
    # Technical Indicators
    "calculate_rsi",
    "calculate_macd",
    "calculate_bollinger_bands",
    "calculate_sma",
    "calculate_ema",
    "calculate_moving_averages",
    "calculate_all_indicators",
    "MACDResult",
    "BollingerBandsResult",
    "MovingAveragesResult",
    "TechnicalIndicators",
    "IndicatorCalculationError",
    # Support/Resistance
    "analyze_support_resistance",
    "identify_support_levels",
    "identify_resistance_levels",
    "is_level_active",
    "get_active_levels",
    "get_nearest_support",
    "get_nearest_resistance",
    "find_local_minima",
    "find_local_maxima",
    "cluster_levels",
    "SupportResistanceResult",
    "ACTIVE_LEVEL_THRESHOLD_PCT",
    "DEFAULT_LOOKBACK_WINDOW",
    "DEFAULT_CLUSTER_THRESHOLD_PCT",
    # Confluence Detection
    "detect_confluence",
    "detect_volume_spike",
    "validate_confluence_score",
    "get_confluence_summary",
    "TOTAL_CONFLUENCE_FACTORS",
    "RSI_OVERSOLD_THRESHOLD",
    "RSI_OVERBOUGHT_THRESHOLD",
    "VOLUME_SPIKE_MULTIPLIER",
    "VOLUME_AVERAGE_PERIOD",
    # Signal Generation
    "TechnicalSignalGenerator",
    "SignalDynamoDBClient",
    "SageMakerClient",
    "generate_signal_id",
    "serialize_technical_signal",
    "determine_trend_direction",
    "determine_market_condition",
    "determine_volume_trend",
    "SAGEMAKER_TIMEOUT_SECONDS",
]

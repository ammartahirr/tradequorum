"""
TechnicalSignal generation for the Technical Agent.

Implements:
- TechnicalSignalGenerator class for generating TechnicalSignal objects
- DynamoDB persistence for signals
- Optional SageMaker pattern prediction with 10s timeout fallback

Requirements:
- 2.8: Generate TechnicalSignal with all required fields
- 9.2: Persist signals to DynamoDB with signal ID, agent type, symbol, payload, timestamp
- 10.3: Skip ML-based pattern prediction on SageMaker error or >10s latency
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from src.models import (
    ConfluenceResult,
    MarketCondition,
    OHLCV,
    SignalLog,
    SupportResistance,
    TechnicalSignal,
    TrendDirection,
)

from .confluence import detect_confluence
from .indicators import calculate_rsi, calculate_moving_averages
from .support_resistance import (
    identify_support_levels,
    identify_resistance_levels,
)

logger = logging.getLogger(__name__)

# Agent type constant for technical signals
TECHNICAL_AGENT_TYPE = "technical"

# Default DynamoDB table name
DEFAULT_SIGNALS_TABLE = "trading-signals"

# SageMaker timeout in seconds (Requirement 10.3)
SAGEMAKER_TIMEOUT_SECONDS = 10

# Volume trend thresholds
VOLUME_INCREASE_THRESHOLD = 1.2  # 20% increase
VOLUME_DECREASE_THRESHOLD = 0.8  # 20% decrease
VOLUME_AVERAGE_PERIOD = 20


class DynamoDBClient:
    """
    Client for interacting with DynamoDB.
    
    Provides low-level operations for storing and retrieving signals.
    """
    
    def __init__(self, table_name: str = DEFAULT_SIGNALS_TABLE):
        """
        Initialize the DynamoDB client.
        
        Args:
            table_name: Name of the DynamoDB table for signals
        """
        self.table_name = table_name
        self._client = None
    
    def _get_client(self):
        """Get or create the boto3 DynamoDB resource."""
        if self._client is None:
            import boto3
            self._client = boto3.resource("dynamodb")
        return self._client
    
    async def put_item(self, item: dict) -> bool:
        """
        Put an item into DynamoDB.
        
        Args:
            item: Dictionary representing the item to store
            
        Returns:
            True if successful, False otherwise
        """
        try:
            table = self._get_client().Table(self.table_name)
            table.put_item(Item=item)
            return True
        except Exception as e:
            logger.error(f"Failed to put item to DynamoDB: {e}")
            return False
    
    async def get_item(self, signal_id: str) -> Optional[dict]:
        """
        Get an item from DynamoDB by signal ID.
        
        Args:
            signal_id: The signal ID to retrieve
            
        Returns:
            The item dictionary if found, None otherwise
        """
        try:
            table = self._get_client().Table(self.table_name)
            response = table.get_item(Key={"signal_id": signal_id})
            return response.get("Item")
        except Exception as e:
            logger.error(f"Failed to get item from DynamoDB: {e}")
            return None


class SageMakerClient:
    """
    Client for SageMaker pattern prediction.
    
    Provides ML-based pattern recognition with timeout handling.
    """
    
    def __init__(
        self,
        endpoint_name: str = "trading-pattern-model",
        region: str = "us-east-1",
    ):
        """
        Initialize the SageMaker client.
        
        Args:
            endpoint_name: SageMaker endpoint name
            region: AWS region
        """
        self.endpoint_name = endpoint_name
        self.region = region
        self._client = None
    
    def _get_client(self):
        """Get or create the boto3 SageMaker runtime client."""
        if self._client is None:
            import boto3
            self._client = boto3.client(
                "sagemaker-runtime",
                region_name=self.region,
            )
        return self._client
    
    async def predict_pattern(
        self,
        candles: list[OHLCV],
        timeout_seconds: float = SAGEMAKER_TIMEOUT_SECONDS,
    ) -> Optional[dict]:
        """
        Get pattern prediction from SageMaker.
        
        Requirements:
        - 10.3: Skip ML-based pattern prediction on error or >10s latency
        
        Args:
            candles: List of OHLCV candles for prediction
            timeout_seconds: Timeout in seconds (default 10s)
            
        Returns:
            Prediction result dict or None if failed/timeout
        """
        try:
            # Prepare input data
            input_data = {
                "candles": [
                    {
                        "timestamp": c.timestamp.isoformat(),
                        "open": c.open,
                        "high": c.high,
                        "low": c.low,
                        "close": c.close,
                        "volume": c.volume,
                    }
                    for c in candles[-100:]  # Use last 100 candles
                ]
            }
            
            # Call SageMaker with timeout
            client = self._get_client()
            
            # Use asyncio timeout
            async def invoke_endpoint():
                response = client.invoke_endpoint(
                    EndpointName=self.endpoint_name,
                    ContentType="application/json",
                    Body=json.dumps(input_data),
                )
                return json.loads(response["Body"].read().decode())
            
            result = await asyncio.wait_for(
                invoke_endpoint(),
                timeout=timeout_seconds,
            )
            
            logger.debug(f"SageMaker prediction received: {result}")
            return result
            
        except asyncio.TimeoutError:
            logger.warning(
                f"SageMaker prediction timed out after {timeout_seconds}s, "
                "skipping ML-based pattern prediction"
            )
            return None
        except Exception as e:
            logger.warning(
                f"SageMaker prediction failed: {e}, "
                "skipping ML-based pattern prediction"
            )
            return None


def generate_signal_id() -> str:
    """
    Generate a unique signal ID.
    
    Returns:
        UUID string for the signal
    """
    return str(uuid.uuid4())


def determine_trend_direction(candles: list[OHLCV]) -> TrendDirection:
    """
    Determine the trend direction based on moving averages and price action.
    
    Args:
        candles: List of OHLCV candles
        
    Returns:
        TrendDirection enum value
    """
    if len(candles) < 200:
        # Not enough data for full analysis
        if len(candles) < 20:
            return TrendDirection.SIDEWAYS
        
        # Use short-term price action
        recent_closes = [c.close for c in candles[-20:]]
        price_change_pct = (recent_closes[-1] - recent_closes[0]) / recent_closes[0]
        
        if price_change_pct > 0.05:
            return TrendDirection.UPTREND
        elif price_change_pct < -0.05:
            return TrendDirection.DOWNTREND
        else:
            return TrendDirection.SIDEWAYS
    
    # Use moving averages for trend determination
    ma_result = calculate_moving_averages(candles)
    current_price = candles[-1].close
    
    # Calculate price position relative to MAs
    above_ma50 = current_price > ma_result.ma_50
    above_ma200 = current_price > ma_result.ma_200
    golden_cross = ma_result.is_golden_cross
    
    # Calculate recent momentum
    recent_closes = [c.close for c in candles[-10:]]
    momentum = (recent_closes[-1] - recent_closes[0]) / recent_closes[0]
    
    if golden_cross and above_ma50 and above_ma200:
        if momentum > 0.03:
            return TrendDirection.STRONG_UPTREND
        return TrendDirection.UPTREND
    elif not golden_cross and not above_ma50 and not above_ma200:
        if momentum < -0.03:
            return TrendDirection.STRONG_DOWNTREND
        return TrendDirection.DOWNTREND
    else:
        return TrendDirection.SIDEWAYS


def determine_market_condition(rsi: float) -> MarketCondition:
    """
    Determine market condition based on RSI.
    
    Args:
        rsi: RSI value (0-100)
        
    Returns:
        MarketCondition enum value
    """
    if rsi <= 30:
        return MarketCondition.OVERSOLD
    elif rsi >= 70:
        return MarketCondition.OVERBOUGHT
    else:
        return MarketCondition.NEUTRAL


def determine_volume_trend(candles: list[OHLCV]) -> str:
    """
    Determine volume trend based on recent volume compared to average.
    
    Args:
        candles: List of OHLCV candles
        
    Returns:
        Volume trend: "increasing", "decreasing", or "stable"
    """
    if len(candles) < VOLUME_AVERAGE_PERIOD + 1:
        return "stable"
    
    # Calculate average volume (excluding current candle)
    avg_volume = sum(
        c.volume for c in candles[-(VOLUME_AVERAGE_PERIOD + 1):-1]
    ) / VOLUME_AVERAGE_PERIOD
    
    if avg_volume <= 0:
        return "stable"
    
    # Compare recent volume to average
    recent_volume = sum(c.volume for c in candles[-5:]) / 5
    volume_ratio = recent_volume / avg_volume
    
    if volume_ratio > VOLUME_INCREASE_THRESHOLD:
        return "increasing"
    elif volume_ratio < VOLUME_DECREASE_THRESHOLD:
        return "decreasing"
    else:
        return "stable"


def serialize_technical_signal(signal: TechnicalSignal) -> dict:
    """
    Serialize a TechnicalSignal to a dictionary for DynamoDB storage.
    
    Args:
        signal: The TechnicalSignal to serialize
        
    Returns:
        Dictionary representation of the signal
    """
    return {
        "symbol": signal.symbol,
        "trend": signal.trend.value,
        "condition": signal.condition.value,
        "rsi": str(signal.rsi),
        "current_price": str(signal.current_price),
        "support_levels": [
            {
                "level": str(s.level),
                "strength": str(s.strength),
                "timeframe": s.timeframe,
                "last_tested": s.last_tested.isoformat(),
            }
            for s in signal.support_levels
        ],
        "resistance_levels": [
            {
                "level": str(r.level),
                "strength": str(r.strength),
                "timeframe": r.timeframe,
                "last_tested": r.last_tested.isoformat(),
            }
            for r in signal.resistance_levels
        ],
        "confluence": {
            "score": str(signal.confluence.score),
            "factors": signal.confluence.factors,
            "description": signal.confluence.description,
        },
        "volume_trend": signal.volume_trend,
        "interest_rate_impact": str(signal.interest_rate_impact),
        "timestamp": signal.timestamp.isoformat(),
    }


def signal_log_to_dynamodb_item(log: SignalLog) -> dict:
    """
    Convert a SignalLog to a DynamoDB item format.
    
    Args:
        log: The SignalLog to convert
        
    Returns:
        Dictionary formatted for DynamoDB put_item
    """
    item = {
        "signal_id": log.signal_id,
        "agent_type": log.agent_type,
        "symbol": log.symbol,
        "signal_data": json.dumps(log.signal_data),
        "created_at": log.created_at.isoformat(),
        "resulted_in_trade": log.resulted_in_trade,
    }
    
    # Add optional fields if present
    if log.consumed_by:
        item["consumed_by"] = log.consumed_by
    if log.trade_id:
        item["trade_id"] = log.trade_id
    
    return item


class TechnicalSignalGenerator:
    """
    Generator for TechnicalSignal objects.
    
    Combines technical indicators, support/resistance levels, and confluence
    detection to produce comprehensive technical signals.
    
    Requirements:
    - 2.8: Generate TechnicalSignal with all required fields
    - 9.2: Persist signals to DynamoDB
    - 10.3: Optional SageMaker pattern prediction with 10s timeout
    """
    
    def __init__(
        self,
        dynamodb_client: Optional[DynamoDBClient] = None,
        sagemaker_client: Optional[SageMakerClient] = None,
        table_name: str = DEFAULT_SIGNALS_TABLE,
        use_sagemaker: bool = True,
    ):
        """
        Initialize the TechnicalSignalGenerator.
        
        Args:
            dynamodb_client: Optional DynamoDB client for persistence
            sagemaker_client: Optional SageMaker client for ML predictions
            table_name: DynamoDB table name for signals
            use_sagemaker: Whether to use SageMaker for pattern prediction
        """
        self.dynamodb_client = dynamodb_client or DynamoDBClient(table_name)
        self.sagemaker_client = sagemaker_client or SageMakerClient()
        self.use_sagemaker = use_sagemaker
    
    async def generate_signal(
        self,
        symbol: str,
        candles: list[OHLCV],
        interest_rate_impact: float = 0.0,
    ) -> TechnicalSignal:
        """
        Generate a TechnicalSignal from market data.
        
        Requirements:
        - 2.8: Generate TechnicalSignal with all required fields
        - 10.3: Skip ML-based pattern prediction on SageMaker error or >10s latency
        
        Args:
            symbol: Trading symbol
            candles: List of OHLCV candles sorted by timestamp ascending
            interest_rate_impact: Interest rate impact factor (-1.0 to 1.0)
            
        Returns:
            TechnicalSignal with all required fields
            
        Raises:
            ValueError: If insufficient candles for analysis
        """
        if len(candles) < 200:
            raise ValueError(
                f"Need at least 200 candles for signal generation, got: {len(candles)}"
            )
        
        current_price = candles[-1].close
        timestamp = datetime.now(timezone.utc)
        
        # Calculate RSI
        rsi = calculate_rsi(candles, period=14)
        
        # Determine trend direction
        trend = determine_trend_direction(candles)
        
        # Determine market condition
        condition = determine_market_condition(rsi)
        
        # Identify support and resistance levels
        support_levels = identify_support_levels(candles)
        resistance_levels = identify_resistance_levels(candles)
        
        # Detect confluence
        confluence = detect_confluence(
            candles,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
        )
        
        # Determine volume trend
        volume_trend = determine_volume_trend(candles)
        
        # Optional: Get SageMaker pattern prediction
        if self.use_sagemaker:
            pattern_prediction = await self._get_pattern_prediction(candles)
            if pattern_prediction:
                # Enhance confluence with ML prediction if available
                confluence = self._enhance_confluence_with_ml(
                    confluence, pattern_prediction
                )
        
        # Create the TechnicalSignal
        signal = TechnicalSignal(
            symbol=symbol,
            trend=trend,
            condition=condition,
            rsi=rsi,
            current_price=current_price,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            confluence=confluence,
            volume_trend=volume_trend,
            interest_rate_impact=interest_rate_impact,
            timestamp=timestamp,
        )
        
        logger.info(
            f"Generated TechnicalSignal for {symbol}: "
            f"trend={trend.value}, condition={condition.value}, "
            f"rsi={rsi:.2f}, confluence={confluence.score:.2f}"
        )
        
        return signal
    
    async def _get_pattern_prediction(
        self,
        candles: list[OHLCV],
    ) -> Optional[dict]:
        """
        Get pattern prediction from SageMaker with timeout handling.
        
        Requirements:
        - 10.3: Skip ML-based pattern prediction on error or >10s latency
        
        Args:
            candles: List of OHLCV candles
            
        Returns:
            Prediction result or None if failed/timeout
        """
        try:
            return await self.sagemaker_client.predict_pattern(
                candles,
                timeout_seconds=SAGEMAKER_TIMEOUT_SECONDS,
            )
        except Exception as e:
            logger.warning(
                f"SageMaker prediction failed: {e}, "
                "skipping ML-based pattern prediction"
            )
            return None
    
    def _enhance_confluence_with_ml(
        self,
        confluence: ConfluenceResult,
        prediction: dict,
    ) -> ConfluenceResult:
        """
        Enhance confluence result with ML pattern prediction.
        
        Args:
            confluence: Original confluence result
            prediction: SageMaker prediction result
            
        Returns:
            Enhanced ConfluenceResult
        """
        # Extract pattern from prediction
        pattern = prediction.get("pattern")
        confidence = prediction.get("confidence", 0.0)
        
        if pattern and confidence > 0.7:
            # Add ML pattern to factors
            new_factors = confluence.factors.copy()
            new_factors.append(f"ml_pattern_{pattern}")
            
            # Recalculate score (now with 7 factors instead of 6)
            new_score = len(new_factors) / 7
            
            return ConfluenceResult(
                score=min(new_score, 1.0),
                factors=new_factors,
                description=f"{confluence.description} + ML pattern: {pattern}",
            )
        
        return confluence
    
    async def persist_signal(
        self,
        signal: TechnicalSignal,
        signal_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Persist a TechnicalSignal to DynamoDB.
        
        Requirements:
        - 9.2: Persist signals to DynamoDB with signal ID, agent type, symbol,
               payload, timestamp
        
        Args:
            signal: The TechnicalSignal to persist
            signal_id: Optional signal ID (generated if not provided)
            
        Returns:
            The signal_id if successful, None if persistence failed
        """
        # Generate signal ID if not provided
        if signal_id is None:
            signal_id = generate_signal_id()
        
        # Create SignalLog entry
        log = SignalLog(
            signal_id=signal_id,
            agent_type=TECHNICAL_AGENT_TYPE,
            symbol=signal.symbol,
            signal_data=serialize_technical_signal(signal),
            created_at=signal.timestamp,
            consumed_by=None,
            resulted_in_trade=False,
            trade_id=None,
        )
        
        # Convert to DynamoDB item format
        item = signal_log_to_dynamodb_item(log)
        
        # Persist to DynamoDB
        success = await self.dynamodb_client.put_item(item)
        
        if success:
            logger.info(
                f"Persisted TechnicalSignal {signal_id} for {signal.symbol} "
                f"(trend={signal.trend.value}, condition={signal.condition.value})"
            )
            return signal_id
        else:
            logger.error(
                f"Failed to persist TechnicalSignal for {signal.symbol}"
            )
            return None
    
    async def generate_and_persist_signal(
        self,
        symbol: str,
        candles: list[OHLCV],
        interest_rate_impact: float = 0.0,
    ) -> tuple[TechnicalSignal, Optional[str]]:
        """
        Generate a TechnicalSignal and persist it to DynamoDB.
        
        Convenience method that combines signal generation and persistence.
        
        Requirements:
        - 2.8: Generate TechnicalSignal with all required fields
        - 9.2: Persist signals to DynamoDB
        - 10.3: Optional SageMaker pattern prediction with 10s timeout
        
        Args:
            symbol: Trading symbol
            candles: List of OHLCV candles
            interest_rate_impact: Interest rate impact factor
            
        Returns:
            Tuple of (TechnicalSignal, signal_id or None if persistence failed)
        """
        # Generate the signal
        signal = await self.generate_signal(
            symbol=symbol,
            candles=candles,
            interest_rate_impact=interest_rate_impact,
        )
        
        # Persist the signal
        signal_id = await self.persist_signal(signal)
        
        return signal, signal_id

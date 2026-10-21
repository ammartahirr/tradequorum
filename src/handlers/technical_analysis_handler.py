"""
Lambda handler for technical analysis.

Triggered by EventBridge to perform technical analysis on configured symbols.
Generates TechnicalSignals with indicators, support/resistance, and confluence.

Requirements:
- 2.1-2.8: Technical analysis and signal generation
- 9.2: Persist signals to DynamoDB
- 10.2: Mark signals as stale when data >5 min old
- 10.3: Skip ML-based pattern prediction on SageMaker error or >10s latency
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import boto3

from src.agents.technical.signal_generator import TechnicalSignalGenerator
from src.agents.technical.market_data import MarketDataFetcher, is_data_stale
from src.agents.technical.mt5_client import MT5Client

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
TECHNICAL_SIGNALS_TABLE = os.environ.get("TECHNICAL_SIGNALS_TABLE", "technical-signals")
SYMBOLS_PARAM = os.environ.get("SYMBOLS_PARAM", "/trading/symbols")
SAGEMAKER_ENDPOINT = os.environ.get("SAGEMAKER_ENDPOINT", "trading-pattern-model")
USE_SAGEMAKER = os.environ.get("USE_SAGEMAKER", "true").lower() == "true"
MT5_SECRETS_ARN = os.environ.get("MT5_SECRETS_ARN", "")


def get_symbols() -> List[str]:
    """Retrieve list of symbols from SSM Parameter Store."""
    try:
        client = boto3.client("ssm")
        response = client.get_parameter(Name=SYMBOLS_PARAM)
        symbols_str = response["Parameter"]["Value"]
        return [s.strip() for s in symbols_str.split(",") if s.strip()]
    except Exception as e:
        logger.warning(f"Error retrieving symbols from SSM: {e}")
        return ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA"]


def get_mt5_credentials() -> Dict[str, str]:
    """Retrieve MT5 credentials from Secrets Manager."""
    if not MT5_SECRETS_ARN:
        return {}
    
    try:
        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=MT5_SECRETS_ARN)
        return json.loads(response["SecretString"])
    except Exception as e:
        logger.error(f"Error retrieving MT5 credentials: {e}")
        return {}


async def analyze_symbol(
    symbol: str,
    mt5_client: MT5Client,
    signal_generator: TechnicalSignalGenerator,
) -> Dict[str, Any]:
    """
    Perform technical analysis for a single symbol.
    
    Args:
        symbol: Trading symbol
        mt5_client: MT5 client for market data
        signal_generator: Technical signal generator
        
    Returns:
        Analysis result dictionary
    """
    result = {
        "symbol": symbol,
        "success": False,
        "signal_id": None,
        "is_stale": False,
        "error": None,
    }
    
    try:
        # Fetch market data
        candles = await mt5_client.get_candles(
            symbol=symbol,
            timeframe="D1",
            count=500,
        )
        
        if not candles:
            result["error"] = "No candles available"
            return result
        
        # Check for stale data
        last_candle_time = candles[-1].timestamp
        if is_data_stale(last_candle_time):
            result["is_stale"] = True
            logger.warning(f"Stale data detected for {symbol}")
        
        # Generate and persist signal
        signal, signal_id = await signal_generator.generate_and_persist_signal(
            symbol=symbol,
            candles=candles,
        )
        
        result["success"] = True
        result["signal_id"] = signal_id
        result["signal_data"] = {
            "trend": signal.trend.value,
            "condition": signal.condition.value,
            "rsi": signal.rsi,
            "confluence_score": signal.confluence.score,
            "confluence_factors": signal.confluence.factors,
            "volume_trend": signal.volume_trend,
        }
        
        logger.info(
            f"Technical analysis for {symbol}: "
            f"trend={signal.trend.value}, "
            f"rsi={signal.rsi:.2f}, "
            f"confluence={signal.confluence.score:.2f}"
        )
        
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Error analyzing {symbol}: {e}")
    
    return result


async def run_technical_analysis(symbols: List[str]) -> Dict[str, Any]:
    """
    Run technical analysis for all symbols.
    
    Args:
        symbols: List of symbols to analyze
        
    Returns:
        Analysis results
    """
    # Initialize components
    credentials = get_mt5_credentials()
    mt5_client = MT5Client(
        login=credentials.get("login"),
        password=credentials.get("password"),
        server=credentials.get("server"),
    )
    
    signal_generator = TechnicalSignalGenerator(
        table_name=TECHNICAL_SIGNALS_TABLE,
        use_sagemaker=USE_SAGEMAKER,
    )
    
    results = {
        "total": len(symbols),
        "successful": 0,
        "stale": 0,
        "errors": 0,
        "signals": [],
    }
    
    try:
        # Connect to MT5
        await mt5_client.connect()
        
        # Analyze each symbol
        for symbol in symbols:
            result = await analyze_symbol(
                symbol=symbol,
                mt5_client=mt5_client,
                signal_generator=signal_generator,
            )
            
            if result["success"]:
                results["successful"] += 1
                results["signals"].append(result)
            else:
                results["errors"] += 1
            
            if result.get("is_stale"):
                results["stale"] += 1
        
    finally:
        # Disconnect from MT5
        await mt5_client.disconnect()
    
    return results


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for technical analysis.
    
    Triggered by EventBridge scheduled events.
    
    Args:
        event: Event payload
        context: Lambda context
        
    Returns:
        Analysis results
    """
    logger.info(f"Technical analysis handler triggered: {json.dumps(event)[:500]}")
    
    try:
        # Get symbols to analyze
        if "symbols" in event:
            symbols = event["symbols"]
        else:
            symbols = get_symbols()
        
        logger.info(f"Analyzing {len(symbols)} symbols: {symbols}")
        
        # Run async analysis
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            results = loop.run_until_complete(run_technical_analysis(symbols))
        finally:
            loop.close()
        
        logger.info(
            f"Technical analysis complete: "
            f"successful={results['successful']}/{results['total']}, "
            f"stale={results['stale']}, "
            f"errors={results['errors']}"
        )
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Technical analysis completed",
                "results": results,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        }
        
    except Exception as e:
        logger.error(f"Error in technical analysis handler: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        }


# EventBridge rule configuration (for reference)
EVENTBRIDGE_RULE_CONFIG = {
    "Name": "technical-analysis-schedule",
    "Description": "Triggers technical analysis Lambda every 5 minutes during market hours",
    "ScheduleExpression": "rate(5 minutes)",
    "State": "ENABLED",
    "Targets": [
        {
            "Id": "technical-analysis-lambda",
            "Arn": "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:technical-analysis",
        }
    ],
}

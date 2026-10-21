"""
Lambda handler for strategy evaluation.

Triggered by EventBridge or signal events to evaluate trading strategies.
Combines news and technical signals to produce trade decisions.

Requirements:
- 3.1-3.9: Strategy decision making
- 4.1-4.8: Stop-loss and take-profit calculation
- 9.3: Persist decisions to DynamoDB
- 10.2: Halt new trade decisions when market data is stale
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import boto3

from src.agents.strategy.strategy_agent import StrategyAgent
from src.agents.technical.market_data import StaleDataDetector
from src.models import NewsSignal, TechnicalSignal
from src.models.enums import (
    ImpactType, MarketCondition, Sentiment, 
    TradingHorizon, TrendDirection, TradeAction,
)

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
NEWS_SIGNALS_TABLE = os.environ.get("NEWS_SIGNALS_TABLE", "news-signals")
TECHNICAL_SIGNALS_TABLE = os.environ.get("TECHNICAL_SIGNALS_TABLE", "technical-signals")
TRADE_DECISIONS_TABLE = os.environ.get("TRADE_DECISIONS_TABLE", "trade-decisions")
SYMBOLS_PARAM = os.environ.get("SYMBOLS_PARAM", "/trading/symbols")


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


def get_latest_news_signal(symbol: str) -> Optional[Dict]:
    """
    Get the latest news signal for a symbol from DynamoDB.
    
    Args:
        symbol: Trading symbol
        
    Returns:
        News signal dictionary or None
    """
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(NEWS_SIGNALS_TABLE)
        
        # Query for latest signal (assumes GSI on symbol + timestamp)
        response = table.query(
            IndexName="symbol-timestamp-index",
            KeyConditionExpression="symbol = :s",
            ExpressionAttributeValues={":s": symbol},
            ScanIndexForward=False,
            Limit=1,
        )
        
        items = response.get("Items", [])
        return items[0] if items else None
    except Exception as e:
        logger.warning(f"Error getting news signal for {symbol}: {e}")
        return None


def get_latest_technical_signal(symbol: str) -> Optional[Dict]:
    """
    Get the latest technical signal for a symbol from DynamoDB.
    
    Args:
        symbol: Trading symbol
        
    Returns:
        Technical signal dictionary or None
    """
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(TECHNICAL_SIGNALS_TABLE)
        
        response = table.query(
            IndexName="symbol-timestamp-index",
            KeyConditionExpression="symbol = :s",
            ExpressionAttributeValues={":s": symbol},
            ScanIndexForward=False,
            Limit=1,
        )
        
        items = response.get("Items", [])
        return items[0] if items else None
    except Exception as e:
        logger.warning(f"Error getting technical signal for {symbol}: {e}")
        return None


def dict_to_news_signal(data: Dict) -> NewsSignal:
    """Convert DynamoDB item to NewsSignal."""
    signal_data = json.loads(data.get("signal_data", "{}"))
    
    return NewsSignal(
        symbol=data.get("symbol", ""),
        sentiment=Sentiment(signal_data.get("sentiment", "neutral")),
        impact_type=ImpactType(signal_data.get("impact_type", "hype")),
        impact_score=float(signal_data.get("impact_score", 0.5)),
        confidence=float(signal_data.get("confidence", 0.5)),
        reasoning=signal_data.get("reasoning", ""),
        source_items=signal_data.get("source_items", []),
        timestamp=datetime.fromisoformat(data.get("created_at", datetime.now(timezone.utc).isoformat())),
        expires_at=datetime.fromisoformat(signal_data.get("expires_at", (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat())),
    )


def dict_to_technical_signal(data: Dict) -> TechnicalSignal:
    """Convert DynamoDB item to TechnicalSignal."""
    from src.models import ConfluenceResult, SupportResistance
    
    signal_data = json.loads(data.get("signal_data", "{}"))
    
    # Parse support levels
    support_levels = []
    for s in signal_data.get("support_levels", []):
        support_levels.append(SupportResistance(
            level=float(s.get("level", 0)),
            strength=float(s.get("strength", 0.5)),
            timeframe=s.get("timeframe", "1y"),
            last_tested=datetime.fromisoformat(s.get("last_tested", datetime.now(timezone.utc).isoformat())),
        ))
    
    # Parse resistance levels
    resistance_levels = []
    for r in signal_data.get("resistance_levels", []):
        resistance_levels.append(SupportResistance(
            level=float(r.get("level", 0)),
            strength=float(r.get("strength", 0.5)),
            timeframe=r.get("timeframe", "1y"),
            last_tested=datetime.fromisoformat(r.get("last_tested", datetime.now(timezone.utc).isoformat())),
        ))
    
    # Parse confluence
    confluence_data = signal_data.get("confluence", {})
    confluence = ConfluenceResult(
        score=float(confluence_data.get("score", 0)),
        factors=confluence_data.get("factors", []),
        description=confluence_data.get("description", ""),
    )
    
    return TechnicalSignal(
        symbol=data.get("symbol", ""),
        trend=TrendDirection(signal_data.get("trend", "sideways")),
        condition=MarketCondition(signal_data.get("condition", "neutral")),
        rsi=float(signal_data.get("rsi", 50)),
        current_price=float(signal_data.get("current_price", 0)),
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        confluence=confluence,
        volume_trend=signal_data.get("volume_trend", "stable"),
        interest_rate_impact=float(signal_data.get("interest_rate_impact", 0)),
        timestamp=datetime.fromisoformat(data.get("created_at", datetime.now(timezone.utc).isoformat())),
    )


async def evaluate_symbol(
    symbol: str,
    strategy_agent: StrategyAgent,
    horizon: TradingHorizon,
) -> Dict[str, Any]:
    """
    Evaluate strategy for a single symbol.
    
    Args:
        symbol: Trading symbol
        strategy_agent: Strategy agent instance
        horizon: Trading horizon
        
    Returns:
        Evaluation result dictionary
    """
    result = {
        "symbol": symbol,
        "success": False,
        "decision_id": None,
        "action": None,
        "error": None,
    }
    
    try:
        # Get latest signals
        news_data = get_latest_news_signal(symbol)
        technical_data = get_latest_technical_signal(symbol)
        
        if not news_data:
            result["error"] = "No news signal available"
            return result
        
        if not technical_data:
            result["error"] = "No technical signal available"
            return result
        
        # Convert to signal objects
        news_signal = dict_to_news_signal(news_data)
        technical_signal = dict_to_technical_signal(technical_data)
        
        # Evaluate strategy
        eval_result = await strategy_agent.evaluate(
            news_signal=news_signal,
            technical_signal=technical_signal,
            horizon=horizon,
            news_signal_id=news_data.get("signal_id"),
            technical_signal_id=technical_data.get("signal_id"),
        )
        
        result["success"] = eval_result.success
        result["decision_id"] = eval_result.decision_id
        
        if eval_result.decision:
            result["action"] = eval_result.decision.action.value
            result["conviction"] = eval_result.decision.conviction.value
            result["entry_price"] = eval_result.decision.entry_price
            result["stop_loss"] = eval_result.decision.stop_loss
            result["take_profit"] = eval_result.decision.take_profit
            result["risk_reward_ratio"] = eval_result.decision.risk_reward_ratio
        
        if eval_result.error_message:
            result["error"] = eval_result.error_message
        
        logger.info(
            f"Strategy evaluation for {symbol}: "
            f"action={result.get('action', 'N/A')}, "
            f"success={result['success']}"
        )
        
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Error evaluating {symbol}: {e}")
    
    return result


async def run_strategy_evaluation(
    symbols: List[str],
    horizon: TradingHorizon,
) -> Dict[str, Any]:
    """
    Run strategy evaluation for all symbols.
    
    Args:
        symbols: List of symbols to evaluate
        horizon: Trading horizon
        
    Returns:
        Evaluation results
    """
    # Initialize strategy agent with stale data detector
    stale_detector = StaleDataDetector()
    strategy_agent = StrategyAgent()
    strategy_agent.set_stale_data_detector(
        lambda s: stale_detector.is_stale(s)
    )
    
    results = {
        "total": len(symbols),
        "successful": 0,
        "actionable": 0,
        "errors": 0,
        "decisions": [],
    }
    
    for symbol in symbols:
        result = await evaluate_symbol(
            symbol=symbol,
            strategy_agent=strategy_agent,
            horizon=horizon,
        )
        
        if result["success"]:
            results["successful"] += 1
            results["decisions"].append(result)
            
            # Count actionable decisions
            actionable_actions = {
                TradeAction.STRONG_BUY.value, TradeAction.BUY.value,
                TradeAction.STRONG_SELL.value, TradeAction.SELL.value,
            }
            if result.get("action") in actionable_actions:
                results["actionable"] += 1
        else:
            results["errors"] += 1
    
    return results


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for strategy evaluation.
    
    Triggered by EventBridge scheduled events or signal events.
    
    Args:
        event: Event payload
        context: Lambda context
        
    Returns:
        Evaluation results
    """
    logger.info(f"Strategy evaluation handler triggered: {json.dumps(event)[:500]}")
    
    try:
        # Get symbols and horizon
        if "symbols" in event:
            symbols = event["symbols"]
        else:
            symbols = get_symbols()
        
        horizon_str = event.get("horizon", "short_term")
        horizon = TradingHorizon(horizon_str)
        
        logger.info(f"Evaluating {len(symbols)} symbols with {horizon.value} horizon")
        
        # Run async evaluation
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            results = loop.run_until_complete(
                run_strategy_evaluation(symbols, horizon)
            )
        finally:
            loop.close()
        
        logger.info(
            f"Strategy evaluation complete: "
            f"successful={results['successful']}/{results['total']}, "
            f"actionable={results['actionable']}, "
            f"errors={results['errors']}"
        )
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Strategy evaluation completed",
                "results": results,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        }
        
    except Exception as e:
        logger.error(f"Error in strategy evaluation handler: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        }


# EventBridge rule configuration (for reference)
EVENTBRIDGE_RULE_CONFIG = {
    "Name": "strategy-evaluation-schedule",
    "Description": "Triggers strategy evaluation Lambda every 5 minutes",
    "ScheduleExpression": "rate(5 minutes)",
    "State": "ENABLED",
    "Targets": [
        {
            "Id": "strategy-evaluation-lambda",
            "Arn": "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:strategy-evaluation",
        }
    ],
}

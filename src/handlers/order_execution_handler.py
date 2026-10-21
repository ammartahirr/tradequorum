"""
Lambda handler for order execution.

Triggered by strategy evaluation events to execute approved trades.
Performs risk assessment and places orders via MT5 API.

Requirements:
- 5.1-5.8: Risk management validation
- 6.1-6.6: Order execution via MT5
- 7.1-7.4: Position tracking
- 13.1-13.5: Trade record validation
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import boto3

from src.agents.risk.risk_manager import RiskManager, Portfolio
from src.agents.risk.exposure_tracker import OpenPosition
from src.execution.order_executor import OrderExecutor, OrderExecutionError
from src.execution.position_manager import PositionManager
from src.execution.websocket_broadcaster import WebSocketBroadcaster
from src.agents.technical.config import MT5Config
from src.agents.technical.mt5_client import MT5Client
from src.models import TradeDecision
from src.models.enums import (
    Conviction, ImpactType, MarketCondition, Sentiment,
    TradeAction, TradingHorizon, TrendDirection,
)

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
TRADE_DECISIONS_TABLE = os.environ.get("TRADE_DECISIONS_TABLE", "trade-decisions")
TRADE_RECORDS_TABLE = os.environ.get("TRADE_RECORDS_TABLE", "trade-records")
POSITIONS_TABLE = os.environ.get("POSITIONS_TABLE", "positions")
MT5_SECRETS_ARN = os.environ.get("MT5_SECRETS_ARN", "")
WEBSOCKET_ENDPOINT = os.environ.get("WEBSOCKET_ENDPOINT", "")


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


def get_pending_decisions(limit: int = 10) -> List[Dict]:
    """
    Get pending trade decisions from DynamoDB.
    
    Args:
        limit: Maximum number of decisions to retrieve
        
    Returns:
        List of decision dictionaries
    """
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(TRADE_DECISIONS_TABLE)
        
        # Scan for pending actionable decisions
        response = table.scan(
            FilterExpression="execution_status = :s AND #action IN (:a1, :a2, :a3, :a4)",
            ExpressionAttributeNames={"#action": "action"},
            ExpressionAttributeValues={
                ":s": "pending",
                ":a1": "strong_buy",
                ":a2": "buy",
                ":a3": "strong_sell",
                ":a4": "sell",
            },
            Limit=limit,
        )
        
        return response.get("Items", [])
    except Exception as e:
        logger.error(f"Error getting pending decisions: {e}")
        return []


def get_open_positions() -> List[Dict]:
    """Get open positions from DynamoDB."""
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(POSITIONS_TABLE)
        
        response = table.scan(
            FilterExpression="#status = :s",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":s": "open"},
        )
        
        return response.get("Items", [])
    except Exception as e:
        logger.error(f"Error getting open positions: {e}")
        return []


def update_decision_status(
    decision_id: str,
    status: str,
    order_id: Optional[str] = None,
    error: Optional[str] = None,
) -> bool:
    """Update decision execution status in DynamoDB."""
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(TRADE_DECISIONS_TABLE)
        
        update_expr = "SET execution_status = :s, updated_at = :t"
        expr_values = {
            ":s": status,
            ":t": datetime.now(timezone.utc).isoformat(),
        }
        
        if order_id:
            update_expr += ", order_id = :o"
            expr_values[":o"] = order_id
        
        if error:
            update_expr += ", execution_error = :e"
            expr_values[":e"] = error
        
        table.update_item(
            Key={"decision_id": decision_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
        )
        return True
    except Exception as e:
        logger.error(f"Error updating decision status: {e}")
        return False


def dict_to_trade_decision(data: Dict) -> TradeDecision:
    """Convert DynamoDB item to TradeDecision."""
    from src.models import NewsSignal, TechnicalSignal, ConfluenceResult, SupportResistance
    
    # Parse nested signal data
    news_data = json.loads(data.get("news_signal", "{}"))
    tech_data = json.loads(data.get("technical_signal", "{}"))
    
    # Create minimal NewsSignal
    news_signal = NewsSignal(
        symbol=data.get("symbol", ""),
        sentiment=Sentiment(news_data.get("sentiment", "neutral")),
        impact_type=ImpactType(news_data.get("impact_type", "hype")),
        impact_score=float(news_data.get("impact_score", 0.5)),
        confidence=float(news_data.get("confidence", 0.5)),
        reasoning=news_data.get("reasoning", ""),
        source_items=news_data.get("source_items", []),
        timestamp=datetime.fromisoformat(news_data.get("timestamp", datetime.now(timezone.utc).isoformat())),
        expires_at=datetime.fromisoformat(news_data.get("expires_at", (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat())),
    )
    
    # Create minimal TechnicalSignal
    confluence = ConfluenceResult(
        score=float(tech_data.get("confluence_score", 0)),
        factors=tech_data.get("confluence_factors", []),
        description="",
    )
    
    technical_signal = TechnicalSignal(
        symbol=data.get("symbol", ""),
        trend=TrendDirection(tech_data.get("trend", "sideways")),
        condition=MarketCondition(tech_data.get("condition", "neutral")),
        rsi=float(tech_data.get("rsi", 50)),
        current_price=float(data.get("entry_price", 0)),
        support_levels=[],
        resistance_levels=[],
        confluence=confluence,
        volume_trend=tech_data.get("volume_trend", "stable"),
        interest_rate_impact=0.0,
        timestamp=datetime.fromisoformat(tech_data.get("timestamp", datetime.now(timezone.utc).isoformat())),
    )
    
    return TradeDecision(
        symbol=data.get("symbol", ""),
        action=TradeAction(data.get("action", "no_trade")),
        conviction=Conviction(data.get("conviction", "low")),
        horizon=TradingHorizon(data.get("horizon", "short_term")),
        entry_price=float(data.get("entry_price", 0)),
        stop_loss=float(data.get("stop_loss", 0)),
        take_profit=float(data.get("take_profit", 0)),
        position_size_pct=float(data.get("position_size_pct", 0.01)),
        risk_reward_ratio=float(data.get("risk_reward_ratio", 1.5)),
        reasoning=data.get("reasoning", ""),
        news_signal=news_signal,
        technical_signal=technical_signal,
        timestamp=datetime.fromisoformat(data.get("timestamp", datetime.now(timezone.utc).isoformat())),
        expires_at=datetime.fromisoformat(data.get("expires_at", (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat())),
    )


async def execute_decision(
    decision_data: Dict,
    risk_manager: RiskManager,
    order_executor: OrderExecutor,
    position_manager: PositionManager,
    portfolio: Portfolio,
) -> Dict[str, Any]:
    """
    Execute a single trade decision.
    
    Args:
        decision_data: Decision dictionary from DynamoDB
        risk_manager: Risk manager instance
        order_executor: Order executor instance
        position_manager: Position manager instance
        portfolio: Current portfolio state
        
    Returns:
        Execution result dictionary
    """
    decision_id = decision_data.get("decision_id", "unknown")
    result = {
        "decision_id": decision_id,
        "symbol": decision_data.get("symbol", ""),
        "success": False,
        "order_id": None,
        "error": None,
    }
    
    try:
        # Convert to TradeDecision
        decision = dict_to_trade_decision(decision_data)
        
        # Check if decision has expired
        if decision.expires_at < datetime.now(timezone.utc):
            result["error"] = "Decision expired"
            update_decision_status(decision_id, "expired", error=result["error"])
            return result
        
        # Risk assessment
        risk_assessment = risk_manager.assess_trade(decision, portfolio)
        
        if not risk_assessment.approved:
            result["error"] = risk_assessment.rejection_reason
            result["rejected"] = True
            update_decision_status(decision_id, "rejected", error=result["error"])
            logger.warning(
                f"Trade rejected for {decision.symbol}: "
                f"{risk_assessment.rejection_reason}"
            )
            return result
        
        # Determine position size
        size = risk_assessment.adjusted_size or decision.position_size_pct
        
        # Execute order
        order_result = await order_executor.place_order(
            decision=decision,
            size=size,
        )
        
        # Track position
        await position_manager.open_position(
            trade_id=order_result.order_id,
            symbol=decision.symbol,
            entry_price=order_result.filled_price,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            position_size=order_result.filled_quantity,
            action=decision.action,
            exness_order_id=order_result.order_id,
        )
        
        # Update decision status
        update_decision_status(decision_id, "executed", order_id=order_result.order_id)
        
        result["success"] = True
        result["order_id"] = order_result.order_id
        result["filled_price"] = order_result.filled_price
        result["filled_quantity"] = order_result.filled_quantity
        
        logger.info(
            f"Order executed for {decision.symbol}: "
            f"order_id={order_result.order_id}, "
            f"price={order_result.filled_price}"
        )
        
    except OrderExecutionError as e:
        result["error"] = str(e)
        update_decision_status(decision_id, "failed", error=str(e))
        logger.error(f"Order execution failed for {decision_id}: {e}")
        
    except Exception as e:
        result["error"] = str(e)
        update_decision_status(decision_id, "error", error=str(e))
        logger.error(f"Error executing decision {decision_id}: {e}")
    
    return result


async def run_order_execution(decisions: List[Dict]) -> Dict[str, Any]:
    """
    Execute pending trade decisions.
    
    Args:
        decisions: List of decision dictionaries
        
    Returns:
        Execution results
    """
    # Initialize components
    # MT5Client loads {server, login, password} from Secrets Manager itself
    mt5_config = MT5Config(credentials_secret_name=MT5_SECRETS_ARN) if MT5_SECRETS_ARN else None
    mt5_client = MT5Client(config=mt5_config)
    
    websocket_broadcaster = WebSocketBroadcaster()
    position_manager = PositionManager(websocket_broadcaster=websocket_broadcaster)
    risk_manager = RiskManager()
    order_executor = OrderExecutor(
        mt5_client=mt5_client,
        websocket_broadcaster=websocket_broadcaster,
    )
    
    results = {
        "total": len(decisions),
        "executed": 0,
        "rejected": 0,
        "errors": 0,
        "orders": [],
    }
    
    try:
        # Connect to MT5
        await mt5_client.connect()
        
        # Get account info for portfolio
        account_info = await order_executor.get_account_info()
        
        # Get open positions for risk calculation
        open_positions_data = get_open_positions()
        open_positions = [
            OpenPosition(
                symbol=p.get("symbol", ""),
                position_size_pct=float(p.get("position_size_pct", 0)),
                entry_price=float(p.get("entry_price", 0)),
            )
            for p in open_positions_data
        ]
        
        portfolio = Portfolio(
            total_value=account_info.get("equity", 100000.0),
            open_positions=open_positions,
        )
        
        # Execute each decision
        for decision_data in decisions:
            result = await execute_decision(
                decision_data=decision_data,
                risk_manager=risk_manager,
                order_executor=order_executor,
                position_manager=position_manager,
                portfolio=portfolio,
            )
            
            if result["success"]:
                results["executed"] += 1
                results["orders"].append(result)
                
                # Update portfolio for next decision
                portfolio.open_positions.append(
                    OpenPosition(
                        symbol=result["symbol"],
                        position_size_pct=float(decision_data.get("position_size_pct", 0)),
                        entry_price=result.get("filled_price", 0),
                    )
                )
            elif result.get("rejected"):
                results["rejected"] += 1
            else:
                results["errors"] += 1
        
    finally:
        # Disconnect from MT5
        await mt5_client.disconnect()
    
    return results


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for order execution.
    
    Triggered by EventBridge or strategy evaluation events.
    
    Args:
        event: Event payload
        context: Lambda context
        
    Returns:
        Execution results
    """
    logger.info(f"Order execution handler triggered: {json.dumps(event)[:500]}")
    
    try:
        # Get decisions to execute
        if "decisions" in event:
            decisions = event["decisions"]
        else:
            decisions = get_pending_decisions(limit=10)
        
        if not decisions:
            logger.info("No pending decisions to execute")
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": "No decisions to execute",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }),
            }
        
        logger.info(f"Executing {len(decisions)} trade decisions")
        
        # Run async execution
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            results = loop.run_until_complete(run_order_execution(decisions))
        finally:
            loop.close()
        
        logger.info(
            f"Order execution complete: "
            f"executed={results['executed']}/{results['total']}, "
            f"rejected={results['rejected']}, "
            f"errors={results['errors']}"
        )
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Order execution completed",
                "results": results,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        }
        
    except Exception as e:
        logger.error(f"Error in order execution handler: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        }


# EventBridge rule configuration (for reference)
EVENTBRIDGE_RULE_CONFIG = {
    "Name": "order-execution-schedule",
    "Description": "Triggers order execution Lambda every minute during market hours",
    "ScheduleExpression": "rate(1 minute)",
    "State": "ENABLED",
    "Targets": [
        {
            "Id": "order-execution-lambda",
            "Arn": "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:order-execution",
        }
    ],
}

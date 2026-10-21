"""
DynamoDB persistence layer for Strategy Agent decisions.

Implements decision persistence to DynamoDB as required by Requirement 9.3:
- Persist TradeDecision with all decision fields including originating signal IDs

This module provides:
- StrategyPersistence class for DynamoDB operations
- Helper functions for decision serialization
- UUID generation for decision IDs
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from src.models.trading import TradeDecision

logger = logging.getLogger(__name__)

# Agent type constant for strategy decisions
STRATEGY_AGENT_TYPE = "strategy"

# DynamoDB table name (configurable via environment)
DEFAULT_DECISIONS_TABLE = "trading-decisions"


class DynamoDBClient:
    """
    Client for interacting with DynamoDB.
    
    This is an interface that can be implemented with actual boto3 calls
    or mocked for testing.
    """
    
    def __init__(self, table_name: str = DEFAULT_DECISIONS_TABLE):
        """
        Initialize the DynamoDB client.
        
        Args:
            table_name: Name of the DynamoDB table for decisions
        """
        self.table_name = table_name
        self._client = None
    
    def _get_client(self):
        """Get or create the boto3 DynamoDB client."""
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
    
    async def get_item(self, decision_id: str) -> Optional[dict]:
        """
        Get an item from DynamoDB by decision ID.
        
        Args:
            decision_id: The decision ID to retrieve
            
        Returns:
            The item dictionary if found, None otherwise
        """
        try:
            table = self._get_client().Table(self.table_name)
            response = table.get_item(Key={"decision_id": decision_id})
            return response.get("Item")
        except Exception as e:
            logger.error(f"Failed to get item from DynamoDB: {e}")
            return None
    
    async def query_by_symbol(
        self,
        symbol: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        Query decisions by symbol.
        
        Args:
            symbol: Stock symbol to query
            limit: Maximum number of results
            
        Returns:
            List of decision items
        """
        try:
            table = self._get_client().Table(self.table_name)
            response = table.query(
                IndexName="symbol-timestamp-index",
                KeyConditionExpression="symbol = :symbol",
                ExpressionAttributeValues={":symbol": symbol},
                Limit=limit,
                ScanIndexForward=False,  # Most recent first
            )
            return response.get("Items", [])
        except Exception as e:
            logger.error(f"Failed to query decisions from DynamoDB: {e}")
            return []


def generate_decision_id() -> str:
    """
    Generate a unique decision ID.
    
    Returns:
        UUID string for the decision
    """
    return str(uuid.uuid4())


def serialize_trade_decision(
    decision: TradeDecision,
    news_signal_id: str,
    technical_signal_id: str,
) -> dict:
    """
    Serialize a TradeDecision to a dictionary for DynamoDB storage.
    
    Args:
        decision: The TradeDecision to serialize
        news_signal_id: ID of the originating news signal
        technical_signal_id: ID of the originating technical signal
        
    Returns:
        Dictionary representation of the decision
    """
    return {
        "symbol": decision.symbol,
        "action": decision.action.value,
        "conviction": decision.conviction.value,
        "horizon": decision.horizon.value,
        "entry_price": str(decision.entry_price),
        "stop_loss": str(decision.stop_loss),
        "take_profit": str(decision.take_profit),
        "position_size_pct": str(decision.position_size_pct),
        "risk_reward_ratio": str(decision.risk_reward_ratio),
        "reasoning": decision.reasoning,
        "news_signal_id": news_signal_id,
        "technical_signal_id": technical_signal_id,
        "timestamp": decision.timestamp.isoformat(),
        "expires_at": decision.expires_at.isoformat(),
    }


def decision_to_dynamodb_item(
    decision: TradeDecision,
    decision_id: str,
    news_signal_id: str,
    technical_signal_id: str,
) -> dict:
    """
    Convert a TradeDecision to a DynamoDB item format.
    
    Args:
        decision: The TradeDecision to convert
        decision_id: Unique ID for the decision
        news_signal_id: ID of the originating news signal
        technical_signal_id: ID of the originating technical signal
        
    Returns:
        Dictionary formatted for DynamoDB put_item
    """
    serialized = serialize_trade_decision(decision, news_signal_id, technical_signal_id)
    
    return {
        "decision_id": decision_id,
        "agent_type": STRATEGY_AGENT_TYPE,
        "symbol": decision.symbol,
        "decision_data": json.dumps(serialized),
        "action": decision.action.value,
        "conviction": decision.conviction.value,
        "timestamp": decision.timestamp.isoformat(),
        "expires_at": decision.expires_at.isoformat(),
        "news_signal_id": news_signal_id,
        "technical_signal_id": technical_signal_id,
    }


class StrategyPersistence:
    """
    Persistence layer for Strategy Agent decisions.
    
    Handles storing TradeDecisions to DynamoDB with proper formatting
    and error handling.
    
    Requirements:
    - 9.3: Persist TradeDecision with all decision fields including originating signal IDs
    """
    
    def __init__(
        self,
        dynamodb_client: Optional[DynamoDBClient] = None,
        table_name: str = DEFAULT_DECISIONS_TABLE,
    ):
        """
        Initialize the strategy persistence layer.
        
        Args:
            dynamodb_client: Optional DynamoDB client (created if not provided)
            table_name: Name of the DynamoDB table
        """
        self.client = dynamodb_client or DynamoDBClient(table_name)
    
    async def persist_decision(
        self,
        decision: TradeDecision,
        news_signal_id: str,
        technical_signal_id: str,
        decision_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Persist a TradeDecision to DynamoDB.
        
        Creates a decision record and stores it in DynamoDB with:
        - decision_id: Unique identifier for the decision
        - agent_type: "strategy"
        - symbol: Stock symbol from the decision
        - decision_data: Full decision payload as JSON
        - news_signal_id: ID of the originating news signal
        - technical_signal_id: ID of the originating technical signal
        - timestamp: Decision timestamp
        
        Args:
            decision: The TradeDecision to persist
            news_signal_id: ID of the originating news signal
            technical_signal_id: ID of the originating technical signal
            decision_id: Optional decision ID (generated if not provided)
            
        Returns:
            The decision_id if successful, None if persistence failed
            
        Requirements:
        - 9.3: Persist TradeDecision with all decision fields including originating signal IDs
        """
        # Generate decision ID if not provided
        if decision_id is None:
            decision_id = generate_decision_id()
        
        # Convert to DynamoDB item format
        item = decision_to_dynamodb_item(
            decision,
            decision_id,
            news_signal_id,
            technical_signal_id,
        )
        
        # Persist to DynamoDB
        success = await self.client.put_item(item)
        
        if success:
            logger.info(
                f"Persisted TradeDecision {decision_id} for {decision.symbol} "
                f"(action={decision.action.value}, conviction={decision.conviction.value})"
            )
            return decision_id
        else:
            logger.error(
                f"Failed to persist TradeDecision for {decision.symbol}"
            )
            return None
    
    async def get_decision(self, decision_id: str) -> Optional[dict]:
        """
        Retrieve a decision from DynamoDB by ID.
        
        Args:
            decision_id: The decision ID to retrieve
            
        Returns:
            Decision data dictionary if found, None otherwise
        """
        item = await self.client.get_item(decision_id)
        
        if item is None:
            return None
        
        # Parse the decision data
        decision_data = json.loads(item.get("decision_data", "{}"))
        return {
            "decision_id": item["decision_id"],
            "agent_type": item["agent_type"],
            "symbol": item["symbol"],
            "action": item["action"],
            "conviction": item["conviction"],
            "timestamp": item["timestamp"],
            "expires_at": item["expires_at"],
            "news_signal_id": item["news_signal_id"],
            "technical_signal_id": item["technical_signal_id"],
            **decision_data,
        }
    
    async def get_recent_decisions(
        self,
        symbol: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        Get recent decisions for a symbol.
        
        Args:
            symbol: Stock symbol to query
            limit: Maximum number of results
            
        Returns:
            List of decision data dictionaries
        """
        items = await self.client.query_by_symbol(symbol, limit)
        
        decisions = []
        for item in items:
            decision_data = json.loads(item.get("decision_data", "{}"))
            decisions.append({
                "decision_id": item["decision_id"],
                "agent_type": item["agent_type"],
                "symbol": item["symbol"],
                "action": item["action"],
                "conviction": item["conviction"],
                "timestamp": item["timestamp"],
                **decision_data,
            })
        
        return decisions

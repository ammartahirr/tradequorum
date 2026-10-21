"""
DynamoDB persistence layer for News Agent signals.

Implements signal persistence to DynamoDB as required by Requirement 9.1:
- Persist NewsSignal with signal ID, agent type, symbol, full signal payload, and timestamp

This module provides:
- SignalPersistence class for DynamoDB operations
- Helper functions for signal serialization
- UUID generation for signal IDs
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from src.models import NewsSignal, SignalLog

logger = logging.getLogger(__name__)

# Agent type constant for news signals
NEWS_AGENT_TYPE = "news"

# DynamoDB table name (configurable via environment)
DEFAULT_SIGNALS_TABLE = "trading-signals"


class DynamoDBClient:
    """
    Client for interacting with DynamoDB.
    
    This is an interface that can be implemented with actual boto3 calls
    or mocked for testing.
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


def generate_signal_id() -> str:
    """
    Generate a unique signal ID.
    
    Returns:
        UUID string for the signal
    """
    return str(uuid.uuid4())


def serialize_news_signal(signal: NewsSignal) -> dict:
    """
    Serialize a NewsSignal to a dictionary for DynamoDB storage.
    
    Args:
        signal: The NewsSignal to serialize
        
    Returns:
        Dictionary representation of the signal
    """
    return {
        "symbol": signal.symbol,
        "sentiment": signal.sentiment.value,
        "impact_type": signal.impact_type.value,
        "impact_score": str(signal.impact_score),  # DynamoDB prefers strings for decimals
        "confidence": str(signal.confidence),
        "reasoning": signal.reasoning,
        "source_items": signal.source_items,
        "timestamp": signal.timestamp.isoformat(),
        "expires_at": signal.expires_at.isoformat(),
    }


def create_signal_log(
    signal: NewsSignal,
    signal_id: Optional[str] = None,
) -> SignalLog:
    """
    Create a SignalLog entry from a NewsSignal.
    
    Args:
        signal: The NewsSignal to log
        signal_id: Optional signal ID (generated if not provided)
        
    Returns:
        SignalLog entry ready for persistence
    """
    return SignalLog(
        signal_id=signal_id or generate_signal_id(),
        agent_type=NEWS_AGENT_TYPE,
        symbol=signal.symbol,
        signal_data=serialize_news_signal(signal),
        created_at=signal.timestamp,
        consumed_by=None,
        resulted_in_trade=False,
        trade_id=None,
    )


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


class SignalPersistence:
    """
    Persistence layer for News Agent signals.
    
    Handles storing NewsSignals to DynamoDB with proper formatting
    and error handling.
    
    Requirements:
    - 9.1: Persist NewsSignal with signal ID, agent type, symbol, payload, timestamp
    """
    
    def __init__(
        self,
        dynamodb_client: Optional[DynamoDBClient] = None,
        table_name: str = DEFAULT_SIGNALS_TABLE,
    ):
        """
        Initialize the signal persistence layer.
        
        Args:
            dynamodb_client: Optional DynamoDB client (created if not provided)
            table_name: Name of the DynamoDB table
        """
        self.client = dynamodb_client or DynamoDBClient(table_name)
    
    async def persist_news_signal(
        self,
        signal: NewsSignal,
        signal_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Persist a NewsSignal to DynamoDB.
        
        Creates a SignalLog entry and stores it in DynamoDB with:
        - signal_id: Unique identifier for the signal
        - agent_type: "news"
        - symbol: Stock symbol from the signal
        - signal_data: Full signal payload as JSON
        - created_at: Signal timestamp
        
        Args:
            signal: The NewsSignal to persist
            signal_id: Optional signal ID (generated if not provided)
            
        Returns:
            The signal_id if successful, None if persistence failed
            
        Requirements:
        - 9.1: Persist NewsSignal with signal ID, agent type, symbol, payload, timestamp
        """
        # Create the signal log entry
        log = create_signal_log(signal, signal_id)
        
        # Convert to DynamoDB item format
        item = signal_log_to_dynamodb_item(log)
        
        # Persist to DynamoDB
        success = await self.client.put_item(item)
        
        if success:
            logger.info(
                f"Persisted NewsSignal {log.signal_id} for {signal.symbol} "
                f"(impact_type={signal.impact_type.value})"
            )
            return log.signal_id
        else:
            logger.error(
                f"Failed to persist NewsSignal for {signal.symbol}"
            )
            return None
    
    async def get_signal(self, signal_id: str) -> Optional[SignalLog]:
        """
        Retrieve a signal from DynamoDB by ID.
        
        Args:
            signal_id: The signal ID to retrieve
            
        Returns:
            SignalLog if found, None otherwise
        """
        item = await self.client.get_item(signal_id)
        
        if item is None:
            return None
        
        # Parse the item back to SignalLog
        return SignalLog(
            signal_id=item["signal_id"],
            agent_type=item["agent_type"],
            symbol=item["symbol"],
            signal_data=json.loads(item["signal_data"]),
            created_at=datetime.fromisoformat(item["created_at"]),
            consumed_by=item.get("consumed_by"),
            resulted_in_trade=item.get("resulted_in_trade", False),
            trade_id=item.get("trade_id"),
        )
    
    async def mark_signal_consumed(
        self,
        signal_id: str,
        consumed_by: str,
        trade_id: Optional[str] = None,
    ) -> bool:
        """
        Mark a signal as consumed by a downstream agent.
        
        Args:
            signal_id: The signal ID to update
            consumed_by: The agent that consumed the signal
            trade_id: Optional trade ID if signal resulted in a trade
            
        Returns:
            True if successful, False otherwise
            
        Requirements:
        - 9.4: Record whether signal was consumed and resulted in trade
        """
        # Get the existing signal
        existing = await self.get_signal(signal_id)
        if existing is None:
            logger.warning(f"Signal {signal_id} not found for update")
            return False
        
        # Update the fields
        existing.consumed_by = consumed_by
        if trade_id:
            existing.resulted_in_trade = True
            existing.trade_id = trade_id
        
        # Persist the updated signal
        item = signal_log_to_dynamodb_item(existing)
        return await self.client.put_item(item)

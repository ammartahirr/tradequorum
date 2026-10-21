"""
Lambda handler for news processing.

Triggered by EventBridge when new news items are available for analysis.
Processes news through the News Agent and generates NewsSignals.

Requirements:
- 1.3: Classify impact type using Claude Opus 4.5 via AWS Bedrock
- 1.4: Confidence >= 0.7 for CASH_FLOW, else downgrade to HYPE
- 1.5: Generate NewsSignal with all required fields
- 1.6: Set signal expiry based on impact type
- 9.1: Persist signals to DynamoDB
- 10.1: Fall back to rule-based analysis when LLM fails
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import boto3

from src.agents.news.analyzer import ClaudeOpusClient, analyze_news_impact
from src.agents.news.persistence import SignalPersistence
from src.models import NewsItem

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
NEWS_ITEMS_TABLE = os.environ.get("NEWS_ITEMS_TABLE", "news-items")
NEWS_SIGNALS_TABLE = os.environ.get("NEWS_SIGNALS_TABLE", "news-signals")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1")
WEBSOCKET_ENDPOINT = os.environ.get("WEBSOCKET_ENDPOINT", "")


def get_unprocessed_news_items(limit: int = 10) -> List[Dict]:
    """
    Retrieve unprocessed news items from DynamoDB.
    
    Args:
        limit: Maximum number of items to retrieve
        
    Returns:
        List of news item dictionaries
    """
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(NEWS_ITEMS_TABLE)
        
        # Scan for unprocessed items (in production, use GSI)
        response = table.scan(
            FilterExpression="processed = :p",
            ExpressionAttributeValues={":p": False},
            Limit=limit,
        )
        
        return response.get("Items", [])
    except Exception as e:
        logger.error(f"Error retrieving news items: {e}")
        return []


def mark_item_processed(item_id: str) -> bool:
    """
    Mark a news item as processed in DynamoDB.
    
    Args:
        item_id: The news item ID
        
    Returns:
        True if successful
    """
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(NEWS_ITEMS_TABLE)
        
        table.update_item(
            Key={"item_id": item_id},
            UpdateExpression="SET processed = :p, processed_at = :t",
            ExpressionAttributeValues={
                ":p": True,
                ":t": datetime.now(timezone.utc).isoformat(),
            },
        )
        return True
    except Exception as e:
        logger.error(f"Error marking item processed: {e}")
        return False


def dict_to_news_item(item_dict: Dict) -> NewsItem:
    """Convert DynamoDB item to NewsItem."""
    return NewsItem(
        source=item_dict.get("source", "unknown"),
        headline=item_dict.get("headline", ""),
        content=item_dict.get("content", ""),
        published_at=datetime.fromisoformat(
            item_dict.get("published_at", datetime.now(timezone.utc).isoformat())
        ),
        symbols=item_dict.get("symbols", []),
        url=item_dict.get("url"),
    )


async def process_news_items(items: List[Dict]) -> Dict[str, Any]:
    """
    Process a batch of news items through the News Agent.
    
    Args:
        items: List of news item dictionaries
        
    Returns:
        Processing results
    """
    # Initialize components
    llm_client = ClaudeOpusClient(region_name=BEDROCK_REGION)
    persistence = SignalPersistence(table_name=NEWS_SIGNALS_TABLE)
    
    results = {
        "processed": 0,
        "signals_generated": 0,
        "errors": 0,
        "signals": [],
    }
    
    for item_dict in items:
        item_id = item_dict.get("item_id", "unknown")
        
        try:
            # Convert to NewsItem
            news_item = dict_to_news_item(item_dict)
            
            # Analyze news impact
            signal = await analyze_news_impact(
                news_item=news_item,
                llm_client=llm_client,
                item_id=item_id,
            )
            
            # Persist signal
            signal_id = await persistence.persist_news_signal(signal)
            
            if signal_id:
                results["signals_generated"] += 1
                results["signals"].append({
                    "signal_id": signal_id,
                    "symbol": signal.symbol,
                    "sentiment": signal.sentiment.value,
                    "impact_type": signal.impact_type.value,
                    "confidence": signal.confidence,
                })
            
            # Mark item as processed
            mark_item_processed(item_id)
            results["processed"] += 1
            
            logger.info(
                f"Processed news item {item_id}: "
                f"symbol={signal.symbol}, "
                f"sentiment={signal.sentiment.value}"
            )
            
        except Exception as e:
            logger.error(f"Error processing news item {item_id}: {e}")
            results["errors"] += 1
    
    return results


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for news processing.
    
    Can be triggered by:
    - EventBridge scheduled events (batch processing)
    - DynamoDB Streams (real-time processing)
    - Direct invocation with news items
    
    Args:
        event: Event payload
        context: Lambda context
        
    Returns:
        Processing results
    """
    logger.info(f"News processing handler triggered: {json.dumps(event)[:500]}")
    
    try:
        # Determine event source and get items
        items = []
        
        if "Records" in event:
            # DynamoDB Stream event
            for record in event["Records"]:
                if record.get("eventName") == "INSERT":
                    new_image = record.get("dynamodb", {}).get("NewImage", {})
                    # Convert DynamoDB format to regular dict
                    item = {
                        k: list(v.values())[0] 
                        for k, v in new_image.items()
                    }
                    items.append(item)
        elif "items" in event:
            # Direct invocation with items
            items = event["items"]
        else:
            # Scheduled event - fetch unprocessed items
            items = get_unprocessed_news_items(limit=20)
        
        if not items:
            logger.info("No news items to process")
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": "No items to process",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }),
            }
        
        logger.info(f"Processing {len(items)} news items")
        
        # Run async processing
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            results = loop.run_until_complete(process_news_items(items))
        finally:
            loop.close()
        
        logger.info(
            f"News processing complete: "
            f"processed={results['processed']}, "
            f"signals={results['signals_generated']}, "
            f"errors={results['errors']}"
        )
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "News processing completed",
                "results": results,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        }
        
    except Exception as e:
        logger.error(f"Error in news processing handler: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        }

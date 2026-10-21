"""
Lambda handler for news scraping.

This handler is triggered by EventBridge scheduled events to periodically
scrape news from configured sources.

Requirements: 1.1 - Scrape news from configured sources within scheduled interval
Requirements: 1.2 - Deduplicate news items referencing the same event
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3

from src.agents.news import (
    BloombergScraper,
    NewsDeduplicator,
    NewsScraperManager,
    ReutersScraper,
    SECEdgarScraper,
    TwitterScraper,
)
from src.models import NewsItem

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
SECRETS_ARN = os.environ.get("SECRETS_ARN", "")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "news-items")
SYMBOLS_PARAM = os.environ.get("SYMBOLS_PARAM", "/trading/symbols")


def get_secrets() -> dict[str, str]:
    """Retrieve API keys from AWS Secrets Manager."""
    if not SECRETS_ARN:
        logger.warning("SECRETS_ARN not configured, using empty credentials")
        return {}
    
    try:
        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=SECRETS_ARN)
        return json.loads(response["SecretString"])
    except Exception as e:
        logger.error(f"Error retrieving secrets: {e}")
        return {}


def get_symbols() -> list[str]:
    """Retrieve list of symbols to scrape from SSM Parameter Store."""
    try:
        client = boto3.client("ssm")
        response = client.get_parameter(Name=SYMBOLS_PARAM)
        symbols_str = response["Parameter"]["Value"]
        return [s.strip() for s in symbols_str.split(",") if s.strip()]
    except Exception as e:
        logger.warning(f"Error retrieving symbols from SSM: {e}")
        # Default symbols for testing
        return ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA"]


def store_news_items(items: list[NewsItem]) -> int:
    """
    Store news items in DynamoDB.
    
    Args:
        items: List of NewsItem objects to store
        
    Returns:
        Number of items successfully stored
    """
    if not items:
        return 0
    
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(DYNAMODB_TABLE)
        
        stored_count = 0
        with table.batch_writer() as batch:
            for item in items:
                try:
                    # Generate a unique ID for the item
                    item_id = f"{item.source}:{item.published_at.isoformat()}:{hash(item.headline)}"
                    
                    batch.put_item(
                        Item={
                            "item_id": item_id,
                            "source": item.source,
                            "headline": item.headline,
                            "content": item.content,
                            "published_at": item.published_at.isoformat(),
                            "symbols": item.symbols,
                            "url": item.url or "",
                            "scraped_at": datetime.now(timezone.utc).isoformat(),
                            "processed": False,
                        }
                    )
                    stored_count += 1
                except Exception as e:
                    logger.error(f"Error storing item: {e}")
        
        return stored_count
    except Exception as e:
        logger.error(f"Error connecting to DynamoDB: {e}")
        return 0


async def scrape_news(symbols: list[str], secrets: dict[str, str]) -> list[NewsItem]:
    """
    Scrape news from all configured sources.
    
    Args:
        symbols: List of stock symbols to scrape
        secrets: Dictionary of API credentials
        
    Returns:
        List of scraped NewsItem objects
    """
    # Initialize scrapers with credentials
    scrapers = [
        ReutersScraper(api_key=secrets.get("reuters_api_key")),
        BloombergScraper(api_key=secrets.get("bloomberg_api_key")),
        SECEdgarScraper(),  # SEC EDGAR doesn't require auth
        TwitterScraper(bearer_token=secrets.get("twitter_bearer_token")),
    ]
    
    manager = NewsScraperManager(scrapers)
    
    try:
        # Scrape from all sources
        all_items = await manager.scrape_all(symbols)
        
        # Deduplicate items
        deduplicator = NewsDeduplicator()
        deduplicated_items = deduplicator.deduplicate(all_items)
        
        return deduplicated_items
    finally:
        await manager.close_all()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for news scraping.
    
    Triggered by EventBridge scheduled events.
    
    Args:
        event: EventBridge event payload
        context: Lambda context
        
    Returns:
        Response with scraping results
    """
    import asyncio
    
    logger.info(f"News scraper triggered: {json.dumps(event)}")
    
    try:
        # Get configuration
        secrets = get_secrets()
        symbols = get_symbols()
        
        logger.info(f"Scraping news for {len(symbols)} symbols")
        
        # Run async scraping
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            items = loop.run_until_complete(scrape_news(symbols, secrets))
        finally:
            loop.close()
        
        logger.info(f"Scraped {len(items)} unique news items")
        
        # Store items in DynamoDB
        stored_count = store_news_items(items)
        
        logger.info(f"Stored {stored_count} items in DynamoDB")
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "News scraping completed",
                "symbols_processed": len(symbols),
                "items_scraped": len(items),
                "items_stored": stored_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        }
    except Exception as e:
        logger.error(f"Error in news scraper: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        }


# EventBridge rule configuration (for reference)
EVENTBRIDGE_RULE_CONFIG = {
    "Name": "news-scraper-schedule",
    "Description": "Triggers news scraping Lambda every 15 minutes",
    "ScheduleExpression": "rate(15 minutes)",
    "State": "ENABLED",
    "Targets": [
        {
            "Id": "news-scraper-lambda",
            "Arn": "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:news-scraper",
        }
    ],
}

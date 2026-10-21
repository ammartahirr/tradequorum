"""
Configuration for the News Agent scrapers and EventBridge triggers.

This module defines the configuration for:
- Scraper settings (timeouts, rate limits)
- EventBridge scheduled triggers
- Source-specific configurations
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ScraperConfig:
    """Configuration for a news scraper."""
    
    enabled: bool = True
    timeout_seconds: int = 30
    max_items_per_symbol: int = 50
    rate_limit_requests_per_minute: int = 60
    retry_attempts: int = 3
    retry_delay_seconds: int = 1


@dataclass
class ReutersConfig(ScraperConfig):
    """Reuters-specific configuration."""
    
    base_url: str = "https://api.reuters.com/v1"
    api_key_secret_name: str = "reuters_api_key"


@dataclass
class BloombergConfig(ScraperConfig):
    """Bloomberg-specific configuration."""
    
    base_url: str = "https://api.bloomberg.com/v1"
    api_key_secret_name: str = "bloomberg_api_key"


@dataclass
class SECEdgarConfig(ScraperConfig):
    """SEC EDGAR-specific configuration."""
    
    base_url: str = "https://data.sec.gov"
    user_agent: str = "AI-Trading-System contact@example.com"
    # SEC EDGAR rate limit: 10 requests per second
    rate_limit_requests_per_minute: int = 600
    # Filing types to include
    filing_types: list[str] = field(
        default_factory=lambda: ["10-K", "10-Q", "8-K", "6-K", "4", "SC 13D", "SC 13G"]
    )


@dataclass
class TwitterConfig(ScraperConfig):
    """Twitter/X-specific configuration."""
    
    base_url: str = "https://api.twitter.com/2"
    bearer_token_secret_name: str = "twitter_bearer_token"
    # Twitter API rate limits are strict
    rate_limit_requests_per_minute: int = 15
    # Minimum engagement for tweets to be included
    min_engagement: int = 5


@dataclass
class DeduplicationConfig:
    """Configuration for news deduplication."""
    
    headline_similarity_threshold: float = 0.75
    content_similarity_threshold: float = 0.60
    time_window_hours: int = 24


@dataclass
class EventBridgeConfig:
    """Configuration for EventBridge scheduled triggers."""
    
    # Schedule expression for the scraping trigger
    # Default: every 15 minutes
    schedule_expression: str = "rate(15 minutes)"
    
    # Rule name
    rule_name: str = "news-scraper-schedule"
    
    # Rule description
    description: str = "Triggers news scraping Lambda periodically"
    
    # Whether the rule is enabled
    enabled: bool = True


@dataclass
class NewsAgentConfig:
    """Complete configuration for the News Agent."""
    
    # Scraper configurations
    reuters: ReutersConfig = field(default_factory=ReutersConfig)
    bloomberg: BloombergConfig = field(default_factory=BloombergConfig)
    sec_edgar: SECEdgarConfig = field(default_factory=SECEdgarConfig)
    twitter: TwitterConfig = field(default_factory=TwitterConfig)
    
    # Deduplication configuration
    deduplication: DeduplicationConfig = field(default_factory=DeduplicationConfig)
    
    # EventBridge configuration
    eventbridge: EventBridgeConfig = field(default_factory=EventBridgeConfig)
    
    # DynamoDB table for storing news items
    dynamodb_table: str = "news-items"
    
    # SSM parameter for symbols list
    symbols_parameter: str = "/trading/symbols"
    
    # Secrets Manager ARN for API credentials
    secrets_arn: Optional[str] = None


# Default configuration instance
DEFAULT_CONFIG = NewsAgentConfig()


def get_eventbridge_rule_definition(config: NewsAgentConfig) -> dict:
    """
    Generate EventBridge rule definition for CloudFormation/CDK.
    
    Args:
        config: NewsAgentConfig instance
        
    Returns:
        Dictionary with EventBridge rule definition
    """
    return {
        "Type": "AWS::Events::Rule",
        "Properties": {
            "Name": config.eventbridge.rule_name,
            "Description": config.eventbridge.description,
            "ScheduleExpression": config.eventbridge.schedule_expression,
            "State": "ENABLED" if config.eventbridge.enabled else "DISABLED",
            "Targets": [
                {
                    "Id": "news-scraper-lambda-target",
                    "Arn": {"Fn::GetAtt": ["NewsScraperFunction", "Arn"]},
                }
            ],
        },
    }


def get_lambda_permission_definition(config: NewsAgentConfig) -> dict:
    """
    Generate Lambda permission for EventBridge invocation.
    
    Args:
        config: NewsAgentConfig instance
        
    Returns:
        Dictionary with Lambda permission definition
    """
    return {
        "Type": "AWS::Lambda::Permission",
        "Properties": {
            "FunctionName": {"Ref": "NewsScraperFunction"},
            "Action": "lambda:InvokeFunction",
            "Principal": "events.amazonaws.com",
            "SourceArn": {"Fn::GetAtt": ["NewsScraperScheduleRule", "Arn"]},
        },
    }

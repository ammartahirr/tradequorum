"""
News Agent module for the AI Trading System.

The News Agent ("The Ear") is responsible for:
- Scraping news from multiple sources (Reuters, Bloomberg, SEC EDGAR, Twitter/X)
- Deduplicating news items referencing the same event
- Analyzing news impact using Claude Opus 4.5 via AWS Bedrock
- Generating NewsSignals with sentiment and impact classification
"""

from .scrapers import (
    BaseScraper,
    BloombergScraper,
    ReutersScraper,
    SECEdgarScraper,
    TwitterScraper,
    NewsScraperManager,
)
from .deduplication import NewsDeduplicator, deduplicate_news_items
from .config import (
    NewsAgentConfig,
    ScraperConfig,
    ReutersConfig,
    BloombergConfig,
    SECEdgarConfig,
    TwitterConfig,
    DeduplicationConfig,
    EventBridgeConfig,
    DEFAULT_CONFIG,
)
from .analyzer import (
    analyze_news_impact,
    analyze_news_batch,
    analyze_and_persist_news_signal,
    analyze_and_persist_news_batch,
    analyze_keywords,
    build_analysis_prompt,
    parse_llm_response,
    BedrockClaudeClient,
    ClaudeOpusClient,  # Alias for backward compatibility
    LLMError,
    LLMAnalysisResult,
    CASH_FLOW_CONFIDENCE_THRESHOLD,
    FALLBACK_CONFIDENCE_MULTIPLIER,
    EXPIRY_HOURS,
    BEDROCK_MODEL_ID,
)
from .persistence import (
    SignalPersistence,
    DynamoDBClient,
    generate_signal_id,
    serialize_news_signal,
    create_signal_log,
    signal_log_to_dynamodb_item,
    NEWS_AGENT_TYPE,
    DEFAULT_SIGNALS_TABLE,
)

__all__ = [
    # Scrapers
    "BaseScraper",
    "BloombergScraper",
    "ReutersScraper",
    "SECEdgarScraper",
    "TwitterScraper",
    "NewsScraperManager",
    # Deduplication
    "NewsDeduplicator",
    "deduplicate_news_items",
    # Configuration
    "NewsAgentConfig",
    "ScraperConfig",
    "ReutersConfig",
    "BloombergConfig",
    "SECEdgarConfig",
    "TwitterConfig",
    "DeduplicationConfig",
    "EventBridgeConfig",
    "DEFAULT_CONFIG",
    # Analyzer (AWS Bedrock Claude Opus 4.5 integration)
    "analyze_news_impact",
    "analyze_news_batch",
    "analyze_and_persist_news_signal",
    "analyze_and_persist_news_batch",
    "analyze_keywords",
    "build_analysis_prompt",
    "parse_llm_response",
    "BedrockClaudeClient",
    "ClaudeOpusClient",  # Alias for backward compatibility
    "LLMError",
    "LLMAnalysisResult",
    "CASH_FLOW_CONFIDENCE_THRESHOLD",
    "FALLBACK_CONFIDENCE_MULTIPLIER",
    "EXPIRY_HOURS",
    "BEDROCK_MODEL_ID",
    # Persistence (DynamoDB)
    "SignalPersistence",
    "DynamoDBClient",
    "generate_signal_id",
    "serialize_news_signal",
    "create_signal_log",
    "signal_log_to_dynamodb_item",
    "NEWS_AGENT_TYPE",
    "DEFAULT_SIGNALS_TABLE",
]

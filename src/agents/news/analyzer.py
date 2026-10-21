"""
AWS Bedrock Claude Opus 4.5 integration for news impact analysis.

Implements the analyze_news_impact() function that uses Claude Opus 4.5 via AWS Bedrock
to classify news impact type and sentiment, with fallback to rule-based keyword analysis.

Requirements:
- 1.3: Classify impact type as CASH_FLOW, HYPE, REGULATORY, or MACRO using Claude Opus 4.5 via AWS Bedrock
- 1.4: Assign confidence >= 0.7 for CASH_FLOW; downgrade to HYPE if below 0.7
- 1.5: Produce NewsSignal with all required fields
- 1.6: Set signal expiry based on impact type
- 9.1: Persist signals to DynamoDB with signal ID, agent type, symbol, payload, timestamp
- 10.1: Fall back to rule-based keyword sentiment analysis when LLM fails
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.models import NewsItem, NewsSignal
from src.models.enums import ImpactType, Sentiment

logger = logging.getLogger(__name__)


# AWS Bedrock model ID for Claude Opus 4.5
BEDROCK_MODEL_ID = "anthropic.claude-opus-4-5-20250514"

# Expiry hours by impact type (Requirement 1.6)
EXPIRY_HOURS = {
    ImpactType.CASH_FLOW: 72,    # Cash flow news stays relevant longer
    ImpactType.REGULATORY: 168,  # Regulatory news: 1 week
    ImpactType.HYPE: 24,         # Hype fades quickly
    ImpactType.MACRO: 24,        # Macro news: 24 hours
}

# Confidence threshold for CASH_FLOW classification (Requirement 1.4)
CASH_FLOW_CONFIDENCE_THRESHOLD = 0.7

# Confidence multiplier for fallback mode (Requirement 10.1)
FALLBACK_CONFIDENCE_MULTIPLIER = 0.5


@dataclass
class LLMAnalysisResult:
    """Result from LLM analysis."""
    sentiment: Sentiment
    impact_type: ImpactType
    impact_score: float
    confidence: float
    reasoning: str


class BedrockClaudeClient:
    """
    Client for interacting with Claude Opus 4.5 via AWS Bedrock.
    
    Uses boto3 bedrock-runtime client to invoke the Claude model.
    No API keys needed - uses IAM roles for authentication.
    """
    
    def __init__(self, region_name: str = "us-east-1", timeout: int = 10):
        """
        Initialize the AWS Bedrock Claude client.
        
        Args:
            region_name: AWS region for Bedrock (default us-east-1)
            timeout: Request timeout in seconds (default 10s per Requirement 12.3)
        """
        self.region_name = region_name
        self.timeout = timeout
        self._client = None
    
    def _get_client(self):
        """Lazy initialization of boto3 bedrock-runtime client."""
        if self._client is None:
            try:
                import boto3
                self._client = boto3.client(
                    'bedrock-runtime',
                    region_name=self.region_name
                )
            except Exception as e:
                raise LLMError(f"Failed to initialize Bedrock client: {e}")
        return self._client
    
    async def analyze(self, prompt: str, system: str) -> str:
        """
        Send a prompt to Claude Opus 4.5 via AWS Bedrock for analysis.
        
        Args:
            prompt: The analysis prompt
            system: System prompt for context
            
        Returns:
            LLM response text
            
        Raises:
            LLMError: If the API call fails or times out
        """
        try:
            client = self._get_client()
            
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "system": system,
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            })
            
            response = client.invoke_model(
                modelId=BEDROCK_MODEL_ID,
                body=body,
                contentType="application/json",
                accept="application/json"
            )
            
            response_body = json.loads(response['body'].read())
            return response_body['content'][0]['text']
            
        except Exception as e:
            raise LLMError(f"AWS Bedrock Claude Opus 4.5 API call failed: {e}")


# Alias for backward compatibility
ClaudeOpusClient = BedrockClaudeClient


class LLMError(Exception):
    """Exception raised when LLM API fails."""
    pass


def build_analysis_prompt(
    headline: str,
    content: str,
    symbols: list[str],
    source: str,
) -> str:
    """
    Build the analysis prompt for Claude Opus.
    
    Args:
        headline: News headline
        content: News content/body
        symbols: Affected stock symbols
        source: News source (reuters, twitter, etc.)
        
    Returns:
        Formatted prompt string
    """
    return f"""Analyze the following news article and determine its impact on the stock(s) mentioned.

Source: {source}
Symbols: {', '.join(symbols)}
Headline: {headline}

Content:
{content[:2000]}  # Limit content to avoid token limits

Please analyze this news and provide:
1. SENTIMENT: How does this news affect the stock? (very_bullish, bullish, neutral, bearish, very_bearish)
2. IMPACT_TYPE: What type of impact does this have?
   - cash_flow: Direct impact on company's revenue, earnings, or cash flow (e.g., earnings reports, major contracts, acquisitions)
   - hype: Market sentiment/speculation without direct financial impact (e.g., social media buzz, analyst opinions)
   - regulatory: Legal or regulatory impact (e.g., lawsuits, FDA approvals, government investigations)
   - macro: Macroeconomic impact (e.g., interest rates, economic indicators, sector-wide news)
3. IMPACT_SCORE: How significant is this impact? (0.0 to 1.0, where 1.0 is extremely significant)
4. CONFIDENCE: How confident are you in this classification? (0.0 to 1.0)
5. REASONING: Brief explanation of your analysis

Respond in JSON format:
{{
    "sentiment": "...",
    "impact_type": "...",
    "impact_score": 0.0,
    "confidence": 0.0,
    "reasoning": "..."
}}"""


def parse_llm_response(response: str) -> LLMAnalysisResult:
    """
    Parse the LLM response into a structured result.
    
    Args:
        response: Raw LLM response text
        
    Returns:
        LLMAnalysisResult with parsed values
        
    Raises:
        ValueError: If response cannot be parsed
    """
    # Try to extract JSON from the response
    json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
    if not json_match:
        raise ValueError("No JSON found in LLM response")
    
    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in LLM response: {e}")
    
    # Parse sentiment
    sentiment_str = data.get("sentiment", "neutral").lower()
    sentiment_map = {
        "very_bullish": Sentiment.VERY_BULLISH,
        "bullish": Sentiment.BULLISH,
        "neutral": Sentiment.NEUTRAL,
        "bearish": Sentiment.BEARISH,
        "very_bearish": Sentiment.VERY_BEARISH,
    }
    sentiment = sentiment_map.get(sentiment_str, Sentiment.NEUTRAL)
    
    # Parse impact type
    impact_str = data.get("impact_type", "hype").lower()
    impact_map = {
        "cash_flow": ImpactType.CASH_FLOW,
        "hype": ImpactType.HYPE,
        "regulatory": ImpactType.REGULATORY,
        "macro": ImpactType.MACRO,
    }
    impact_type = impact_map.get(impact_str, ImpactType.HYPE)
    
    # Parse scores with bounds checking
    impact_score = max(0.0, min(1.0, float(data.get("impact_score", 0.5))))
    confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    
    reasoning = data.get("reasoning", "No reasoning provided")
    
    return LLMAnalysisResult(
        sentiment=sentiment,
        impact_type=impact_type,
        impact_score=impact_score,
        confidence=confidence,
        reasoning=reasoning,
    )


# Keywords for rule-based fallback analysis
BULLISH_KEYWORDS = [
    "beat", "beats", "exceeded", "exceeds", "surpass", "surpassed",
    "growth", "growing", "profit", "profitable", "revenue increase",
    "strong earnings", "record", "upgrade", "upgraded", "buy rating",
    "outperform", "positive", "bullish", "rally", "surge", "soar",
    "breakthrough", "innovation", "partnership", "acquisition",
    "dividend increase", "buyback", "share repurchase",
]

BEARISH_KEYWORDS = [
    "miss", "missed", "below", "decline", "declining", "loss",
    "losses", "weak", "weakness", "downgrade", "downgraded",
    "sell rating", "underperform", "negative", "bearish", "drop",
    "plunge", "crash", "layoff", "layoffs", "restructuring",
    "bankruptcy", "default", "investigation", "lawsuit", "recall",
    "warning", "guidance cut", "revenue decline",
]

CASH_FLOW_KEYWORDS = [
    "earnings", "revenue", "profit", "loss", "eps", "guidance",
    "forecast", "quarterly results", "annual results", "financial",
    "cash flow", "margin", "dividend", "buyback", "acquisition",
    "merger", "contract", "deal", "sales", "income", "ebitda",
]

REGULATORY_KEYWORDS = [
    "fda", "sec", "ftc", "doj", "regulation", "regulatory",
    "approval", "approved", "rejected", "lawsuit", "legal",
    "investigation", "subpoena", "fine", "penalty", "compliance",
    "antitrust", "patent", "court", "ruling", "settlement",
]

MACRO_KEYWORDS = [
    "fed", "federal reserve", "interest rate", "inflation",
    "gdp", "unemployment", "economic", "economy", "recession",
    "stimulus", "tariff", "trade war", "oil price", "commodity",
    "sector", "industry", "market", "index",
]


def analyze_keywords(text: str) -> tuple[Sentiment, ImpactType, float, float]:
    """
    Perform rule-based keyword sentiment analysis.
    
    This is the fallback when Claude Opus is unavailable (Requirement 10.1).
    
    Args:
        text: Combined headline and content text
        
    Returns:
        Tuple of (sentiment, impact_type, impact_score, confidence)
    """
    text_lower = text.lower()
    
    # Count keyword matches
    bullish_count = sum(1 for kw in BULLISH_KEYWORDS if kw in text_lower)
    bearish_count = sum(1 for kw in BEARISH_KEYWORDS if kw in text_lower)
    cash_flow_count = sum(1 for kw in CASH_FLOW_KEYWORDS if kw in text_lower)
    regulatory_count = sum(1 for kw in REGULATORY_KEYWORDS if kw in text_lower)
    macro_count = sum(1 for kw in MACRO_KEYWORDS if kw in text_lower)
    
    # Determine sentiment
    sentiment_diff = bullish_count - bearish_count
    if sentiment_diff >= 3:
        sentiment = Sentiment.VERY_BULLISH
    elif sentiment_diff >= 1:
        sentiment = Sentiment.BULLISH
    elif sentiment_diff <= -3:
        sentiment = Sentiment.VERY_BEARISH
    elif sentiment_diff <= -1:
        sentiment = Sentiment.BEARISH
    else:
        sentiment = Sentiment.NEUTRAL
    
    # Determine impact type based on keyword counts
    impact_counts = {
        ImpactType.CASH_FLOW: cash_flow_count,
        ImpactType.REGULATORY: regulatory_count,
        ImpactType.MACRO: macro_count,
        ImpactType.HYPE: 0,  # Default if no specific keywords
    }
    
    # Find the impact type with most matches
    max_count = max(impact_counts.values())
    if max_count > 0:
        impact_type = max(impact_counts, key=impact_counts.get)
    else:
        impact_type = ImpactType.HYPE
    
    # Calculate impact score based on total keyword matches
    total_matches = bullish_count + bearish_count + cash_flow_count + regulatory_count + macro_count
    impact_score = min(1.0, total_matches / 10.0)  # Normalize to 0-1
    
    # Confidence is lower for keyword-based analysis
    # Base confidence on number of matches
    confidence = min(0.8, 0.3 + (total_matches * 0.05))
    
    return sentiment, impact_type, impact_score, confidence


async def analyze_news_impact(
    news_item: NewsItem,
    llm_client: Optional[ClaudeOpusClient] = None,
    item_id: Optional[str] = None,
) -> NewsSignal:
    """
    Analyze news impact using Claude Opus with fallback to rule-based analysis.
    
    Uses Claude Opus to determine if news has genuine cash-flow impact on stocks
    or is merely market hype. Falls back to keyword-based analysis if LLM fails.
    
    Preconditions:
        - news_item.content is non-empty
        - news_item.symbols contains at least one valid stock symbol
        - Claude Opus API is available (or fallback will be used)
    
    Postconditions:
        - Returns NewsSignal with impact_score in [0.0, 1.0]
        - Returns NewsSignal with confidence in [0.0, 1.0]
        - impact_type is CASH_FLOW only if confidence >= 0.7 (Requirement 1.4)
        - reasoning contains explanation for the classification
    
    Requirements:
        - 1.3: Classify impact type using Claude Opus
        - 1.4: Confidence >= 0.7 for CASH_FLOW, else downgrade to HYPE
        - 10.1: Fall back to rule-based analysis when LLM fails
    
    Args:
        news_item: The news item to analyze
        llm_client: Optional Claude Opus client (uses fallback if None)
        item_id: Optional ID for the news item (for source_items field)
        
    Returns:
        NewsSignal with sentiment, impact classification, and reasoning
    """
    symbol = news_item.symbols[0] if news_item.symbols else "UNKNOWN"
    source_item_id = item_id or f"{news_item.source}:{hash(news_item.headline)}"
    
    # Track if we're using fallback mode
    using_fallback = False
    
    # Try LLM analysis first
    if llm_client is not None:
        try:
            # Build the analysis prompt
            prompt = build_analysis_prompt(
                headline=news_item.headline,
                content=news_item.content,
                symbols=news_item.symbols,
                source=news_item.source,
            )
            
            # Query Claude Opus for impact analysis
            system_prompt = (
                "You are a senior financial analyst with 10+ years experience. "
                "Determine if this news directly impacts the company's cash flow, "
                "revenue, or fundamental value — or if it's just market hype."
            )
            
            llm_response = await llm_client.analyze(
                prompt=prompt,
                system=system_prompt,
            )
            
            # Parse the structured response
            analysis = parse_llm_response(llm_response)
            
            sentiment = analysis.sentiment
            impact_type = analysis.impact_type
            impact_score = analysis.impact_score
            confidence = analysis.confidence
            reasoning = analysis.reasoning
            
        except (LLMError, ValueError, Exception) as e:
            # Fall back to rule-based analysis (Requirement 10.1)
            logger.warning(f"LLM analysis failed, using fallback: {e}")
            using_fallback = True
    else:
        # No LLM client provided, use fallback
        using_fallback = True
    
    # Fallback to keyword-based analysis
    if using_fallback:
        combined_text = f"{news_item.headline} {news_item.content}"
        sentiment, impact_type, impact_score, confidence = analyze_keywords(combined_text)
        
        # Multiply confidence by 0.5 in fallback mode (Requirement 10.1)
        confidence = confidence * FALLBACK_CONFIDENCE_MULTIPLIER
        
        reasoning = (
            f"Rule-based analysis (LLM unavailable): "
            f"Detected {sentiment.value} sentiment with {impact_type.value} impact "
            f"based on keyword matching."
        )
    
    # Apply confidence threshold for CASH_FLOW classification (Requirement 1.4)
    # If confidence is below 0.7, downgrade CASH_FLOW to HYPE
    if impact_type == ImpactType.CASH_FLOW and confidence < CASH_FLOW_CONFIDENCE_THRESHOLD:
        original_impact_type = impact_type
        impact_type = ImpactType.HYPE
        reasoning = (
            f"{reasoning} "
            f"[Downgraded from {original_impact_type.value} to {impact_type.value} "
            f"due to confidence {confidence:.2f} < {CASH_FLOW_CONFIDENCE_THRESHOLD}]"
        )
        logger.info(
            f"Downgraded impact type from CASH_FLOW to HYPE for {symbol} "
            f"(confidence {confidence:.2f} < {CASH_FLOW_CONFIDENCE_THRESHOLD})"
        )
    
    # Calculate signal expiry based on impact type (Requirement 1.6)
    expiry_hours = EXPIRY_HOURS.get(impact_type, 24)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=expiry_hours)
    
    # Build and return the NewsSignal
    return NewsSignal(
        symbol=symbol,
        sentiment=sentiment,
        impact_type=impact_type,
        impact_score=impact_score,
        confidence=confidence,
        reasoning=reasoning,
        source_items=[source_item_id],
        timestamp=now,
        expires_at=expires_at,
    )


async def analyze_news_batch(
    news_items: list[NewsItem],
    llm_client: Optional[ClaudeOpusClient] = None,
) -> list[NewsSignal]:
    """
    Analyze a batch of news items.
    
    Args:
        news_items: List of news items to analyze
        llm_client: Optional Claude Opus client
        
    Returns:
        List of NewsSignal objects
    """
    signals = []
    for i, item in enumerate(news_items):
        item_id = f"{item.source}:{i}:{hash(item.headline)}"
        signal = await analyze_news_impact(item, llm_client, item_id)
        signals.append(signal)
    return signals


async def analyze_and_persist_news_signal(
    news_item: NewsItem,
    llm_client: Optional[ClaudeOpusClient] = None,
    persistence: Optional["SignalPersistence"] = None,
    item_id: Optional[str] = None,
) -> tuple[NewsSignal, Optional[str]]:
    """
    Analyze news impact and persist the resulting signal to DynamoDB.
    
    This function combines news analysis with persistence, ensuring that
    every generated NewsSignal is stored in DynamoDB for auditing and
    downstream consumption.
    
    Requirements:
        - 1.5: Generate NewsSignal with all required fields
        - 1.6: Set signal expiry based on impact type
        - 9.1: Persist signals to DynamoDB with signal ID, agent type, symbol, payload, timestamp
    
    Args:
        news_item: The news item to analyze
        llm_client: Optional Claude Opus client (uses fallback if None)
        persistence: Optional SignalPersistence instance for DynamoDB storage
        item_id: Optional ID for the news item (for source_items field)
        
    Returns:
        Tuple of (NewsSignal, signal_id) where signal_id is None if persistence failed
    """
    # Import here to avoid circular imports
    from src.agents.news.persistence import SignalPersistence
    
    # Analyze the news item
    signal = await analyze_news_impact(news_item, llm_client, item_id)
    
    # Persist to DynamoDB if persistence layer is provided
    signal_id = None
    if persistence is not None:
        signal_id = await persistence.persist_news_signal(signal)
        if signal_id:
            logger.info(
                f"Persisted NewsSignal {signal_id} for {signal.symbol} "
                f"(sentiment={signal.sentiment.value}, impact_type={signal.impact_type.value})"
            )
        else:
            logger.warning(
                f"Failed to persist NewsSignal for {signal.symbol}"
            )
    
    return signal, signal_id


async def analyze_and_persist_news_batch(
    news_items: list[NewsItem],
    llm_client: Optional[ClaudeOpusClient] = None,
    persistence: Optional["SignalPersistence"] = None,
) -> list[tuple[NewsSignal, Optional[str]]]:
    """
    Analyze and persist a batch of news items.
    
    Args:
        news_items: List of news items to analyze
        llm_client: Optional Claude Opus client
        persistence: Optional SignalPersistence instance for DynamoDB storage
        
    Returns:
        List of (NewsSignal, signal_id) tuples
    """
    results = []
    for i, item in enumerate(news_items):
        item_id = f"{item.source}:{i}:{hash(item.headline)}"
        signal, signal_id = await analyze_and_persist_news_signal(
            item, llm_client, persistence, item_id
        )
        results.append((signal, signal_id))
    return results

"""News Agent service - integrates with AWS Bedrock for analysis."""
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import uuid4

import boto3
from botocore.config import Config

from core.config import settings
from core.database import get_db_context
from models.signal import NewsSignal
from api.websocket import broadcast_signal

logger = logging.getLogger(__name__)


class NewsService:
    """Service for news scraping and analysis using AWS Bedrock."""
    
    def __init__(self):
        # Configure boto3 for cross-cloud access to AWS Bedrock
        self.bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
            config=Config(
                retries={"max_attempts": 3, "mode": "adaptive"},
                connect_timeout=5,
                read_timeout=30,
            ),
        )
    
    async def scrape_and_analyze_news(self) -> int:
        """Scrape configured news sources for tracked symbols and analyze each item."""
        from src.agents.news.scrapers import (
            BloombergScraper,
            NewsScraperManager,
            ReutersScraper,
            SECEdgarScraper,
            TwitterScraper,
        )

        scrapers = [SECEdgarScraper(user_agent=settings.SEC_EDGAR_USER_AGENT)]
        if settings.REUTERS_API_KEY:
            scrapers.append(ReutersScraper(api_key=settings.REUTERS_API_KEY))
        if settings.BLOOMBERG_API_KEY:
            scrapers.append(BloombergScraper(api_key=settings.BLOOMBERG_API_KEY))
        if settings.TWITTER_BEARER_TOKEN:
            scrapers.append(TwitterScraper(
                api_key=settings.TWITTER_API_KEY,
                api_secret=settings.TWITTER_API_SECRET,
                bearer_token=settings.TWITTER_BEARER_TOKEN,
            ))
        manager = NewsScraperManager(scrapers)

        # SEC EDGAR / news APIs only make sense for equities
        from src.brokers.symbols import parse_symbol
        symbols = [s for s in settings.trading_symbols_list if parse_symbol(s).asset_class == "stock"]
        if not symbols:
            return 0

        count = 0
        try:
            items = await manager.scrape_all(symbols)
        finally:
            await manager.close_all()

        for item in items:
            try:
                signal = await self.analyze_single_news(
                    headline=item.headline,
                    content=item.content,
                    symbols=item.symbols,
                    source=item.source,
                    url=item.url,
                )
                if signal:
                    count += 1
            except Exception as e:
                logger.error(f"Error analyzing news item '{item.headline[:60]}': {e}")
        return count

    async def analyze_single_news(
        self,
        headline: str,
        content: str,
        symbols: List[str],
        source: str,
        url: Optional[str] = None,
    ) -> Optional[NewsSignal]:
        """Analyze a single news item using AWS Bedrock Claude."""
        import json
        
        # Build prompt for Claude
        prompt = f"""Analyze this financial news and determine its impact on the stock(s).

Headline: {headline}

Content: {content}

Affected Symbols: {', '.join(symbols)}

Classify the impact as one of:
- CASH_FLOW: Direct impact on company's revenue, earnings, or cash flow
- HYPE: Market sentiment/speculation without fundamental impact
- REGULATORY: Legal or regulatory impact
- MACRO: Macroeconomic factors

Provide your analysis in JSON format:
{{
    "sentiment": "very_bullish|bullish|neutral|bearish|very_bearish",
    "impact_type": "cash_flow|hype|regulatory|macro",
    "impact_score": 0.0-1.0,
    "confidence": 0.0-1.0,
    "reasoning": "explanation"
}}"""

        try:
            response = self.bedrock_client.invoke_model(
                modelId=settings.BEDROCK_MODEL_ID,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                    "system": "You are a senior financial analyst. Analyze news for genuine cash flow impact vs market hype.",
                }),
            )
            
            response_body = json.loads(response["body"].read())
            analysis_text = response_body["content"][0]["text"]
            
            # Parse JSON from response
            analysis = json.loads(analysis_text)
            
        except Exception as e:
            logger.error(f"Bedrock analysis failed, using fallback: {e}")
            # Fallback to rule-based analysis
            analysis = self._fallback_analysis(headline, content)
            analysis["confidence"] *= 0.5  # Reduce confidence for fallback
        
        # Validate CASH_FLOW confidence requirement
        if analysis["impact_type"] == "cash_flow" and analysis["confidence"] < 0.7:
            analysis["impact_type"] = "hype"
        
        # Calculate expiry based on impact type
        expiry_hours = {
            "cash_flow": 72,
            "regulatory": 168,
            "hype": 24,
            "macro": 24,
        }.get(analysis["impact_type"], 24)
        
        # Create and persist signal
        signal = None  # stays None if the item has no symbols
        async with get_db_context() as db:
            for symbol in symbols:
                signal = NewsSignal(
                    signal_id=uuid4(),
                    symbol=symbol,
                    sentiment=analysis["sentiment"],
                    impact_type=analysis["impact_type"],
                    impact_score=analysis["impact_score"],
                    confidence=analysis["confidence"],
                    reasoning=analysis["reasoning"],
                    source_items=[url] if url else [],
                    timestamp=datetime.utcnow(),
                    expires_at=datetime.utcnow() + timedelta(hours=expiry_hours),
                )
                db.add(signal)
                
                # Broadcast to WebSocket clients
                await broadcast_signal("news", {
                    "signal_id": str(signal.signal_id),
                    "symbol": symbol,
                    "sentiment": analysis["sentiment"],
                    "impact_type": analysis["impact_type"],
                    "confidence": analysis["confidence"],
                })
        
        return signal
    
    def _fallback_analysis(self, headline: str, content: str) -> dict:
        """Rule-based fallback when Bedrock is unavailable."""
        text = (headline + " " + content).lower()
        
        # Simple keyword-based sentiment
        bullish_words = ["profit", "growth", "beat", "surge", "record", "upgrade"]
        bearish_words = ["loss", "decline", "miss", "cut", "downgrade", "warning"]
        
        bullish_count = sum(1 for w in bullish_words if w in text)
        bearish_count = sum(1 for w in bearish_words if w in text)
        
        if bullish_count > bearish_count + 1:
            sentiment = "bullish"
        elif bearish_count > bullish_count + 1:
            sentiment = "bearish"
        else:
            sentiment = "neutral"
        
        return {
            "sentiment": sentiment,
            "impact_type": "hype",  # Conservative default
            "impact_score": 0.5,
            "confidence": 0.4,
            "reasoning": "Fallback rule-based analysis",
        }
    
    async def get_aggregate_sentiment(self, symbol: str) -> str:
        """Get aggregate sentiment from recent news signals."""
        from sqlalchemy import select, func
        
        async with get_db_context() as db:
            result = await db.execute(
                select(NewsSignal.sentiment, func.count(NewsSignal.sentiment))
                .where(
                    NewsSignal.symbol == symbol,
                    NewsSignal.expires_at > datetime.utcnow(),
                )
                .group_by(NewsSignal.sentiment)
            )
            
            sentiments = dict(result.fetchall())
            
            if not sentiments:
                return "neutral"
            
            # Weight sentiments
            weights = {
                "very_bullish": 2,
                "bullish": 1,
                "neutral": 0,
                "bearish": -1,
                "very_bearish": -2,
            }
            
            total_weight = sum(
                weights.get(s, 0) * count
                for s, count in sentiments.items()
            )
            
            if total_weight >= 2:
                return "very_bullish"
            elif total_weight >= 1:
                return "bullish"
            elif total_weight <= -2:
                return "very_bearish"
            elif total_weight <= -1:
                return "bearish"
            return "neutral"

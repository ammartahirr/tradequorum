"""
Unit tests for the News Agent analyzer module.

Tests the AWS Bedrock Claude Opus 4.5 integration for news impact analysis including:
- Sentiment classification with mocked AWS Bedrock Claude Opus 4.5 responses
- Impact type classification (CASH_FLOW, HYPE, REGULATORY, MACRO)
- Confidence scoring with 0.7 threshold for CASH_FLOW
- Fallback to rule-based keyword sentiment analysis

Requirements: 1.3, 1.4, 10.1
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from src.agents.news.analyzer import (
    analyze_news_impact,
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
)
from src.models import NewsItem, NewsSignal
from src.models.enums import ImpactType, Sentiment


class TestBuildAnalysisPrompt:
    """Tests for build_analysis_prompt function."""
    
    def test_prompt_contains_headline(self):
        """Prompt should include the news headline."""
        prompt = build_analysis_prompt(
            headline="Apple reports record earnings",
            content="Apple Inc. reported...",
            symbols=["AAPL"],
            source="reuters",
        )
        assert "Apple reports record earnings" in prompt
    
    def test_prompt_contains_symbols(self):
        """Prompt should include the stock symbols."""
        prompt = build_analysis_prompt(
            headline="Tech stocks rally",
            content="Multiple tech companies...",
            symbols=["AAPL", "GOOGL", "MSFT"],
            source="bloomberg",
        )
        assert "AAPL" in prompt
        assert "GOOGL" in prompt
        assert "MSFT" in prompt
    
    def test_prompt_contains_source(self):
        """Prompt should include the news source."""
        prompt = build_analysis_prompt(
            headline="Test headline",
            content="Test content",
            symbols=["TEST"],
            source="sec_edgar",
        )
        assert "sec_edgar" in prompt
    
    def test_prompt_truncates_long_content(self):
        """Prompt should truncate very long content."""
        long_content = "x" * 5000
        prompt = build_analysis_prompt(
            headline="Test",
            content=long_content,
            symbols=["TEST"],
            source="reuters",
        )
        # Content should be truncated to 2000 chars
        assert len(prompt) < len(long_content) + 500


class TestParseLLMResponse:
    """Tests for parse_llm_response function."""
    
    def test_parse_valid_json_response(self):
        """Should parse a valid JSON response correctly."""
        response = '''
        Here is my analysis:
        {
            "sentiment": "bullish",
            "impact_type": "cash_flow",
            "impact_score": 0.85,
            "confidence": 0.9,
            "reasoning": "Strong earnings beat indicates solid fundamentals"
        }
        '''
        result = parse_llm_response(response)
        
        assert result.sentiment == Sentiment.BULLISH
        assert result.impact_type == ImpactType.CASH_FLOW
        assert result.impact_score == 0.85
        assert result.confidence == 0.9
        assert "Strong earnings" in result.reasoning
    
    def test_parse_very_bullish_sentiment(self):
        """Should parse very_bullish sentiment."""
        response = '{"sentiment": "very_bullish", "impact_type": "hype", "impact_score": 0.5, "confidence": 0.6, "reasoning": "test"}'
        result = parse_llm_response(response)
        assert result.sentiment == Sentiment.VERY_BULLISH
    
    def test_parse_very_bearish_sentiment(self):
        """Should parse very_bearish sentiment."""
        response = '{"sentiment": "very_bearish", "impact_type": "regulatory", "impact_score": 0.7, "confidence": 0.8, "reasoning": "test"}'
        result = parse_llm_response(response)
        assert result.sentiment == Sentiment.VERY_BEARISH
    
    def test_parse_all_impact_types(self):
        """Should parse all impact types correctly."""
        for impact_type in ["cash_flow", "hype", "regulatory", "macro"]:
            response = f'{{"sentiment": "neutral", "impact_type": "{impact_type}", "impact_score": 0.5, "confidence": 0.5, "reasoning": "test"}}'
            result = parse_llm_response(response)
            assert result.impact_type.value == impact_type
    
    def test_parse_clamps_scores_to_bounds(self):
        """Should clamp scores to [0.0, 1.0] range."""
        response = '{"sentiment": "neutral", "impact_type": "hype", "impact_score": 1.5, "confidence": -0.2, "reasoning": "test"}'
        result = parse_llm_response(response)
        assert result.impact_score == 1.0
        assert result.confidence == 0.0
    
    def test_parse_defaults_for_missing_fields(self):
        """Should use defaults for missing fields."""
        response = '{"sentiment": "bullish"}'
        result = parse_llm_response(response)
        assert result.sentiment == Sentiment.BULLISH
        assert result.impact_type == ImpactType.HYPE  # Default
        assert result.impact_score == 0.5  # Default
        assert result.confidence == 0.5  # Default
    
    def test_parse_raises_on_no_json(self):
        """Should raise ValueError when no JSON found."""
        with pytest.raises(ValueError, match="No JSON found"):
            parse_llm_response("This is just plain text without JSON")
    
    def test_parse_raises_on_invalid_json(self):
        """Should raise ValueError on invalid JSON."""
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_llm_response("{invalid json}")


class TestAnalyzeKeywords:
    """Tests for rule-based keyword analysis fallback."""
    
    def test_bullish_keywords_detected(self):
        """Should detect bullish sentiment from keywords."""
        text = "Apple beats earnings expectations with record revenue growth"
        sentiment, impact_type, impact_score, confidence = analyze_keywords(text)
        assert sentiment in [Sentiment.BULLISH, Sentiment.VERY_BULLISH]
    
    def test_bearish_keywords_detected(self):
        """Should detect bearish sentiment from keywords."""
        text = "Company reports massive losses, announces layoffs and restructuring"
        sentiment, impact_type, impact_score, confidence = analyze_keywords(text)
        assert sentiment in [Sentiment.BEARISH, Sentiment.VERY_BEARISH]
    
    def test_neutral_when_no_keywords(self):
        """Should return neutral when no significant keywords found."""
        text = "The company held its annual meeting today"
        sentiment, impact_type, impact_score, confidence = analyze_keywords(text)
        assert sentiment == Sentiment.NEUTRAL
    
    def test_cash_flow_impact_detected(self):
        """Should detect CASH_FLOW impact from financial keywords."""
        text = "Quarterly earnings report shows strong revenue and profit margins"
        sentiment, impact_type, impact_score, confidence = analyze_keywords(text)
        assert impact_type == ImpactType.CASH_FLOW
    
    def test_regulatory_impact_detected(self):
        """Should detect REGULATORY impact from legal keywords."""
        text = "FDA approves new drug, SEC investigation ongoing"
        sentiment, impact_type, impact_score, confidence = analyze_keywords(text)
        assert impact_type == ImpactType.REGULATORY
    
    def test_macro_impact_detected(self):
        """Should detect MACRO impact from economic keywords."""
        text = "Federal Reserve raises interest rates amid inflation concerns"
        sentiment, impact_type, impact_score, confidence = analyze_keywords(text)
        assert impact_type == ImpactType.MACRO
    
    def test_hype_when_no_specific_keywords(self):
        """Should default to HYPE when no specific impact keywords found."""
        text = "Stock is trending on social media"
        sentiment, impact_type, impact_score, confidence = analyze_keywords(text)
        assert impact_type == ImpactType.HYPE
    
    def test_impact_score_increases_with_keywords(self):
        """Impact score should increase with more keyword matches."""
        text_few = "Company reports earnings"
        text_many = "Company beats earnings expectations with record revenue growth and profit increase"
        
        _, _, score_few, _ = analyze_keywords(text_few)
        _, _, score_many, _ = analyze_keywords(text_many)
        
        assert score_many > score_few
    
    def test_confidence_bounded(self):
        """Confidence should be bounded between 0 and 1."""
        text = "x" * 1000  # Long text with no keywords
        _, _, _, confidence = analyze_keywords(text)
        assert 0.0 <= confidence <= 1.0


class TestAnalyzeNewsImpact:
    """Tests for the main analyze_news_impact function."""
    
    @pytest.fixture
    def sample_news_item(self):
        """Create a sample news item for testing."""
        return NewsItem(
            source="reuters",
            headline="Apple reports record Q4 earnings",
            content="Apple Inc. reported record quarterly earnings, beating analyst expectations.",
            published_at=datetime.now(timezone.utc),
            symbols=["AAPL"],
            url="https://reuters.com/article/123",
        )
    
    @pytest.mark.asyncio
    async def test_fallback_when_no_llm_client(self, sample_news_item):
        """Should use fallback analysis when no LLM client provided."""
        signal = await analyze_news_impact(sample_news_item, llm_client=None)
        
        assert isinstance(signal, NewsSignal)
        assert signal.symbol == "AAPL"
        assert "Rule-based analysis" in signal.reasoning
    
    @pytest.mark.asyncio
    async def test_fallback_confidence_multiplier(self, sample_news_item):
        """Fallback mode should multiply confidence by 0.5 (Requirement 10.1)."""
        signal = await analyze_news_impact(sample_news_item, llm_client=None)
        
        # Confidence should be reduced by fallback multiplier
        # Max base confidence is 0.8, so max fallback confidence is 0.4
        assert signal.confidence <= 0.8 * FALLBACK_CONFIDENCE_MULTIPLIER
    
    @pytest.mark.asyncio
    async def test_cash_flow_downgrade_below_threshold(self, sample_news_item):
        """CASH_FLOW should be downgraded to HYPE if confidence < 0.7 (Requirement 1.4)."""
        # Create a mock LLM client that returns CASH_FLOW with low confidence
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "bullish",
            "impact_type": "cash_flow",
            "impact_score": 0.8,
            "confidence": 0.6,
            "reasoning": "Earnings beat but uncertain outlook"
        }
        '''
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        # Should be downgraded from CASH_FLOW to HYPE
        assert signal.impact_type == ImpactType.HYPE
        assert "Downgraded" in signal.reasoning
    
    @pytest.mark.asyncio
    async def test_cash_flow_not_downgraded_above_threshold(self, sample_news_item):
        """CASH_FLOW should NOT be downgraded if confidence >= 0.7 (Requirement 1.4)."""
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "very_bullish",
            "impact_type": "cash_flow",
            "impact_score": 0.9,
            "confidence": 0.85,
            "reasoning": "Strong earnings with clear guidance"
        }
        '''
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        # Should remain CASH_FLOW
        assert signal.impact_type == ImpactType.CASH_FLOW
        assert signal.confidence == 0.85
    
    @pytest.mark.asyncio
    async def test_llm_error_triggers_fallback(self, sample_news_item):
        """LLM errors should trigger fallback analysis (Requirement 10.1)."""
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.side_effect = LLMError("API timeout")
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        assert isinstance(signal, NewsSignal)
        assert "Rule-based analysis" in signal.reasoning
        assert "LLM unavailable" in signal.reasoning
    
    @pytest.mark.asyncio
    async def test_expiry_hours_by_impact_type(self, sample_news_item):
        """Signal expiry should be set based on impact type (Requirement 1.6)."""
        # Test CASH_FLOW expiry (72 hours)
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "bullish",
            "impact_type": "cash_flow",
            "impact_score": 0.8,
            "confidence": 0.9,
            "reasoning": "test"
        }
        '''
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        # Check expiry is approximately 72 hours from now
        time_diff = signal.expires_at - signal.timestamp
        assert 71 <= time_diff.total_seconds() / 3600 <= 73
    
    @pytest.mark.asyncio
    async def test_regulatory_expiry(self, sample_news_item):
        """REGULATORY signals should have 168 hour expiry."""
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "bearish",
            "impact_type": "regulatory",
            "impact_score": 0.7,
            "confidence": 0.8,
            "reasoning": "SEC investigation"
        }
        '''
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        time_diff = signal.expires_at - signal.timestamp
        assert 167 <= time_diff.total_seconds() / 3600 <= 169
    
    @pytest.mark.asyncio
    async def test_hype_expiry(self, sample_news_item):
        """HYPE signals should have 24 hour expiry."""
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "bullish",
            "impact_type": "hype",
            "impact_score": 0.5,
            "confidence": 0.6,
            "reasoning": "Social media buzz"
        }
        '''
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        time_diff = signal.expires_at - signal.timestamp
        assert 23 <= time_diff.total_seconds() / 3600 <= 25
    
    @pytest.mark.asyncio
    async def test_signal_contains_required_fields(self, sample_news_item):
        """NewsSignal should contain all required fields (Requirement 1.5)."""
        signal = await analyze_news_impact(sample_news_item, llm_client=None)
        
        assert signal.symbol == "AAPL"
        assert isinstance(signal.sentiment, Sentiment)
        assert isinstance(signal.impact_type, ImpactType)
        assert 0.0 <= signal.impact_score <= 1.0
        assert 0.0 <= signal.confidence <= 1.0
        assert len(signal.reasoning) > 0
        assert len(signal.source_items) > 0
        assert signal.timestamp is not None
        assert signal.expires_at is not None
        assert signal.expires_at > signal.timestamp
    
    @pytest.mark.asyncio
    async def test_uses_first_symbol_when_multiple(self):
        """Should use the first symbol when multiple are provided."""
        news_item = NewsItem(
            source="bloomberg",
            headline="Tech sector news",
            content="Multiple companies affected",
            published_at=datetime.now(timezone.utc),
            symbols=["AAPL", "GOOGL", "MSFT"],
        )
        
        signal = await analyze_news_impact(news_item, llm_client=None)
        
        assert signal.symbol == "AAPL"


class TestExpiryHoursConstants:
    """Tests for expiry hours constants."""
    
    def test_cash_flow_expiry(self):
        """CASH_FLOW should have 72 hour expiry."""
        assert EXPIRY_HOURS[ImpactType.CASH_FLOW] == 72
    
    def test_regulatory_expiry(self):
        """REGULATORY should have 168 hour expiry."""
        assert EXPIRY_HOURS[ImpactType.REGULATORY] == 168
    
    def test_hype_expiry(self):
        """HYPE should have 24 hour expiry."""
        assert EXPIRY_HOURS[ImpactType.HYPE] == 24
    
    def test_macro_expiry(self):
        """MACRO should have 24 hour expiry."""
        assert EXPIRY_HOURS[ImpactType.MACRO] == 24


class TestConfidenceThreshold:
    """Tests for confidence threshold constant."""
    
    def test_cash_flow_threshold_is_0_7(self):
        """CASH_FLOW confidence threshold should be 0.7 (Requirement 1.4)."""
        assert CASH_FLOW_CONFIDENCE_THRESHOLD == 0.7
    
    def test_fallback_multiplier_is_0_5(self):
        """Fallback confidence multiplier should be 0.5 (Requirement 10.1)."""
        assert FALLBACK_CONFIDENCE_MULTIPLIER == 0.5



class TestAnalyzeNewsImpactWithMockedLLM:
    """
    Tests for sentiment classification with mocked AWS Bedrock Claude Opus 4.5 responses.
    
    These tests verify that the analyze_news_impact function correctly handles
    all sentiment values and impact types when receiving responses from AWS Bedrock Claude Opus 4.5.
    
    Requirements: 1.3, 1.4, 1.5, 1.6
    """
    
    @pytest.fixture
    def sample_news_item(self):
        """Create a sample news item for testing."""
        return NewsItem(
            source="reuters",
            headline="Apple reports record Q4 earnings",
            content="Apple Inc. reported record quarterly earnings, beating analyst expectations.",
            published_at=datetime.now(timezone.utc),
            symbols=["AAPL"],
            url="https://reuters.com/article/123",
        )
    
    @pytest.mark.asyncio
    async def test_very_bullish_sentiment_classification(self, sample_news_item):
        """Test VERY_BULLISH sentiment is correctly classified (Requirement 1.3)."""
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "very_bullish",
            "impact_type": "cash_flow",
            "impact_score": 0.95,
            "confidence": 0.9,
            "reasoning": "Exceptional earnings beat with strong guidance"
        }
        '''
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        assert signal.sentiment == Sentiment.VERY_BULLISH
        assert signal.impact_type == ImpactType.CASH_FLOW
        assert signal.confidence == 0.9
    
    @pytest.mark.asyncio
    async def test_bullish_sentiment_classification(self, sample_news_item):
        """Test BULLISH sentiment is correctly classified (Requirement 1.3)."""
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "bullish",
            "impact_type": "hype",
            "impact_score": 0.6,
            "confidence": 0.75,
            "reasoning": "Positive market sentiment"
        }
        '''
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        assert signal.sentiment == Sentiment.BULLISH
        assert signal.impact_type == ImpactType.HYPE
    
    @pytest.mark.asyncio
    async def test_neutral_sentiment_classification(self, sample_news_item):
        """Test NEUTRAL sentiment is correctly classified (Requirement 1.3)."""
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "neutral",
            "impact_type": "macro",
            "impact_score": 0.3,
            "confidence": 0.8,
            "reasoning": "General market news with no direct impact"
        }
        '''
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        assert signal.sentiment == Sentiment.NEUTRAL
        assert signal.impact_type == ImpactType.MACRO
    
    @pytest.mark.asyncio
    async def test_bearish_sentiment_classification(self, sample_news_item):
        """Test BEARISH sentiment is correctly classified (Requirement 1.3)."""
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "bearish",
            "impact_type": "regulatory",
            "impact_score": 0.7,
            "confidence": 0.85,
            "reasoning": "SEC investigation announced"
        }
        '''
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        assert signal.sentiment == Sentiment.BEARISH
        assert signal.impact_type == ImpactType.REGULATORY
    
    @pytest.mark.asyncio
    async def test_very_bearish_sentiment_classification(self, sample_news_item):
        """Test VERY_BEARISH sentiment is correctly classified (Requirement 1.3)."""
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "very_bearish",
            "impact_type": "cash_flow",
            "impact_score": 0.9,
            "confidence": 0.95,
            "reasoning": "Major earnings miss with lowered guidance"
        }
        '''
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        assert signal.sentiment == Sentiment.VERY_BEARISH
        assert signal.impact_type == ImpactType.CASH_FLOW
    
    @pytest.mark.asyncio
    async def test_cash_flow_at_exact_threshold(self, sample_news_item):
        """Test CASH_FLOW is NOT downgraded when confidence is exactly 0.7 (Requirement 1.4)."""
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "bullish",
            "impact_type": "cash_flow",
            "impact_score": 0.8,
            "confidence": 0.7,
            "reasoning": "Earnings beat at threshold confidence"
        }
        '''
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        # Should NOT be downgraded since confidence == 0.7 (threshold)
        assert signal.impact_type == ImpactType.CASH_FLOW
        assert signal.confidence == 0.7
        assert "Downgraded" not in signal.reasoning
    
    @pytest.mark.asyncio
    async def test_cash_flow_just_below_threshold(self, sample_news_item):
        """Test CASH_FLOW is downgraded when confidence is just below 0.7 (Requirement 1.4)."""
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "bullish",
            "impact_type": "cash_flow",
            "impact_score": 0.8,
            "confidence": 0.69,
            "reasoning": "Earnings beat with slight uncertainty"
        }
        '''
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        # Should be downgraded since confidence < 0.7
        assert signal.impact_type == ImpactType.HYPE
        assert "Downgraded" in signal.reasoning
    
    @pytest.mark.asyncio
    async def test_macro_expiry_24_hours(self, sample_news_item):
        """Test MACRO signals have 24 hour expiry (Requirement 1.6)."""
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "neutral",
            "impact_type": "macro",
            "impact_score": 0.5,
            "confidence": 0.8,
            "reasoning": "Federal Reserve announcement"
        }
        '''
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        time_diff = signal.expires_at - signal.timestamp
        assert 23 <= time_diff.total_seconds() / 3600 <= 25
    
    @pytest.mark.asyncio
    async def test_regulatory_not_downgraded_regardless_of_confidence(self, sample_news_item):
        """Test REGULATORY impact type is not affected by confidence threshold (Requirement 1.4)."""
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "bearish",
            "impact_type": "regulatory",
            "impact_score": 0.7,
            "confidence": 0.5,
            "reasoning": "SEC investigation with low confidence"
        }
        '''
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        # REGULATORY should NOT be downgraded (only CASH_FLOW is subject to threshold)
        assert signal.impact_type == ImpactType.REGULATORY
        assert "Downgraded" not in signal.reasoning
    
    @pytest.mark.asyncio
    async def test_hype_not_downgraded_regardless_of_confidence(self, sample_news_item):
        """Test HYPE impact type is not affected by confidence threshold (Requirement 1.4)."""
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "bullish",
            "impact_type": "hype",
            "impact_score": 0.6,
            "confidence": 0.4,
            "reasoning": "Social media buzz with low confidence"
        }
        '''
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        # HYPE should NOT be downgraded (only CASH_FLOW is subject to threshold)
        assert signal.impact_type == ImpactType.HYPE
        assert "Downgraded" not in signal.reasoning
    
    @pytest.mark.asyncio
    async def test_llm_response_with_extra_text(self, sample_news_item):
        """Test parsing LLM response that includes extra text around JSON."""
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        Based on my analysis of this news article, here is my assessment:
        
        {
            "sentiment": "bullish",
            "impact_type": "cash_flow",
            "impact_score": 0.85,
            "confidence": 0.9,
            "reasoning": "Strong earnings beat"
        }
        
        This indicates a positive outlook for the stock.
        '''
        
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client)
        
        assert signal.sentiment == Sentiment.BULLISH
        assert signal.impact_type == ImpactType.CASH_FLOW
        assert signal.impact_score == 0.85
    
    @pytest.mark.asyncio
    async def test_signal_source_items_contains_item_id(self, sample_news_item):
        """Test that NewsSignal source_items contains the news item ID (Requirement 1.5)."""
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "bullish",
            "impact_type": "hype",
            "impact_score": 0.5,
            "confidence": 0.7,
            "reasoning": "test"
        }
        '''
        
        custom_item_id = "custom-item-123"
        signal = await analyze_news_impact(sample_news_item, llm_client=mock_client, item_id=custom_item_id)
        
        assert custom_item_id in signal.source_items


class TestAnalyzeNewsBatch:
    """Tests for analyze_news_batch function."""
    
    @pytest.fixture
    def sample_news_items(self):
        """Create sample news items for testing."""
        now = datetime.now(timezone.utc)
        return [
            NewsItem(
                source="reuters",
                headline="Apple earnings beat",
                content="Strong quarterly results",
                published_at=now,
                symbols=["AAPL"],
            ),
            NewsItem(
                source="bloomberg",
                headline="Tesla production update",
                content="Factory output increases",
                published_at=now,
                symbols=["TSLA"],
            ),
            NewsItem(
                source="sec_edgar",
                headline="Microsoft 10-K Filing",
                content="Annual report filed",
                published_at=now,
                symbols=["MSFT"],
            ),
        ]
    
    @pytest.mark.asyncio
    async def test_batch_processes_all_items_without_llm(self, sample_news_items):
        """Test batch processing without LLM client uses fallback for all items."""
        from src.agents.news.analyzer import analyze_news_batch
        
        signals = await analyze_news_batch(sample_news_items, llm_client=None)
        
        assert len(signals) == 3
        assert all(isinstance(s, NewsSignal) for s in signals)
        assert all("Rule-based analysis" in s.reasoning for s in signals)
    
    @pytest.mark.asyncio
    async def test_batch_processes_all_items_with_llm(self, sample_news_items):
        """Test batch processing with mocked LLM client."""
        from src.agents.news.analyzer import analyze_news_batch
        
        mock_client = AsyncMock(spec=ClaudeOpusClient)
        mock_client.analyze.return_value = '''
        {
            "sentiment": "bullish",
            "impact_type": "cash_flow",
            "impact_score": 0.8,
            "confidence": 0.85,
            "reasoning": "Positive news"
        }
        '''
        
        signals = await analyze_news_batch(sample_news_items, llm_client=mock_client)
        
        assert len(signals) == 3
        assert all(s.sentiment == Sentiment.BULLISH for s in signals)
        assert mock_client.analyze.call_count == 3
    
    @pytest.mark.asyncio
    async def test_batch_assigns_unique_source_item_ids(self, sample_news_items):
        """Test that batch processing assigns unique source item IDs."""
        from src.agents.news.analyzer import analyze_news_batch
        
        signals = await analyze_news_batch(sample_news_items, llm_client=None)
        
        # Each signal should have a unique source_items entry
        all_source_items = [s.source_items[0] for s in signals]
        assert len(set(all_source_items)) == 3  # All unique


class TestAnalyzeAndPersistNewsSignal:
    """Tests for analyze_and_persist_news_signal function."""
    
    @pytest.fixture
    def sample_news_item(self):
        """Create a sample news item for testing."""
        return NewsItem(
            source="reuters",
            headline="Apple reports record Q4 earnings",
            content="Apple Inc. reported record quarterly earnings, beating analyst expectations.",
            published_at=datetime.now(timezone.utc),
            symbols=["AAPL"],
            url="https://reuters.com/article/123",
        )
    
    @pytest.fixture
    def mock_persistence(self):
        """Create a mock SignalPersistence."""
        from src.agents.news.persistence import SignalPersistence
        persistence = MagicMock(spec=SignalPersistence)
        persistence.persist_news_signal = AsyncMock(return_value="test-signal-id-123")
        return persistence
    
    @pytest.mark.asyncio
    async def test_returns_signal_and_id_with_persistence(self, sample_news_item, mock_persistence):
        """Should return both signal and signal_id when persistence succeeds."""
        from src.agents.news.analyzer import analyze_and_persist_news_signal
        
        signal, signal_id = await analyze_and_persist_news_signal(
            sample_news_item,
            llm_client=None,
            persistence=mock_persistence,
        )
        
        assert isinstance(signal, NewsSignal)
        assert signal_id == "test-signal-id-123"
        mock_persistence.persist_news_signal.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_returns_none_id_when_persistence_fails(self, sample_news_item, mock_persistence):
        """Should return None signal_id when persistence fails."""
        from src.agents.news.analyzer import analyze_and_persist_news_signal
        
        mock_persistence.persist_news_signal = AsyncMock(return_value=None)
        
        signal, signal_id = await analyze_and_persist_news_signal(
            sample_news_item,
            llm_client=None,
            persistence=mock_persistence,
        )
        
        assert isinstance(signal, NewsSignal)
        assert signal_id is None
    
    @pytest.mark.asyncio
    async def test_returns_none_id_without_persistence(self, sample_news_item):
        """Should return None signal_id when no persistence provided."""
        from src.agents.news.analyzer import analyze_and_persist_news_signal
        
        signal, signal_id = await analyze_and_persist_news_signal(
            sample_news_item,
            llm_client=None,
            persistence=None,
        )
        
        assert isinstance(signal, NewsSignal)
        assert signal_id is None
    
    @pytest.mark.asyncio
    async def test_signal_has_correct_expiry(self, sample_news_item, mock_persistence):
        """Should generate signal with correct expiry based on impact type (Requirement 1.6)."""
        from src.agents.news.analyzer import analyze_and_persist_news_signal
        
        signal, _ = await analyze_and_persist_news_signal(
            sample_news_item,
            llm_client=None,
            persistence=mock_persistence,
        )
        
        # Signal should have expiry set
        assert signal.expires_at > signal.timestamp
        
        # Expiry should match impact type
        time_diff_hours = (signal.expires_at - signal.timestamp).total_seconds() / 3600
        expected_hours = EXPIRY_HOURS.get(signal.impact_type, 24)
        assert abs(time_diff_hours - expected_hours) < 1  # Within 1 hour tolerance


class TestAnalyzeAndPersistNewsBatch:
    """Tests for analyze_and_persist_news_batch function."""
    
    @pytest.fixture
    def sample_news_items(self):
        """Create sample news items for testing."""
        now = datetime.now(timezone.utc)
        return [
            NewsItem(
                source="reuters",
                headline="Apple earnings beat",
                content="Strong quarterly results",
                published_at=now,
                symbols=["AAPL"],
            ),
            NewsItem(
                source="bloomberg",
                headline="Tesla production update",
                content="Factory output increases",
                published_at=now,
                symbols=["TSLA"],
            ),
        ]
    
    @pytest.fixture
    def mock_persistence(self):
        """Create a mock SignalPersistence."""
        from src.agents.news.persistence import SignalPersistence
        persistence = MagicMock(spec=SignalPersistence)
        persistence.persist_news_signal = AsyncMock(side_effect=["id-1", "id-2"])
        return persistence
    
    @pytest.mark.asyncio
    async def test_processes_all_items(self, sample_news_items, mock_persistence):
        """Should process all news items in batch."""
        from src.agents.news.analyzer import analyze_and_persist_news_batch
        
        results = await analyze_and_persist_news_batch(
            sample_news_items,
            llm_client=None,
            persistence=mock_persistence,
        )
        
        assert len(results) == 2
        assert all(isinstance(r[0], NewsSignal) for r in results)
    
    @pytest.mark.asyncio
    async def test_returns_signal_ids(self, sample_news_items, mock_persistence):
        """Should return signal IDs for each item."""
        from src.agents.news.analyzer import analyze_and_persist_news_batch
        
        results = await analyze_and_persist_news_batch(
            sample_news_items,
            llm_client=None,
            persistence=mock_persistence,
        )
        
        signal_ids = [r[1] for r in results]
        assert signal_ids == ["id-1", "id-2"]

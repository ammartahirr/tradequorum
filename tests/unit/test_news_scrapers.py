"""
Unit tests for news scrapers.

Tests the scraper implementations for Reuters, Bloomberg, SEC EDGAR, and Twitter/X.
Requirements: 1.1 - Scrape news from configured sources
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.news import (
    ReutersScraper,
    BloombergScraper,
    SECEdgarScraper,
    TwitterScraper,
    NewsScraperManager,
)
from src.models import NewsItem


class TestReutersScraper:
    """Tests for ReutersScraper."""
    
    @pytest.fixture
    def scraper(self):
        return ReutersScraper(api_key="test_key")
    
    @pytest.mark.asyncio
    async def test_scrape_returns_news_items(self, scraper):
        """Test that scraper returns NewsItem objects."""
        mock_response = {
            "articles": [
                {
                    "headline": "Apple Reports Record Earnings",
                    "body": "Apple Inc. reported record quarterly earnings...",
                    "published_at": "2024-01-15T10:30:00Z",
                    "url": "https://reuters.com/article/1",
                    "related_symbols": ["AAPL"],
                }
            ]
        }
        
        with patch.object(scraper, "_get_session") as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp))
            )
            
            items = await scraper.scrape(["AAPL"])
            
            assert len(items) == 1
            assert isinstance(items[0], NewsItem)
            assert items[0].source == "reuters"
            assert items[0].headline == "Apple Reports Record Earnings"
            assert "AAPL" in items[0].symbols
    
    @pytest.mark.asyncio
    async def test_scrape_handles_api_error(self, scraper):
        """Test that scraper handles API errors gracefully."""
        with patch.object(scraper, "_get_session") as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 500
            
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp))
            )
            
            items = await scraper.scrape(["AAPL"])
            
            assert items == []
    
    @pytest.mark.asyncio
    async def test_scrape_handles_empty_response(self, scraper):
        """Test that scraper handles empty response."""
        mock_response = {"articles": []}
        
        with patch.object(scraper, "_get_session") as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp))
            )
            
            items = await scraper.scrape(["AAPL"])
            
            assert items == []


class TestBloombergScraper:
    """Tests for BloombergScraper."""
    
    @pytest.fixture
    def scraper(self):
        return BloombergScraper(api_key="test_key")
    
    @pytest.mark.asyncio
    async def test_scrape_returns_news_items(self, scraper):
        """Test that scraper returns NewsItem objects."""
        mock_response = {
            "stories": [
                {
                    "title": "Microsoft Cloud Revenue Surges",
                    "abstract": "Microsoft's cloud business continues to grow...",
                    "publishedAt": "2024-01-15T14:00:00Z",
                    "url": "https://bloomberg.com/news/1",
                    "tickers": ["MSFT"],
                }
            ]
        }
        
        with patch.object(scraper, "_get_session") as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp))
            )
            
            items = await scraper.scrape(["MSFT"])
            
            assert len(items) == 1
            assert isinstance(items[0], NewsItem)
            assert items[0].source == "bloomberg"
            assert items[0].headline == "Microsoft Cloud Revenue Surges"


class TestSECEdgarScraper:
    """Tests for SECEdgarScraper."""
    
    @pytest.fixture
    def scraper(self):
        return SECEdgarScraper()
    
    @pytest.mark.asyncio
    async def test_scrape_returns_sec_filings(self, scraper):
        """Test that scraper returns SEC filing items."""
        mock_cik_response = {
            "0": {"cik_str": "320193", "ticker": "AAPL", "title": "Apple Inc."}
        }
        
        mock_filings_response = {
            "cik": "320193",
            "name": "Apple Inc.",
            "filings": {
                "recent": {
                    "form": ["10-K", "10-Q", "8-K"],
                    "filingDate": ["2024-01-15", "2024-01-10", "2024-01-05"],
                    "primaryDocument": ["aapl-10k.htm", "aapl-10q.htm", "aapl-8k.htm"],
                    "accessionNumber": ["0001-24-000001", "0001-24-000002", "0001-24-000003"],
                }
            },
        }
        
        with patch.object(scraper, "_get_session") as mock_session:
            mock_cik_resp = AsyncMock()
            mock_cik_resp.status = 200
            mock_cik_resp.json = AsyncMock(return_value=mock_cik_response)
            
            mock_filings_resp = AsyncMock()
            mock_filings_resp.status = 200
            mock_filings_resp.json = AsyncMock(return_value=mock_filings_response)
            
            # Mock both API calls
            mock_session.return_value.get = MagicMock(
                side_effect=[
                    AsyncMock(__aenter__=AsyncMock(return_value=mock_cik_resp)),
                    AsyncMock(__aenter__=AsyncMock(return_value=mock_filings_resp)),
                ]
            )
            
            items = await scraper.scrape(["AAPL"])
            
            assert len(items) == 3
            assert all(item.source == "sec_edgar" for item in items)
            assert any("10-K" in item.headline for item in items)


class TestTwitterScraper:
    """Tests for TwitterScraper."""
    
    @pytest.fixture
    def scraper(self):
        return TwitterScraper(bearer_token="test_token")
    
    @pytest.mark.asyncio
    async def test_scrape_returns_tweets(self, scraper):
        """Test that scraper returns tweet items."""
        mock_response = {
            "data": [
                {
                    "id": "123456789",
                    "text": "$TSLA is looking strong today! Great earnings report.",
                    "author_id": "user123",
                    "created_at": "2024-01-15T16:00:00Z",
                    "public_metrics": {
                        "like_count": 100,
                        "retweet_count": 50,
                        "reply_count": 20,
                    },
                }
            ],
            "includes": {
                "users": [
                    {
                        "id": "user123",
                        "name": "Stock Analyst",
                        "username": "stockanalyst",
                        "verified": True,
                    }
                ]
            },
        }
        
        with patch.object(scraper, "_get_session") as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp))
            )
            
            items = await scraper.scrape(["TSLA"])
            
            assert len(items) == 1
            assert items[0].source == "twitter"
            assert "TSLA" in items[0].symbols
    
    @pytest.mark.asyncio
    async def test_scrape_filters_low_engagement_tweets(self, scraper):
        """Test that low engagement tweets are filtered out."""
        mock_response = {
            "data": [
                {
                    "id": "123456789",
                    "text": "$TSLA random tweet",
                    "author_id": "user123",
                    "created_at": "2024-01-15T16:00:00Z",
                    "public_metrics": {
                        "like_count": 1,
                        "retweet_count": 0,
                        "reply_count": 0,
                    },
                }
            ],
            "includes": {
                "users": [
                    {"id": "user123", "name": "Random User", "username": "random"}
                ]
            },
        }
        
        with patch.object(scraper, "_get_session") as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp))
            )
            
            items = await scraper.scrape(["TSLA"])
            
            # Low engagement tweet should be filtered
            assert len(items) == 0
    
    @pytest.mark.asyncio
    async def test_scrape_without_bearer_token(self):
        """Test that scraper returns empty list without bearer token."""
        scraper = TwitterScraper(bearer_token=None)
        items = await scraper.scrape(["TSLA"])
        assert items == []


class TestNewsScraperManager:
    """Tests for NewsScraperManager."""
    
    @pytest.mark.asyncio
    async def test_scrape_all_aggregates_results(self):
        """Test that manager aggregates results from all scrapers."""
        mock_scraper1 = MagicMock()
        mock_scraper1.source_name = "source1"
        mock_scraper1.scrape = AsyncMock(
            return_value=[
                NewsItem(
                    source="source1",
                    headline="News 1",
                    content="Content 1",
                    published_at=datetime.now(timezone.utc),
                    symbols=["AAPL"],
                )
            ]
        )
        mock_scraper1.close = AsyncMock()
        
        mock_scraper2 = MagicMock()
        mock_scraper2.source_name = "source2"
        mock_scraper2.scrape = AsyncMock(
            return_value=[
                NewsItem(
                    source="source2",
                    headline="News 2",
                    content="Content 2",
                    published_at=datetime.now(timezone.utc),
                    symbols=["AAPL"],
                )
            ]
        )
        mock_scraper2.close = AsyncMock()
        
        manager = NewsScraperManager([mock_scraper1, mock_scraper2])
        items = await manager.scrape_all(["AAPL"])
        
        assert len(items) == 2
        assert items[0].source == "source1"
        assert items[1].source == "source2"
    
    @pytest.mark.asyncio
    async def test_scrape_all_handles_scraper_errors(self):
        """Test that manager handles individual scraper errors."""
        mock_scraper1 = MagicMock()
        mock_scraper1.source_name = "source1"
        mock_scraper1.scrape = AsyncMock(side_effect=Exception("API Error"))
        mock_scraper1.close = AsyncMock()
        
        mock_scraper2 = MagicMock()
        mock_scraper2.source_name = "source2"
        mock_scraper2.scrape = AsyncMock(
            return_value=[
                NewsItem(
                    source="source2",
                    headline="News 2",
                    content="Content 2",
                    published_at=datetime.now(timezone.utc),
                    symbols=["AAPL"],
                )
            ]
        )
        mock_scraper2.close = AsyncMock()
        
        manager = NewsScraperManager([mock_scraper1, mock_scraper2])
        items = await manager.scrape_all(["AAPL"])
        
        # Should still get results from working scraper
        assert len(items) == 1
        assert items[0].source == "source2"



class TestScraperEdgeCases:
    """
    Additional edge case tests for news scrapers.
    
    Requirements: 1.1 - Scrape news from configured sources
    """
    
    @pytest.mark.asyncio
    async def test_reuters_scraper_multiple_symbols(self):
        """Test Reuters scraper with multiple symbols."""
        scraper = ReutersScraper(api_key="test_key")
        
        mock_response = {
            "articles": [
                {
                    "headline": "Tech stocks rally",
                    "body": "Multiple tech companies...",
                    "published_at": "2024-01-15T10:30:00Z",
                    "url": "https://reuters.com/article/1",
                    "related_symbols": [],
                }
            ]
        }
        
        with patch.object(scraper, "_get_session") as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp))
            )
            
            items = await scraper.scrape(["AAPL", "GOOGL", "MSFT"])
            
            # Should make requests for each symbol
            assert mock_session.return_value.get.call_count == 3
    
    @pytest.mark.asyncio
    async def test_bloomberg_scraper_handles_missing_fields(self):
        """Test Bloomberg scraper handles missing optional fields."""
        scraper = BloombergScraper(api_key="test_key")
        
        mock_response = {
            "stories": [
                {
                    "title": "Market Update",
                    # Missing abstract, body, url, tickers
                    "publishedAt": "2024-01-15T14:00:00Z",
                }
            ]
        }
        
        with patch.object(scraper, "_get_session") as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp))
            )
            
            items = await scraper.scrape(["AAPL"])
            
            assert len(items) == 1
            assert items[0].headline == "Market Update"
            assert items[0].content == ""  # Default for missing content
    
    @pytest.mark.asyncio
    async def test_sec_edgar_scraper_filters_filing_types(self):
        """Test SEC EDGAR scraper only includes material filings."""
        scraper = SECEdgarScraper()
        
        mock_cik_response = {
            "0": {"cik_str": "320193", "ticker": "AAPL", "title": "Apple Inc."}
        }
        
        mock_filings_response = {
            "cik": "320193",
            "name": "Apple Inc.",
            "filings": {
                "recent": {
                    "form": ["10-K", "10-Q", "8-K", "DEF 14A", "S-1", "4"],
                    "filingDate": ["2024-01-15", "2024-01-14", "2024-01-13", "2024-01-12", "2024-01-11", "2024-01-10"],
                    "primaryDocument": ["doc1.htm", "doc2.htm", "doc3.htm", "doc4.htm", "doc5.htm", "doc6.htm"],
                    "accessionNumber": ["0001-24-000001", "0001-24-000002", "0001-24-000003", "0001-24-000004", "0001-24-000005", "0001-24-000006"],
                }
            },
        }
        
        with patch.object(scraper, "_get_session") as mock_session:
            mock_cik_resp = AsyncMock()
            mock_cik_resp.status = 200
            mock_cik_resp.json = AsyncMock(return_value=mock_cik_response)
            
            mock_filings_resp = AsyncMock()
            mock_filings_resp.status = 200
            mock_filings_resp.json = AsyncMock(return_value=mock_filings_response)
            
            mock_session.return_value.get = MagicMock(
                side_effect=[
                    AsyncMock(__aenter__=AsyncMock(return_value=mock_cik_resp)),
                    AsyncMock(__aenter__=AsyncMock(return_value=mock_filings_resp)),
                ]
            )
            
            items = await scraper.scrape(["AAPL"])
            
            # Should only include 10-K, 10-Q, 8-K, and 4 (material filings)
            # DEF 14A and S-1 should be filtered out
            assert len(items) == 4
            form_types = [item.headline.split(" - ")[1].split(" ")[0] for item in items]
            assert "10-K" in form_types
            assert "10-Q" in form_types
            assert "8-K" in form_types
            assert "4" in form_types
    
    @pytest.mark.asyncio
    async def test_twitter_scraper_rate_limit_handling(self):
        """Test Twitter scraper handles rate limiting."""
        scraper = TwitterScraper(bearer_token="test_token")
        
        with patch.object(scraper, "_get_session") as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 429  # Rate limit
            
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp))
            )
            
            items = await scraper.scrape(["TSLA"])
            
            # Should return empty list on rate limit
            assert items == []
    
    @pytest.mark.asyncio
    async def test_twitter_scraper_engagement_threshold(self):
        """Test Twitter scraper filters by engagement threshold."""
        scraper = TwitterScraper(bearer_token="test_token")
        
        mock_response = {
            "data": [
                {
                    "id": "1",
                    "text": "$AAPL high engagement tweet",
                    "author_id": "user1",
                    "created_at": "2024-01-15T16:00:00Z",
                    "public_metrics": {
                        "like_count": 100,
                        "retweet_count": 50,
                        "reply_count": 20,
                    },
                },
                {
                    "id": "2",
                    "text": "$AAPL low engagement tweet",
                    "author_id": "user2",
                    "created_at": "2024-01-15T16:00:00Z",
                    "public_metrics": {
                        "like_count": 2,
                        "retweet_count": 0,
                        "reply_count": 1,
                    },
                },
                {
                    "id": "3",
                    "text": "$AAPL medium engagement tweet",
                    "author_id": "user3",
                    "created_at": "2024-01-15T16:00:00Z",
                    "public_metrics": {
                        "like_count": 5,
                        "retweet_count": 0,
                        "reply_count": 0,
                    },
                },
            ],
            "includes": {
                "users": [
                    {"id": "user1", "name": "User 1", "username": "user1"},
                    {"id": "user2", "name": "User 2", "username": "user2"},
                    {"id": "user3", "name": "User 3", "username": "user3"},
                ]
            },
        }
        
        with patch.object(scraper, "_get_session") as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp))
            )
            
            items = await scraper.scrape(["AAPL"])
            
            # Should only include tweets with engagement >= 5
            assert len(items) == 2
            assert any("high engagement" in item.content for item in items)
            assert any("medium engagement" in item.content for item in items)
            assert not any("low engagement" in item.content for item in items)


class TestNewsScraperManagerEdgeCases:
    """Additional tests for NewsScraperManager."""
    
    @pytest.mark.asyncio
    async def test_scrape_all_with_no_scrapers(self):
        """Test manager with no scrapers configured."""
        manager = NewsScraperManager([])
        items = await manager.scrape_all(["AAPL"])
        assert items == []
    
    @pytest.mark.asyncio
    async def test_scrape_all_with_empty_symbols(self):
        """Test manager with empty symbols list."""
        mock_scraper = MagicMock()
        mock_scraper.source_name = "test"
        mock_scraper.scrape = AsyncMock(return_value=[])
        mock_scraper.close = AsyncMock()
        
        manager = NewsScraperManager([mock_scraper])
        items = await manager.scrape_all([])
        
        # Should call scraper with empty list
        mock_scraper.scrape.assert_called_once_with([])
    
    @pytest.mark.asyncio
    async def test_add_scraper(self):
        """Test adding scrapers to manager."""
        manager = NewsScraperManager([])
        
        mock_scraper = MagicMock()
        mock_scraper.source_name = "test"
        
        manager.add_scraper(mock_scraper)
        
        assert len(manager.scrapers) == 1
        assert manager.scrapers[0] == mock_scraper
    
    @pytest.mark.asyncio
    async def test_close_all_scrapers(self):
        """Test closing all scraper sessions."""
        mock_scraper1 = MagicMock()
        mock_scraper1.close = AsyncMock()
        
        mock_scraper2 = MagicMock()
        mock_scraper2.close = AsyncMock()
        
        manager = NewsScraperManager([mock_scraper1, mock_scraper2])
        await manager.close_all()
        
        mock_scraper1.close.assert_called_once()
        mock_scraper2.close.assert_called_once()


class TestBaseScraperMethods:
    """Tests for BaseScraper methods."""
    
    @pytest.mark.asyncio
    async def test_generate_item_id_uniqueness(self):
        """Test that item IDs are unique for different inputs."""
        scraper = ReutersScraper(api_key="test")
        
        id1 = scraper._generate_item_id("https://example.com/1", "Headline 1")
        id2 = scraper._generate_item_id("https://example.com/2", "Headline 2")
        id3 = scraper._generate_item_id("https://example.com/1", "Headline 1")
        
        assert id1 != id2
        assert id1 == id3  # Same inputs should produce same ID
    
    @pytest.mark.asyncio
    async def test_scraper_close_session(self):
        """Test that scraper properly closes session."""
        scraper = ReutersScraper(api_key="test")
        
        # Create a mock session
        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        scraper._session = mock_session
        
        await scraper.close()
        
        mock_session.close.assert_called_once()

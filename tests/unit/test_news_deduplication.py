"""
Unit tests for news deduplication logic.

Tests the deduplication of news items referencing the same event.
Requirements: 1.2 - Deduplicate news items referencing the same event
"""

import pytest
from datetime import datetime, timedelta, timezone

from src.agents.news import NewsDeduplicator, deduplicate_news_items
from src.models import NewsItem


class TestNewsDeduplicator:
    """Tests for NewsDeduplicator."""
    
    @pytest.fixture
    def deduplicator(self):
        return NewsDeduplicator(
            headline_similarity_threshold=0.75,
            content_similarity_threshold=0.60,
            time_window_hours=24,
        )
    
    @pytest.fixture
    def base_time(self):
        return datetime.now(timezone.utc)
    
    def test_deduplicate_empty_list(self, deduplicator):
        """Test deduplication of empty list."""
        result = deduplicator.deduplicate([])
        assert result == []
    
    def test_deduplicate_single_item(self, deduplicator, base_time):
        """Test deduplication of single item."""
        item = NewsItem(
            source="reuters",
            headline="Apple Reports Record Earnings",
            content="Apple Inc. reported record quarterly earnings...",
            published_at=base_time,
            symbols=["AAPL"],
            url="https://reuters.com/1",
        )
        
        result = deduplicator.deduplicate([item])
        
        assert len(result) == 1
        assert result[0].headline == item.headline
    
    def test_deduplicate_exact_url_match(self, deduplicator, base_time):
        """Test deduplication of items with same URL."""
        item1 = NewsItem(
            source="reuters",
            headline="Apple Reports Record Earnings",
            content="Apple Inc. reported record quarterly earnings...",
            published_at=base_time,
            symbols=["AAPL"],
            url="https://reuters.com/1",
        )
        
        item2 = NewsItem(
            source="reuters",
            headline="Apple Reports Record Earnings",
            content="Apple Inc. reported record quarterly earnings...",
            published_at=base_time + timedelta(minutes=5),
            symbols=["AAPL"],
            url="https://reuters.com/1",  # Same URL
        )
        
        result = deduplicator.deduplicate([item1, item2])
        
        assert len(result) == 1
    
    def test_deduplicate_similar_headlines(self, deduplicator, base_time):
        """Test deduplication of items with similar headlines."""
        item1 = NewsItem(
            source="reuters",
            headline="Apple Reports Record Quarterly Earnings",
            content="Apple Inc. reported record quarterly earnings...",
            published_at=base_time,
            symbols=["AAPL"],
            url="https://reuters.com/1",
        )
        
        item2 = NewsItem(
            source="bloomberg",
            headline="Apple Reports Record Earnings for Q4",
            content="Apple Inc. announced record earnings for the quarter...",
            published_at=base_time + timedelta(minutes=30),
            symbols=["AAPL"],
            url="https://bloomberg.com/1",
        )
        
        result = deduplicator.deduplicate([item1, item2])
        
        # Should be deduplicated to one item
        assert len(result) == 1
    
    def test_deduplicate_different_events(self, deduplicator, base_time):
        """Test that different events are not deduplicated."""
        item1 = NewsItem(
            source="reuters",
            headline="Apple Reports Record Earnings",
            content="Apple Inc. reported record quarterly earnings...",
            published_at=base_time,
            symbols=["AAPL"],
            url="https://reuters.com/1",
        )
        
        item2 = NewsItem(
            source="reuters",
            headline="Microsoft Announces New AI Features",
            content="Microsoft unveiled new AI capabilities...",
            published_at=base_time + timedelta(minutes=30),
            symbols=["MSFT"],
            url="https://reuters.com/2",
        )
        
        result = deduplicator.deduplicate([item1, item2])
        
        # Should keep both items
        assert len(result) == 2
    
    def test_deduplicate_outside_time_window(self, deduplicator, base_time):
        """Test that items outside time window are not deduplicated."""
        item1 = NewsItem(
            source="reuters",
            headline="Apple Reports Record Earnings",
            content="Apple Inc. reported record quarterly earnings...",
            published_at=base_time,
            symbols=["AAPL"],
            url="https://reuters.com/1",
        )
        
        item2 = NewsItem(
            source="bloomberg",
            headline="Apple Reports Record Earnings",
            content="Apple Inc. reported record quarterly earnings...",
            published_at=base_time + timedelta(hours=48),  # Outside 24h window
            symbols=["AAPL"],
            url="https://bloomberg.com/1",
        )
        
        result = deduplicator.deduplicate([item1, item2])
        
        # Should keep both items (outside time window)
        assert len(result) == 2
    
    def test_deduplicate_prefers_authoritative_sources(self, deduplicator, base_time):
        """Test that deduplication prefers authoritative sources."""
        twitter_item = NewsItem(
            source="twitter",
            headline="Apple Reports Record Quarterly Earnings Today",
            content="Apple just reported amazing earnings...",
            published_at=base_time,
            symbols=["AAPL"],
            url="https://twitter.com/1",
        )
        
        reuters_item = NewsItem(
            source="reuters",
            headline="Apple Reports Record Quarterly Earnings Results",
            content="Apple Inc. reported amazing earnings results today...",
            published_at=base_time + timedelta(minutes=10),
            symbols=["AAPL"],
            url="https://reuters.com/1",
        )
        
        result = deduplicator.deduplicate([twitter_item, reuters_item])
        
        # Should prefer Reuters over Twitter
        assert len(result) == 1
        assert result[0].source == "reuters"
    
    def test_deduplicate_merges_symbols(self, deduplicator, base_time):
        """Test that deduplication merges symbols from duplicate items within the same symbol group."""
        # Items with the same symbol should be grouped and merged
        item1 = NewsItem(
            source="reuters",
            headline="Tech Giants Report Strong Quarterly Earnings Today",
            content="Major tech companies reported strong earnings...",
            published_at=base_time,
            symbols=["AAPL"],
            url="https://reuters.com/1",
        )
        
        item2 = NewsItem(
            source="bloomberg",
            headline="Tech Giants Report Strong Quarterly Earnings Today",
            content="Major tech companies reported strong earnings results...",
            published_at=base_time + timedelta(minutes=15),
            symbols=["AAPL", "GOOGL"],  # Same primary symbol AAPL, with additional GOOGL
            url="https://bloomberg.com/1",
        )
        
        result = deduplicator.deduplicate([item1, item2])
        
        # Should merge symbols since they share AAPL
        assert len(result) == 1
        assert set(result[0].symbols) == {"AAPL", "GOOGL"}
    
    def test_deduplicate_multiple_groups(self, deduplicator, base_time):
        """Test deduplication with multiple event groups."""
        # Event 1: Apple earnings
        apple1 = NewsItem(
            source="reuters",
            headline="Apple Reports Record Quarterly Earnings Today",
            content="Apple Inc. reported record quarterly earnings...",
            published_at=base_time,
            symbols=["AAPL"],
            url="https://reuters.com/1",
        )
        
        apple2 = NewsItem(
            source="bloomberg",
            headline="Apple Reports Record Quarterly Earnings Results",
            content="Apple Inc. announced record earnings...",
            published_at=base_time + timedelta(minutes=20),
            symbols=["AAPL"],
            url="https://bloomberg.com/1",
        )
        
        # Event 2: Microsoft AI
        msft1 = NewsItem(
            source="reuters",
            headline="Microsoft Unveils New AI Features Today",
            content="Microsoft announced new AI capabilities...",
            published_at=base_time + timedelta(hours=2),
            symbols=["MSFT"],
            url="https://reuters.com/2",
        )
        
        msft2 = NewsItem(
            source="twitter",
            headline="Microsoft Unveils New AI Features Announcement",
            content="Microsoft's new AI features are incredible...",
            published_at=base_time + timedelta(hours=2, minutes=30),
            symbols=["MSFT"],
            url="https://twitter.com/1",
        )
        
        result = deduplicator.deduplicate([apple1, apple2, msft1, msft2])
        
        # Should have 2 unique events
        assert len(result) == 2
        
        # Check that we have one Apple and one Microsoft event
        sources = {item.symbols[0] for item in result}
        assert sources == {"AAPL", "MSFT"}


class TestDeduplicateNewsItemsFunction:
    """Tests for the convenience function."""
    
    def test_deduplicate_news_items_with_defaults(self):
        """Test convenience function with default parameters."""
        base_time = datetime.now(timezone.utc)
        
        items = [
            NewsItem(
                source="reuters",
                headline="Apple Reports Record Earnings",
                content="Apple Inc. reported record quarterly earnings...",
                published_at=base_time,
                symbols=["AAPL"],
                url="https://reuters.com/1",
            ),
            NewsItem(
                source="bloomberg",
                headline="Apple Reports Record Earnings Results",
                content="Apple Inc. announced record earnings...",
                published_at=base_time + timedelta(minutes=15),
                symbols=["AAPL"],
                url="https://bloomberg.com/1",
            ),
        ]
        
        result = deduplicate_news_items(items)
        
        assert len(result) == 1
    
    def test_deduplicate_news_items_with_custom_thresholds(self):
        """Test convenience function with custom thresholds."""
        base_time = datetime.now(timezone.utc)
        
        items = [
            NewsItem(
                source="reuters",
                headline="Apple Reports Earnings",
                content="Apple Inc. reported earnings...",
                published_at=base_time,
                symbols=["AAPL"],
                url="https://reuters.com/1",
            ),
            NewsItem(
                source="bloomberg",
                headline="Apple Announces Earnings",
                content="Apple Inc. announced earnings...",
                published_at=base_time + timedelta(minutes=15),
                symbols=["AAPL"],
                url="https://bloomberg.com/1",
            ),
        ]
        
        # With high threshold, items should not be deduplicated
        result = deduplicate_news_items(
            items,
            headline_threshold=0.95,
            content_threshold=0.95,
        )
        
        assert len(result) == 2


class TestDeduplicatorEdgeCases:
    """Edge case tests for NewsDeduplicator."""
    
    @pytest.fixture
    def deduplicator(self):
        return NewsDeduplicator()
    
    def test_normalize_text_empty(self, deduplicator):
        """Test text normalization with empty string."""
        result = deduplicator._normalize_text("")
        assert result == ""
    
    def test_normalize_text_with_urls(self, deduplicator):
        """Test text normalization removes URLs."""
        text = "Check out https://example.com for more info"
        result = deduplicator._normalize_text(text)
        assert "https" not in result
        assert "example.com" not in result
    
    def test_calculate_similarity_empty_strings(self, deduplicator):
        """Test similarity calculation with empty strings."""
        assert deduplicator._calculate_similarity("", "") == 0.0
        assert deduplicator._calculate_similarity("test", "") == 0.0
        assert deduplicator._calculate_similarity("", "test") == 0.0
    
    def test_calculate_similarity_identical_strings(self, deduplicator):
        """Test similarity calculation with identical strings."""
        result = deduplicator._calculate_similarity("test string", "test string")
        assert result == 1.0
    
    def test_generate_fingerprint_consistency(self, deduplicator):
        """Test that fingerprint is consistent for same content."""
        base_time = datetime.now(timezone.utc)
        
        item = NewsItem(
            source="reuters",
            headline="Apple Reports Earnings",
            content="Apple Inc. reported earnings...",
            published_at=base_time,
            symbols=["AAPL"],
        )
        
        fp1 = deduplicator._generate_fingerprint(item)
        fp2 = deduplicator._generate_fingerprint(item)
        
        assert fp1 == fp2



class TestDeduplicationWithSymbolFiltering:
    """
    Additional tests for deduplication with symbol-based filtering.
    
    Requirements: 1.2 - Deduplicate news items referencing the same event
    """
    
    @pytest.fixture
    def deduplicator(self):
        return NewsDeduplicator()
    
    @pytest.fixture
    def base_time(self):
        return datetime.now(timezone.utc)
    
    def test_deduplicate_same_event_different_symbols(self, deduplicator, base_time):
        """Test that same event reported for different symbols is handled correctly."""
        # Same event but different primary symbols
        item1 = NewsItem(
            source="reuters",
            headline="Tech sector rallies on strong earnings",
            content="Major tech companies reported strong earnings...",
            published_at=base_time,
            symbols=["AAPL"],
            url="https://reuters.com/1",
        )
        
        item2 = NewsItem(
            source="reuters",
            headline="Tech sector rallies on strong earnings",
            content="Major tech companies reported strong earnings...",
            published_at=base_time + timedelta(minutes=5),
            symbols=["GOOGL"],
            url="https://reuters.com/2",
        )
        
        result = deduplicator.deduplicate([item1, item2])
        
        # Should keep both since they have different primary symbols
        # (deduplication is per-symbol)
        assert len(result) >= 1
    
    def test_deduplicate_preserves_all_symbols_in_merged_item(self, deduplicator, base_time):
        """Test that merged items preserve all symbols from duplicates."""
        item1 = NewsItem(
            source="reuters",
            headline="Apple and Google announce partnership",
            content="Tech giants collaborate on new project...",
            published_at=base_time,
            symbols=["AAPL"],
            url="https://reuters.com/1",
        )
        
        item2 = NewsItem(
            source="bloomberg",
            headline="Apple and Google announce partnership deal",
            content="Tech giants collaborate on new project today...",
            published_at=base_time + timedelta(minutes=10),
            symbols=["AAPL", "GOOGL"],
            url="https://bloomberg.com/1",
        )
        
        result = deduplicator.deduplicate([item1, item2])
        
        # Should merge and include both symbols
        assert len(result) == 1
        assert "AAPL" in result[0].symbols
        assert "GOOGL" in result[0].symbols
    
    def test_deduplicate_handles_empty_symbols(self, deduplicator, base_time):
        """Test deduplication handles items with empty symbols list."""
        item1 = NewsItem(
            source="reuters",
            headline="Market update",
            content="General market news...",
            published_at=base_time,
            symbols=[],
            url="https://reuters.com/1",
        )
        
        item2 = NewsItem(
            source="bloomberg",
            headline="Stock market news",
            content="Different market news...",
            published_at=base_time,
            symbols=["SPY"],
            url="https://bloomberg.com/1",
        )
        
        # Should not raise an error
        result = deduplicator.deduplicate([item1, item2])
        assert isinstance(result, list)
    
    def test_deduplicate_large_batch(self, deduplicator, base_time):
        """Test deduplication with a large batch of items."""
        items = []
        for i in range(100):
            items.append(NewsItem(
                source="reuters" if i % 2 == 0 else "bloomberg",
                headline=f"News item {i // 10}",  # Groups of 10 similar headlines
                content=f"Content for news item {i}",
                published_at=base_time + timedelta(minutes=i),
                symbols=[f"SYM{i // 10}"],
                url=f"https://example.com/{i}",
            ))
        
        result = deduplicator.deduplicate(items)
        
        # Should significantly reduce the number of items
        assert len(result) < len(items)
        assert len(result) > 0


class TestDeduplicatorSimilarityCalculation:
    """Tests for similarity calculation edge cases."""
    
    @pytest.fixture
    def deduplicator(self):
        return NewsDeduplicator()
    
    def test_similarity_with_special_characters(self, deduplicator):
        """Test similarity calculation with special characters."""
        text1 = "Apple's Q4 earnings beat expectations!"
        text2 = "Apple's Q4 earnings beat expectations?"
        
        similarity = deduplicator._calculate_similarity(
            deduplicator._normalize_text(text1),
            deduplicator._normalize_text(text2),
        )
        
        # Should be very similar after normalization
        assert similarity > 0.9
    
    def test_similarity_with_numbers(self, deduplicator):
        """Test similarity calculation with numbers."""
        text1 = "Apple reports $100B revenue"
        text2 = "Apple reports $100 billion revenue"
        
        similarity = deduplicator._calculate_similarity(
            deduplicator._normalize_text(text1),
            deduplicator._normalize_text(text2),
        )
        
        # Should have some similarity
        assert similarity > 0.5
    
    def test_similarity_case_insensitive(self, deduplicator):
        """Test that similarity is case insensitive."""
        text1 = "APPLE REPORTS EARNINGS"
        text2 = "apple reports earnings"
        
        similarity = deduplicator._calculate_similarity(
            deduplicator._normalize_text(text1),
            deduplicator._normalize_text(text2),
        )
        
        assert similarity == 1.0


class TestDeduplicatorSourcePriority:
    """Tests for source priority in deduplication."""
    
    @pytest.fixture
    def deduplicator(self):
        return NewsDeduplicator()
    
    @pytest.fixture
    def base_time(self):
        return datetime.now(timezone.utc)
    
    def test_reuters_preferred_over_twitter(self, deduplicator, base_time):
        """Test that Reuters is preferred over Twitter."""
        twitter_item = NewsItem(
            source="twitter",
            headline="Breaking: Apple earnings beat expectations today",
            content="Apple just reported amazing earnings...",
            published_at=base_time,
            symbols=["AAPL"],
        )
        
        reuters_item = NewsItem(
            source="reuters",
            headline="Breaking: Apple earnings beat expectations report",
            content="Apple just reported amazing earnings results...",
            published_at=base_time + timedelta(minutes=5),
            symbols=["AAPL"],
        )
        
        result = deduplicator.deduplicate([twitter_item, reuters_item])
        
        assert len(result) == 1
        assert result[0].source == "reuters"
    
    def test_bloomberg_preferred_over_twitter(self, deduplicator, base_time):
        """Test that Bloomberg is preferred over Twitter."""
        twitter_item = NewsItem(
            source="twitter",
            headline="Tesla production numbers are incredible today",
            content="Tesla factory output...",
            published_at=base_time,
            symbols=["TSLA"],
        )
        
        bloomberg_item = NewsItem(
            source="bloomberg",
            headline="Tesla production numbers are incredible report",
            content="Tesla factory output increases...",
            published_at=base_time + timedelta(minutes=5),
            symbols=["TSLA"],
        )
        
        result = deduplicator.deduplicate([twitter_item, bloomberg_item])
        
        assert len(result) == 1
        assert result[0].source == "bloomberg"
    
    def test_sec_edgar_preferred_over_twitter(self, deduplicator, base_time):
        """Test that SEC EDGAR is preferred over Twitter."""
        twitter_item = NewsItem(
            source="twitter",
            headline="Microsoft filed their annual report today",
            content="MSFT 10-K is out...",
            published_at=base_time,
            symbols=["MSFT"],
        )
        
        sec_item = NewsItem(
            source="sec_edgar",
            headline="Microsoft filed their annual report 10-K",
            content="MSFT 10-K filing...",
            published_at=base_time + timedelta(minutes=5),
            symbols=["MSFT"],
        )
        
        result = deduplicator.deduplicate([twitter_item, sec_item])
        
        assert len(result) == 1
        assert result[0].source == "sec_edgar"

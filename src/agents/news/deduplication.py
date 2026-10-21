"""
News deduplication logic for the News Agent.

Implements deduplication of news items that reference the same event,
producing a single consolidated analysis.

Requirements: 1.2 - Deduplicate news items referencing the same event
"""

import hashlib
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Optional

from src.models import NewsItem

logger = logging.getLogger(__name__)


class NewsDeduplicator:
    """
    Deduplicates news items that reference the same event.
    
    Uses multiple strategies to identify duplicate news:
    1. URL-based deduplication (exact match)
    2. Headline similarity (fuzzy matching)
    3. Content fingerprinting (semantic similarity)
    4. Temporal clustering (events within time window)
    
    Requirements: 1.2 - Deduplicate news items referencing the same event
    """
    
    def __init__(
        self,
        headline_similarity_threshold: float = 0.75,
        content_similarity_threshold: float = 0.60,
        time_window_hours: int = 24,
    ):
        """
        Initialize the deduplicator.
        
        Args:
            headline_similarity_threshold: Minimum similarity ratio for headlines
                to be considered duplicates (0.0 to 1.0)
            content_similarity_threshold: Minimum similarity ratio for content
                to be considered duplicates (0.0 to 1.0)
            time_window_hours: Maximum time difference in hours for items
                to be considered duplicates of the same event
        """
        self.headline_similarity_threshold = headline_similarity_threshold
        self.content_similarity_threshold = content_similarity_threshold
        self.time_window = timedelta(hours=time_window_hours)
    
    def deduplicate(self, items: list[NewsItem]) -> list[NewsItem]:
        """
        Deduplicate a list of news items.
        
        Groups items that reference the same event and returns a consolidated
        list with one representative item per event.
        
        Args:
            items: List of NewsItem objects to deduplicate
            
        Returns:
            Deduplicated list of NewsItem objects
        """
        if not items:
            return []
        
        # Group items by symbol for more efficient processing
        items_by_symbol: dict[str, list[NewsItem]] = defaultdict(list)
        for item in items:
            for symbol in item.symbols:
                items_by_symbol[symbol].append(item)
        
        # Track which items have been processed
        processed_urls: set[str] = set()
        deduplicated: list[NewsItem] = []
        
        for symbol, symbol_items in items_by_symbol.items():
            # Sort by published_at to process oldest first
            sorted_items = sorted(symbol_items, key=lambda x: x.published_at)
            
            # Group similar items
            groups: list[list[NewsItem]] = []
            
            for item in sorted_items:
                # Skip if already processed via URL
                if item.url and item.url in processed_urls:
                    continue
                
                # Try to find an existing group for this item
                added_to_group = False
                for group in groups:
                    if self._is_duplicate(item, group[0]):
                        group.append(item)
                        added_to_group = True
                        break
                
                if not added_to_group:
                    groups.append([item])
                
                if item.url:
                    processed_urls.add(item.url)
            
            # Select representative item from each group
            for group in groups:
                representative = self._select_representative(group)
                # Merge symbols from all items in the group
                all_symbols = set()
                for item in group:
                    all_symbols.update(item.symbols)
                
                # Create consolidated item
                consolidated = NewsItem(
                    source=representative.source,
                    headline=representative.headline,
                    content=representative.content,
                    published_at=representative.published_at,
                    symbols=list(all_symbols),
                    url=representative.url,
                )
                
                # Only add if not already in deduplicated list
                if not self._item_exists(consolidated, deduplicated):
                    deduplicated.append(consolidated)
        
        logger.info(
            f"Deduplicated {len(items)} items to {len(deduplicated)} unique events"
        )
        
        return deduplicated
    
    def _is_duplicate(self, item1: NewsItem, item2: NewsItem) -> bool:
        """
        Check if two news items are duplicates (reference the same event).
        
        Args:
            item1: First news item
            item2: Second news item
            
        Returns:
            True if items are duplicates, False otherwise
        """
        # Check time window first (fast filter)
        time_diff = abs(item1.published_at - item2.published_at)
        if time_diff > self.time_window:
            return False
        
        # Check URL match (exact duplicate)
        if item1.url and item2.url and item1.url == item2.url:
            return True
        
        # Check headline similarity
        headline_similarity = self._calculate_similarity(
            self._normalize_text(item1.headline),
            self._normalize_text(item2.headline),
        )
        if headline_similarity >= self.headline_similarity_threshold:
            return True
        
        # Check content similarity for items with similar headlines
        if headline_similarity >= 0.5:
            content_similarity = self._calculate_similarity(
                self._normalize_text(item1.content[:500]),  # Compare first 500 chars
                self._normalize_text(item2.content[:500]),
            )
            if content_similarity >= self.content_similarity_threshold:
                return True
        
        # Check content fingerprint
        fp1 = self._generate_fingerprint(item1)
        fp2 = self._generate_fingerprint(item2)
        if fp1 == fp2:
            return True
        
        return False
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate similarity ratio between two texts.
        
        Uses SequenceMatcher for fuzzy string matching.
        
        Args:
            text1: First text
            text2: Second text
            
        Returns:
            Similarity ratio between 0.0 and 1.0
        """
        if not text1 or not text2:
            return 0.0
        
        return SequenceMatcher(None, text1, text2).ratio()
    
    def _normalize_text(self, text: str) -> str:
        """
        Normalize text for comparison.
        
        - Converts to lowercase
        - Removes extra whitespace
        - Removes common stop words
        - Removes punctuation
        
        Args:
            text: Text to normalize
            
        Returns:
            Normalized text
        """
        if not text:
            return ""
        
        # Convert to lowercase
        text = text.lower()
        
        # Remove URLs
        text = re.sub(r"https?://\S+", "", text)
        
        # Remove punctuation
        text = re.sub(r"[^\w\s]", " ", text)
        
        # Remove extra whitespace
        text = " ".join(text.split())
        
        return text
    
    def _generate_fingerprint(self, item: NewsItem) -> str:
        """
        Generate a content fingerprint for a news item.
        
        Uses key terms from the headline and content to create a
        fingerprint that identifies the core event.
        
        Args:
            item: NewsItem to fingerprint
            
        Returns:
            Fingerprint string
        """
        # Extract key terms (nouns, numbers, proper nouns)
        text = f"{item.headline} {item.content[:200]}"
        normalized = self._normalize_text(text)
        
        # Get significant words (longer than 4 chars, not common words)
        common_words = {
            "the", "and", "for", "that", "this", "with", "from", "have",
            "has", "had", "will", "would", "could", "should", "been",
            "being", "their", "there", "which", "about", "into", "more",
            "some", "than", "when", "what", "were", "said", "says",
        }
        
        words = [
            w for w in normalized.split()
            if len(w) > 4 and w not in common_words
        ]
        
        # Sort and take top 10 significant words
        words = sorted(set(words))[:10]
        
        # Add symbols to fingerprint
        symbols = sorted(item.symbols)
        
        # Create fingerprint
        fingerprint_content = f"{','.join(symbols)}:{','.join(words)}"
        return hashlib.md5(fingerprint_content.encode()).hexdigest()
    
    def _select_representative(self, group: list[NewsItem]) -> NewsItem:
        """
        Select the best representative item from a group of duplicates.
        
        Prefers items with:
        1. More authoritative sources (Reuters, Bloomberg > Twitter)
        2. More complete content
        3. Earlier publication time
        
        Args:
            group: List of duplicate NewsItem objects
            
        Returns:
            Best representative NewsItem
        """
        if len(group) == 1:
            return group[0]
        
        # Source priority (higher is better)
        source_priority = {
            "reuters": 4,
            "bloomberg": 4,
            "sec_edgar": 3,
            "twitter": 1,
        }
        
        def score_item(item: NewsItem) -> tuple[int, int, datetime]:
            """Score an item for selection (higher is better)."""
            priority = source_priority.get(item.source, 2)
            content_length = len(item.content)
            # Negate published_at so earlier items score higher
            return (priority, content_length, item.published_at)
        
        # Sort by score (descending) and return best
        sorted_group = sorted(group, key=score_item, reverse=True)
        return sorted_group[0]
    
    def _item_exists(self, item: NewsItem, items: list[NewsItem]) -> bool:
        """Check if an item already exists in the list."""
        for existing in items:
            if item.url and existing.url and item.url == existing.url:
                return True
            if (
                item.headline == existing.headline
                and item.source == existing.source
            ):
                return True
        return False


def deduplicate_news_items(
    items: list[NewsItem],
    headline_threshold: float = 0.75,
    content_threshold: float = 0.60,
    time_window_hours: int = 24,
) -> list[NewsItem]:
    """
    Convenience function to deduplicate news items.
    
    Args:
        items: List of NewsItem objects to deduplicate
        headline_threshold: Minimum headline similarity for duplicates
        content_threshold: Minimum content similarity for duplicates
        time_window_hours: Maximum time difference for duplicates
        
    Returns:
        Deduplicated list of NewsItem objects
    """
    deduplicator = NewsDeduplicator(
        headline_similarity_threshold=headline_threshold,
        content_similarity_threshold=content_threshold,
        time_window_hours=time_window_hours,
    )
    return deduplicator.deduplicate(items)

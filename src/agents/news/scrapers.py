"""
News scrapers for various data sources.

Implements scrapers for:
- Reuters
- Bloomberg
- SEC EDGAR
- Twitter/X

Requirements: 1.1 - Scrape news from configured sources within scheduled interval
"""

import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from src.models import NewsItem

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Base class for all news scrapers."""
    
    source_name: str = "base"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 30,
    ):
        """
        Initialize the scraper.
        
        Args:
            api_key: API key for authenticated endpoints
            base_url: Base URL for the API
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
    
    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    @abstractmethod
    async def scrape(self, symbols: list[str]) -> list[NewsItem]:
        """
        Scrape news items for the given symbols.
        
        Args:
            symbols: List of stock symbols to scrape news for
            
        Returns:
            List of NewsItem objects
        """
        pass
    
    def _generate_item_id(self, url: str, headline: str) -> str:
        """Generate a unique ID for a news item."""
        content = f"{url}:{headline}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class ReutersScraper(BaseScraper):
    """
    Scraper for Reuters news articles.
    
    Fetches financial news from Reuters API for specified stock symbols.
    """
    
    source_name: str = "reuters"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.reuters.com/v1",
        timeout: int = 30,
    ):
        super().__init__(api_key, base_url, timeout)
    
    async def scrape(self, symbols: list[str]) -> list[NewsItem]:
        """
        Scrape Reuters news for the given symbols.
        
        Args:
            symbols: List of stock symbols
            
        Returns:
            List of NewsItem objects from Reuters
        """
        news_items: list[NewsItem] = []
        session = await self._get_session()
        
        for symbol in symbols:
            try:
                # Reuters API endpoint for company news
                url = f"{self.base_url}/news/company/{symbol}"
                headers = {}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        items = self._parse_response(data, symbol)
                        news_items.extend(items)
                    else:
                        logger.warning(
                            f"Reuters API returned status {response.status} for {symbol}"
                        )
            except aiohttp.ClientError as e:
                logger.error(f"Error fetching Reuters news for {symbol}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error scraping Reuters for {symbol}: {e}")
        
        return news_items
    
    def _parse_response(self, data: dict, symbol: str) -> list[NewsItem]:
        """Parse Reuters API response into NewsItem objects."""
        items: list[NewsItem] = []
        
        articles = data.get("articles", [])
        for article in articles:
            try:
                published_str = article.get("published_at", "")
                published_at = (
                    datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                    if published_str
                    else datetime.now(timezone.utc)
                )
                
                item = NewsItem(
                    source=self.source_name,
                    headline=article.get("headline", ""),
                    content=article.get("body", article.get("summary", "")),
                    published_at=published_at,
                    symbols=[symbol] + article.get("related_symbols", []),
                    url=article.get("url"),
                )
                items.append(item)
            except Exception as e:
                logger.warning(f"Error parsing Reuters article: {e}")
        
        return items


class BloombergScraper(BaseScraper):
    """
    Scraper for Bloomberg news articles.
    
    Fetches financial news from Bloomberg API for specified stock symbols.
    """
    
    source_name: str = "bloomberg"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.bloomberg.com/v1",
        timeout: int = 30,
    ):
        super().__init__(api_key, base_url, timeout)
    
    async def scrape(self, symbols: list[str]) -> list[NewsItem]:
        """
        Scrape Bloomberg news for the given symbols.
        
        Args:
            symbols: List of stock symbols
            
        Returns:
            List of NewsItem objects from Bloomberg
        """
        news_items: list[NewsItem] = []
        session = await self._get_session()
        
        for symbol in symbols:
            try:
                url = f"{self.base_url}/news"
                headers = {}
                if self.api_key:
                    headers["X-Bloomberg-API-Key"] = self.api_key
                
                params = {"symbol": symbol, "limit": 50}
                
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        items = self._parse_response(data, symbol)
                        news_items.extend(items)
                    else:
                        logger.warning(
                            f"Bloomberg API returned status {response.status} for {symbol}"
                        )
            except aiohttp.ClientError as e:
                logger.error(f"Error fetching Bloomberg news for {symbol}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error scraping Bloomberg for {symbol}: {e}")
        
        return news_items
    
    def _parse_response(self, data: dict, symbol: str) -> list[NewsItem]:
        """Parse Bloomberg API response into NewsItem objects."""
        items: list[NewsItem] = []
        
        stories = data.get("stories", [])
        for story in stories:
            try:
                published_str = story.get("publishedAt", "")
                published_at = (
                    datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                    if published_str
                    else datetime.now(timezone.utc)
                )
                
                item = NewsItem(
                    source=self.source_name,
                    headline=story.get("title", ""),
                    content=story.get("abstract", story.get("body", "")),
                    published_at=published_at,
                    symbols=[symbol] + story.get("tickers", []),
                    url=story.get("url"),
                )
                items.append(item)
            except Exception as e:
                logger.warning(f"Error parsing Bloomberg story: {e}")
        
        return items



class SECEdgarScraper(BaseScraper):
    """
    Scraper for SEC EDGAR filings.
    
    Fetches SEC filings (10-K, 10-Q, 8-K, etc.) for specified stock symbols.
    SEC EDGAR is a public API and doesn't require authentication.
    """
    
    source_name: str = "sec_edgar"
    
    def __init__(
        self,
        api_key: Optional[str] = None,  # Not required for SEC EDGAR
        base_url: str = "https://data.sec.gov",
        timeout: int = 30,
        user_agent: str = "AI-Trading-System contact@example.com",
    ):
        super().__init__(api_key, base_url, timeout)
        self.user_agent = user_agent
    
    async def scrape(self, symbols: list[str]) -> list[NewsItem]:
        """
        Scrape SEC EDGAR filings for the given symbols.
        
        Args:
            symbols: List of stock symbols (tickers)
            
        Returns:
            List of NewsItem objects from SEC EDGAR
        """
        news_items: list[NewsItem] = []
        session = await self._get_session()
        
        for symbol in symbols:
            try:
                # First, get the CIK (Central Index Key) for the ticker
                cik = await self._get_cik_for_ticker(session, symbol)
                if not cik:
                    logger.warning(f"Could not find CIK for symbol {symbol}")
                    continue
                
                # Fetch recent filings for the CIK
                url = f"{self.base_url}/submissions/CIK{cik.zfill(10)}.json"
                headers = {"User-Agent": self.user_agent}
                
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        items = self._parse_response(data, symbol)
                        news_items.extend(items)
                    else:
                        logger.warning(
                            f"SEC EDGAR API returned status {response.status} for {symbol}"
                        )
            except aiohttp.ClientError as e:
                logger.error(f"Error fetching SEC filings for {symbol}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error scraping SEC EDGAR for {symbol}: {e}")
        
        return news_items
    
    async def _get_cik_for_ticker(
        self, session: aiohttp.ClientSession, ticker: str
    ) -> Optional[str]:
        """Look up the CIK for a given ticker symbol."""
        try:
            url = f"{self.base_url}/files/company_tickers.json"
            headers = {"User-Agent": self.user_agent}
            
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    # Search for the ticker in the response
                    for entry in data.values():
                        if entry.get("ticker", "").upper() == ticker.upper():
                            return str(entry.get("cik_str", ""))
        except Exception as e:
            logger.error(f"Error looking up CIK for {ticker}: {e}")
        
        return None
    
    def _parse_response(self, data: dict, symbol: str) -> list[NewsItem]:
        """Parse SEC EDGAR API response into NewsItem objects."""
        items: list[NewsItem] = []
        
        company_name = data.get("name", symbol)
        filings = data.get("filings", {}).get("recent", {})
        
        # Get the filing arrays
        forms = filings.get("form", [])
        filing_dates = filings.get("filingDate", [])
        descriptions = filings.get("primaryDocument", [])
        accession_numbers = filings.get("accessionNumber", [])
        
        # Only process recent filings (last 50)
        for i in range(min(50, len(forms))):
            try:
                form_type = forms[i] if i < len(forms) else ""
                
                # Only include material filings
                if form_type not in ["10-K", "10-Q", "8-K", "6-K", "4", "SC 13D", "SC 13G"]:
                    continue
                
                filing_date_str = filing_dates[i] if i < len(filing_dates) else ""
                published_at = (
                    datetime.strptime(filing_date_str, "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                    if filing_date_str
                    else datetime.now(timezone.utc)
                )
                
                accession = accession_numbers[i] if i < len(accession_numbers) else ""
                doc_name = descriptions[i] if i < len(descriptions) else ""
                
                # Build the filing URL
                accession_clean = accession.replace("-", "")
                filing_url = (
                    f"https://www.sec.gov/Archives/edgar/data/"
                    f"{data.get('cik', '')}/{accession_clean}/{doc_name}"
                )
                
                headline = f"{company_name} - {form_type} Filing"
                content = f"SEC {form_type} filing for {company_name} ({symbol})"
                
                item = NewsItem(
                    source=self.source_name,
                    headline=headline,
                    content=content,
                    published_at=published_at,
                    symbols=[symbol],
                    url=filing_url,
                )
                items.append(item)
            except Exception as e:
                logger.warning(f"Error parsing SEC filing: {e}")
        
        return items


class TwitterScraper(BaseScraper):
    """
    Scraper for Twitter/X posts.
    
    Fetches tweets from company accounts and influential financial accounts
    for specified stock symbols.
    """
    
    source_name: str = "twitter"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        bearer_token: Optional[str] = None,
        base_url: str = "https://api.twitter.com/2",
        timeout: int = 30,
    ):
        super().__init__(api_key, base_url, timeout)
        self.api_secret = api_secret
        self.bearer_token = bearer_token
    
    async def scrape(self, symbols: list[str]) -> list[NewsItem]:
        """
        Scrape Twitter/X for the given symbols.
        
        Args:
            symbols: List of stock symbols
            
        Returns:
            List of NewsItem objects from Twitter
        """
        news_items: list[NewsItem] = []
        session = await self._get_session()
        
        if not self.bearer_token:
            logger.warning("Twitter bearer token not configured, skipping Twitter scraping")
            return news_items
        
        for symbol in symbols:
            try:
                # Search for tweets mentioning the stock symbol
                query = f"${symbol} OR #{symbol} -is:retweet lang:en"
                url = f"{self.base_url}/tweets/search/recent"
                headers = {"Authorization": f"Bearer {self.bearer_token}"}
                params = {
                    "query": query,
                    "max_results": 50,
                    "tweet.fields": "created_at,author_id,text,public_metrics",
                    "expansions": "author_id",
                    "user.fields": "name,username,verified",
                }
                
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        items = self._parse_response(data, symbol)
                        news_items.extend(items)
                    elif response.status == 429:
                        logger.warning("Twitter API rate limit reached")
                    else:
                        logger.warning(
                            f"Twitter API returned status {response.status} for {symbol}"
                        )
            except aiohttp.ClientError as e:
                logger.error(f"Error fetching Twitter data for {symbol}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error scraping Twitter for {symbol}: {e}")
        
        return news_items
    
    def _parse_response(self, data: dict, symbol: str) -> list[NewsItem]:
        """Parse Twitter API response into NewsItem objects."""
        items: list[NewsItem] = []
        
        tweets = data.get("data", [])
        users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
        
        for tweet in tweets:
            try:
                author_id = tweet.get("author_id", "")
                author = users.get(author_id, {})
                author_name = author.get("name", "Unknown")
                author_username = author.get("username", "unknown")
                
                created_str = tweet.get("created_at", "")
                published_at = (
                    datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    if created_str
                    else datetime.now(timezone.utc)
                )
                
                tweet_id = tweet.get("id", "")
                tweet_url = f"https://twitter.com/{author_username}/status/{tweet_id}"
                
                # Use engagement metrics to filter low-quality tweets
                metrics = tweet.get("public_metrics", {})
                engagement = (
                    metrics.get("like_count", 0)
                    + metrics.get("retweet_count", 0) * 2
                    + metrics.get("reply_count", 0)
                )
                
                # Only include tweets with some engagement
                if engagement < 5:
                    continue
                
                headline = f"@{author_username}: {tweet.get('text', '')[:100]}..."
                
                item = NewsItem(
                    source=self.source_name,
                    headline=headline,
                    content=tweet.get("text", ""),
                    published_at=published_at,
                    symbols=[symbol],
                    url=tweet_url,
                )
                items.append(item)
            except Exception as e:
                logger.warning(f"Error parsing tweet: {e}")
        
        return items


class NewsScraperManager:
    """
    Manager for coordinating multiple news scrapers.
    
    Provides a unified interface for scraping news from all configured sources
    and handles aggregation of results.
    """
    
    def __init__(self, scrapers: Optional[list[BaseScraper]] = None):
        """
        Initialize the scraper manager.
        
        Args:
            scrapers: List of scraper instances to use. If None, creates default scrapers.
        """
        self.scrapers = scrapers or []
    
    def add_scraper(self, scraper: BaseScraper) -> None:
        """Add a scraper to the manager."""
        self.scrapers.append(scraper)
    
    async def scrape_all(self, symbols: list[str]) -> list[NewsItem]:
        """
        Scrape news from all configured sources for the given symbols.
        
        Args:
            symbols: List of stock symbols to scrape news for
            
        Returns:
            Aggregated list of NewsItem objects from all sources
        """
        all_items: list[NewsItem] = []
        
        for scraper in self.scrapers:
            try:
                items = await scraper.scrape(symbols)
                all_items.extend(items)
                logger.info(
                    f"Scraped {len(items)} items from {scraper.source_name} "
                    f"for {len(symbols)} symbols"
                )
            except Exception as e:
                logger.error(f"Error in {scraper.source_name} scraper: {e}")
        
        return all_items
    
    async def close_all(self) -> None:
        """Close all scraper sessions."""
        for scraper in self.scrapers:
            await scraper.close()

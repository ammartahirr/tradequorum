# Lambda handlers
"""
Contains AWS Lambda handler functions for:
- News scraping and analysis
- Technical analysis
- Strategy evaluation
- Order execution
- WebSocket message handling
"""

from .news_scraper_handler import handler as news_scraper_handler
from .news_processing_handler import handler as news_processing_handler
from .technical_analysis_handler import handler as technical_analysis_handler
from .strategy_evaluation_handler import handler as strategy_evaluation_handler
from .order_execution_handler import handler as order_execution_handler

__all__ = [
    "news_scraper_handler",
    "news_processing_handler",
    "technical_analysis_handler",
    "strategy_evaluation_handler",
    "order_execution_handler",
]

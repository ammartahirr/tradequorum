"""
Background task scheduler for periodic jobs.
Replaces AWS EventBridge scheduled triggers.
"""
import asyncio
import logging
from datetime import datetime
from typing import Callable, Dict, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.config import settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def news_scraping_job():
    """Periodic news scraping job (replaces Lambda + EventBridge)."""
    from services.news_service import NewsService
    
    logger.info(f"Running news scraping job at {datetime.utcnow()}")
    try:
        service = NewsService()
        await service.scrape_and_analyze_news()
    except Exception as e:
        logger.error(f"News scraping job failed: {e}")


async def technical_analysis_job():
    """Periodic technical analysis job."""
    from services.technical_service import TechnicalService
    
    logger.info(f"Running technical analysis job at {datetime.utcnow()}")
    try:
        service = TechnicalService()
        await service.analyze_all_symbols()
    except Exception as e:
        logger.error(f"Technical analysis job failed: {e}")


async def strategy_evaluation_job():
    """Periodic strategy evaluation job."""
    from services.strategy_service import StrategyService
    
    logger.info(f"Running strategy evaluation job at {datetime.utcnow()}")
    try:
        if settings.STRATEGY_ENGINE.lower() == "quant":
            from services.quant_service import evaluate_and_store
            stored = await evaluate_and_store()
            logger.info(f"Quant engine stored {stored} new trade decision(s)")
            return
        service = StrategyService()
        await service.evaluate_pending_signals()
    except Exception as e:
        logger.error(f"Strategy evaluation job failed: {e}")


async def position_monitoring_job():
    """Monitor open positions for SL/TP hits."""
    from services.position_service import PositionService
    
    logger.info(f"Running position monitoring job at {datetime.utcnow()}")
    try:
        service = PositionService()
        await service.monitor_positions()
    except Exception as e:
        logger.error(f"Position monitoring job failed: {e}")


async def start_scheduler():
    """Start the background scheduler."""
    # News scraping every 5 minutes
    scheduler.add_job(
        news_scraping_job,
        IntervalTrigger(minutes=settings.NEWS_SCRAPE_INTERVAL_MINUTES),
        id="news_scraping",
        name="News Scraping",
        replace_existing=True,
    )
    
    # Technical analysis every minute
    scheduler.add_job(
        technical_analysis_job,
        IntervalTrigger(minutes=settings.TECHNICAL_ANALYSIS_INTERVAL_MINUTES),
        id="technical_analysis",
        name="Technical Analysis",
        replace_existing=True,
    )
    
    # Strategy evaluation every minute
    scheduler.add_job(
        strategy_evaluation_job,
        IntervalTrigger(minutes=settings.QUANT_EVAL_INTERVAL_MINUTES
                        if settings.STRATEGY_ENGINE.lower() == "quant" else 1),
        id="strategy_evaluation",
        name="Strategy Evaluation",
        replace_existing=True,
    )
    
    # Position monitoring every 10 seconds
    scheduler.add_job(
        position_monitoring_job,
        IntervalTrigger(seconds=10),
        id="position_monitoring",
        name="Position Monitoring",
        replace_existing=True,
    )
    
    scheduler.start()
    logger.info("Background scheduler started")


async def stop_scheduler():
    """Stop the background scheduler."""
    scheduler.shutdown(wait=False)
    logger.info("Background scheduler stopped")

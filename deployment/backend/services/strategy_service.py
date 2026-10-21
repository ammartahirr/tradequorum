"""Strategy Agent service."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select

from core.config import settings
from core.database import get_db_context
from models.signal import NewsSignal, TechnicalSignal
from models.trade import TradeDecision
from api.websocket import broadcast_decision

logger = logging.getLogger(__name__)


class StrategyService:
    """Service for strategy evaluation and trade decision making."""
    
    async def evaluate_pending_signals(self):
        """Evaluate all pending signal pairs and generate decisions."""
        async with get_db_context() as db:
            # Get unconsumed news signals
            news_result = await db.execute(
                select(NewsSignal)
                .where(
                    NewsSignal.consumed_by.is_(None),
                    NewsSignal.expires_at > datetime.utcnow(),
                )
            )
            news_signals = news_result.scalars().all()
            
            # Get unconsumed technical signals (within 1 hour)
            tech_cutoff = datetime.utcnow() - timedelta(hours=1)
            tech_result = await db.execute(
                select(TechnicalSignal)
                .where(
                    TechnicalSignal.consumed_by.is_(None),
                    TechnicalSignal.timestamp > tech_cutoff,
                )
            )
            tech_signals = tech_result.scalars().all()
            
            # Match signals by symbol
            tech_by_symbol = {s.symbol: s for s in tech_signals}
            
            for news in news_signals:
                if news.symbol in tech_by_symbol:
                    tech = tech_by_symbol[news.symbol]
                    await self._evaluate_signal_pair(news, tech, db)
    
    async def evaluate_signals(
        self,
        symbol: str,
        news_signal_id: UUID,
        technical_signal_id: UUID,
        horizon: str = "short_term",
    ) -> TradeDecision:
        """Manually evaluate a specific signal pair."""
        async with get_db_context() as db:
            news = await db.get(NewsSignal, news_signal_id)
            tech = await db.get(TechnicalSignal, technical_signal_id)
            
            if not news or not tech:
                raise ValueError("Signal not found")
            
            return await self._evaluate_signal_pair(news, tech, db, horizon)
    
    async def _evaluate_signal_pair(
        self,
        news: NewsSignal,
        tech: TechnicalSignal,
        db,
        horizon: str = "short_term",
    ) -> Optional[TradeDecision]:
        """Evaluate a news/technical pair with the real src StrategyAgent."""
        from src.agents.strategy.strategy_agent import StrategyAgent
        from src.models.enums import (
            ImpactType, MarketCondition, Sentiment, TradeAction, TradingHorizon, TrendDirection,
        )
        from src.models.signals import (
            ConfluenceResult, NewsSignal as NewsSignalModel,
            SupportResistance, TechnicalSignal as TechnicalSignalModel,
        )

        def aware(dt: datetime) -> datetime:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        def levels(raw) -> list:
            out = []
            for lv in raw or []:
                try:
                    out.append(SupportResistance(
                        level=float(lv["level"]),
                        strength=float(lv.get("strength", 0.5)),
                        timeframe=str(lv.get("timeframe", "1y")),
                        last_tested=aware(datetime.fromisoformat(lv["last_tested"]))
                        if lv.get("last_tested") else datetime.now(timezone.utc),
                    ))
                except (KeyError, ValueError, TypeError):
                    continue
            return out

        news_model = NewsSignalModel(
            symbol=news.symbol,
            sentiment=Sentiment(news.sentiment),
            impact_type=ImpactType(news.impact_type),
            impact_score=float(news.impact_score),
            confidence=float(news.confidence),
            reasoning=news.reasoning,
            source_items=list(news.source_items or []),
            timestamp=aware(news.timestamp),
            expires_at=aware(news.expires_at),
        )
        tech_model = TechnicalSignalModel(
            symbol=tech.symbol,
            trend=TrendDirection(tech.trend),
            condition=MarketCondition(tech.condition),
            rsi=float(tech.rsi),
            current_price=float(tech.current_price),
            support_levels=levels(tech.support_levels),
            resistance_levels=levels(tech.resistance_levels),
            confluence=ConfluenceResult(
                score=min(1.0, float(tech.confluence_score)),
                factors=list(tech.confluence_factors or []),
                description=tech.confluence_description or "",
            ),
            volume_trend=tech.volume_trend,
            interest_rate_impact=float(tech.interest_rate_impact or 0.0),
            timestamp=aware(tech.timestamp),
        )

        class _NoPersist:
            async def persist_decision(self, *a, **k):
                return None

        agent = StrategyAgent(persistence=_NoPersist())
        result = await agent.evaluate(
            news_signal=news_model,
            technical_signal=tech_model,
            horizon=TradingHorizon(horizon),
        )
        news.consumed_by = "strategy_agent"
        tech.consumed_by = "strategy_agent"

        if not result.success or result.decision is None:
            logger.info(f"No decision for {news.symbol}: {result.error_message}")
            return None
        d = result.decision
        if d.action not in {TradeAction.BUY, TradeAction.STRONG_BUY, TradeAction.SELL, TradeAction.STRONG_SELL}:
            logger.info(f"{news.symbol}: {d.action.value} – not actionable")
            return None

        decision = TradeDecision(
            decision_id=uuid4(),
            symbol=d.symbol,
            action=d.action.value,
            conviction=d.conviction.value,
            horizon=d.horizon.value,
            entry_price=d.entry_price,
            stop_loss=d.stop_loss,
            take_profit=d.take_profit,
            position_size_pct=min(d.position_size_pct, settings.MAX_POSITION_PCT),
            risk_reward_ratio=d.risk_reward_ratio,
            reasoning=d.reasoning,
            news_signal_id=news.signal_id,
            technical_signal_id=tech.signal_id,
            timestamp=d.timestamp,
            expires_at=d.expires_at,
        )
        db.add(decision)

        await broadcast_decision({
            "decision_id": str(decision.decision_id),
            "symbol": decision.symbol,
            "action": decision.action,
            "conviction": decision.conviction,
            "entry_price": decision.entry_price,
            "stop_loss": decision.stop_loss,
            "take_profit": decision.take_profit,
            "risk_reward_ratio": decision.risk_reward_ratio,
            "reasoning": decision.reasoning,
        })
        return decision

    async def get_performance(self, period: str = "30d") -> dict:
        """Get strategy performance metrics."""
        from sqlalchemy import func
        from models.trade import TradeRecord
        
        # Parse period
        days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365, "all": 3650}.get(period, 30)
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        async with get_db_context() as db:
            result = await db.execute(
                select(
                    func.count(TradeRecord.trade_id).label("total"),
                    func.count(TradeRecord.trade_id).filter(
                        TradeRecord.status.in_(["closed_profit", "closed_tp"])
                    ).label("wins"),
                    func.avg(TradeRecord.pnl_pct).label("avg_pnl"),
                    func.min(TradeRecord.pnl_pct).label("max_drawdown"),
                )
                .where(
                    TradeRecord.opened_at >= cutoff,
                    TradeRecord.status != "open",
                )
            )
            
            row = result.fetchone()
            
            total = row.total or 0
            wins = row.wins or 0
            
            return {
                "total_trades": total,
                "winning_trades": wins,
                "win_rate": (wins / total * 100) if total > 0 else 0,
                "avg_risk_reward": 2.0,  # Would need to calculate from actual trades
                "max_drawdown": row.max_drawdown or 0,
                "sharpe_ratio": None,  # Would need more complex calculation
            }
    
    async def backtest(self, symbol: str, start_date: datetime, end_date: datetime) -> dict:
        """Run the sandbox backtest on daily bars covering [start_date, end_date]."""
        from services.sandbox_service import SandboxRequest, run_sandbox

        days = max(300, (end_date - start_date).days)
        result = await run_sandbox(SandboxRequest(symbol=symbol, timeframe="D1", bars=days))
        result.pop("candles", None)
        return result

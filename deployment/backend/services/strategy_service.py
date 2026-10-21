"""Strategy Agent service."""
import logging
from datetime import datetime, timedelta
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
    ) -> TradeDecision:
        """Evaluate a news/technical signal pair using the decision matrix."""
        from src.agents.strategy.decision_matrix import evaluate_decision_matrix
        from src.agents.strategy.stop_loss import calculate_stop_loss
        from src.agents.strategy.take_profit import calculate_take_profit
        
        # Apply decision matrix
        action, conviction = evaluate_decision_matrix(
            sentiment=news.sentiment,
            condition=tech.condition,
            confluence_score=tech.confluence_score,
        )
        
        # Skip if no trade
        if action == "no_trade":
            logger.info(f"No trade for {news.symbol}: conflicting signals")
            return None
        
        # Calculate entry, stop-loss, take-profit
        entry_price = tech.current_price
        
        support_levels = [s["level"] for s in tech.support_levels]
        resistance_levels = [r["level"] for r in tech.resistance_levels]
        
        stop_loss = calculate_stop_loss(
            action=action,
            entry_price=entry_price,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            horizon=horizon,
        )
        
        take_profit = calculate_take_profit(
            action=action,
            entry_price=entry_price,
            stop_loss=stop_loss,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            horizon=horizon,
        )
        
        # Calculate risk-reward ratio
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)
        risk_reward_ratio = reward / risk if risk > 0 else 0
        
        # Validate minimum risk-reward
        if risk_reward_ratio < 1.5:
            logger.info(f"Skipping {news.symbol}: risk-reward {risk_reward_ratio:.2f} < 1.5")
            return None
        
        # Calculate position size based on conviction
        position_size_pct = self._calculate_position_size(conviction, risk_reward_ratio)
        
        # Create decision
        decision = TradeDecision(
            decision_id=uuid4(),
            symbol=news.symbol,
            action=action,
            conviction=conviction,
            horizon=horizon,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_pct=position_size_pct,
            risk_reward_ratio=risk_reward_ratio,
            reasoning=f"News: {news.sentiment}, Tech: {tech.condition}, Confluence: {tech.confluence_score:.2f}",
            news_signal_id=news.signal_id,
            technical_signal_id=tech.signal_id,
            timestamp=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=4),
        )
        
        # Mark signals as consumed
        news.consumed_by = "strategy_agent"
        tech.consumed_by = "strategy_agent"
        
        db.add(decision)
        
        # Broadcast decision
        await broadcast_decision({
            "decision_id": str(decision.decision_id),
            "symbol": decision.symbol,
            "action": decision.action,
            "conviction": decision.conviction,
            "entry_price": decision.entry_price,
            "stop_loss": decision.stop_loss,
            "take_profit": decision.take_profit,
            "risk_reward_ratio": decision.risk_reward_ratio,
        })
        
        return decision
    
    def _calculate_position_size(self, conviction: str, risk_reward: float) -> float:
        """Calculate position size based on conviction and risk-reward."""
        base_size = {
            "high": 0.04,
            "medium": 0.025,
            "low": 0.01,
        }.get(conviction, 0.01)
        
        # Adjust based on risk-reward
        if risk_reward >= 3.0:
            base_size *= 1.2
        elif risk_reward < 2.0:
            base_size *= 0.8
        
        # Cap at max position size
        return min(base_size, settings.MAX_POSITION_PCT)
    
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
        """Run backtest for a symbol over a date range."""
        # This would integrate with the existing backtest logic
        # For now, return placeholder
        return {
            "symbol": symbol,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "status": "not_implemented",
            "message": "Backtest functionality requires historical data integration",
        }

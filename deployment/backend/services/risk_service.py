"""Risk Manager service."""
import logging
from datetime import datetime, date
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select, func

from core.config import settings
from core.database import get_db_context
from models.trade import TradeDecision, TradeRecord
from models.risk import RiskAssessment, DailyLossTracking
from api.websocket import broadcast_risk_alert

logger = logging.getLogger(__name__)


class RiskService:
    """Service for risk management and validation."""
    
    async def assess_trade(self, decision_id: UUID) -> RiskAssessment:
        """Assess risk for a trade decision."""
        async with get_db_context() as db:
            decision = await db.get(TradeDecision, decision_id)
            if not decision:
                raise ValueError("Decision not found")
            
            warnings = []
            rejection_reason = None
            approved = True
            adjusted_size = None
            
            # Get portfolio info
            portfolio = await self._get_portfolio_info(db)
            
            # Check 1: Position size limit (5%)
            if decision.position_size_pct > settings.MAX_POSITION_PCT:
                warnings.append(f"Position size {decision.position_size_pct:.1%} exceeds limit {settings.MAX_POSITION_PCT:.1%}")
                adjusted_size = settings.MAX_POSITION_PCT
            
            # Check 2: Portfolio risk per trade (2%)
            risk_per_trade = self._calculate_trade_risk(decision, portfolio["total_value"])
            if risk_per_trade > settings.MAX_PORTFOLIO_RISK_PCT:
                warnings.append(f"Trade risk {risk_per_trade:.1%} exceeds limit {settings.MAX_PORTFOLIO_RISK_PCT:.1%}")
                # Adjust position size to meet risk limit
                adjusted_size = self._adjust_for_risk_limit(decision, portfolio["total_value"])
            
            # Check 3: Correlated exposure (20%)
            correlated_exposure = await self._get_correlated_exposure(db, decision.symbol)
            if correlated_exposure + (adjusted_size or decision.position_size_pct) > settings.MAX_CORRELATED_EXPOSURE:
                warnings.append(f"Correlated exposure would exceed {settings.MAX_CORRELATED_EXPOSURE:.0%}")
                max_allowed = settings.MAX_CORRELATED_EXPOSURE - correlated_exposure
                if max_allowed <= 0:
                    approved = False
                    rejection_reason = "Correlated exposure limit reached"
                else:
                    adjusted_size = min(adjusted_size or decision.position_size_pct, max_allowed)
            
            # Check 4: Daily loss limit (5%)
            daily_loss = await self._get_daily_loss(db)
            if daily_loss["trading_halted"]:
                approved = False
                rejection_reason = "Daily loss limit breached - trading halted"
                await broadcast_risk_alert({
                    "type": "daily_loss_limit",
                    "message": "Trading halted due to daily loss limit",
                    "loss_pct": daily_loss["loss_pct"],
                })
            
            # Check 5: Open positions limit (10)
            open_count = portfolio["open_positions_count"]
            if open_count >= settings.MAX_OPEN_POSITIONS:
                approved = False
                rejection_reason = f"Maximum open positions ({settings.MAX_OPEN_POSITIONS}) reached"
            
            # Calculate risk score
            risk_score = self._calculate_risk_score(
                position_size=adjusted_size or decision.position_size_pct,
                trade_risk=risk_per_trade,
                correlated_exposure=correlated_exposure,
                daily_loss_pct=daily_loss["loss_pct"],
                open_positions=open_count,
            )
            
            # Create assessment
            assessment = RiskAssessment(
                id=uuid4(),
                decision_id=decision_id,
                approved=approved,
                adjusted_size=adjusted_size,
                risk_score=risk_score,
                warnings=warnings,
                rejection_reason=rejection_reason,
            )
            
            db.add(assessment)
            
            return assessment
    
    async def get_portfolio_risk(self) -> dict:
        """Get current portfolio risk status."""
        async with get_db_context() as db:
            portfolio = await self._get_portfolio_info(db)
            daily_loss = await self._get_daily_loss(db)
            
            # Get correlated exposure by sector/correlation group
            correlated = await self._get_all_correlated_exposures(db)
            
            return {
                "total_value": portfolio["total_value"],
                "open_positions_count": portfolio["open_positions_count"],
                "total_exposure": portfolio["total_exposure"],
                "correlated_exposure": correlated,
                "daily_loss": daily_loss["cumulative_loss"],
                "daily_loss_pct": daily_loss["loss_pct"],
                "trading_halted": daily_loss["trading_halted"],
            }
    
    async def get_daily_loss(self) -> dict:
        """Get current day's loss tracking."""
        async with get_db_context() as db:
            return await self._get_daily_loss(db)
    
    async def reset_daily_loss(self):
        """Reset daily loss tracking (for testing)."""
        async with get_db_context() as db:
            today = date.today()
            result = await db.execute(
                select(DailyLossTracking).where(DailyLossTracking.date == today)
            )
            tracking = result.scalar_one_or_none()
            
            if tracking:
                tracking.cumulative_loss = 0
                tracking.loss_pct = 0
                tracking.trading_halted = False
    
    async def _get_portfolio_info(self, db) -> dict:
        """Get portfolio information."""
        # Get open positions
        result = await db.execute(
            select(
                func.count(TradeRecord.trade_id).label("count"),
                func.sum(TradeRecord.position_size * TradeRecord.entry_price).label("exposure"),
            )
            .where(TradeRecord.status == "open")
        )
        row = result.fetchone()
        
        # In production, this would come from MT5 account info
        total_value = 100000.0  # Placeholder
        
        return {
            "total_value": total_value,
            "open_positions_count": row.count or 0,
            "total_exposure": row.exposure or 0,
        }
    
    async def _get_daily_loss(self, db) -> dict:
        """Get today's loss tracking."""
        today = date.today()
        
        result = await db.execute(
            select(DailyLossTracking).where(DailyLossTracking.date == today)
        )
        tracking = result.scalar_one_or_none()
        
        if not tracking:
            # Create new tracking for today
            portfolio = await self._get_portfolio_info(db)
            tracking = DailyLossTracking(
                date=today,
                cumulative_loss=0,
                portfolio_value=portfolio["total_value"],
                loss_pct=0,
                trading_halted=False,
            )
            db.add(tracking)
        
        return {
            "date": tracking.date,
            "cumulative_loss": tracking.cumulative_loss,
            "portfolio_value": tracking.portfolio_value,
            "loss_pct": tracking.loss_pct,
            "trading_halted": tracking.trading_halted,
        }
    
    async def _get_correlated_exposure(self, db, symbol: str) -> float:
        """Get exposure in assets correlated with the given symbol."""
        # Simplified correlation groups (in production, use actual correlation data)
        tech_stocks = {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA"}
        
        if symbol in tech_stocks:
            correlated_symbols = tech_stocks
        else:
            correlated_symbols = {symbol}
        
        result = await db.execute(
            select(func.sum(TradeRecord.position_size * TradeRecord.entry_price))
            .where(
                TradeRecord.status == "open",
                TradeRecord.symbol.in_(correlated_symbols),
            )
        )
        
        exposure = result.scalar() or 0
        portfolio = await self._get_portfolio_info(db)
        
        return exposure / portfolio["total_value"] if portfolio["total_value"] > 0 else 0
    
    async def _get_all_correlated_exposures(self, db) -> dict:
        """Get all correlated exposures by group."""
        # Simplified - in production, use actual correlation matrix
        return {
            "tech": 0.15,
            "finance": 0.05,
            "energy": 0.0,
        }
    
    def _calculate_trade_risk(self, decision: TradeDecision, portfolio_value: float) -> float:
        """Calculate risk as percentage of portfolio."""
        position_value = decision.position_size_pct * portfolio_value
        risk_per_share = abs(decision.entry_price - decision.stop_loss)
        shares = position_value / decision.entry_price
        total_risk = shares * risk_per_share
        
        return total_risk / portfolio_value if portfolio_value > 0 else 0
    
    def _adjust_for_risk_limit(self, decision: TradeDecision, portfolio_value: float) -> float:
        """Adjust position size to meet risk limit."""
        max_risk = settings.MAX_PORTFOLIO_RISK_PCT * portfolio_value
        risk_per_share = abs(decision.entry_price - decision.stop_loss)
        max_shares = max_risk / risk_per_share if risk_per_share > 0 else 0
        max_position_value = max_shares * decision.entry_price
        
        return max_position_value / portfolio_value if portfolio_value > 0 else 0
    
    def _calculate_risk_score(
        self,
        position_size: float,
        trade_risk: float,
        correlated_exposure: float,
        daily_loss_pct: float,
        open_positions: int,
    ) -> float:
        """Calculate overall risk score (0-1)."""
        # Weighted risk factors
        score = 0.0
        
        # Position size contribution (0-0.25)
        score += min(position_size / settings.MAX_POSITION_PCT, 1.0) * 0.25
        
        # Trade risk contribution (0-0.25)
        score += min(trade_risk / settings.MAX_PORTFOLIO_RISK_PCT, 1.0) * 0.25
        
        # Correlated exposure contribution (0-0.2)
        score += min(correlated_exposure / settings.MAX_CORRELATED_EXPOSURE, 1.0) * 0.2
        
        # Daily loss contribution (0-0.2)
        score += min(daily_loss_pct / settings.MAX_DAILY_LOSS_PCT, 1.0) * 0.2
        
        # Open positions contribution (0-0.1)
        score += min(open_positions / settings.MAX_OPEN_POSITIONS, 1.0) * 0.1
        
        return min(score, 1.0)

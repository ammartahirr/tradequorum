"""Trading Pipeline - Wires all components together."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.models import NewsItem, NewsSignal, TechnicalSignal, OHLCV
from src.models.enums import TradeAction, TradingHorizon
from src.models.trading import TradeDecision, OrderResult, RiskAssessment

from src.agents.news.analyzer import analyze_news_impact, ClaudeOpusClient
from src.agents.news.persistence import SignalPersistence as NewsSignalPersistence
from src.agents.technical.signal_generator import TechnicalSignalGenerator
from src.agents.technical.market_data import StaleDataDetector
from src.agents.strategy.strategy_agent import StrategyAgent
from src.agents.risk.risk_manager import RiskManager, Portfolio
from src.agents.risk.exposure_tracker import OpenPosition

from src.execution.order_executor import OrderExecutor
from src.execution.position_manager import PositionManager
from src.execution.websocket_broadcaster import WebSocketBroadcaster
from src.execution.trade_persistence import TradePersistence

from .pipeline_config import PipelineConfig, DEFAULT_PIPELINE_CONFIG

logger = logging.getLogger(__name__)


class TradingPipelineError(Exception):
    """Exception raised when pipeline execution fails."""
    pass


class PipelineResult:
    """Result of a pipeline execution."""
    
    def __init__(
        self,
        success: bool,
        symbol: str,
        news_signal: Optional[NewsSignal] = None,
        technical_signal: Optional[TechnicalSignal] = None,
        trade_decision: Optional[TradeDecision] = None,
        risk_assessment: Optional[RiskAssessment] = None,
        order_result: Optional[OrderResult] = None,
        error_message: Optional[str] = None,
        stage_reached: str = "init",
    ):
        self.success = success
        self.symbol = symbol
        self.news_signal = news_signal
        self.technical_signal = technical_signal
        self.trade_decision = trade_decision
        self.risk_assessment = risk_assessment
        self.order_result = order_result
        self.error_message = error_message
        self.stage_reached = stage_reached




class TradingPipeline:
    """Main trading pipeline that wires all components together."""
    
    def __init__(
        self,
        config: PipelineConfig = None,
        llm_client: Optional[ClaudeOpusClient] = None,
        mt5_client: Any = None,
    ):
        self.config = config or DEFAULT_PIPELINE_CONFIG
        self._llm_client = llm_client
        self._mt5_client = mt5_client
        self._init_components()
        self._is_running = False

    def _init_components(self) -> None:
        """Initialize all pipeline components."""
        self._websocket_broadcaster = WebSocketBroadcaster(
            config=self.config.execution_config,
        )
        self._trade_persistence = TradePersistence(
            config=self.config.execution_config,
        )
        self._news_persistence = None
        if self.config.enable_persistence:
            self._news_persistence = NewsSignalPersistence(
                table_name=self.config.signals_table,
            )
        
        self._stale_detector = StaleDataDetector(
            self.config.technical_config.stale_data
        )
        self._technical_generator = TechnicalSignalGenerator(
            use_sagemaker=self.config.use_sagemaker,
        )
        self._strategy_agent = StrategyAgent(
            config=self.config.strategy_config,
            stale_data_detector=self._stale_detector.is_stale,
        )
        self._risk_manager = RiskManager(
            config=self.config.risk_config,
            alert_callback=self._on_risk_alert,
        )
        self._position_manager = PositionManager(
            config=self.config.execution_config,
            websocket_broadcaster=self._websocket_broadcaster,
            trade_persistence=self._trade_persistence,
            risk_manager=self._risk_manager,
        )
        self._order_executor = OrderExecutor(
            config=self.config.execution_config,
            mt5_client=self._mt5_client,
            websocket_broadcaster=self._websocket_broadcaster,
            trade_persistence=self._trade_persistence,
        )

    async def _on_risk_alert(self, alert_type: str, alert_data: dict) -> None:
        """Handle risk alerts by broadcasting to dashboard."""
        if self.config.enable_websocket_broadcasts:
            await self._websocket_broadcaster.broadcast_alert(alert_type, alert_data)

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def position_manager(self) -> PositionManager:
        return self._position_manager

    @property
    def risk_manager(self) -> RiskManager:
        return self._risk_manager

    @property
    def websocket_broadcaster(self) -> WebSocketBroadcaster:
        return self._websocket_broadcaster

    def add_websocket_connection(self, connection_id: str) -> None:
        """Add a WebSocket connection for dashboard updates."""
        self._websocket_broadcaster.add_connection(connection_id)

    def remove_websocket_connection(self, connection_id: str) -> None:
        """Remove a WebSocket connection."""
        self._websocket_broadcaster.remove_connection(connection_id)



    async def analyze_news(
        self, news_item: NewsItem
    ) -> tuple[NewsSignal, Optional[str]]:
        """Stage 1: Analyze news item and generate NewsSignal."""
        llm_client = self._llm_client if self.config.use_llm else None
        signal = await analyze_news_impact(news_item, llm_client=llm_client)
        
        signal_id = None
        if self._news_persistence:
            signal_id = await self._news_persistence.persist_news_signal(signal)
        
        logger.info(f"News analysis: {signal.symbol} - {signal.sentiment.value}")
        return signal, signal_id

    async def analyze_technical(
        self, symbol: str, candles: List[OHLCV]
    ) -> tuple[TechnicalSignal, Optional[str]]:
        """Stage 2: Analyze market data and generate TechnicalSignal."""
        self._stale_detector.record_update(symbol, datetime.now(timezone.utc))
        signal, signal_id = await self._technical_generator.generate_and_persist_signal(
            symbol=symbol, candles=candles
        )
        logger.info(f"Technical analysis: {symbol} - {signal.condition.value}")
        return signal, signal_id

    async def evaluate_strategy(
        self,
        news_signal: NewsSignal,
        technical_signal: TechnicalSignal,
        horizon: TradingHorizon = TradingHorizon.SHORT_TERM,
        news_signal_id: Optional[str] = None,
        technical_signal_id: Optional[str] = None,
    ) -> tuple[Optional[TradeDecision], Optional[str]]:
        """Stage 3: Evaluate signals and generate TradeDecision."""
        result = await self._strategy_agent.evaluate(
            news_signal=news_signal,
            technical_signal=technical_signal,
            horizon=horizon,
            news_signal_id=news_signal_id,
            technical_signal_id=technical_signal_id,
        )
        
        if not result.success:
            logger.warning(f"Strategy failed: {result.error_message}")
            return None, None
        
        action = result.decision.action.value if result.decision else "NO_DECISION"
        logger.info(f"Strategy: {news_signal.symbol} - {action}")
        return result.decision, result.decision_id

    async def assess_risk(
        self, decision: TradeDecision, portfolio_value: float
    ) -> RiskAssessment:
        """Stage 4: Assess trade risk against portfolio constraints."""
        open_positions = [
            OpenPosition(
                symbol=p.symbol,
                position_size_pct=p.position_size / portfolio_value,
                entry_price=p.entry_price,
            )
            for p in self._position_manager.get_open_positions()
        ]
        
        portfolio = Portfolio(total_value=portfolio_value, open_positions=open_positions)
        assessment = self._risk_manager.assess_trade(decision, portfolio)
        
        status = "APPROVED" if assessment.approved else "REJECTED"
        logger.info(f"Risk: {decision.symbol} - {status}")
        return assessment

    async def execute_order(
        self, decision: TradeDecision, size: float
    ) -> Optional[OrderResult]:
        """Stage 5: Execute the approved order."""
        try:
            result = await self._order_executor.place_order(decision, size)
            logger.info(f"Order: {decision.symbol} - {result.order_id}")
            return result
        except Exception as e:
            logger.error(f"Order failed: {decision.symbol} - {e}")
            return None

    async def open_position_from_order(
        self, decision: TradeDecision, order_result: OrderResult
    ) -> None:
        """Stage 6: Track the new position."""
        await self._position_manager.open_position(
            trade_id=str(uuid.uuid4()),
            symbol=decision.symbol,
            entry_price=order_result.filled_price,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            position_size=order_result.filled_quantity,
            action=decision.action,
            exness_order_id=order_result.order_id,
        )



    async def run_full_pipeline(
        self,
        news_item: NewsItem,
        candles: List[OHLCV],
        portfolio_value: float,
        horizon: TradingHorizon = TradingHorizon.SHORT_TERM,
    ) -> PipelineResult:
        """Run the complete trading pipeline from news to execution."""
        symbol = news_item.symbols[0] if news_item.symbols else "UNKNOWN"
        
        try:
            news_signal, news_signal_id = await self.analyze_news(news_item)
            technical_signal, tech_signal_id = await self.analyze_technical(
                symbol, candles
            )
            decision, decision_id = await self.evaluate_strategy(
                news_signal, technical_signal, horizon, news_signal_id, tech_signal_id
            )
            
            non_actionable = {
                TradeAction.NO_TRADE, TradeAction.HOLD, TradeAction.WAIT_PULLBACK
            }
            if decision is None or decision.action in non_actionable:
                return PipelineResult(
                    success=True, symbol=symbol,
                    news_signal=news_signal, technical_signal=technical_signal,
                    trade_decision=decision, stage_reached="strategy",
                )
            
            risk_assessment = await self.assess_risk(decision, portfolio_value)
            
            if not risk_assessment.approved:
                return PipelineResult(
                    success=True, symbol=symbol,
                    news_signal=news_signal, technical_signal=technical_signal,
                    trade_decision=decision, risk_assessment=risk_assessment,
                    stage_reached="risk", error_message=risk_assessment.rejection_reason,
                )
            
            size = risk_assessment.adjusted_size or decision.position_size_pct
            order_result = await self.execute_order(decision, size * portfolio_value)
            
            if order_result is None:
                return PipelineResult(
                    success=False, symbol=symbol,
                    news_signal=news_signal, technical_signal=technical_signal,
                    trade_decision=decision, risk_assessment=risk_assessment,
                    stage_reached="execution", error_message="Order execution failed",
                )
            
            await self.open_position_from_order(decision, order_result)
            
            return PipelineResult(
                success=True, symbol=symbol,
                news_signal=news_signal, technical_signal=technical_signal,
                trade_decision=decision, risk_assessment=risk_assessment,
                order_result=order_result, stage_reached="complete",
            )
            
        except Exception as e:
            logger.error(f"Pipeline error for {symbol}: {e}")
            return PipelineResult(
                success=False, symbol=symbol,
                error_message=str(e), stage_reached="error",
            )

'''
Backtester for strategy validation.

Runs the trading strategy against historical data to validate:
- Win rate metrics
- Drawdown metrics
- Risk-reward performance

Requirements: All (Backtest Validation)
'''

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

from src.models import NewsItem, NewsSignal, TechnicalSignal, OHLCV
from src.models.enums import (
    Conviction, ImpactType, MarketCondition, Sentiment,
    TradeAction, TradingHorizon, TrendDirection,
)
from src.models.signals import ConfluenceResult, SupportResistance

from src.agents.technical.signal_generator import TechnicalSignalGenerator
from src.agents.strategy.strategy_agent import StrategyAgent
from src.agents.strategy.config import StrategyConfig

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    '''Configuration for backtesting.'''
    initial_capital: float = 100000.0
    position_size_pct: float = 0.05
    max_positions: int = 10
    commission_pct: float = 0.001
    slippage_pct: float = 0.0005


@dataclass
class TradeResult:
    '''Result of a single trade in backtest.'''
    symbol: str
    action: TradeAction
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    position_size: float
    pnl: float
    pnl_pct: float
    exit_reason: str  # 'tp', 'sl', 'timeout'


@dataclass
class BacktestResult:
    '''Result of a backtest run.'''
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    total_pnl_pct: float
    max_drawdown: float
    max_drawdown_pct: float
    avg_win: float
    avg_loss: float
    avg_risk_reward: float
    sharpe_ratio: float
    trades: List[TradeResult] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        '''Convert to dictionary for reporting.'''
        return {
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'total_pnl': self.total_pnl,
            'total_pnl_pct': self.total_pnl_pct,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': self.max_drawdown_pct,
            'avg_win': self.avg_win,
            'avg_loss': self.avg_loss,
            'avg_risk_reward': self.avg_risk_reward,
            'sharpe_ratio': self.sharpe_ratio,
        }


class Backtester:
    '''
    Backtester for validating trading strategy against historical data.
    
    Simulates the trading pipeline using historical OHLCV data and
    synthetic news signals to validate strategy performance.
    '''
    
    def __init__(
        self,
        config: BacktestConfig = None,
        strategy_config: StrategyConfig = None,
    ):
        self.config = config or BacktestConfig()
        self.strategy_config = strategy_config or StrategyConfig()
        self._strategy_agent = StrategyAgent(config=self.strategy_config)
        self._technical_generator = TechnicalSignalGenerator(use_sagemaker=False)
    
    def _generate_synthetic_news_signal(
        self,
        symbol: str,
        timestamp: datetime,
        price_change_pct: float,
    ) -> NewsSignal:
        '''Generate synthetic news signal based on price movement.'''
        if price_change_pct > 0.03:
            sentiment = Sentiment.VERY_BULLISH
            impact_score = 0.9
        elif price_change_pct > 0.01:
            sentiment = Sentiment.BULLISH
            impact_score = 0.7
        elif price_change_pct < -0.03:
            sentiment = Sentiment.VERY_BEARISH
            impact_score = 0.9
        elif price_change_pct < -0.01:
            sentiment = Sentiment.BEARISH
            impact_score = 0.7
        else:
            sentiment = Sentiment.NEUTRAL
            impact_score = 0.5
        
        return NewsSignal(
            symbol=symbol,
            sentiment=sentiment,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=impact_score,
            confidence=0.8,
            reasoning='Synthetic signal for backtest',
            source_items=['backtest'],
            timestamp=timestamp,
            expires_at=timestamp + timedelta(hours=72),
        )
    
    async def _generate_technical_signal(
        self,
        symbol: str,
        candles: List[OHLCV],
    ) -> TechnicalSignal:
        '''Generate technical signal from candles.'''
        return await self._technical_generator.generate_signal(symbol, candles)
    
    def _simulate_trade_exit(
        self,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        action: TradeAction,
        future_candles: List[OHLCV],
        max_hold_days: int = 30,
    ) -> tuple[float, str, int]:
        '''
        Simulate trade exit based on future price action.
        
        Returns: (exit_price, exit_reason, days_held)
        '''
        is_buy = action in {TradeAction.BUY, TradeAction.STRONG_BUY}
        
        for i, candle in enumerate(future_candles[:max_hold_days]):
            if is_buy:
                if candle.low <= stop_loss:
                    return stop_loss, 'sl', i + 1
                if candle.high >= take_profit:
                    return take_profit, 'tp', i + 1
            else:
                if candle.high >= stop_loss:
                    return stop_loss, 'sl', i + 1
                if candle.low <= take_profit:
                    return take_profit, 'tp', i + 1
        
        # Timeout - exit at last close
        if future_candles:
            return future_candles[min(max_hold_days - 1, len(future_candles) - 1)].close, 'timeout', max_hold_days
        return entry_price, 'timeout', 0
    
    def _calculate_pnl(
        self,
        entry_price: float,
        exit_price: float,
        position_size: float,
        action: TradeAction,
        commission_pct: float,
    ) -> tuple[float, float]:
        '''Calculate PnL for a trade.'''
        is_buy = action in {TradeAction.BUY, TradeAction.STRONG_BUY}
        
        if is_buy:
            gross_pnl = (exit_price - entry_price) * position_size / entry_price
        else:
            gross_pnl = (entry_price - exit_price) * position_size / entry_price
        
        commission = position_size * commission_pct * 2  # Entry and exit
        net_pnl = gross_pnl - commission
        pnl_pct = net_pnl / position_size * 100
        
        return net_pnl, pnl_pct
    
    def _calculate_max_drawdown(self, equity_curve: List[float]) -> tuple[float, float]:
        '''Calculate maximum drawdown from equity curve.'''
        if not equity_curve:
            return 0.0, 0.0
        
        peak = equity_curve[0]
        max_dd = 0.0
        max_dd_pct = 0.0
        
        for equity in equity_curve:
            if equity > peak:
                peak = equity
            dd = peak - equity
            dd_pct = dd / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd_pct
        
        return max_dd, max_dd_pct
    
    def _calculate_sharpe_ratio(
        self,
        returns: List[float],
        risk_free_rate: float = 0.02,
    ) -> float:
        '''Calculate Sharpe ratio from returns.'''
        if not returns or len(returns) < 2:
            return 0.0
        
        import statistics
        avg_return = statistics.mean(returns)
        std_return = statistics.stdev(returns)
        
        if std_return == 0:
            return 0.0
        
        # Annualize (assuming daily returns)
        annual_return = avg_return * 252
        annual_std = std_return * (252 ** 0.5)
        
        return (annual_return - risk_free_rate) / annual_std
    
    async def run_backtest(
        self,
        symbol: str,
        candles: List[OHLCV],
        horizon: TradingHorizon = TradingHorizon.SHORT_TERM,
    ) -> BacktestResult:
        '''
        Run backtest on historical data.
        
        Args:
            symbol: Trading symbol
            candles: Historical OHLCV data (at least 2 years recommended)
            horizon: Trading horizon
            
        Returns:
            BacktestResult with performance metrics
        '''
        if len(candles) < 250:
            raise ValueError('Need at least 250 candles for backtest')
        
        trades: List[TradeResult] = []
        equity = self.config.initial_capital
        equity_curve = [equity]
        daily_returns: List[float] = []
        
        # Start from day 200 to have enough history for indicators
        start_idx = 200
        
        for i in range(start_idx, len(candles) - 30):
            # Get historical candles up to current point
            historical = candles[:i + 1]
            current_candle = candles[i]
            
            # Calculate price change for synthetic news
            if i > 0:
                price_change = (current_candle.close - candles[i - 1].close) / candles[i - 1].close
            else:
                price_change = 0
            
            # Generate signals
            news_signal = self._generate_synthetic_news_signal(
                symbol, current_candle.timestamp, price_change
            )
            
            try:
                tech_signal = await self._generate_technical_signal(symbol, historical)
            except Exception:
                continue
            
            # Evaluate strategy
            result = await self._strategy_agent.evaluate(
                news_signal=news_signal,
                technical_signal=tech_signal,
                horizon=horizon,
            )
            
            if not result.success or result.decision is None:
                continue
            
            decision = result.decision
            
            # Skip non-actionable decisions
            actionable = {TradeAction.BUY, TradeAction.STRONG_BUY, TradeAction.SELL, TradeAction.STRONG_SELL}
            if decision.action not in actionable:
                continue
            
            # Calculate position size
            position_size = equity * self.config.position_size_pct
            
            # Get future candles for trade simulation
            future_candles = candles[i + 1:i + 31]
            
            # Simulate trade
            exit_price, exit_reason, days_held = self._simulate_trade_exit(
                entry_price=decision.entry_price,
                stop_loss=decision.stop_loss,
                take_profit=decision.take_profit,
                action=decision.action,
                future_candles=future_candles,
            )
            
            # Calculate PnL
            pnl, pnl_pct = self._calculate_pnl(
                entry_price=decision.entry_price,
                exit_price=exit_price,
                position_size=position_size,
                action=decision.action,
                commission_pct=self.config.commission_pct,
            )
            
            # Record trade
            trade = TradeResult(
                symbol=symbol,
                action=decision.action,
                entry_price=decision.entry_price,
                exit_price=exit_price,
                entry_time=current_candle.timestamp,
                exit_time=current_candle.timestamp + timedelta(days=days_held),
                position_size=position_size,
                pnl=pnl,
                pnl_pct=pnl_pct,
                exit_reason=exit_reason,
            )
            trades.append(trade)
            
            # Update equity
            equity += pnl
            equity_curve.append(equity)
            daily_returns.append(pnl / (equity - pnl) if equity > pnl else 0)
            
            # Skip ahead to avoid overlapping trades
            # (simplified - in production would track open positions)
        
        # Calculate metrics
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl <= 0]
        
        total_trades = len(trades)
        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = win_count / total_trades if total_trades > 0 else 0
        
        total_pnl = sum(t.pnl for t in trades)
        total_pnl_pct = (equity - self.config.initial_capital) / self.config.initial_capital * 100
        
        avg_win = sum(t.pnl for t in winning_trades) / win_count if win_count > 0 else 0
        avg_loss = sum(t.pnl for t in losing_trades) / loss_count if loss_count > 0 else 0
        
        avg_rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
        max_dd, max_dd_pct = self._calculate_max_drawdown(equity_curve)
        sharpe = self._calculate_sharpe_ratio(daily_returns)
        
        return BacktestResult(
            total_trades=total_trades,
            winning_trades=win_count,
            losing_trades=loss_count,
            win_rate=win_rate,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            max_drawdown=max_dd,
            max_drawdown_pct=max_dd_pct,
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_risk_reward=avg_rr,
            sharpe_ratio=sharpe,
            trades=trades,
            equity_curve=equity_curve,
        )

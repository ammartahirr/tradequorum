"""
Backtester / training sandbox for strategy validation.

Replays historical candles through the bot's *real* Technical Agent and
Strategy Agent, then simulates bracket-order execution bar by bar:

- signal is computed on the close of bar ``i`` (no look-ahead)
- entry fills at the open of bar ``i+1`` (+ slippage)
- stop-loss / take-profit are checked against each following bar's range;
  gaps through a level fill at the open; if both are touched in one bar the
  stop-loss is assumed first (conservative)
- one open position at a time, max holding period in bars
- equity curve is marked-to-market every bar

Historical news is not available offline, so the News Agent is replaced by a
transparent *price-momentum proxy* (``news_mode``): the bar's return z-score
is mapped to a sentiment. Use ``news_mode="neutral"`` to see the strategy with
no news input (it will rarely trade – by design of the decision matrix).

Requirements: All (Backtest Validation)
"""

from __future__ import annotations

import logging
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.agents.strategy.config import StrategyConfig
from src.agents.strategy.strategy_agent import StrategyAgent
from src.agents.technical.signal_generator import TechnicalSignalGenerator
from src.models import OHLCV, NewsSignal, TechnicalSignal
from src.models.enums import ImpactType, Sentiment, TradeAction, TradingHorizon

logger = logging.getLogger(__name__)

BUY_ACTIONS = {TradeAction.BUY, TradeAction.STRONG_BUY}
SELL_ACTIONS = {TradeAction.SELL, TradeAction.STRONG_SELL}
ACTIONABLE = BUY_ACTIONS | SELL_ACTIONS


class _NullPersistence:
    """Strategy persistence that does nothing (no DynamoDB writes in backtests)."""

    async def persist_decision(self, *args, **kwargs) -> Optional[str]:
        return None


@dataclass
class BacktestConfig:
    """Configuration for backtesting."""

    initial_capital: float = 100000.0
    # "strategy" = use the Strategy Agent's conviction-based size (5%/3%/1%),
    # "fixed"    = always use ``position_size_pct``
    sizing_mode: str = "fixed"
    position_size_pct: float = 0.05
    max_risk_per_trade_pct: float = 0.02  # cap: equity at risk between entry and SL
    max_positions: int = 1
    commission_pct: float = 0.001
    slippage_pct: float = 0.0005
    max_hold_bars: int = 30
    warmup_bars: int = 200
    lookback_bars: int = 500  # rolling window fed to the Technical Agent
    news_mode: str = "momentum"  # "momentum" | "neutral"
    allow_short: bool = True
    max_signal_log: int = 500


@dataclass
class TradeResult:
    """Result of a single trade in backtest."""

    symbol: str
    action: TradeAction
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    position_size: float  # notional at entry
    pnl: float
    pnl_pct: float
    exit_reason: str  # 'tp' | 'sl' | 'timeout' | 'end_of_data'
    stop_loss: float = 0.0
    take_profit: float = 0.0
    quantity: float = 0.0
    signal_time: Optional[datetime] = None
    bars_held: int = 0
    conviction: str = ""
    planned_rr: float = 0.0
    r_multiple: float = 0.0
    rsi: float = 0.0
    confluence: float = 0.0
    news_sentiment: str = ""
    reasoning: str = ""

    @property
    def side(self) -> str:
        return "long" if self.action in BUY_ACTIONS else "short"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action": self.action.value,
            "side": self.side,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat(),
            "signal_time": self.signal_time.isoformat() if self.signal_time else None,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "quantity": self.quantity,
            "position_size": self.position_size,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "exit_reason": self.exit_reason,
            "bars_held": self.bars_held,
            "conviction": self.conviction,
            "planned_rr": self.planned_rr,
            "r_multiple": self.r_multiple,
            "rsi": self.rsi,
            "confluence": self.confluence,
            "news_sentiment": self.news_sentiment,
            "reasoning": self.reasoning,
        }


@dataclass
class BacktestResult:
    """Result of a backtest run."""

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
    avg_risk_reward: float  # realised avg win / |avg loss|
    sharpe_ratio: float
    trades: List[TradeResult] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    equity_times: List[datetime] = field(default_factory=list)
    profit_factor: float = 0.0
    expectancy: float = 0.0
    avg_r_multiple: float = 0.0
    avg_planned_rr: float = 0.0
    avg_bars_held: float = 0.0
    exposure_pct: float = 0.0
    buy_and_hold_pct: float = 0.0
    long_trades: int = 0
    short_trades: int = 0
    exit_reasons: Dict[str, int] = field(default_factory=dict)
    action_counts: Dict[str, int] = field(default_factory=dict)
    bars_evaluated: int = 0
    skipped_signals: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self, include_details: bool = False) -> Dict[str, Any]:
        """Convert to dictionary for reporting."""
        d: Dict[str, Any] = {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "total_pnl": self.total_pnl,
            "total_pnl_pct": self.total_pnl_pct,
            "max_drawdown": self.max_drawdown,
            "max_drawdown_pct": self.max_drawdown_pct,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "avg_risk_reward": self.avg_risk_reward,
            "sharpe_ratio": self.sharpe_ratio,
            "profit_factor": self.profit_factor,
            "expectancy": self.expectancy,
            "avg_r_multiple": self.avg_r_multiple,
            "avg_planned_rr": self.avg_planned_rr,
            "avg_bars_held": self.avg_bars_held,
            "exposure_pct": self.exposure_pct,
            "buy_and_hold_pct": self.buy_and_hold_pct,
            "long_trades": self.long_trades,
            "short_trades": self.short_trades,
            "exit_reasons": self.exit_reasons,
            "action_counts": self.action_counts,
            "bars_evaluated": self.bars_evaluated,
        }
        if include_details:
            d["trades"] = [t.to_dict() for t in self.trades]
            d["equity_curve"] = [
                {"time": t.isoformat(), "equity": e}
                for t, e in zip(self.equity_times, self.equity_curve)
            ]
            d["skipped_signals"] = self.skipped_signals
        return d


class Backtester:
    """
    Validates the trading strategy against historical data using the real
    Technical and Strategy agents.
    """

    def __init__(
        self,
        config: Optional[BacktestConfig] = None,
        strategy_config: Optional[StrategyConfig] = None,
    ):
        self.config = config or BacktestConfig()
        self.strategy_config = strategy_config or StrategyConfig()
        # Backtests must never halt on "stale" wall-clock data or write to DynamoDB
        self.strategy_config.stale_data.halt_on_stale_data = False
        self._strategy_agent = StrategyAgent(
            config=self.strategy_config, persistence=_NullPersistence()
        )
        self._technical_generator = TechnicalSignalGenerator(use_sagemaker=False)

    # ----------------------------------------------------------- news proxy
    def _generate_synthetic_news_signal(
        self,
        symbol: str,
        timestamp: datetime,
        price_change_pct: float,
        zscore: Optional[float] = None,
    ) -> NewsSignal:
        """
        Momentum proxy for news sentiment.

        If ``zscore`` (bar return / rolling stdev) is given it is used so the
        thresholds work on any timeframe; otherwise fixed % thresholds apply.
        """
        if self.config.news_mode == "neutral":
            sentiment, impact = Sentiment.NEUTRAL, 0.5
        elif zscore is not None:
            if zscore > 2.0:
                sentiment, impact = Sentiment.VERY_BULLISH, 0.9
            elif zscore > 1.0:
                sentiment, impact = Sentiment.BULLISH, 0.7
            elif zscore < -2.0:
                sentiment, impact = Sentiment.VERY_BEARISH, 0.9
            elif zscore < -1.0:
                sentiment, impact = Sentiment.BEARISH, 0.7
            else:
                sentiment, impact = Sentiment.NEUTRAL, 0.5
        else:
            if price_change_pct > 0.03:
                sentiment, impact = Sentiment.VERY_BULLISH, 0.9
            elif price_change_pct > 0.01:
                sentiment, impact = Sentiment.BULLISH, 0.7
            elif price_change_pct < -0.03:
                sentiment, impact = Sentiment.VERY_BEARISH, 0.9
            elif price_change_pct < -0.01:
                sentiment, impact = Sentiment.BEARISH, 0.7
            else:
                sentiment, impact = Sentiment.NEUTRAL, 0.5

        return NewsSignal(
            symbol=symbol,
            sentiment=sentiment,
            impact_type=ImpactType.CASH_FLOW,
            impact_score=impact,
            confidence=0.8,
            reasoning=f"Backtest momentum proxy ({self.config.news_mode})",
            source_items=["backtest"],
            timestamp=timestamp,
            expires_at=timestamp + timedelta(hours=72),
        )

    async def _generate_technical_signal(
        self, symbol: str, candles: List[OHLCV]
    ) -> TechnicalSignal:
        return await self._technical_generator.generate_signal(
            symbol, candles, as_of=candles[-1].timestamp
        )

    # ------------------------------------------------------------ execution
    def _simulate_trade_exit(
        self,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        action: TradeAction,
        future_candles: List[OHLCV],
        max_hold_days: Optional[int] = None,
    ) -> tuple[float, str, int]:
        """
        Walk forward through ``future_candles`` (starting with the entry bar)
        and return ``(exit_price, exit_reason, bars_held)``.
        """
        max_bars = max_hold_days or self.config.max_hold_bars
        is_buy = action in BUY_ACTIONS
        slip = self.config.slippage_pct
        window = future_candles[:max_bars]

        for i, c in enumerate(window):
            if is_buy:
                if i > 0 and c.open <= stop_loss:
                    return c.open * (1 - slip), "sl", i + 1  # gap through stop
                if c.low <= stop_loss:
                    return stop_loss * (1 - slip), "sl", i + 1
                if i > 0 and c.open >= take_profit:
                    return c.open, "tp", i + 1  # gap through target (limit fills better)
                if c.high >= take_profit:
                    return take_profit, "tp", i + 1
            else:
                if i > 0 and c.open >= stop_loss:
                    return c.open * (1 + slip), "sl", i + 1
                if c.high >= stop_loss:
                    return stop_loss * (1 + slip), "sl", i + 1
                if i > 0 and c.open <= take_profit:
                    return c.open, "tp", i + 1
                if c.low <= take_profit:
                    return take_profit, "tp", i + 1

        if not window:
            return entry_price, "end_of_data", 0
        reason = "timeout" if len(window) >= max_bars else "end_of_data"
        last = window[-1].close
        return last * (1 - slip if is_buy else 1 + slip), reason, len(window)

    def _calculate_pnl(
        self,
        entry_price: float,
        exit_price: float,
        position_size: float,
        action: TradeAction,
        commission_pct: float,
    ) -> tuple[float, float]:
        """PnL for a notional ``position_size``. Returns (net_pnl, pnl_pct)."""
        if action in BUY_ACTIONS:
            gross = (exit_price - entry_price) * position_size / entry_price
        else:
            gross = (entry_price - exit_price) * position_size / entry_price
        exit_notional = position_size * exit_price / entry_price
        commission = (position_size + exit_notional) * commission_pct
        net = gross - commission
        return net, net / position_size * 100 if position_size else 0.0

    def _position_notional(self, equity: float, decision: Any) -> float:
        pct = (
            decision.position_size_pct
            if self.config.sizing_mode == "strategy"
            else self.config.position_size_pct
        )
        notional = equity * pct
        risk_frac = abs(decision.entry_price - decision.stop_loss) / decision.entry_price
        if risk_frac > 0 and self.config.max_risk_per_trade_pct > 0:
            notional = min(notional, equity * self.config.max_risk_per_trade_pct / risk_frac)
        return notional

    # -------------------------------------------------------------- metrics
    @staticmethod
    def _calculate_max_drawdown(equity_curve: List[float]) -> tuple[float, float]:
        if not equity_curve:
            return 0.0, 0.0
        peak = equity_curve[0]
        max_dd = max_dd_pct = 0.0
        for eq in equity_curve:
            peak = max(peak, eq)
            dd = peak - eq
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd / peak if peak > 0 else 0.0
        return max_dd, max_dd_pct

    @staticmethod
    def _calculate_sharpe_ratio(
        returns: List[float], periods_per_year: float = 252.0, risk_free_rate: float = 0.0
    ) -> float:
        """Annualised Sharpe from per-period returns."""
        if len(returns) < 2:
            return 0.0
        std = statistics.stdev(returns)
        if std == 0:
            return 0.0
        rf = risk_free_rate / periods_per_year
        return (statistics.mean(returns) - rf) / std * math.sqrt(periods_per_year)

    @staticmethod
    def _periods_per_year(candles: List[OHLCV]) -> float:
        span_days = (candles[-1].timestamp - candles[0].timestamp).total_seconds() / 86400
        if span_days <= 0:
            return 252.0
        return len(candles) / (span_days / 365.25)

    # ------------------------------------------------------------------ run
    async def run_backtest(
        self,
        symbol: str,
        candles: List[OHLCV],
        horizon: TradingHorizon = TradingHorizon.SHORT_TERM,
    ) -> BacktestResult:
        """
        Run the strategy over ``candles`` (ascending). Needs ``warmup_bars + 50``.
        """
        cfg = self.config
        min_bars = max(250, cfg.warmup_bars + 50)
        if len(candles) < min_bars:
            raise ValueError(f"Need at least {min_bars} candles for backtest, got {len(candles)}")

        candles = sorted(candles, key=lambda c: c.timestamp)
        n = len(candles)
        start_idx = max(cfg.warmup_bars, 200)

        trades: List[TradeResult] = []
        trade_spans: List[tuple[int, int, TradeResult]] = []
        action_counts: Counter = Counter()
        skipped: List[Dict[str, Any]] = []
        equity = cfg.initial_capital
        bars_evaluated = 0

        returns = [0.0] + [
            (candles[k].close - candles[k - 1].close) / candles[k - 1].close for k in range(1, n)
        ]

        i = start_idx
        while i < n - 1:
            bar = candles[i]
            window = candles[max(0, i + 1 - cfg.lookback_bars): i + 1]
            recent = returns[max(1, i - 19): i + 1]
            sd = statistics.pstdev(recent) if len(recent) > 1 else 0.0
            z = returns[i] / sd if sd > 0 else 0.0

            news = self._generate_synthetic_news_signal(symbol, bar.timestamp, returns[i], z)
            try:
                tech = await self._generate_technical_signal(symbol, window)
            except Exception as e:  # indicator edge cases
                logger.debug(f"Technical signal failed at {bar.timestamp}: {e}")
                i += 1
                continue

            bars_evaluated += 1
            result = await self._strategy_agent.evaluate(
                news_signal=news,
                technical_signal=tech,
                horizon=horizon,
                current_time=bar.timestamp,
            )
            if not result.success or result.decision is None:
                action_counts["rejected"] += 1
                i += 1
                continue

            decision = result.decision
            action_counts[decision.action.value] += 1
            if decision.action not in ACTIONABLE:
                i += 1
                continue

            def skip(reason: str) -> None:
                if len(skipped) < cfg.max_signal_log:
                    skipped.append({
                        "time": bar.timestamp.isoformat(),
                        "action": decision.action.value,
                        "price": decision.entry_price,
                        "reason": reason,
                    })

            if decision.action in SELL_ACTIONS and not cfg.allow_short:
                skip("shorting disabled")
                i += 1
                continue

            is_buy = decision.action in BUY_ACTIONS
            entry_bar = candles[i + 1]
            entry = entry_bar.open * (1 + cfg.slippage_pct if is_buy else 1 - cfg.slippage_pct)
            sl, tp = decision.stop_loss, decision.take_profit
            # Bracket is invalid if the next open already gapped past SL or TP
            if (is_buy and not sl < entry < tp) or (not is_buy and not tp < entry < sl):
                skip("next-bar open gapped past stop/target")
                i += 1
                continue

            notional = self._position_notional(equity, decision)
            if notional <= 0:
                skip("zero size")
                i += 1
                continue

            exit_price, reason, bars_held = self._simulate_trade_exit(
                entry, sl, tp, decision.action, candles[i + 1:],
            )
            exit_idx = min(i + bars_held, n - 1)
            pnl, pnl_pct = self._calculate_pnl(
                entry, exit_price, notional, decision.action, cfg.commission_pct
            )
            risk_amt = notional * abs(entry - sl) / entry
            trade = TradeResult(
                symbol=symbol,
                action=decision.action,
                entry_price=entry,
                exit_price=exit_price,
                entry_time=entry_bar.timestamp,
                exit_time=candles[exit_idx].timestamp,
                position_size=notional,
                pnl=pnl,
                pnl_pct=pnl_pct,
                exit_reason=reason,
                stop_loss=sl,
                take_profit=tp,
                quantity=notional / entry,
                signal_time=bar.timestamp,
                bars_held=bars_held,
                conviction=decision.conviction.value,
                planned_rr=decision.risk_reward_ratio,
                r_multiple=pnl / risk_amt if risk_amt > 0 else 0.0,
                rsi=tech.rsi,
                confluence=tech.confluence.score,
                news_sentiment=news.sentiment.value,
                reasoning=decision.reasoning,
            )
            trades.append(trade)
            trade_spans.append((i + 1, exit_idx, trade))
            equity += pnl
            # Resume signal evaluation on the exit bar (position is flat after it)
            i = max(exit_idx, i + 1)

        # ---- mark-to-market equity curve (one point per bar from warmup)
        equity_curve: List[float] = []
        equity_times: List[datetime] = []
        cash = cfg.initial_capital
        realized_at: Dict[int, float] = {}
        active: List[Optional[TradeResult]] = [None] * n
        for entry_idx, exit_idx, t in trade_spans:  # spans never overlap
            realized_at[exit_idx] = realized_at.get(exit_idx, 0.0) + t.pnl
            for k in range(entry_idx, exit_idx):
                active[k] = t
        in_market_bars = 0
        for k in range(start_idx, n):
            cash += realized_at.get(k, 0.0)
            t = active[k]
            mtm = 0.0
            if t is not None:
                direction = 1 if t.action in BUY_ACTIONS else -1
                mtm = (candles[k].close - t.entry_price) * t.quantity * direction
                in_market_bars += 1
            equity_curve.append(cash + mtm)
            equity_times.append(candles[k].timestamp)

        # ---- metrics
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        total = len(trades)
        gross_win = sum(t.pnl for t in wins)
        gross_loss = -sum(t.pnl for t in losses)
        avg_win = gross_win / len(wins) if wins else 0.0
        avg_loss = -gross_loss / len(losses) if losses else 0.0
        eq_returns = [
            (equity_curve[k] - equity_curve[k - 1]) / equity_curve[k - 1]
            for k in range(1, len(equity_curve))
            if equity_curve[k - 1] > 0
        ]
        max_dd, max_dd_pct = self._calculate_max_drawdown(equity_curve)
        first_px = candles[start_idx].close

        return BacktestResult(
            total_trades=total,
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=len(wins) / total if total else 0.0,
            total_pnl=sum(t.pnl for t in trades),
            total_pnl_pct=(equity - cfg.initial_capital) / cfg.initial_capital * 100,
            max_drawdown=max_dd,
            max_drawdown_pct=max_dd_pct,
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_risk_reward=abs(avg_win / avg_loss) if avg_loss else 0.0,
            sharpe_ratio=self._calculate_sharpe_ratio(
                eq_returns, self._periods_per_year(candles)
            ),
            trades=trades,
            equity_curve=equity_curve,
            equity_times=equity_times,
            profit_factor=(gross_win / gross_loss) if gross_loss > 0 else (float(total > 0) * 999.0),
            expectancy=(sum(t.pnl for t in trades) / total) if total else 0.0,
            avg_r_multiple=statistics.mean(t.r_multiple for t in trades) if trades else 0.0,
            avg_planned_rr=statistics.mean(t.planned_rr for t in trades) if trades else 0.0,
            avg_bars_held=statistics.mean(t.bars_held for t in trades) if trades else 0.0,
            exposure_pct=in_market_bars / max(1, n - start_idx) * 100,
            buy_and_hold_pct=(candles[-1].close - first_px) / first_px * 100,
            long_trades=sum(1 for t in trades if t.action in BUY_ACTIONS),
            short_trades=sum(1 for t in trades if t.action in SELL_ACTIONS),
            exit_reasons=dict(Counter(t.exit_reason for t in trades)),
            action_counts=dict(action_counts),
            bars_evaluated=bars_evaluated,
            skipped_signals=skipped,
        )

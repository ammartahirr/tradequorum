"""Quant engine v2 service: live decisions, news aggregation, portfolio backtests."""
import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

import numpy as np
import pandas as pd

from core.config import settings
from services.broker_service import get_data_provider
from src.quant import QuantConfig, QuantEngine

logger = logging.getLogger(__name__)

SENTIMENT_VALUE = {
    "very_bullish": 1.0, "bullish": 0.5, "neutral": 0.0, "bearish": -0.5, "very_bearish": -1.0,
}


def quant_config(**overrides) -> QuantConfig:
    cfg = QuantConfig(
        use_meta_model=settings.QUANT_USE_META_MODEL,
        allow_short=settings.QUANT_ALLOW_SHORT,
        max_risk_per_trade=settings.QUANT_MAX_RISK_PER_TRADE,
        base_risk=settings.QUANT_BASE_RISK,
    )
    for k, v in overrides.items():
        if v is not None and hasattr(cfg, k):
            setattr(cfg, k, v)
    return cfg


async def news_score(symbol: str, halflife_hours: float = 12.0) -> tuple[float, int]:
    """Confidence- and recency-weighted sentiment of unexpired news signals, in [-1, 1]."""
    try:
        from sqlalchemy import select

        from core.database import get_db_context
        from models.signal import NewsSignal

        now = datetime.now(timezone.utc)
        async with get_db_context() as db:
            rows = (await db.execute(
                select(NewsSignal).where(NewsSignal.symbol == symbol, NewsSignal.expires_at > now)
            )).scalars().all()
    except Exception as e:
        logger.debug(f"news_score unavailable for {symbol}: {e}")
        return 0.0, 0
    num = den = 0.0
    for r in rows:
        ts = r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc)
        age_h = max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 3600)
        w = float(r.confidence) * math.exp(-math.log(2) * age_h / halflife_hours)
        impact = 1.0 if r.impact_type == "cash_flow" else 0.6 if r.impact_type in {"regulatory", "macro"} else 0.3
        num += w * SENTIMENT_VALUE.get(r.sentiment, 0.0) * float(r.impact_score) * impact
        den += w
    return (float(np.clip(num / den, -1, 1)) if den > 0 else 0.0), len(rows)


async def live_decision(symbol: str, timeframe: Optional[str] = None, source: Optional[str] = None,
                        equity: Optional[float] = None) -> dict:
    tf = timeframe or settings.QUANT_TIMEFRAME
    provider = get_data_provider(source)
    candles = await provider.get_candles(symbol.upper(), tf, settings.QUANT_HISTORY_BARS)
    score, n_news = await news_score(symbol.upper())
    engine = QuantEngine(quant_config())
    decision = await asyncio.to_thread(engine.decide, symbol.upper(), candles, score, equity)
    decision.update(timeframe=tf, news_score=score, news_items=n_news, source=provider.name)
    from src.quant.engine import json_safe
    return json_safe(decision)


async def evaluate_and_store(symbols: Optional[list[str]] = None) -> int:
    """Scheduler job: run the quant engine for each symbol and store actionable decisions."""
    from sqlalchemy import select

    from api.websocket import broadcast_decision
    from core.database import get_db_context
    from models.trade import TradeDecision

    stored = 0
    equity = None
    try:
        from services.broker_service import get_broker
        acct = await get_broker().get_account_info()
        equity = float(acct.get("equity") or 0) or None
    except Exception:
        pass

    for symbol in symbols or settings.trading_symbols_list:
        try:
            d = await live_decision(symbol, equity=equity)
        except Exception as e:
            logger.warning(f"Quant decision failed for {symbol}: {e}")
            continue
        if d["action"] not in {"buy", "sell"}:
            logger.info(f"{symbol}: flat – {'; '.join(d['reasons'])}")
            continue
        now = datetime.now(timezone.utc)
        async with get_db_context() as db:
            existing = (await db.execute(
                select(TradeDecision).where(TradeDecision.symbol == symbol, TradeDecision.expires_at > now)
            )).scalars().first()
            if existing:
                continue
            prob = d.get("prob")
            conviction = "high" if (prob or 0) >= 0.6 else "medium" if (prob or 0) >= 0.5 else "low"
            row = TradeDecision(
                decision_id=uuid4(), symbol=symbol, action=d["action"], conviction=conviction,
                horizon="short_term", entry_price=d["entry_price"], stop_loss=d["stop_loss"],
                take_profit=d["take_profit"], position_size_pct=max(1e-4, min(1.0, d["position_size_pct"])),
                risk_reward_ratio=d["risk_reward"], reasoning=" | ".join(d["reasons"]),
                timestamp=now, expires_at=now + timedelta(hours=settings.QUANT_DECISION_TTL_HOURS),
            )
            db.add(row)
        stored += 1
        await broadcast_decision({
            "decision_id": str(row.decision_id), "symbol": symbol, "action": d["action"],
            "conviction": conviction, "entry_price": d["entry_price"], "stop_loss": d["stop_loss"],
            "take_profit": d["take_profit"], "risk_reward_ratio": d["risk_reward"],
            "regime": d["regime"], "composite": d["composite"], "prob": prob,
            "reasoning": row.reasoning,
        })
    return stored


async def portfolio_backtest(symbols: list[str], timeframe: str, bars: int, source: Optional[str],
                             overrides: dict) -> dict:
    """Equal risk budget per symbol; combined equity is the sum of sleeve P&L."""
    provider = get_data_provider(source)
    n = len(symbols)
    cfg_kwargs = dict(overrides)
    per_capital = (cfg_kwargs.pop("initial_capital", None) or 100_000.0)

    async def one(sym: str):
        candles = await provider.get_candles(sym, timeframe, bars)
        eng = QuantEngine(quant_config(**cfg_kwargs, initial_capital=per_capital / n))
        return sym, await asyncio.to_thread(eng.backtest, sym, candles, None, False)

    results, errors = {}, {}
    for coro in asyncio.as_completed([one(s) for s in symbols]):
        try:
            sym, res = await coro
            results[sym] = res
        except Exception as e:
            errors[str(e)[:80]] = errors.get(str(e)[:80], 0) + 1
    if not results:
        raise ValueError(f"No symbol could be backtested: {errors}")

    curves = []
    for sym, r in results.items():
        s = pd.Series({p["time"]: p["equity"] for p in r["equity_curve"]}, name=sym)
        curves.append(s - s.iloc[0])
    pnl = pd.concat(curves, axis=1).sort_index().ffill().fillna(0.0).sum(axis=1)
    equity = per_capital + pnl
    rets = equity.pct_change().dropna().to_numpy()
    span_days = (equity.index[-1] - equity.index[0]) / 86400 if len(equity) > 1 else 1
    ppy = len(equity) / (span_days / 365.25) if span_days > 0 else 252
    sharpe = float(rets.mean() / rets.std() * math.sqrt(ppy)) if len(rets) > 1 and rets.std() > 0 else 0.0
    eq = equity.to_numpy()
    mdd = float(np.max(1 - eq / np.maximum.accumulate(eq))) if len(eq) else 0.0
    rets_by_sym = pd.concat([pd.Series({p["time"]: p["equity"] for p in r["equity_curve"]}).pct_change()
                             for r in results.values()], axis=1)
    avg_corr = rets_by_sym.corr().to_numpy()
    avg_corr = float(avg_corr[np.triu_indices_from(avg_corr, 1)].mean()) if len(results) > 1 else 1.0
    from src.quant.engine import json_safe
    return json_safe({
        "symbols": list(results), "errors": errors, "timeframe": timeframe,
        "portfolio": {
            "total_return_pct": float((eq[-1] / per_capital - 1) * 100), "sharpe": sharpe,
            "max_drawdown_pct": mdd * 100,
            "total_trades": int(sum(r["stats"]["total_trades"] for r in results.values())),
            "avg_pairwise_correlation": avg_corr,
        },
        "per_symbol": {s: {k: r["stats"][k] for k in ("total_return_pct", "sharpe", "max_drawdown_pct",
                                                       "total_trades", "win_rate", "profit_factor")}
                       for s, r in results.items()},
        "equity_curve": [{"time": int(t), "equity": float(v)} for t, v in equity.items()],
    })

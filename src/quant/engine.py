"""
TradeQuorum Quant Engine v2.

Pipeline (all causal; decisions at bar close t, fills at bar t+1 open):

  candles ─► features ─► regime ─► alpha ensemble (regime prior × rolling IC)
          ─► candidate events (|composite| > threshold)
          ─► triple-barrier labels ─► walk-forward meta-model  P(win)
          ─► fractional-Kelly risk × vol-target cap × drawdown throttle
          ─► execution sim: ATR stop/target, breakeven, chandelier trail,
             signal-flip exit, time stop, gap fills, commission + slippage
          ─► metrics: Sharpe/Sortino/Calmar, PSR, Monte Carlo, meta-model AUC,
             and a "primary only" (no-ML) benchmark to show what the ML adds
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.models.signals import OHLCV

from .alphas import ALPHAS, EnsembleConfig, combine, compute_alphas
from .features import compute_features, ohlcv_to_frame
from .meta_model import (
    MetaConfig, MetaModel, build_meta_matrix, causal_trust, meta_feature_names,
    walk_forward_probabilities,
)
from .regime import detect_regime, regime_segments

logger = logging.getLogger(__name__)


@dataclass
class QuantConfig:
    initial_capital: float = 100_000.0
    warmup_bars: int = 250
    # signal
    entry_threshold: float = 0.25
    event_spacing: int = 5            # min bars between same-side candidate events
    exit_on_flip: float = 0.15        # exit if composite crosses this against the position
    allow_short: bool = True
    trend_filter: bool = True         # no longs below / shorts above the 200-bar SMA
    min_edge_cost_ratio: float = 8.0  # target distance must be >= N x round-trip costs
    # barriers / exits (ATR multiples)
    sl_atr: float = 2.0
    tp_atr: float = 3.0
    breakeven_atr: float = 1.0
    trail_atr: float = 2.5
    max_hold_bars: int = 40
    # costs (per side)
    commission_bps: float = 2.0
    slippage_bps: float = 3.0
    # sizing
    use_meta_model: bool = False     # walk-forward tests: OOS AUC ~0.50 on OHLCV-only features
    min_prob: float = 0.45
    kelly_fraction: float = 0.25
    max_risk_per_trade: float = 0.01
    base_risk: float = 0.005          # risk per trade when the meta-model hasn't earned trust
    target_vol: float = 0.15          # annualised, caps notional
    max_leverage: float = 1.0
    dd_soft: float = 0.10
    dd_hard: float = 0.25
    # ML / ensemble
    meta: MetaConfig = field(default_factory=MetaConfig)
    ensemble: EnsembleConfig = field(default_factory=EnsembleConfig)
    monte_carlo_runs: int = 1000


@dataclass
class QuantTrade:
    side: int
    signal_idx: int
    entry_idx: int
    exit_idx: int
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    final_stop: float
    quantity: float
    risk_amount: float
    pnl: float
    r_multiple: float
    exit_reason: str
    prob: Optional[float]
    model_trusted: bool
    kelly: float
    regime: str
    composite: float
    alpha_contrib: dict
    equity_at_entry: float


# ----------------------------------------------------------------- utilities
def periods_per_year(index: pd.DatetimeIndex) -> float:
    span = (index[-1] - index[0]).total_seconds() / 86400
    return len(index) / (span / 365.25) if span > 0 else 252.0


def _cost(price: float, cfg: QuantConfig) -> float:
    return price * (cfg.commission_bps + cfg.slippage_bps) / 1e4


def triple_barrier(
    o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray,
    t: int, side: int, atr_t: float, cfg: QuantConfig,
) -> tuple[int, float, str]:
    """Label for an event at bar t: enter at o[t+1]. Returns (exit_idx, net_ret, reason)."""
    n = len(o)
    e = t + 1
    if e >= n:
        return n - 1, 0.0, "none"
    entry = o[e]
    sl = entry - side * cfg.sl_atr * atr_t
    tp = entry + side * cfg.tp_atr * atr_t
    end = min(n - 1, e + cfg.max_hold_bars - 1)
    for j in range(e, end + 1):
        if j > e and (o[j] - sl) * side <= 0:
            px, why = o[j], "sl"
        elif (l[j] - sl if side > 0 else sl - h[j]) <= 0:
            px, why = sl, "sl"
        elif (h[j] - tp if side > 0 else tp - l[j]) >= 0:
            px, why = (o[j] if j > e and (o[j] - tp) * side >= 0 else tp), "tp"
        else:
            continue
        ret = side * (px - entry) / entry - 2 * (cfg.commission_bps + cfg.slippage_bps) / 1e4
        return j, ret, why
    ret = side * (c[end] - entry) / entry - 2 * (cfg.commission_bps + cfg.slippage_bps) / 1e4
    return end, ret, "time"


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def probabilistic_sharpe(returns: np.ndarray, benchmark_sr: float = 0.0) -> float:
    """Bailey & López de Prado PSR: P(true SR > benchmark) given skew/kurtosis."""
    r = returns[np.isfinite(returns)]
    if len(r) < 30 or r.std() == 0:
        return 0.0
    sr = r.mean() / r.std()
    s = pd.Series(r)
    skew, kurt = float(s.skew()), float(s.kurt()) + 3.0
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr**2))
    return _norm_cdf((sr - benchmark_sr) * math.sqrt(len(r) - 1) / denom)


def compute_metrics(equity: np.ndarray, ppy: float, trades: list[QuantTrade],
                    first_price: float, last_price: float, n_bars: int, mc_runs: int,
                    seed: int = 11) -> dict:
    eq = np.asarray(equity, dtype=float)
    rets = np.diff(eq) / eq[:-1] if len(eq) > 1 else np.array([])
    years = max(1e-9, len(eq) / ppy)
    total = eq[-1] / eq[0] - 1 if len(eq) else 0.0
    cagr = (eq[-1] / eq[0]) ** (1 / years) - 1 if len(eq) and eq[-1] > 0 else -1.0
    vol = rets.std() * math.sqrt(ppy) if len(rets) > 1 else 0.0
    sharpe = rets.mean() / rets.std() * math.sqrt(ppy) if len(rets) > 1 and rets.std() > 0 else 0.0
    downside = rets[rets < 0]
    dd_std = math.sqrt((downside**2).mean()) if len(downside) else 0.0
    sortino = rets.mean() / dd_std * math.sqrt(ppy) if dd_std > 0 else 0.0
    peak = np.maximum.accumulate(eq) if len(eq) else eq
    dd = (peak - eq) / peak if len(eq) else np.array([0.0])
    max_dd = float(dd.max()) if len(dd) else 0.0
    calmar = cagr / max_dd if max_dd > 0 else 0.0

    pnls = np.array([t.pnl for t in trades])
    rs = np.array([t.r_multiple for t in trades])
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    exposure = sum(t.exit_idx - t.entry_idx + 1 for t in trades) / max(1, n_bars)

    mc = {}
    if len(trades) >= 5 and mc_runs > 0:
        rng = np.random.default_rng(seed)
        tr = np.array([t.pnl / t.equity_at_entry for t in trades])
        sims = rng.choice(tr, size=(mc_runs, len(tr)), replace=True)
        curves = np.cumprod(1 + sims, axis=1)
        finals = curves[:, -1] - 1
        mdd = np.max(1 - curves / np.maximum.accumulate(curves, axis=1), axis=1)
        mc = {
            "runs": mc_runs,
            "return_p5": float(np.percentile(finals, 5)),
            "return_p50": float(np.percentile(finals, 50)),
            "return_p95": float(np.percentile(finals, 95)),
            "max_dd_p50": float(np.percentile(mdd, 50)),
            "max_dd_p95": float(np.percentile(mdd, 95)),
            "prob_loss": float(np.mean(finals < 0)),
        }

    return {
        "total_return_pct": total * 100,
        "cagr_pct": cagr * 100,
        "ann_vol_pct": vol * 100,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "psr": probabilistic_sharpe(rets),
        "max_drawdown_pct": max_dd * 100,
        "buy_and_hold_pct": (last_price / first_price - 1) * 100,
        "total_trades": len(trades),
        "long_trades": sum(1 for t in trades if t.side > 0),
        "short_trades": sum(1 for t in trades if t.side < 0),
        "win_rate": float(len(wins) / len(trades)) if trades else 0.0,
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else (999.0 if len(wins) else 0.0),
        "avg_r": float(rs.mean()) if len(rs) else 0.0,
        "expectancy": float(pnls.mean()) if len(pnls) else 0.0,
        "avg_bars_held": float(np.mean([t.exit_idx - t.entry_idx + 1 for t in trades])) if trades else 0.0,
        "exposure_pct": exposure * 100,
        "exit_reasons": {str(k): int(v) for k, v in pd.Series([t.exit_reason for t in trades]).value_counts().items()} if trades else {},
        "monte_carlo": mc,
    }


# --------------------------------------------------------------------- engine
class QuantEngine:
    def __init__(self, config: Optional[QuantConfig] = None):
        self.cfg = config or QuantConfig()

    # -- analysis common to backtest and live -------------------------------
    def analyze(self, candles: list[OHLCV], news: Optional[pd.Series] = None) -> dict[str, Any]:
        cfg = self.cfg
        df = ohlcv_to_frame(candles)
        f = compute_features(df)
        reg = detect_regime(df, f)
        alphas = compute_alphas(f, news)
        composite, weights, ics = combine(alphas, reg["regime"], df["close"], cfg.ensemble)

        o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
        atr_v = f["atr_14"].to_numpy()
        comp = composite.to_numpy()
        n = len(df)

        # candidate events
        ev_idx, ev_side = [], []
        filtered = {"trend_filter": 0, "cost_filter": 0}
        last_t = {1: -10**9, -1: -10**9}
        dist200 = f["dist_sma200_atr"].to_numpy()
        roundtrip = 2 * (cfg.commission_bps + cfg.slippage_bps) / 1e4
        for t in range(cfg.warmup_bars, n - 1):
            s = comp[t]
            if not np.isfinite(s) or abs(s) < cfg.entry_threshold or not np.isfinite(atr_v[t]) or atr_v[t] <= 0:
                continue
            side = 1 if s > 0 else -1
            if side < 0 and not cfg.allow_short:
                continue
            if cfg.trend_filter and np.isfinite(dist200[t]) and dist200[t] * side < 0:
                filtered["trend_filter"] += 1
                continue
            if cfg.tp_atr * atr_v[t] / c[t] < cfg.min_edge_cost_ratio * roundtrip:
                filtered["cost_filter"] += 1
                continue
            if t - last_t[side] >= cfg.event_spacing or last_t[-side] > last_t[side]:
                ev_idx.append(t)
                ev_side.append(side)
                last_t[side] = t
        ev_idx = np.array(ev_idx, dtype=int)
        ev_side = np.array(ev_side, dtype=int)

        labels = np.zeros(len(ev_idx), dtype=int)
        label_end = np.zeros(len(ev_idx), dtype=int)
        label_ret = np.zeros(len(ev_idx))
        for k, (t, s) in enumerate(zip(ev_idx, ev_side)):
            j, r, _ = triple_barrier(o, h, l, c, t, s, atr_v[t], cfg)
            label_end[k], label_ret[k], labels[k] = j, r, int(r > 0)
        # events whose label isn't resolved yet (end of data) must not be trained on
        resolved = label_end < n - 1

        X = (build_meta_matrix(f, alphas, composite, reg["regime"], ev_idx, ev_side)
             if len(ev_idx) else np.zeros((0, len(meta_feature_names()))))

        return dict(df=df, f=f, reg=reg, alphas=alphas, composite=composite, weights=weights,
                    ics=ics, o=o, h=h, l=l, c=c, atr=atr_v, n=n, ev_idx=ev_idx, ev_side=ev_side,
                    filtered=filtered,
                    labels=labels, label_end=np.where(resolved, label_end, 10**9),
                    label_ret=label_ret, X=X)

    # -- sizing ---------------------------------------------------------------
    def _risk_fraction(self, prob: Optional[float], trusted: bool = True) -> tuple[float, float]:
        """Fractional-Kelly risk if the meta-model is trusted, otherwise the flat base risk."""
        cfg = self.cfg
        if not cfg.use_meta_model or not trusted or prob is None or not np.isfinite(prob):
            return cfg.base_risk, 0.0
        if prob < cfg.min_prob:
            return 0.0, 0.0
        b = cfg.tp_atr / cfg.sl_atr
        kelly = prob - (1 - prob) / b
        if kelly <= 0:
            return 0.0, kelly
        return min(cfg.max_risk_per_trade, cfg.kelly_fraction * kelly), kelly

    # -- execution simulation ----------------------------------------------
    def _simulate(self, a: dict, probs: dict[int, tuple], use_meta: bool) -> tuple[list[QuantTrade], np.ndarray]:
        cfg = self.cfg
        o, h, l, c, atr_v, n = a["o"], a["h"], a["l"], a["c"], a["atr"], a["n"]
        comp = a["composite"].to_numpy()
        regime = a["reg"]["regime"].to_numpy()
        weights, alphas = a["weights"], a["alphas"]
        ppy = periods_per_year(a["df"].index)
        vol20 = a["f"]["vol_20"].to_numpy()
        events = dict(zip(a["ev_idx"].tolist(), a["ev_side"].tolist()))

        saved_meta = cfg.use_meta_model
        cfg.use_meta_model = use_meta
        cash = cfg.initial_capital
        peak = cash
        equity = np.full(n, cfg.initial_capital, dtype=float)
        trades: list[QuantTrade] = []
        pos = None  # dict while in a trade
        pending = None  # order to fill at next open

        try:
            for t in range(cfg.warmup_bars, n):
                # 1) fill pending entry at this bar's open
                if pending is not None and pos is None:
                    side = pending["side"]
                    entry = o[t] + side * _cost(o[t], cfg)
                    sl = entry - side * cfg.sl_atr * pending["atr"]
                    tp = entry + side * cfg.tp_atr * pending["atr"]
                    qty = pending["risk_amt"] / (cfg.sl_atr * pending["atr"])
                    ann_vol = max(1e-6, pending["vol20"] * math.sqrt(ppy))
                    max_notional = cash * min(cfg.max_leverage, cfg.target_vol / ann_vol)
                    qty = min(qty, max_notional / entry)
                    if qty > 0:
                        pos = dict(side=side, entry=entry, sl=sl, tp=tp, stop=sl, qty=qty,
                                   entry_idx=t, best=entry, atr=pending["atr"],
                                   risk_amt=qty * cfg.sl_atr * pending["atr"], **pending["meta"])
                    pending = None

                # 2) manage open position on this bar
                if pos is not None:
                    side = pos["side"]
                    exit_px, why = None, None
                    if t > pos["entry_idx"] and (o[t] - pos["stop"]) * side <= 0:
                        exit_px, why = o[t], ("sl" if pos["stop"] == pos["sl"] else "trail")
                    elif (l[t] - pos["stop"] if side > 0 else pos["stop"] - h[t]) <= 0:
                        exit_px, why = pos["stop"], ("sl" if pos["stop"] == pos["sl"] else "trail")
                    elif (h[t] - pos["tp"] if side > 0 else pos["tp"] - l[t]) >= 0:
                        exit_px = o[t] if t > pos["entry_idx"] and (o[t] - pos["tp"]) * side >= 0 else pos["tp"]
                        why = "tp"
                    elif t - pos["entry_idx"] + 1 >= cfg.max_hold_bars:
                        exit_px, why = c[t], "time"
                    elif np.isfinite(comp[t]) and comp[t] * side < -cfg.exit_on_flip:
                        exit_px, why = c[t], "signal_flip"

                    if exit_px is not None:
                        exit_px = exit_px - side * (_cost(exit_px, cfg) if why != "tp" else exit_px * cfg.commission_bps / 1e4)
                        pnl = side * (exit_px - pos["entry"]) * pos["qty"]
                        cash += pnl
                        trades.append(QuantTrade(
                            side=side, signal_idx=pos["signal_idx"], entry_idx=pos["entry_idx"], exit_idx=t,
                            entry_price=pos["entry"], exit_price=exit_px, stop_loss=pos["sl"],
                            take_profit=pos["tp"], final_stop=pos["stop"], quantity=pos["qty"],
                            risk_amount=pos["risk_amt"], pnl=pnl,
                            r_multiple=pnl / pos["risk_amt"] if pos["risk_amt"] > 0 else 0.0,
                            exit_reason=why, prob=pos["prob"], model_trusted=pos["model_trusted"], kelly=pos["kelly"], regime=pos["regime"],
                            composite=pos["composite"], alpha_contrib=pos["alpha_contrib"],
                            equity_at_entry=pos["equity_at_entry"],
                        ))
                        pos = None
                    else:
                        # trailing logic on the close (applies from next bar)
                        pos["best"] = max(pos["best"], c[t]) if side > 0 else min(pos["best"], c[t])
                        fav = (pos["best"] - pos["entry"]) * side
                        if fav >= cfg.breakeven_atr * pos["atr"]:
                            be = pos["entry"]
                            pos["stop"] = max(pos["stop"], be) if side > 0 else min(pos["stop"], be)
                        if np.isfinite(atr_v[t]):
                            trail = pos["best"] - side * cfg.trail_atr * atr_v[t]
                            pos["stop"] = max(pos["stop"], trail) if side > 0 else min(pos["stop"], trail)

                # 3) mark to market
                mtm = 0.0
                if pos is not None:
                    mtm = pos["side"] * (c[t] - pos["entry"]) * pos["qty"]
                equity[t] = cash + mtm
                peak = max(peak, equity[t])

                # 4) new signal at this close -> order for next open
                if pos is None and pending is None and t in events and t < n - 1:
                    side = events[t]
                    prob, trusted = probs.get(t, (None, False))
                    risk_frac, kelly = self._risk_fraction(prob, trusted)
                    dd = 1 - equity[t] / peak
                    if dd >= cfg.dd_hard:
                        risk_frac = 0.0
                    elif dd > cfg.dd_soft:
                        risk_frac *= max(0.0, 1 - (dd - cfg.dd_soft) / (cfg.dd_hard - cfg.dd_soft))
                    if risk_frac > 0:
                        w = weights.iloc[t]
                        contrib = {k: float(w[k] * alphas[k].iloc[t]) for k in ALPHAS}
                        pending = dict(side=side, atr=atr_v[t], vol20=vol20[t] if np.isfinite(vol20[t]) else 0.01,
                                       risk_amt=equity[t] * risk_frac,
                                       meta=dict(signal_idx=t, prob=None if prob is None or not np.isfinite(prob) else float(prob),
                                                 model_trusted=bool(trusted and use_meta),
                                                 kelly=float(kelly), regime=str(regime[t]), composite=float(comp[t]),
                                                 alpha_contrib=contrib, equity_at_entry=float(equity[t])))
            # close anything open at the end
            if pos is not None:
                t = n - 1
                exit_px = c[t] - pos["side"] * _cost(c[t], cfg)
                pnl = pos["side"] * (exit_px - pos["entry"]) * pos["qty"]
                cash += pnl
                equity[t] = cash
                trades.append(QuantTrade(
                    side=pos["side"], signal_idx=pos["signal_idx"], entry_idx=pos["entry_idx"], exit_idx=t,
                    entry_price=pos["entry"], exit_price=exit_px, stop_loss=pos["sl"], take_profit=pos["tp"],
                    final_stop=pos["stop"], quantity=pos["qty"], risk_amount=pos["risk_amt"], pnl=pnl,
                    r_multiple=pnl / pos["risk_amt"] if pos["risk_amt"] > 0 else 0.0, exit_reason="end_of_data",
                    prob=pos["prob"], model_trusted=pos["model_trusted"], kelly=pos["kelly"], regime=pos["regime"], composite=pos["composite"],
                    alpha_contrib=pos["alpha_contrib"], equity_at_entry=pos["equity_at_entry"],
                ))
        finally:
            cfg.use_meta_model = saved_meta
        return trades, equity

    # -- public: backtest ----------------------------------------------------
    def backtest(self, symbol: str, candles: list[OHLCV], news: Optional[pd.Series] = None,
                 compare: bool = True) -> dict[str, Any]:
        """``compare=False`` skips the alternate variant (and ML fitting when the model is off)."""
        cfg = self.cfg
        if len(candles) < cfg.warmup_bars + 100:
            raise ValueError(f"Need at least {cfg.warmup_bars + 100} candles, got {len(candles)}")
        a = self.analyze(candles, news)
        n, idx = a["n"], a["df"].index

        need_ml = cfg.use_meta_model or compare
        if need_ml:
            probs_arr, last_model, fit_log = walk_forward_probabilities(
                a["X"], a["labels"], a["ev_idx"], a["label_end"], n, cfg.warmup_bars, cfg.meta,
            )
        else:
            probs_arr, last_model, fit_log = np.full(len(a["ev_idx"]), np.nan), None, []
        auc_at, trusted = causal_trust(probs_arr, a["labels"], a["ev_idx"], a["label_end"], cfg.meta)
        probs = {int(t): (float(p), bool(tr)) for t, p, tr in zip(a["ev_idx"], probs_arr, trusted)}

        ml_trades, ml_equity = self._simulate(a, probs, use_meta=True) if need_ml else ([], None)
        base_trades, base_equity = (self._simulate(a, probs, use_meta=False)
                                    if (compare or not cfg.use_meta_model) else ([], None))
        if cfg.use_meta_model:
            trades, equity, alt_trades, alt_equity = ml_trades, ml_equity, base_trades, base_equity
        else:
            trades, equity, alt_trades, alt_equity = base_trades, base_equity, ml_trades, ml_equity

        ppy = periods_per_year(idx)
        sl = slice(cfg.warmup_bars, n)
        first_px, last_px = a["c"][cfg.warmup_bars], a["c"][-1]
        stats = compute_metrics(equity[sl], ppy, trades, first_px, last_px, n - cfg.warmup_bars, cfg.monte_carlo_runs)
        alt_stats = (compute_metrics(alt_equity[sl], ppy, alt_trades, first_px, last_px, n - cfg.warmup_bars, 0)
                     if alt_equity is not None else None)

        # meta-model out-of-sample diagnostics
        oos = np.isfinite(probs_arr) & (a["label_end"] < 10**9)
        meta_diag: dict[str, Any] = {"oos_events": int(oos.sum()), "events": int(len(a["ev_idx"])),
                                     "filtered": a["filtered"],
                                     "trusted_events": int(trusted.sum()),
                                     "trust_rule": f"AUC >= {cfg.meta.trust_min_auc} on >= {cfg.meta.trust_min_events} past OOS trades",
                                     "refits": fit_log[-20:], "n_refits": len(fit_log)}
        if oos.sum() >= 20 and len(np.unique(a["labels"][oos])) == 2:
            from sklearn.metrics import brier_score_loss, roc_auc_score
            y, p = a["labels"][oos], probs_arr[oos]
            meta_diag.update(
                auc=float(roc_auc_score(y, p)),
                brier=float(brier_score_loss(y, p)),
                base_rate=float(y.mean()),
                precision_taken=float(y[p >= cfg.min_prob].mean()) if (p >= cfg.min_prob).any() else None,
            )
        if last_model is not None:
            meta_diag["top_features"] = last_model.top_coefficients(meta_feature_names())

        reg = a["reg"]
        regime_stats = {}
        for r in sorted({t.regime for t in trades}):
            rt = [t for t in trades if t.regime == r]
            regime_stats[r] = {"trades": len(rt), "win_rate": float(np.mean([t.pnl > 0 for t in rt])),
                               "avg_r": float(np.mean([t.r_multiple for t in rt])),
                               "pnl": float(sum(t.pnl for t in rt))}
        alpha_ic = {k: float(np.nanmean(a["ics"][k].iloc[sl])) for k in a["ics"].columns}

        ts = lambda i: int(idx[i].timestamp())  # noqa: E731
        return json_safe({
            "engine": "quant_v2",
            "symbol": symbol,
            "stats": stats,
            "meta_model_enabled": cfg.use_meta_model,
            # the other variant, so you can see what the ML filter adds or costs
            "comparison_label": "without meta-model" if cfg.use_meta_model else "with meta-model",
            "comparison_stats": alt_stats,
            "meta_model": meta_diag,
            "regime_stats": regime_stats,
            "alpha_sharpe": alpha_ic,
            "regimes": regime_segments(idx[sl], reg["regime"].iloc[sl]),
            "composite": [{"time": ts(i), "value": float(v)} for i, v in enumerate(a["composite"].to_numpy())
                          if i >= cfg.warmup_bars and np.isfinite(v)],
            "equity_curve": [{"time": ts(i), "equity": float(equity[i])} for i in range(cfg.warmup_bars, n)],
            "comparison_equity_curve": ([{"time": ts(i), "equity": float(alt_equity[i])}
                                         for i in range(cfg.warmup_bars, n)] if alt_equity is not None else []),
            "trades": [self._trade_dict(t, idx) for t in trades],
            "config": _config_dict(cfg),
        })

    # -- public: live decision on the latest bar -----------------------------
    def decide(self, symbol: str, candles: list[OHLCV], news_score: float = 0.0,
               equity: Optional[float] = None) -> dict[str, Any]:
        """Decision for the next bar using a model trained on all resolved history."""
        cfg = self.cfg
        if len(candles) < cfg.warmup_bars + 100:
            raise ValueError(f"Need at least {cfg.warmup_bars + 100} candles, got {len(candles)}")
        df_idx = pd.DatetimeIndex([c.timestamp for c in candles])
        news = pd.Series(0.0, index=df_idx)
        news.iloc[-1] = float(np.clip(news_score, -1, 1))
        a = self.analyze(candles, news)
        t = a["n"] - 1
        comp = float(a["composite"].iloc[t])
        regime = str(a["reg"]["regime"].iloc[t])
        atr_t = float(a["atr"][t])
        side = 1 if comp > 0 else -1
        w = a["weights"].iloc[t]
        contrib = {k: float(w[k] * a["alphas"][k].iloc[t]) for k in ALPHAS}
        out: dict[str, Any] = {
            "engine": "quant_v2", "symbol": symbol, "time": a["df"].index[t].isoformat(), "price": float(a["c"][t]),
            "composite": comp, "regime": regime, "alpha_contrib": contrib,
            "trend_strength": float(a["reg"]["trend_strength"].iloc[t]),
            "atr": atr_t, "action": "flat", "reasons": [],
        }
        if abs(comp) < cfg.entry_threshold:
            out["reasons"].append(f"|composite| {abs(comp):.2f} below entry threshold {cfg.entry_threshold}")
            return out
        if side < 0 and not cfg.allow_short:
            out["reasons"].append("short signal but shorting disabled")
            return out
        d200 = float(a["f"]["dist_sma200_atr"].iloc[t])
        if cfg.trend_filter and np.isfinite(d200) and d200 * side < 0:
            out["reasons"].append("against the 200-bar trend (trend filter)")
            return out
        roundtrip = 2 * (cfg.commission_bps + cfg.slippage_bps) / 1e4
        if cfg.tp_atr * atr_t / float(a["c"][t]) < cfg.min_edge_cost_ratio * roundtrip:
            out["reasons"].append("expected move too small versus trading costs")
            return out

        usable = np.where(a["label_end"] < t - cfg.meta.embargo_bars)[0]
        prob, trusted, live_auc = None, False, None
        if cfg.use_meta_model and len(a["ev_idx"]):
            wf, _, _ = walk_forward_probabilities(a["X"], a["labels"], a["ev_idx"], a["label_end"],
                                                  a["n"], cfg.warmup_bars, cfg.meta)
            past = np.isfinite(wf) & (a["label_end"] < t)
            if past.sum() >= cfg.meta.trust_min_events and len(np.unique(a["labels"][past])) == 2:
                from sklearn.metrics import roc_auc_score
                live_auc = float(roc_auc_score(a["labels"][past], wf[past]))
                trusted = live_auc >= cfg.meta.trust_min_auc
        if cfg.use_meta_model and len(usable) >= cfg.meta.min_train_events:
            model = MetaModel().fit(a["X"][usable], a["labels"][usable])
            Xt = build_meta_matrix(a["f"], a["alphas"], a["composite"], a["reg"]["regime"],
                                   np.array([t]), np.array([side]))
            prob = float(model.predict_proba(Xt)[0])
            out["model"] = {"n_train": int(len(usable)), "base_rate": model.base_rate,
                            "top_features": model.top_coefficients(meta_feature_names(), 6)}
        risk_frac, kelly = self._risk_fraction(prob, trusted)
        out.update(prob=prob, kelly=kelly, risk_fraction=risk_frac, model_trusted=trusted,
                   model_oos_auc=live_auc)
        if risk_frac <= 0:
            out["reasons"].append(
                f"meta-model P(win)={prob:.2f} too low (min {cfg.min_prob}, Kelly {kelly:.3f})"
                if prob is not None else "no risk budget")
            return out

        price = float(a["c"][t])
        sl = price - side * cfg.sl_atr * atr_t
        tp = price + side * cfg.tp_atr * atr_t
        eq = equity or cfg.initial_capital
        qty = eq * risk_frac / (cfg.sl_atr * atr_t)
        vol20 = float(a["f"]["vol_20"].iloc[t])
        ann_vol = max(1e-6, vol20 * math.sqrt(periods_per_year(a["df"].index)))
        qty = min(qty, eq * min(cfg.max_leverage, cfg.target_vol / ann_vol) / price)
        out.update(
            action="buy" if side > 0 else "sell",
            entry_price=price, stop_loss=sl, take_profit=tp,
            risk_reward=cfg.tp_atr / cfg.sl_atr, quantity=qty,
            position_size_pct=min(1.0, qty * price / eq),
            reasons=[f"{regime} regime; composite {comp:+.2f}",
                     (f"P(win)={prob:.2f}, model trusted (OOS AUC {live_auc:.2f}) -> Kelly sizing" if trusted
                      else f"model not trusted yet (OOS AUC {live_auc if live_auc is not None else 'n/a'}) -> base size"),
                     f"risk {risk_frac * 100:.2f}% of equity, stop {cfg.sl_atr}×ATR, target {cfg.tp_atr}×ATR, "
                     f"trail {cfg.trail_atr}×ATR"],
        )
        return out

    @staticmethod
    def _trade_dict(t: QuantTrade, idx: pd.DatetimeIndex) -> dict:
        d = asdict(t)
        d.update(
            side="long" if t.side > 0 else "short",
            action="buy" if t.side > 0 else "sell",
            entry_ts=int(idx[t.entry_idx].timestamp()),
            exit_ts=int(idx[t.exit_idx].timestamp()),
            signal_ts=int(idx[t.signal_idx].timestamp()),
            entry_time=idx[t.entry_idx].isoformat(),
            exit_time=idx[t.exit_idx].isoformat(),
            bars_held=t.exit_idx - t.entry_idx + 1,
            pnl_pct=t.pnl / t.equity_at_entry * 100,
        )
        return d


def json_safe(obj: Any) -> Any:
    """Recursively convert numpy scalars and replace NaN/inf with None (strict JSON)."""
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if math.isfinite(f) else None
    return obj


def _config_dict(cfg: QuantConfig) -> dict:
    d = asdict(cfg)
    d["ensemble"].pop("priors", None)
    return d

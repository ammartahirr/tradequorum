"""
Alpha models and the regime-aware, performance-weighted ensemble.

Each alpha returns a continuous score in [-1, 1] (+ long, - short).
The ensemble weights alphas by
  1. a regime prior (trend alphas in trends, mean-reversion in ranges), and
  2. each alpha's own recent risk-adjusted performance: the exponentially
     weighted Sharpe of the P&L stream ``alpha[t-1] * return[t]``. This is
     causal, so alphas that stop working are down-weighted.

(A rolling-window IC was tried first and rejected: correlating a persistent
signal with overlapping forward returns inside a finite window is biased
negative, which systematically penalised the trend alphas.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .features import EPS

ALPHAS = ["momentum", "trend", "breakout", "mean_reversion", "news"]

REGIME_PRIORS: dict[str, dict[str, float]] = {
    "trend_up":   {"momentum": 0.35, "trend": 0.30, "breakout": 0.25, "mean_reversion": 0.10},
    "trend_down": {"momentum": 0.35, "trend": 0.30, "breakout": 0.25, "mean_reversion": 0.10},
    "range":      {"momentum": 0.10, "trend": 0.05, "breakout": 0.15, "mean_reversion": 0.70},
    "transition": {"momentum": 0.25, "trend": 0.25, "breakout": 0.25, "mean_reversion": 0.25},
    "crisis":     {"momentum": 0.40, "trend": 0.20, "breakout": 0.10, "mean_reversion": 0.30},
}


@dataclass
class EnsembleConfig:
    perf_halflife: int = 126      # bars, EW half-life of the alpha P&L statistics
    perf_gain: float = 0.5        # weight multiplier = clip(1 + gain*sharpe, min, max)
    perf_min_mult: float = 0.25
    perf_max_mult: float = 1.75
    news_weight: float = 0.25     # share of the ensemble given to news when present
    priors: dict = field(default_factory=lambda: REGIME_PRIORS)


def alpha_momentum(f: pd.DataFrame) -> pd.Series:
    """Time-series momentum (Moskowitz/Ooi/Pedersen), vol-scaled, multi-horizon."""
    parts = []
    for n in (20, 60, 120):
        parts.append(np.tanh(f[f"ret_{n}"] / (f["vol_20"] * np.sqrt(n) + EPS)))
    return pd.concat(parts, axis=1).mean(axis=1)


def alpha_trend(f: pd.DataFrame) -> pd.Series:
    """MA spread in ATR units, scaled by trend strength (ADX)."""
    return np.tanh(f["sma20_100_atr"] / 3.0) * (f["adx_14"] / 25.0).clip(0, 1)


def alpha_breakout(f: pd.DataFrame) -> pd.Series:
    """Donchian-55 breakout, stronger after a volatility squeeze."""
    pos = f["donchian_pos_55"]
    raw = pd.Series(0.0, index=f.index)
    raw[pos >= 0.97] = 1.0
    raw[pos <= 0.03] = -1.0
    squeeze = (f["bb_width_pctile"].shift(1) < 0.30).astype(float)
    raw = raw * (0.6 + 0.4 * squeeze)
    # persist the signal for a few bars after the break (decays)
    return raw.ewm(span=4, adjust=False).mean().clip(-1, 1)


def alpha_mean_reversion(f: pd.DataFrame) -> pd.Series:
    """Buy short-term dips in long-term uptrends (and vice versa)."""
    z = -np.tanh(f["zscore_20"] / 1.5) * 0.5
    r2 = pd.Series(0.0, index=f.index)
    r2[f["rsi_2"] < 10] = 0.5
    r2[f["rsi_2"] > 90] = -0.5
    base = z + r2
    up = f["dist_sma200_atr"] > 0
    aligned = ((base > 0) & up) | ((base < 0) & ~up)
    return base.where(aligned, base * 0.3).clip(-1, 1)


def compute_alphas(f: pd.DataFrame, news: Optional[pd.Series] = None) -> pd.DataFrame:
    a = pd.DataFrame(index=f.index)
    a["momentum"] = alpha_momentum(f)
    a["trend"] = alpha_trend(f)
    a["breakout"] = alpha_breakout(f)
    a["mean_reversion"] = alpha_mean_reversion(f)
    a["news"] = (news.reindex(f.index).fillna(0.0).clip(-1, 1) if news is not None else 0.0)
    return a.fillna(0.0)


def rolling_alpha_sharpe(alpha: pd.Series, close: pd.Series, halflife: int) -> pd.Series:
    """Annualised EW Sharpe of the alpha's own P&L, known at bar t."""
    pnl = alpha.shift(1) * np.log(close).diff()
    mean = pnl.ewm(halflife=halflife, min_periods=halflife // 2).mean()
    std = pnl.ewm(halflife=halflife, min_periods=halflife // 2).std()
    return mean / (std + EPS) * np.sqrt(252)


def combine(
    alphas: pd.DataFrame,
    regime: pd.Series,
    close: pd.Series,
    cfg: EnsembleConfig,
    news_present: Optional[pd.Series] = None,
) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    """Return (composite score, effective weights, rolling alpha Sharpe table)."""
    techs = ["momentum", "trend", "breakout", "mean_reversion"]
    ics = pd.DataFrame({k: rolling_alpha_sharpe(alphas[k], close, cfg.perf_halflife) for k in techs})
    mult = (1 + cfg.perf_gain * ics.fillna(0.0)).clip(cfg.perf_min_mult, cfg.perf_max_mult)

    prior = pd.DataFrame(
        [cfg.priors.get(r, cfg.priors["transition"]) for r in regime], index=alphas.index
    )[techs]
    w = prior * mult
    w = w.div(w.sum(axis=1) + EPS, axis=0)

    if news_present is not None:
        nw = news_present.reindex(alphas.index).fillna(False).astype(float) * cfg.news_weight
    else:
        nw = (alphas["news"].abs() > 0).astype(float) * cfg.news_weight
    w = w.mul(1 - nw, axis=0)
    w["news"] = nw

    composite = (w * alphas[techs + ["news"]]).sum(axis=1).clip(-1, 1)
    return composite, w, ics

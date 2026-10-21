"""
Market regime detection.

Combines trend strength (ADX + Kaufman efficiency ratio), persistence
(variance ratio: >1 trending, <1 mean-reverting) and the volatility
percentile into one of: trend_up, trend_down, range, transition, crisis.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .features import EPS

REGIMES = ["trend_up", "trend_down", "range", "transition", "crisis"]


def variance_ratio(close: pd.Series, q: int = 10, window: int = 120) -> pd.Series:
    r1 = np.log(close).diff()
    rq = np.log(close).diff(q)
    return rq.rolling(window).var() / (q * r1.rolling(window).var() + EPS)


def detect_regime(df: pd.DataFrame, f: pd.DataFrame) -> pd.DataFrame:
    adx_n = ((f["adx_14"] - 15) / 25).clip(0, 1)
    strength = (0.5 * adx_n + 0.5 * f["efficiency_20"].clip(0, 1)).ewm(span=5, adjust=False).mean()
    vr = variance_ratio(df["close"])
    direction = np.sign(f["sma50_slope_atr"].fillna(0) + 0.5 * np.sign(f["dist_sma200_atr"].fillna(0)))

    regime = pd.Series("transition", index=df.index, dtype=object)
    trending = (strength > 0.45) & (vr.fillna(1.0) > 0.95)
    regime[trending & (direction > 0)] = "trend_up"
    regime[trending & (direction < 0)] = "trend_down"
    regime[(strength < 0.30) | (vr < 0.8)] = "range"
    regime[f["vol_pctile"] > 0.95] = "crisis"
    regime[f["adx_14"].isna()] = "transition"

    return pd.DataFrame(
        {"regime": regime, "trend_strength": strength, "variance_ratio": vr, "trend_dir": direction},
        index=df.index,
    )


def regime_segments(times: pd.DatetimeIndex, regime: pd.Series) -> list[dict]:
    """Compress a per-bar regime series into [{from, to, regime}] runs."""
    out: list[dict] = []
    vals = regime.to_numpy()
    if len(vals) == 0:
        return out
    start = 0
    for i in range(1, len(vals) + 1):
        if i == len(vals) or vals[i] != vals[start]:
            out.append({
                "from": int(times[start].timestamp()),
                "to": int(times[i - 1].timestamp()),
                "regime": str(vals[start]),
            })
            start = i
    return out

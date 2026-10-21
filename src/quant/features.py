"""
Causal feature engineering.

Every feature at bar ``t`` uses only data up to and including bar ``t``'s
close. Trades decided on bar ``t`` fill at bar ``t+1``'s open, so there is no
look-ahead anywhere in the pipeline.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.models.signals import OHLCV

EPS = 1e-12


def ohlcv_to_frame(candles: list[OHLCV]) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [float(c.volume) for c in candles],
        },
        index=pd.DatetimeIndex([c.timestamp for c in candles], name="time"),
    )
    return df[~df.index.duplicated(keep="last")].sort_index()


def wilder(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1
    ).max(axis=1)
    return wilder(tr, n)


def rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = wilder(d.clip(lower=0), n)
    dn = wilder((-d).clip(lower=0), n)
    return 100 - 100 / (1 + up / (dn + EPS))


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    a = atr(df, n)
    plus_di = 100 * wilder(plus_dm, n) / (a + EPS)
    minus_di = 100 * wilder(minus_dm, n) / (a + EPS)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + EPS)
    return wilder(dx, n)


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return a feature frame aligned with ``df`` (NaN during warm-up)."""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    logc = np.log(c)
    r1 = logc.diff()
    f = pd.DataFrame(index=df.index)

    for n in (1, 5, 20, 60, 120):
        f[f"ret_{n}"] = logc - logc.shift(n)

    f["vol_20"] = r1.rolling(20).std()
    f["vol_60"] = r1.rolling(60).std()
    f["vol_ratio"] = f["vol_20"] / (f["vol_60"] + EPS)
    hl = np.log(h / l)
    f["parkinson_20"] = np.sqrt((hl**2).rolling(20).mean() / (4 * np.log(2)))
    f["vol_of_vol"] = f["vol_20"].rolling(60).std() / (f["vol_20"].rolling(60).mean() + EPS)
    f["vol_pctile"] = f["vol_20"].rolling(252, min_periods=60).rank(pct=True)

    a14 = atr(df, 14)
    f["atr_14"] = a14
    f["atr_pct"] = a14 / c

    f["rsi_14"] = rsi(c, 14)
    f["rsi_2"] = rsi(c, 2)

    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    f["macd_hist_atr"] = (macd - macd.ewm(span=9, adjust=False).mean()) / (a14 + EPS)

    sma20, std20 = c.rolling(20).mean(), c.rolling(20).std()
    f["zscore_20"] = (c - sma20) / (std20 + EPS)
    f["bb_pctb"] = (c - (sma20 - 2 * std20)) / (4 * std20 + EPS)
    bbw = 4 * std20 / (sma20 + EPS)
    f["bb_width_pctile"] = bbw.rolling(120, min_periods=40).rank(pct=True)

    sma50, sma100, sma200 = c.rolling(50).mean(), c.rolling(100).mean(), c.rolling(200).mean()
    f["dist_sma50_atr"] = (c - sma50) / (a14 + EPS)
    f["dist_sma200_atr"] = (c - sma200) / (a14 + EPS)
    f["sma20_100_atr"] = (sma20 - sma100) / (a14 + EPS)
    f["sma50_slope_atr"] = (sma50 - sma50.shift(10)) / (a14 + EPS)

    f["adx_14"] = adx(df, 14)
    f["efficiency_20"] = (c - c.shift(20)).abs() / (c.diff().abs().rolling(20).sum() + EPS)

    hi55, lo55 = h.rolling(55).max(), l.rolling(55).min()
    f["donchian_pos_55"] = (c - lo55) / (hi55 - lo55 + EPS)

    vstd = v.rolling(20).std()
    f["volume_z"] = ((v - v.rolling(20).mean()) / vstd.replace(0, np.nan)).fillna(0.0)

    f["skew_60"] = r1.rolling(60).skew()
    f["kurt_60"] = r1.rolling(60).kurt()
    f["autocorr_60"] = r1.rolling(60).corr(r1.shift(1))

    body = (c - df["open"]).abs()
    f["close_loc"] = (c - l) / (h - l + EPS)  # where the bar closed inside its range
    f["body_atr"] = body / (a14 + EPS)
    return f.replace([np.inf, -np.inf], np.nan)


# Columns fed to the meta-model (scale-free, comparable across symbols)
META_FEATURES = [
    "ret_1", "ret_5", "ret_20", "ret_60",
    "vol_ratio", "vol_of_vol", "vol_pctile", "atr_pct",
    "rsi_14", "rsi_2", "macd_hist_atr", "zscore_20", "bb_pctb", "bb_width_pctile",
    "dist_sma50_atr", "dist_sma200_atr", "sma50_slope_atr",
    "adx_14", "efficiency_20", "donchian_pos_55", "volume_z",
    "skew_60", "kurt_60", "autocorr_60", "close_loc", "body_atr",
]

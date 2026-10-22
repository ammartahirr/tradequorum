"""
Meta-labeling (López de Prado, *Advances in Financial Machine Learning*).

The primary model (alpha ensemble) decides the *side*. A secondary ML model
predicts the probability that the primary trade hits its profit barrier
before its stop / time barrier. That probability filters and sizes trades.

Training is strictly walk-forward:
- labels come from the triple-barrier method and end at ``t1`` (exit bar)
- a sample is usable for a model trained at bar ``T`` only if ``t1 < T - embargo``
  (purging + embargo: no label overlaps the prediction period)
- the model is refit every ``retrain_every`` bars on an expanding window
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from .features import META_FEATURES

logger = logging.getLogger(__name__)

# Features whose sign carries direction: multiplied by trade side so the model
# learns "aligned with the trade" vs "against the trade".
DIRECTIONAL = {
    "ret_1", "ret_5", "ret_20", "ret_60", "macd_hist_atr", "zscore_20",
    "dist_sma50_atr", "dist_sma200_atr", "sma50_slope_atr", "skew_60",
}
CENTERED = {"bb_pctb": 0.5, "donchian_pos_55": 0.5, "close_loc": 0.5, "rsi_14": 50.0, "rsi_2": 50.0}


@dataclass
class MetaConfig:
    trust_min_events: int = 50    # resolved OOS predictions needed before trusting the model
    trust_min_auc: float = 0.55   # walk-forward AUC the model must have earned
    min_train_events: int = 40
    retrain_every: int = 60
    embargo_bars: int = 5
    max_train_events: int = 2000


def build_meta_matrix(
    f: pd.DataFrame, alphas: pd.DataFrame, composite: pd.Series, regime: pd.Series,
    idx: np.ndarray, sides: np.ndarray,
) -> np.ndarray:
    cols = []
    for name in META_FEATURES:
        x = f[name].to_numpy()[idx].astype(float)
        if name in CENTERED:
            x = x - CENTERED[name]
        if name in DIRECTIONAL or name in CENTERED:
            x = x * sides
        cols.append(x)
    for a in ("momentum", "trend", "breakout", "mean_reversion", "news"):
        cols.append(alphas[a].to_numpy()[idx] * sides)
    comp = composite.to_numpy()[idx]
    cols.append(np.abs(comp))
    cols.append(comp * sides)
    reg = regime.to_numpy()[idx]
    for r in ("trend_up", "trend_down", "range", "crisis"):
        cols.append((reg == r).astype(float))
    cols.append(sides.astype(float))
    X = np.column_stack(cols)
    return np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)


def meta_feature_names() -> list[str]:
    return (
        list(META_FEATURES)
        + [f"alpha_{a}" for a in ("momentum", "trend", "breakout", "mean_reversion", "news")]
        + ["abs_composite", "composite_x_side", "reg_trend_up", "reg_trend_down", "reg_range",
           "reg_crisis", "side"]
    )


class MetaModel:
    """Soft-voting ensemble of L2 logistic regression and shallow gradient boosting."""

    def __init__(self):
        self._lr = None
        self._gb = None
        self.n_train = 0
        self.base_rate = 0.5

    def fit(self, X: np.ndarray, y: np.ndarray) -> "MetaModel":
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        self.n_train = len(y)
        self.base_rate = float(np.mean(y)) if len(y) else 0.5
        if len(np.unique(y)) < 2:
            self._lr = self._gb = None
            return self
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._lr = make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=500))
            self._lr.fit(X, y)
            self._gb = HistGradientBoostingClassifier(
                max_depth=3, max_iter=120, learning_rate=0.05, min_samples_leaf=max(8, len(y) // 20),
                l2_regularization=1.0, random_state=7,
            )
            self._gb.fit(X, y)
        return self

    @property
    def ready(self) -> bool:
        return self._lr is not None

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self.ready:
            return np.full(len(X), self.base_rate)
        p = 0.5 * self._lr.predict_proba(X)[:, 1] + 0.5 * self._gb.predict_proba(X)[:, 1]
        # shrink toward the base rate when training data is scarce (Bayesian-style)
        k = self.n_train / (self.n_train + 100.0)
        return k * p + (1 - k) * self.base_rate

    def top_coefficients(self, names: list[str], k: int = 10) -> list[dict]:
        if not self.ready:
            return []
        coef = self._lr[-1].coef_[0]
        order = np.argsort(-np.abs(coef))[:k]
        return [{"feature": names[i], "weight": float(coef[i])} for i in order]


def walk_forward_probabilities(
    X: np.ndarray, y: np.ndarray, event_idx: np.ndarray, label_end: np.ndarray,
    n_bars: int, start_bar: int, cfg: MetaConfig,
) -> tuple[np.ndarray, Optional[MetaModel], list[dict]]:
    """
    Out-of-sample probability for every candidate event.
    Returns (probs, last_model, fit_log). NaN prob = no model yet (warm-up).
    """
    probs = np.full(len(event_idx), np.nan)
    model: Optional[MetaModel] = None
    fit_log: list[dict] = []
    order = np.argsort(event_idx)
    next_fit = start_bar
    for j in order:
        t = event_idx[j]
        if t >= next_fit or model is None:
            usable = np.where(label_end < t - cfg.embargo_bars)[0]
            if len(usable) >= cfg.min_train_events:
                usable = usable[-cfg.max_train_events:]
                model = MetaModel().fit(X[usable], y[usable])
                fit_log.append({"bar": int(t), "n_train": int(len(usable)),
                                "base_rate": round(model.base_rate, 3)})
                next_fit = t + cfg.retrain_every
        if model is not None and model.ready:
            probs[j] = model.predict_proba(X[j:j + 1])[0]
    return probs, model, fit_log


def causal_trust(
    probs: np.ndarray, y: np.ndarray, event_idx: np.ndarray, label_end: np.ndarray, cfg: MetaConfig,
) -> tuple[np.ndarray, np.ndarray]:
    """
    For each event, the AUC of the model's *earlier* out-of-sample predictions
    whose outcomes were already known at that time, and whether it passes the
    trust bar. Uses only information available at the event bar.
    """
    from sklearn.metrics import roc_auc_score

    auc_at = np.full(len(event_idx), np.nan)
    trusted = np.zeros(len(event_idx), dtype=bool)
    have = np.isfinite(probs)
    for j in np.argsort(event_idx):
        t = event_idx[j]
        past = have & (label_end < t)
        if past.sum() >= cfg.trust_min_events and len(np.unique(y[past])) == 2:
            auc_at[j] = roc_auc_score(y[past], probs[past])
            trusted[j] = auc_at[j] >= cfg.trust_min_auc
    return auc_at, trusted

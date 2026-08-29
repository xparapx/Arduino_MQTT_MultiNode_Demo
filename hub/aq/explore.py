"""Exploratory aggregates for page 2 section H (Phase 5).

These are the two RobustScaling regime views and the correlation heatmap that
page 1 used to compute from raw rows on every refresh. analyst.py now computes
them once per daily run over the analysis window and stores the aggregates in
the analysis table (kind 'explore'); the page only draws. They are viewing
tools -- the decision engine (B-E) uses the fixed-scale GMM only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CORR_VARS = ("co2", "voc", "pm2p5", "temp", "hum")
POOLED_BINS = 24
NODE_BINS = 20
RANGE_MIN, RANGE_MAX, RANGE_PAD = 1.5, 3.0, 1.15
MIN_ROWS = 3


def robust_params(s: pd.Series) -> tuple[float, float]:
    med = float(s.median())
    iqr = float(s.quantile(0.75) - s.quantile(0.25))
    return med, iqr


def robust(s: pd.Series, med: float, iqr: float) -> pd.Series:
    return (s - med) / iqr if iqr and iqr > 0 else (s - med) * 0.0


def _amax(zx: pd.Series, zy: pd.Series) -> float:
    """Symmetric axis range from the 2nd / 98th percentiles, clamped to [1.5, 3]."""
    def prange(s):
        return max(abs(float(s.quantile(0.02))), abs(float(s.quantile(0.98))))
    a = max(prange(zx), prange(zy))
    a = a * RANGE_PAD if a > 0 else 1.0
    return float(min(max(a, RANGE_MIN), RANGE_MAX))


def density(d: pd.DataFrame, bins: int) -> dict | None:
    """RobustScaling parameters + bins x bins histogram of (co2, voc) rows."""
    d = d[["co2", "voc"]].dropna()
    if len(d) < MIN_ROWS:
        return None
    co2_med, co2_iqr = robust_params(d["co2"])
    voc_med, voc_iqr = robust_params(d["voc"])
    zx, zy = robust(d["co2"], co2_med, co2_iqr), robust(d["voc"], voc_med, voc_iqr)
    amax = _amax(zx, zy)
    H, _, _ = np.histogram2d(zx.clip(-amax, amax), zy.clip(-amax, amax), bins=bins,
                             range=[[-amax, amax], [-amax, amax]])
    return {"co2_med": round(co2_med, 2), "co2_iqr": round(co2_iqr, 2),
            "voc_med": round(voc_med, 2), "voc_iqr": round(voc_iqr, 2),
            "amax": round(amax, 3), "bins": int(bins), "n": int(len(d)),
            "hist": H.astype(int).tolist()}


def correlation(df: pd.DataFrame) -> tuple[list, dict]:
    cols = [c for c in CORR_VARS if c in df.columns]
    corr = df[cols].corr(method="spearman")
    return cols, {a: {b: (None if pd.isna(corr.loc[a, b]) else round(float(corr.loc[a, b]), 3))
                      for b in cols} for a in cols}


def payload(df: pd.DataFrame, cfg: dict) -> dict:
    """explore payload over QC-passed rows of the daily window."""
    vars_, corr = correlation(df)
    pooled = density(df, POOLED_BINS) or {}
    nodes = {}
    for node, g in df.groupby("node", sort=True):
        d = density(g, NODE_BINS)
        if d:
            nodes[node] = d
    return {"vars": vars_, "corr": corr, "pooled": pooled, "nodes": nodes}

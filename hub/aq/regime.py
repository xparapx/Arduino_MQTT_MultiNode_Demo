"""CO2 / VOC regime model (Phase 3).

Fixed-scale inputs (co2/400, voc/100), GaussianMixture(4, full, random_state=0,
n_init=5), quadrant-anchored labels clean / matter / human / mixed, rolling-mode
smoothing (window 9, broken at gaps) and gap-aware transition matrices.

The GMM is unsupervised (no circular labels); the anchoring step only names
the four clusters by which quadrant their centroid sits in, relative to the
fixed baseline (co2 700 ppm, voc 120). If two centroids share a quadrant the
candidate is rejected (AnchorError) -- plan section 2.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture

REGIMES = ("clean", "matter", "human", "mixed")


class AnchorError(ValueError):
    """Two GMM components fall in the same quadrant: candidate rejected."""


# ---- features -------------------------------------------------------------------

def features(df: pd.DataFrame, cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    """(X, mask): X = [co2/co2_scale, voc/voc_scale] for rows where both are
    present; mask marks those rows in df's order. Rows with either NaN are
    excluded from fitting and prediction alike (no interpolation)."""
    reg = cfg["regime"]
    co2 = pd.to_numeric(df["co2"], errors="coerce").to_numpy(float)
    voc = pd.to_numeric(df["voc"], errors="coerce").to_numpy(float)
    mask = ~(np.isnan(co2) | np.isnan(voc))
    X = np.column_stack([co2[mask] / reg["co2_scale"], voc[mask] / reg["voc_scale"]])
    return X, mask


def anchors(cfg: dict) -> tuple[float, float]:
    reg = cfg["regime"]
    return reg["anchor_co2_ppm"] / reg["co2_scale"], reg["anchor_voc_index"] / reg["voc_scale"]


def quadrant(mu_co2: float, mu_voc: float, cfg: dict) -> str:
    """clean = low/low, matter = low co2 / high voc, human = high co2 / low voc,
    mixed = high/high."""
    a_co2, a_voc = anchors(cfg)
    hi_co2, hi_voc = mu_co2 >= a_co2, mu_voc >= a_voc
    if hi_co2 and hi_voc:
        return "mixed"
    if hi_co2:
        return "human"
    if hi_voc:
        return "matter"
    return "clean"


# ---- model ----------------------------------------------------------------------

def fit(df: pd.DataFrame, cfg: dict) -> GaussianMixture:
    reg = cfg["regime"]
    X, _ = features(df, cfg)
    if len(X) < reg["n_components"] * 2:
        raise ValueError(f"regime.fit: only {len(X)} usable rows")
    model = GaussianMixture(n_components=reg["n_components"],
                            covariance_type=reg["covariance_type"],
                            random_state=reg["random_state"], n_init=reg["n_init"])
    model.fit(X)
    return model


def anchor_labels(model: GaussianMixture, cfg: dict) -> dict[int, str]:
    """component index -> regime name. Raises AnchorError unless the four
    centroids occupy four different quadrants."""
    labels = {i: quadrant(float(m[0]), float(m[1]), cfg) for i, m in enumerate(model.means_)}
    dup = [q for q, c in Counter(labels.values()).items() if c > 1]
    if dup:
        mus = {i: (round(float(m[0]), 2), round(float(m[1]), 2))
               for i, m in enumerate(model.means_)}
        raise AnchorError(f"components share quadrant(s) {dup}: {mus}")
    return labels


def predict(model: GaussianMixture, labels: dict[int, str], df: pd.DataFrame,
            cfg: dict) -> pd.Series:
    """Regime name per row of df (object Series aligned to df.index); None where
    co2 or voc is missing."""
    X, mask = features(df, cfg)
    out = pd.Series([None] * len(df), index=df.index, dtype=object)
    if len(X):
        comp = model.predict(X)
        out.loc[df.index[mask]] = [labels[int(c)] for c in comp]
    return out


def model_meta(model: GaussianMixture, labels: dict[int, str], cfg: dict) -> dict:
    """Serialisable description: centroids (scaled + raw units), weights, quadrant map."""
    reg = cfg["regime"]
    comps = []
    for i, (m, w) in enumerate(zip(model.means_, model.weights_, strict=True)):
        comps.append({"component": i, "regime": labels[i],
                      "mu_scaled": [round(float(m[0]), 4), round(float(m[1]), 4)],
                      "mu_raw": [round(float(m[0]) * reg["co2_scale"], 1),
                                 round(float(m[1]) * reg["voc_scale"], 1)],
                      "weight": round(float(w), 4)})
    return {"n_components": int(model.n_components), "covariance_type": model.covariance_type,
            "random_state": reg["random_state"], "anchors_scaled": list(anchors(cfg)),
            "components": comps, "converged": bool(model.converged_)}


# ---- time post-processing (HMM approximation) --------------------------------------

def _minutes_between(buckets: pd.Series) -> np.ndarray:
    t = pd.to_datetime(buckets).to_numpy()
    return np.diff(t).astype("timedelta64[s]").astype(float) / 60.0


def segments(buckets: pd.Series, cfg: dict) -> list[tuple[int, int]]:
    """[start, end) index ranges of consecutive buckets exactly one bucket apart.
    A missing bucket (dt != bucket_minutes) starts a new segment."""
    n = len(buckets)
    if n == 0:
        return []
    step = float(cfg["time"]["bucket_minutes"])
    dts = _minutes_between(buckets)
    segs, start = [], 0
    for i, dt in enumerate(dts, start=1):
        if dt != step:
            segs.append((start, i))
            start = i
    segs.append((start, n))
    return segs


def _mode(values: list, fallback):
    vals = [v for v in values if v is not None]
    if not vals:
        return fallback
    counts = Counter(vals)
    best = max(counts.values())
    winners = [v for v, c in counts.items() if c == best]
    if fallback in winners or (len(winners) > 1 and fallback in vals):
        return fallback
    return winners[0]


def smooth(series: pd.Series, buckets: pd.Series, cfg: dict) -> pd.Series:
    """Rolling mode (window smooth_window, centred) within each contiguous
    segment; the window never crosses a gap. Ties keep the current value."""
    win = int(cfg["time"]["smooth_window"])
    half = win // 2
    vals = list(series)
    out = list(vals)
    for a, b in segments(buckets, cfg):
        for i in range(a, b):
            lo, hi = max(a, i - half), min(b, i + half + 1)
            out[i] = _mode(vals[lo:hi], vals[i]) if vals[i] is not None else None
    return pd.Series(out, index=series.index, dtype=object)


def runs(series: pd.Series, buckets: pd.Series, cfg: dict) -> list[dict]:
    """Maximal runs of one regime inside a segment: regime, start, end (bucket
    strings), buckets (count), minutes, left/right-censored flags (run touches
    a segment edge, so its true length is only bounded from below)."""
    step = int(cfg["time"]["bucket_minutes"])
    vals, bk = list(series), list(buckets)
    out = []
    for a, b in segments(buckets, cfg):
        i = a
        while i < b:
            j = i
            while j + 1 < b and vals[j + 1] == vals[i]:
                j += 1
            if vals[i] is not None:
                out.append({"regime": vals[i], "start": bk[i], "end": bk[j],
                            "buckets": j - i + 1, "minutes": (j - i + 1) * step,
                            "left_censored": i == a, "right_censored": j == b - 1})
            i = j + 1
    return out


def transitions(series: pd.Series, buckets: pd.Series, cfg: dict) -> dict:
    """transition payload. A consecutive pair counts only if its buckets are
    bucket_minutes +/- tolerance apart and both regimes are known; other pairs
    are reported in gap_pairs. dwell_median is over runs of the smoothed series
    (minutes); runs touching a segment edge are lower bounds but are included."""
    step, tol = cfg["time"]["transition_dt_minutes"], cfg["time"]["transition_dt_tolerance"]
    vals = list(series)
    counts = {r: {c: 0 for c in REGIMES} for r in REGIMES}
    gap = valid = 0
    if len(vals) > 1:
        for dt, a, b in zip(_minutes_between(buckets), vals[:-1], vals[1:], strict=True):
            if abs(dt - step) > tol:
                gap += 1
                continue
            if a is None or b is None:
                continue
            counts[a][b] += 1
            valid += 1
    matrix = {}
    for r in REGIMES:
        tot = sum(counts[r].values())
        matrix[r] = {c: (round(counts[r][c] / tot, 4) if tot else 0.0) for c in REGIMES}
    dwell: dict[str, list[int]] = {r: [] for r in REGIMES}
    for run in runs(series, buckets, cfg):
        dwell[run["regime"]].append(run["minutes"])
    dwell_median = {r: (float(np.median(v)) if v else None) for r, v in dwell.items()}
    return {"matrix": matrix, "counts": counts, "gap_pairs": int(gap), "valid_pairs": int(valid),
            "dwell_median": dwell_median}


def current_dwell(series: pd.Series, buckets: pd.Series, cfg: dict) -> tuple[float, bool]:
    """(minutes, censored) of the last run. Censored when the run starts at a
    segment edge (window start or a gap) -- the true dwell is at least this."""
    rs = runs(series, buckets, cfg)
    if not rs:
        return 0.0, True
    last = rs[-1]
    return float(last["minutes"]), bool(last["left_censored"])

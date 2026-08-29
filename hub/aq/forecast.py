"""Short-horizon CO2 / VOC forecast (Phase 3).

Target = the observed value target_shift_buckets later (30 min): an independent
future measurement, never a label derived from the inputs. Features are the
current level, three lags and the last change, on a contiguous bucket grid.
One sklearn Pipeline (StandardScaler -> Ridge, multi-output) is fitted on the
rows that have a target and applied to the newest row, so preprocessing is
identical in training and inference and no future row leaks into the fit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

TARGETS = ("co2", "voc")
LAGS = (1, 2, 3)


def make_pipeline() -> Pipeline:
    return Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=1.0))])


def supervised(df_node: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(X, Y) on a complete 5-min grid for ONE node. Y is X shifted -shift
    buckets (future observation); rows whose features or targets are missing are
    dropped. The last `shift` rows of the window have no target yet and stay in
    X only (Y is NaN there) so the caller can predict from the newest row."""
    step = cfg["time"]["bucket_minutes"]
    shift = cfg["forecast"]["target_shift_buckets"]
    d = df_node[["bucket", "co2", "voc"]].copy()
    d["bucket"] = pd.to_datetime(d["bucket"])
    d = d.set_index("bucket").sort_index()
    if d.empty:
        return pd.DataFrame(), pd.DataFrame()
    grid = pd.date_range(d.index.min(), d.index.max(), freq=f"{step}min")
    d = d.reindex(grid)                       # gaps become NaN rows (no interpolation)
    X = pd.DataFrame(index=grid)
    for t in TARGETS:
        X[t] = d[t]
        for lag in LAGS:
            X[f"{t}_lag{lag}"] = d[t].shift(lag)
        X[f"{t}_diff1"] = d[t] - d[t].shift(1)
    Y = pd.DataFrame({t: d[t].shift(-shift) for t in TARGETS}, index=grid)
    ok = X.notna().all(axis=1)
    return X[ok], Y[ok]


def fit_predict(df_node: pd.DataFrame, cfg: dict, horizon: int | None = None) -> dict | None:
    """forecast payload for one node, or None when the window is too short.
    `horizon` (minutes) is informational; the model horizon is fixed by
    forecast.target_shift_buckets * time.bucket_minutes."""
    X, Y = supervised(df_node, cfg)
    train = Y.notna().all(axis=1)
    if int(train.sum()) < cfg["run"]["forecast_min_rows"]:
        return None
    pipe = make_pipeline()
    pipe.fit(X[train].to_numpy(float), Y[train].to_numpy(float))
    pred = pipe.predict(X.iloc[[-1]].to_numpy(float))[0]
    co2_pred, voc_pred = float(pred[0]), float(pred[1])
    horizon_min = int(horizon if horizon is not None
                      else cfg["forecast"]["target_shift_buckets"] * cfg["time"]["bucket_minutes"])
    alert = bool(co2_pred > cfg["rules"]["fan"]["on_co2"]
                 or voc_pred > cfg["rules"]["purifier"]["on_voc"])
    return {"horizon_min": horizon_min, "co2_pred": round(co2_pred, 1),
            "voc_pred": round(voc_pred, 1), "alert": alert,
            "train_rows": int(train.sum()),
            "as_of_bucket": X.index[-1].strftime("%Y-%m-%d %H:%M:%S")}


def leakage_check(df_node: pd.DataFrame, cfg: dict) -> bool:
    """True when every training target lies strictly after its feature row
    (the -shift alignment is correct). Used by tests."""
    X, Y = supervised(df_node, cfg)
    shift = cfg["forecast"]["target_shift_buckets"]
    step = cfg["time"]["bucket_minutes"]
    d = df_node[["bucket", "co2"]].copy()
    d["bucket"] = pd.to_datetime(d["bucket"])
    obs = d.set_index("bucket")["co2"]
    for t, y in Y["co2"].dropna().items():
        future = obs.get(t + pd.Timedelta(minutes=shift * step))
        if future is None or not np.isclose(future, y):
            return False
    return True

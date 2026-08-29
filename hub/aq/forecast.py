"""Short-horizon CO2 / VOC forecast (Phase 3).

Target is the future observation (shift -6 buckets = 30 min); the same Pipeline
is used for fit and inference. Tests only assert shape and absence of leakage.
"""

from __future__ import annotations


def fit_predict(df, horizon: int = 30, cfg: dict | None = None) -> dict:
    raise NotImplementedError("Phase 3")

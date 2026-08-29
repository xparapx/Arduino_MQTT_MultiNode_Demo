"""CO2 / VOC regime model (Phase 3).

Fixed-scale inputs (co2/400, voc/100), GaussianMixture(4, full, random_state=0,
n_init=5), quadrant-anchored labels clean / matter / human / mixed, rolling-mode
smoothing (window 9, broken at gaps) and gap-aware transition matrices.
"""

from __future__ import annotations

REGIMES = ("clean", "matter", "human", "mixed")


def fit(df, cfg: dict):
    raise NotImplementedError("Phase 3")


def anchor_labels(model, cfg: dict) -> dict:
    raise NotImplementedError("Phase 3")


def predict(model, df, cfg: dict):
    raise NotImplementedError("Phase 3")


def smooth(series, gaps, cfg: dict):
    raise NotImplementedError("Phase 3")


def transitions(series, ts, cfg: dict):
    raise NotImplementedError("Phase 3")

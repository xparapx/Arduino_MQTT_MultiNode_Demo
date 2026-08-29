"""aq.regime: quadrant anchoring 1:1, random_state reproducibility, NaN rows excluded,
smoothing that stops at gaps, transition pairs dropped outside 5 +/- 2 min."""

import numpy as np
import pandas as pd
import pytest

from aq import config, regime


@pytest.fixture(scope="module")
def cfg():
    return config.load()


def _blobs(seed=0, n=300):
    """Four well-separated clusters, one per quadrant (raw ppm / index units)."""
    rng = np.random.default_rng(seed)
    centers = {"clean": (500, 80), "matter": (500, 250), "human": (1200, 80), "mixed": (1300, 260)}
    parts = []
    for name, (c, v) in centers.items():
        parts.append(pd.DataFrame({"co2": rng.normal(c, 40, n), "voc": rng.normal(v, 12, n),
                                   "truth": name}))
    df = pd.concat(parts, ignore_index=True)
    df["bucket"] = [f"2026-08-{1 + i // 288:02d} {(i % 288) // 12:02d}:{(i % 12) * 5:02d}:00"
                    for i in range(len(df))]
    return df


def test_quadrant_function(cfg):
    assert regime.quadrant(1.0, 1.0, cfg) == "clean"
    assert regime.quadrant(1.0, 1.2, cfg) == "matter"      # anchors are inclusive
    assert regime.quadrant(1.75, 1.0, cfg) == "human"
    assert regime.quadrant(3.0, 2.5, cfg) == "mixed"


def test_fit_anchor_predict_one_to_one(cfg):
    df = _blobs()
    model = regime.fit(df, cfg)
    labels = regime.anchor_labels(model, cfg)
    assert sorted(labels.values()) == sorted(regime.REGIMES)
    pred = regime.predict(model, labels, df, cfg)
    agreement = (pred == df["truth"]).mean()
    assert agreement > 0.97
    meta = regime.model_meta(model, labels, cfg)
    assert {c["regime"] for c in meta["components"]} == set(regime.REGIMES)
    assert meta["converged"]


def test_random_state_reproducible(cfg):
    df = _blobs()
    m1, m2 = regime.fit(df, cfg), regime.fit(df, cfg)
    assert np.allclose(np.sort(m1.means_, axis=0), np.sort(m2.means_, axis=0))


def test_anchor_rejects_shared_quadrant(cfg):
    df = _blobs()
    df = df[df["truth"].isin(["clean", "human"])]        # only two real clusters
    model = regime.fit(df, cfg)                          # 4 components forced onto 2 blobs
    with pytest.raises(regime.AnchorError):
        regime.anchor_labels(model, cfg)


def test_nan_rows_are_excluded(cfg):
    df = _blobs()
    df.loc[df.index[:5], "voc"] = np.nan
    model = regime.fit(df, cfg)
    X, mask = regime.features(df, cfg)
    assert len(X) == len(df) - 5 and mask[:5].sum() == 0
    pred = regime.predict(model, regime.anchor_labels(model, cfg), df, cfg)
    assert pred.iloc[:5].isna().all() and pred.iloc[5:].notna().all()


def _series(labels, buckets):
    return pd.Series(labels, dtype=object), pd.Series(buckets)


def test_smooth_breaks_at_gap(cfg):
    # 12 buckets, gap of 30 min after index 5; a single spike inside a segment is removed,
    # a value at a segment edge is not contaminated by the other segment.
    b = [f"2026-08-29 00:{i * 5:02d}:00" for i in range(6)] + \
        [f"2026-08-29 01:{i * 5:02d}:00" for i in range(6)]
    s, bk = _series(["clean"] * 2 + ["human"] + ["clean"] * 3 + ["human"] * 6, b)
    sm = regime.smooth(s, bk, cfg)
    assert sm.tolist()[:6] == ["clean"] * 6              # spike at 2 smoothed away
    assert sm.tolist()[6:] == ["human"] * 6              # not pulled toward 'clean'
    assert regime.segments(bk, cfg) == [(0, 6), (6, 12)]


def test_smooth_keeps_none(cfg):
    b = [f"2026-08-29 00:{i * 5:02d}:00" for i in range(5)]
    s, bk = _series(["clean", None, "clean", "clean", "clean"], b)
    assert regime.smooth(s, bk, cfg).tolist()[1] is None


def test_transitions_gap_pairs_and_dwell(cfg):
    b = [f"2026-08-29 00:{i * 5:02d}:00" for i in range(4)] + ["2026-08-29 00:30:00",
                                                               "2026-08-29 00:35:00"]
    s, bk = _series(["clean", "clean", "human", "human", "human", "clean"], b)
    t = regime.transitions(s, bk, cfg)
    assert t["gap_pairs"] == 1                            # 00:15 -> 00:30 is 15 min
    assert t["valid_pairs"] == 4
    assert t["counts"]["clean"]["human"] == 1 and t["counts"]["human"]["clean"] == 1
    assert t["matrix"]["clean"]["clean"] == 0.5 and t["matrix"]["human"]["human"] == 0.5
    assert t["dwell_median"]["clean"] == 7.5              # runs of 10 and 5 min
    assert t["dwell_median"]["matter"] is None
    dwell, censored = regime.current_dwell(s, bk, cfg)
    assert dwell == 5.0 and censored is False


def test_current_dwell_censored_at_window_start(cfg):
    b = [f"2026-08-29 00:{i * 5:02d}:00" for i in range(3)]
    s, bk = _series(["human"] * 3, b)
    assert regime.current_dwell(s, bk, cfg) == (15.0, True)

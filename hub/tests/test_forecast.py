"""aq.forecast: target is the observation 6 buckets later, one Pipeline, no leakage,
too-short windows return None."""

import numpy as np
import pandas as pd
import pytest

from aq import config, forecast


@pytest.fixture(scope="module")
def cfg():
    return config.load()


def _node(n=120, gap_at=None, seed=1):
    rng = np.random.default_rng(seed)
    t = pd.date_range("2026-08-28 00:00:00", periods=n, freq="5min")
    co2 = 600 + 300 * np.sin(np.arange(n) / 20) + rng.normal(0, 10, n)
    voc = 100 + 50 * np.cos(np.arange(n) / 15) + rng.normal(0, 3, n)
    df = pd.DataFrame({"node": "env_01", "bucket": t.strftime("%Y-%m-%d %H:%M:%S"),
                       "co2": co2, "voc": voc})
    if gap_at:
        df = df.drop(index=range(gap_at, gap_at + 4)).reset_index(drop=True)
    return df


def test_target_is_future_observation(cfg):
    df = _node()
    X, Y = forecast.supervised(df, cfg)
    assert forecast.leakage_check(df, cfg)
    shift = cfg["forecast"]["target_shift_buckets"]
    # the last `shift` rows have features but no target
    assert Y["co2"].isna().sum() == shift
    assert Y.index[-1] == X.index[-1]
    assert {"co2", "co2_lag1", "co2_lag3", "co2_diff1", "voc_lag2"} <= set(X.columns)


def test_gap_breaks_rows_not_interpolates(cfg):
    df = _node(gap_at=50)
    X, _ = forecast.supervised(df, cfg)
    # rows whose lags would span the hole are dropped, none invented
    assert len(X) < 120 and X.notna().all().all()


def test_fit_predict_payload_and_reproducible(cfg):
    df = _node()
    p1, p2 = forecast.fit_predict(df, cfg), forecast.fit_predict(df, cfg)
    assert p1 == p2
    assert set(p1) >= {"horizon_min", "co2_pred", "voc_pred", "alert"}
    assert p1["horizon_min"] == 30 and isinstance(p1["alert"], bool)
    assert 300 < p1["co2_pred"] < 1000 and 30 < p1["voc_pred"] < 200


def test_short_window_returns_none(cfg):
    assert forecast.fit_predict(_node(n=30), cfg) is None
    assert forecast.fit_predict(_node(n=0), cfg) is None

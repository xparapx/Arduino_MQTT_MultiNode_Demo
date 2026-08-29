"""aq.occ_co2: exact (room, bucket) join, n >= 25 filter, Spearman + slope."""

import numpy as np
import pandas as pd
import pytest

from aq import config, occ_co2

LABELS = {"env_01": "CLASS_01", "vis_01": "CLASS_01", "env_02": "CLASS_02", "vis_02": "CLASS_02"}


@pytest.fixture(scope="module")
def cfg():
    return config.load()


def _data():
    b = [f"2026-08-29 00:{i * 5:02d}:00" for i in range(12)]
    env = pd.DataFrame({"node": ["env_01"] * 12 + ["env_02"] * 12, "bucket": b + b,
                        "co2": ([500 + 20 * i for i in range(12)]
                                + [600 + 15 * i for i in range(12)])})
    occ = pd.DataFrame({"node": ["vis_01"] * 12 + ["vis_02"] * 12, "bucket": b + b,
                        "occ": [float(i) for i in range(12)] * 2,
                        "n": [30] * 11 + [10] + [30] * 12})       # one low-quality bucket
    return env, occ


def test_join_is_exact_and_filters_n(cfg):
    env, occ = _data()
    j = occ_co2.join_rooms(env, occ, LABELS, cfg)
    assert len(j) == 23 and set(j["room"]) == {"CLASS_01", "CLASS_02"}
    assert not ((j["room"] == "CLASS_01") & (j["bucket"] == "2026-08-29 00:55:00")).any()
    # a bucket shifted by one minute must not match
    occ2 = occ.copy()
    occ2.loc[occ2.index[0], "bucket"] = "2026-08-29 00:01:00"
    assert len(occ_co2.join_rooms(env, occ2, LABELS, cfg)) == 22


def test_spearman_by_room_payload(cfg):
    env, occ = _data()
    p = occ_co2.spearman_by_room(env, occ, LABELS, cfg)
    assert set(p) == {"spearman_rho", "n", "slope_ppm_per_person", "by_room"}
    assert p["n"] == 23 and p["spearman_rho"] > 0.7   # pooled: two rooms, two baselines
    assert p["by_room"]["CLASS_01"]["slope"] == pytest.approx(20.0, abs=0.01)
    assert p["by_room"]["CLASS_02"]["rho"] == pytest.approx(1.0)
    # without last_seen the window's occupancy frame gives the last bucket
    assert p["by_room"]["CLASS_01"]["last_bucket"] == "2026-08-29 00:55:00"
    assert list(p["by_room"]) == ["CLASS_01", "CLASS_02"]


def test_last_seen_adds_stopped_rooms(cfg):
    """A room whose vision node stopped before the window keeps a row
    (n = 0) with its all-time last bucket; last_seen wins over the frame."""
    env, occ = _data()
    labels = dict(LABELS, vis_03="CLASS_03", env_03="CLASS_03")
    last_seen = {"vis_01": "2026-08-29 01:00:00", "vis_02": "2026-08-29 00:55:00",
                 "vis_03": "2026-08-10 12:00:00", "vis_99": "2026-08-01 00:00:00"}
    p = occ_co2.spearman_by_room(env, occ, labels, cfg, last_seen)
    assert list(p["by_room"]) == ["CLASS_01", "CLASS_02", "CLASS_03"]
    assert p["by_room"]["CLASS_01"]["last_bucket"] == "2026-08-29 01:00:00"
    assert p["by_room"]["CLASS_03"] == {"rho": None, "n": 0, "slope": None,
                                        "last_bucket": "2026-08-10 12:00:00"}
    assert p["n"] == 23                                  # pooled stats unchanged


def test_unlabelled_nodes_and_empty(cfg):
    env, occ = _data()
    p = occ_co2.spearman_by_room(env, occ, {"env_01": "X"}, cfg)   # vision node unlabelled
    assert p["n"] == 0 and np.isnan(p["spearman_rho"]) and p["by_room"] == {}
    assert occ_co2.spearman_by_room(env.iloc[:0], occ, LABELS, cfg)["n"] == 0

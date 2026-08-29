"""aq.governance: versioned store (no overwrite, current as symlink or pointer),
and the four decision scenarios keep / promote / reject / rollback."""

import json

import numpy as np
import pandas as pd
import pytest

from aq import config, governance, regime


@pytest.fixture(scope="module")
def cfg():
    return config.load()


def _blobs(seed=0, n=250, shift=0.0):
    rng = np.random.default_rng(seed)
    centers = {"clean": (500, 80), "matter": (500, 250), "human": (1200, 80), "mixed": (1300, 260)}
    parts = []
    for c, v in centers.values():
        parts.append(pd.DataFrame({"co2": rng.normal(c + shift, 40, n),
                                   "voc": rng.normal(v, 12, n)}))
    return pd.concat(parts, ignore_index=True)


def _pack(df, cfg):
    model = regime.fit(df, cfg)
    labels = regime.anchor_labels(model, cfg)
    meta = regime.model_meta(model, labels, cfg)
    meta["labels"] = {str(k): v for k, v in labels.items()}
    return model, labels, meta


# ---- store ----------------------------------------------------------------------

def test_store_versions_current_and_no_overwrite(tmp_path, cfg):
    model, labels, meta = _pack(_blobs(), cfg)
    assert governance.list_versions(tmp_path) == [] and governance.resolve_current(tmp_path) is None
    v1 = governance.save_version(model, meta, tmp_path)
    assert v1 == "gmm_v1" and governance.next_version(tmp_path) == "gmm_v2"
    with pytest.raises(governance.GovernanceError, match="never overwritten"):
        governance.save_version(model, meta, tmp_path, "gmm_v1")
    governance.set_current(tmp_path, "gmm_v1")
    assert governance.resolve_current(tmp_path) == "gmm_v1"
    m, lab, me = governance.load_current(tmp_path)
    assert lab == labels and me["version"] == "gmm_v1"
    assert json.loads((tmp_path / "gmm_v1.json").read_text())["version"] == "gmm_v1"
    with pytest.raises(governance.GovernanceError, match="unknown"):
        governance.set_current(tmp_path, "gmm_v9")


def test_pointer_file_is_read_like_a_symlink(tmp_path, cfg):
    model, labels, meta = _pack(_blobs(), cfg)
    governance.save_version(model, meta, tmp_path)
    (tmp_path / "current").write_text("gmm_v1.joblib\n")     # what git gives on Windows
    assert governance.resolve_current(tmp_path) == "gmm_v1"
    assert governance.load_current(tmp_path)[2]["version"] == "gmm_v1"


# ---- decisions ------------------------------------------------------------------

def test_first_model_promotes(cfg):
    cand = _pack(_blobs(), cfg)
    d = governance.compare(None, cand, _blobs(seed=1), cfg)
    assert d["decision"] == "promote" and d["reason"] == "first model"


def test_keep_when_nothing_changed(cfg):
    cur = _pack(_blobs(seed=0), cfg)
    cand = _pack(_blobs(seed=0), cfg)                  # identical data -> same model
    d = governance.compare(cur, cand, _blobs(seed=2), cfg)
    assert d["decision"] == "keep"
    assert d["centroid_shift"] < cfg["governance"]["centroid_shift_min"]
    assert abs(d["loglik_delta"]) < cfg["governance"]["loglik_gain_min"]


def test_promote_on_centroid_shift(cfg):
    cur = _pack(_blobs(seed=0), cfg)
    cand = _pack(_blobs(seed=0, shift=200), cfg)      # every centroid moves 0.5 on co2/400
    d = governance.compare(cur, cand, _blobs(seed=0, shift=200), cfg)
    assert d["decision"] == "promote" and d["centroid_shift"] >= 0.25
    assert "centroid shift" in d["reason"] or "log-likelihood" in d["reason"]


def test_promote_on_loglik_gain(cfg):
    cur = _pack(_blobs(seed=0, shift=120), cfg)       # trained elsewhere
    cand = _pack(_blobs(seed=0), cfg)                  # matches the recent data
    d = governance.compare(cur, cand, _blobs(seed=3), cfg)
    assert d["decision"] == "promote" and d["loglik_delta"] >= 0.02


def test_reject_without_four_quadrants(cfg):
    cur = _pack(_blobs(), cfg)
    assert governance.compare(cur, None, _blobs(), cfg)["decision"] == "reject"
    bad_meta = dict(cur[2], components=cur[2]["components"][:3])
    d = governance.compare(cur, (cur[0], cur[1], bad_meta), _blobs(), cfg)
    assert d["decision"] == "reject" and "four distinct" in d["reason"]


def test_forced_promotion_at_calendar_boundary(cfg):
    cur = _pack(_blobs(seed=0), cfg)
    cand = _pack(_blobs(seed=0), cfg)
    d = governance.compare(cur, cand, _blobs(seed=2), cfg, forced=True)
    assert d["decision"] == "promote" and d["reason"].startswith("calendar boundary")


def test_promote_and_rollback_move_current(tmp_path, cfg):
    m1 = _pack(_blobs(seed=0), cfg)
    m2 = _pack(_blobs(seed=0, shift=200), cfg)
    governance.save_version(m1[0], m1[2], tmp_path)
    governance.save_version(m2[0], m2[2], tmp_path)
    e = governance.promote(tmp_path, "gmm_v2", cfg)
    assert e["decision"] == "promote" and governance.resolve_current(tmp_path) == "gmm_v2"
    r = governance.rollback(tmp_path, "gmm_v1", cfg)
    assert r["decision"] == "rollback" and governance.resolve_current(tmp_path) == "gmm_v1"
    assert "was gmm_v2" in r["reason"]
    with pytest.raises(governance.GovernanceError):
        governance.rollback(tmp_path, "gmm_v7", cfg)
    assert governance.list_versions(tmp_path) == ["gmm_v1", "gmm_v2"]   # nothing deleted

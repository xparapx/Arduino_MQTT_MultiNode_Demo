"""aq.rules: 1001 -> ON, 999 -> keep, 699 -> OFF, no OFF inside 10 min, hold when excluded."""

import pytest

from aq import config, rules

T0 = "2026-08-29 03:00:00"


@pytest.fixture(scope="module")
def cfg():
    return config.load()


def fan(regime, co2, prev, now=T0, cfg=None):
    return rules.decide(regime, co2, 100.0, {"fan": prev} if prev else None, now, cfg)["fan"]


def test_thresholds(cfg):
    assert fan("human", 1001, None, cfg=cfg)["state"] == 1
    assert fan("human", 1000, None, cfg=cfg)["state"] == 0          # strictly greater
    assert fan("human", 999, None, cfg=cfg)["state"] == 0           # keep (was off)
    assert fan("human", 999, {"state": 1, "since": "2026-08-29 02:00:00"}, cfg=cfg)["state"] == 1
    assert fan("human", 699, {"state": 1, "since": "2026-08-29 02:00:00"}, cfg=cfg)["state"] == 0
    assert fan("clean", 1500, None, cfg=cfg)["state"] == 0          # regime gate


def test_min_run_blocks_early_off_and_on(cfg):
    on_since = {"state": 1, "since": "2026-08-29 02:55:00"}         # 5 min ago
    a = fan("human", 699, on_since, cfg=cfg)
    assert a["state"] == 1 and a["rule"].startswith("min_run")
    assert a["since"] == "2026-08-29 02:55:00"
    assert a["hold_until"] == "2026-08-29 03:05:00"
    late = fan("human", 699, on_since, now="2026-08-29 03:05:00", cfg=cfg)
    assert late["state"] == 0 and late["since"] == "2026-08-29 03:05:00"
    off_since = {"state": 0, "since": "2026-08-29 02:58:00"}
    assert fan("human", 1200, off_since, cfg=cfg)["state"] == 0     # ON also waits


def test_hold_keeps_previous(cfg):
    prev = {"fan": {"state": 1, "since": "2026-08-29 01:00:00"},
            "purifier": {"state": 0, "since": "2026-08-29 01:00:00"}}
    d = rules.decide(rules.HOLD, 2000.0, 400.0, prev, T0, cfg)
    assert d["fan"]["state"] == 1 and d["fan"]["rule"] == "hold"
    assert d["purifier"]["state"] == 0 and d["purifier"]["rule"] == "hold"
    d2 = rules.decide(None, None, None, None, T0, cfg)
    assert d2["fan"]["state"] == 0 and d2["purifier"]["rule"] == "hold"


def test_purifier_and_payload_shape(cfg):
    d = rules.decide("matter", 500.0, 201.0, None, T0, cfg)
    assert d["purifier"]["state"] == 1 and d["fan"]["state"] == 0
    p = d["purifier"]
    assert set(p) == {"device", "state", "rule", "values", "since", "hold_until"}
    assert p["values"] == {"regime": "matter", "voc": 201.0}
    prev = {"purifier": {"state": 1, "since": "2026-08-29 02:00:00"}}
    assert rules.decide("mixed", 500.0, 119.0, prev, T0, cfg)["purifier"]["state"] == 0

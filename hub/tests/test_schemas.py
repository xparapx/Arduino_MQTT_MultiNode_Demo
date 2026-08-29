"""aq.schemas: one valid sample per kind passes; a missing key or wrong type fails."""

import pytest

from aq import schemas

SAMPLES = {
    "qc": {"valid_co2_pct": 99.1, "valid_voc_pct": 100.0, "rows": 288, "passed": True,
           "reason": ""},
    "regime_now": {"regime": "human", "co2": 1180.0, "voc": 95.0, "dwell_min": 35.0,
                   "dwell_censored": False, "trail": [["2026-08-29 03:00:00", "human"]]},
    "band": {"slots": [{"bucket": "2026-08-29 03:00:00", "regime": "clean"},
                       {"bucket": "2026-08-29 04:00:00", "regime": None}]},
    "transition": {"matrix": {"clean": {"clean": 0.9, "human": 0.1}},
                   "counts": {"clean": {"clean": 90, "human": 10}},
                   "gap_pairs": 4, "valid_pairs": 100, "dwell_median": {"clean": 45.0}},
    "action": {"device": "fan", "state": 1, "rule": "regime in {human,mixed} and co2 > 1000",
               "values": {"co2": 1180.0, "regime": "human"},
               "since": "2026-08-29 03:05:00", "hold_until": "2026-08-29 03:15:00"},
    "forecast": {"horizon_min": 30, "co2_pred": 1250.0, "voc_pred": 110.0, "alert": True},
    "occ_co2": {"spearman_rho": 0.62, "n": 400, "slope_ppm_per_person": 18.5,
                "by_room": {"CLASS_01": {"rho": 0.7, "n": 120}}},
    "model_event": {"candidate_ver": "v2", "decision": "keep", "centroid_shift": 0.12,
                    "loglik_delta": 0.004, "reason": "below thresholds"},
    "summary": {"lines": ["CLASS_01: human regime for 35 min, fan ON"]},
    "explore": {"vars": ["co2", "voc"], "corr": {"co2": {"co2": 1.0, "voc": 0.1}},
                "pooled": {"co2_med": 600.0, "co2_iqr": 200.0, "voc_med": 100.0, "voc_iqr": 40.0,
                           "amax": 2.0, "bins": 2, "hist": [[1, 0], [0, 1]]},
                "nodes": {"env_01": {"co2_med": 600.0, "co2_iqr": 200.0, "voc_med": 100.0,
                                     "voc_iqr": 40.0, "amax": 2.0, "bins": 2,
                                     "hist": [[1, 0], [0, 1]]}}},
}


def test_every_kind_has_a_sample():
    assert set(SAMPLES) == set(schemas.KINDS)


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_sample_passes(kind):
    schemas.validate(kind, SAMPLES[kind])


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_each_required_key_is_required(kind):
    for key in schemas.required_keys(kind):
        broken = dict(SAMPLES[kind])
        del broken[key]
        with pytest.raises(schemas.SchemaError, match=key):
            schemas.validate(kind, broken)


def test_wrong_type_fails():
    bad = dict(SAMPLES["qc"], rows="288")
    with pytest.raises(schemas.SchemaError, match="rows"):
        schemas.validate("qc", bad)


def test_int_accepted_for_float_but_bool_not_for_int():
    schemas.validate("forecast", dict(SAMPLES["forecast"], co2_pred=1200))
    with pytest.raises(schemas.SchemaError, match="expected int, got bool"):
        schemas.validate("action", dict(SAMPLES["action"], state=True))


def test_unknown_kind_and_non_dict():
    with pytest.raises(schemas.SchemaError, match="unknown"):
        schemas.validate("nope", {})
    with pytest.raises(schemas.SchemaError, match="dict"):
        schemas.validate("qc", [1, 2])


def test_extra_keys_allowed():
    schemas.validate("summary", {"lines": [], "note": "extra is fine"})

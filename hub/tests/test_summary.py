"""aq.summary: template lines, at most summary.max_lines, most actionable first."""

import pytest

from aq import config, summary


@pytest.fixture(scope="module")
def cfg():
    return config.load()


def _results():
    return {
        "labels": {"env_01": "CLASS_01", "env_02": "CLASS_02", "env_03": "CLASS_03"},
        "regime_now": {"env_01": {"regime": "human", "co2": 1180.0, "voc": 90.0, "dwell_min": 35.0,
                                  "dwell_censored": True, "trail": []},
                       "env_02": {"regime": "clean", "co2": 520.0, "voc": 60.0, "dwell_min": 120.0,
                                  "dwell_censored": False, "trail": []}},
        "action": {"env_01": {"fan": {"state": 1}, "purifier": {"state": 0}},
                   "env_02": {"fan": {"state": 0}, "purifier": {"state": 0}}},
        "qc": {"env_01": {"passed": True}, "env_02": {"passed": True}, "env_03": {"passed": False}},
        "forecast": {"env_01": {"alert": True, "co2_pred": 1250.0, "voc_pred": 95.0}},
    }


def test_lines_content_and_limit(cfg):
    out = summary.lines(_results(), cfg)
    assert 1 <= len(out) <= cfg["summary"]["max_lines"]
    assert out[0].startswith("Regimes now: human 1, clean 1")
    assert "ON: CLASS_01 fan." in out
    assert any("QC hold" in ln and "CLASS_03" in ln for ln in out)
    assert any("Forecast alert" in ln and "CLASS_01" in ln for ln in out)
    assert any("Highest CO2: CLASS_01 1180 ppm, human for >=35 min" in ln for ln in out)


def test_empty_results(cfg):
    out = summary.lines({}, cfg)
    assert out == ["No actuator is on."]

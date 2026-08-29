"""aq.config: analyst.toml carries every plan-section-2 constant; calendar.json helpers."""

import json
from datetime import date, datetime

import pytest

from aq import config


def test_default_config_loads_and_matches_plan():
    cfg = config.load()
    assert cfg["time"]["bucket_minutes"] == 5
    assert cfg["time"]["smooth_window"] == 9
    assert cfg["qc"]["daily_valid_pct_min"] == 95.0
    assert cfg["qc"]["range"]["co2"] == [350, 5000]
    assert cfg["regime"]["co2_scale"] == 400 and cfg["regime"]["voc_scale"] == 100
    assert cfg["regime"]["n_components"] == 4 and cfg["regime"]["random_state"] == 0
    assert cfg["regime"]["labels"] == ["clean", "matter", "human", "mixed"]
    assert cfg["rules"]["fan"]["on_co2"] == 1000 and cfg["rules"]["fan"]["off_co2"] == 700
    assert cfg["rules"]["purifier"]["on_voc"] == 200 and cfg["rules"]["purifier"]["off_voc"] == 120
    assert cfg["rules"]["min_run_minutes"] == 10
    assert cfg["governance"]["train_window_days"] == 28
    assert cfg["governance"]["loglik_gain_min"] == 0.02
    assert cfg["governance"]["centroid_shift_min"] == 0.25
    assert cfg["forecast"]["target_shift_buckets"] == 6
    assert cfg["occ_co2"]["min_occ_n"] == 25
    assert cfg["summary"]["max_lines"] == 5


def _write(tmp_path, text):
    p = tmp_path / "analyst.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_missing_key_fails(tmp_path):
    src = config.DEFAULT_CONFIG.read_text(encoding="utf-8").replace("n_init = 5\n", "")
    with pytest.raises(config.ConfigError, match="n_init"):
        config.load(_write(tmp_path, src))


def test_wrong_type_fails(tmp_path):
    src = config.DEFAULT_CONFIG.read_text(encoding="utf-8").replace(
        "random_state = 0", 'random_state = "0"')
    with pytest.raises(config.ConfigError, match="random_state"):
        config.load(_write(tmp_path, src))


def test_hysteresis_order_enforced(tmp_path):
    src = config.DEFAULT_CONFIG.read_text(encoding="utf-8").replace(
        "off_co2 = 700", "off_co2 = 1200")
    with pytest.raises(config.ConfigError, match="hysteresis"):
        config.load(_write(tmp_path, src))


def test_four_regimes_enforced(tmp_path):
    src = config.DEFAULT_CONFIG.read_text(encoding="utf-8").replace(
        "n_components = 4", "n_components = 3")
    with pytest.raises(config.ConfigError, match="4 components"):
        config.load(_write(tmp_path, src))


# ---- calendar ----------------------------------------------------------------

def test_default_calendar_loads():
    cal = config.load_calendar()
    assert [p["name"] for p in cal["periods"]] == ["term", "vacation", "term"]
    assert config.period_for(cal, date(2026, 7, 16)) == "term"
    assert config.period_for(cal, date(2026, 7, 17)) == "vacation"
    assert config.period_for(cal, date(2026, 8, 10)) == "vacation"
    assert config.period_for(cal, date(2026, 8, 11)) == "term"
    assert config.boundary_dates(cal) == [date(2026, 7, 17), date(2026, 8, 11)]


def test_school_hours_with_friday_override_and_lunch():
    cal = config.load_calendar()
    # 2026-08-27 is a Thursday, 2026-08-28 a Friday, 2026-08-29 a Saturday
    assert config.school_hours_for(cal, 3)[1].strftime("%H:%M") == "16:30"
    assert config.school_hours_for(cal, 4)[1].strftime("%H:%M") == "15:30"
    assert config.school_hours_for(cal, 5) is None
    assert config.in_school_hours(cal, datetime(2026, 8, 27, 16, 0))
    assert not config.in_school_hours(cal, datetime(2026, 8, 28, 16, 0))     # Friday ends 15:30
    assert not config.in_school_hours(cal, datetime(2026, 8, 29, 10, 0))     # Saturday
    assert not config.in_school_hours(cal, datetime(2026, 8, 27, 8, 39))
    assert config.in_school_hours(cal, datetime(2026, 8, 27, 8, 40))
    assert config.in_school_hours(cal, datetime(2026, 8, 27, 13, 0))
    assert not config.in_school_hours(cal, datetime(2026, 8, 27, 13, 0), exclude_lunch=True)
    assert not config.in_school_hours(cal, datetime(2026, 7, 20, 10, 0))     # vacation (Monday)


def test_calendar_gap_between_periods_fails(tmp_path):
    cal = json.loads(config.DEFAULT_CALENDAR.read_text(encoding="utf-8"))
    cal["periods"][2]["start"] = "2026-08-12"          # leaves 08-11 uncovered
    p = tmp_path / "calendar.json"
    p.write_text(json.dumps(cal), encoding="utf-8")
    with pytest.raises(config.ConfigError, match="day after"):
        config.load_calendar(p)


def test_calendar_bad_time_fails(tmp_path):
    cal = json.loads(config.DEFAULT_CALENDAR.read_text(encoding="utf-8"))
    cal["school_hours"]["end"] = "8:40am"
    p = tmp_path / "calendar.json"
    p.write_text(json.dumps(cal), encoding="utf-8")
    with pytest.raises(config.ConfigError, match="HH:MM"):
        config.load_calendar(p)

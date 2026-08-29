"""Configuration: config/analyst.toml (all plan section 2 constants) and calendar.json.

``load()`` reads and validates the TOML -- every section and key the analysis
modules rely on must exist with the right type, so a typo fails at start-up,
not in an hourly run at 03:00. ``load_calendar()`` does the same for the
school calendar and offers the two questions the analysis asks of it:
which period a date falls in, and whether a moment is inside school hours.
"""

from __future__ import annotations

import json
import tomllib
from datetime import date, datetime, time
from pathlib import Path

HUB_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = HUB_DIR / "config" / "analyst.toml"
DEFAULT_CALENDAR = HUB_DIR / "calendar.json"


class ConfigError(ValueError):
    """Missing section/key or wrong type in analyst.toml / calendar.json."""


# section -> {key: expected type(s)}. Lists are checked for element type below.
NUM = (int, float)
_SPEC: dict[str, dict[str, type | tuple]] = {
    "time": {"tz_offset_hours": int, "bucket_minutes": int, "smooth_window": int,
             "transition_dt_minutes": int, "transition_dt_tolerance": int},
    "qc": {"daily_valid_pct_min": NUM},
    "qc.range": {"co2": list, "temp": list, "hum": list, "voc": list, "pm": list,
                 "pm_max_exclusive": bool, "pm_column": str},
    "regime": {"co2_scale": NUM, "voc_scale": NUM, "n_components": int,
               "covariance_type": str, "random_state": int, "n_init": int, "labels": list,
               "anchor_co2_ppm": NUM, "anchor_voc_index": NUM},
    "rules": {"min_run_minutes": int},
    "rules.fan": {"on_regimes": list, "on_co2": NUM, "off_co2": NUM},
    "rules.purifier": {"on_regimes": list, "on_voc": NUM, "off_voc": NUM},
    "governance": {"train_window_days": int, "eval_window_days": int,
                   "loglik_gain_min": NUM, "centroid_shift_min": NUM,
                   "weekly_day": int, "weekly_time_utc": str, "models_dir": str,
                   "current_link": str},
    "forecast": {"horizon_minutes": int, "target_shift_buckets": int},
    "occ_co2": {"min_occ_n": int},
    "summary": {"max_lines": int},
    "run": {"hourly_window_hours": int, "daily_window_days": int, "forecast_min_rows": int,
            "trail_buckets": int, "band_slot_minutes": int},
    "schedule": {"hourly": str, "daily": str, "weekly": str, "timeout_start_sec": int},
}


def _section(cfg: dict, dotted: str) -> dict:
    node = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ConfigError(f"analyst.toml: missing section [{dotted}]")
        node = node[part]
    return node


def validate(cfg: dict) -> dict:
    """Check every section/key in _SPEC plus the cross-field rules. Returns cfg."""
    for dotted, keys in _SPEC.items():
        sec = _section(cfg, dotted)
        for key, typ in keys.items():
            if key not in sec:
                raise ConfigError(f"analyst.toml: [{dotted}] missing key {key!r}")
            val = sec[key]
            if isinstance(val, bool) and typ is not bool:
                raise ConfigError(f"analyst.toml: [{dotted}].{key} must be {typ}, got bool")
            if not isinstance(val, typ):
                raise ConfigError(f"analyst.toml: [{dotted}].{key} must be {typ}, "
                                  f"got {type(val).__name__}")
    rng = cfg["qc"]["range"]
    for key in ("co2", "temp", "hum", "voc", "pm"):
        lo_hi = rng[key]
        if (len(lo_hi) != 2 or not all(isinstance(v, NUM) for v in lo_hi)
                or lo_hi[0] >= lo_hi[1]):
            raise ConfigError(f"analyst.toml: [qc.range].{key} must be [min, max], min < max")
    reg = cfg["regime"]
    if reg["n_components"] != 4 or len(reg["labels"]) != 4:
        raise ConfigError("analyst.toml: regime needs exactly 4 components / labels (plan 2)")
    for dev in ("fan", "purifier"):
        bad = set(cfg["rules"][dev]["on_regimes"]) - set(reg["labels"])
        if bad:
            raise ConfigError(f"analyst.toml: [rules.{dev}].on_regimes unknown {sorted(bad)}")
    if cfg["rules"]["fan"]["off_co2"] >= cfg["rules"]["fan"]["on_co2"]:
        raise ConfigError("analyst.toml: fan off_co2 must be below on_co2 (hysteresis)")
    if cfg["rules"]["purifier"]["off_voc"] >= cfg["rules"]["purifier"]["on_voc"]:
        raise ConfigError("analyst.toml: purifier off_voc must be below on_voc (hysteresis)")
    if cfg["time"]["smooth_window"] % 2 == 0:
        raise ConfigError("analyst.toml: smooth_window must be odd (center=True)")
    if not 0 <= cfg["governance"]["weekly_day"] <= 6:
        raise ConfigError("analyst.toml: governance.weekly_day must be 0..6")
    return cfg


def load(path: str | Path = DEFAULT_CONFIG) -> dict:
    """Load and validate analyst.toml."""
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"config not found: {p}")
    with open(p, "rb") as f:
        cfg = tomllib.load(f)
    return validate(cfg)


# ---- calendar.json -------------------------------------------------------

def _hhmm(s, where: str) -> time:
    try:
        return datetime.strptime(s, "%H:%M").time()
    except (TypeError, ValueError):
        raise ConfigError(f"calendar.json: {where} must be 'HH:MM', got {s!r}") from None


def _ymd(s, where: str) -> date | None:
    if s is None:
        return None
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        raise ConfigError(f"calendar.json: {where} must be 'YYYY-MM-DD' or null, "
                          f"got {s!r}") from None


def validate_calendar(cal: dict) -> dict:
    """Structure + ordering checks. Periods must be contiguous and non-overlapping."""
    periods = cal.get("periods")
    if not isinstance(periods, list) or not periods:
        raise ConfigError("calendar.json: 'periods' must be a non-empty list")
    prev_end: date | None = None
    for i, p in enumerate(periods):
        if not isinstance(p, dict) or "name" not in p:
            raise ConfigError(f"calendar.json: periods[{i}] needs a name")
        start = _ymd(p.get("start"), f"periods[{i}].start")
        end = _ymd(p.get("end"), f"periods[{i}].end")
        if start and end and start > end:
            raise ConfigError(f"calendar.json: periods[{i}] start after end")
        if i > 0:
            if start is None:
                raise ConfigError(f"calendar.json: periods[{i}].start may be null only "
                                  "for the first period")
            if prev_end is None or (start - prev_end).days != 1:
                raise ConfigError(f"calendar.json: periods[{i}] must start the day after "
                                  f"periods[{i - 1}] ends")
        if end is None and i != len(periods) - 1:
            raise ConfigError("calendar.json: only the last period may have end = null")
        prev_end = end
    sh = cal.get("school_hours")
    if not isinstance(sh, dict):
        raise ConfigError("calendar.json: 'school_hours' missing")
    s, e = _hhmm(sh.get("start"), "school_hours.start"), _hhmm(sh.get("end"), "school_hours.end")
    if s >= e:
        raise ConfigError("calendar.json: school_hours start must be before end")
    days = sh.get("days")
    if not isinstance(days, list) or not all(isinstance(d, int) and 0 <= d <= 6 for d in days):
        raise ConfigError("calendar.json: school_hours.days must be weekday ints 0..6 (Mon=0)")
    for key, ov in (sh.get("overrides") or {}).items():
        if not (key.isdigit() and 0 <= int(key) <= 6):
            raise ConfigError(f"calendar.json: overrides key {key!r} must be a weekday 0..6")
        os_ = _hhmm(ov.get("start"), f"overrides.{key}.start")
        oe = _hhmm(ov.get("end"), f"overrides.{key}.end")
        if os_ >= oe:
            raise ConfigError(f"calendar.json: overrides.{key} start must be before end")
    lunch = cal.get("lunch")
    if lunch is not None:
        ls, le = _hhmm(lunch.get("start"), "lunch.start"), _hhmm(lunch.get("end"), "lunch.end")
        if ls >= le:
            raise ConfigError("calendar.json: lunch start must be before end")
    return cal


def load_calendar(path: str | Path = DEFAULT_CALENDAR) -> dict:
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"calendar not found: {p}")
    with open(p, encoding="utf-8") as f:
        return validate_calendar(json.load(f))


def period_for(cal: dict, day: date) -> str | None:
    """Name of the period containing `day` (KST date), or None if before the first."""
    for p in cal["periods"]:
        start, end = _ymd(p.get("start"), ""), _ymd(p.get("end"), "")
        if (start is None or start <= day) and (end is None or day <= end):
            return p["name"]
    return None


def boundary_dates(cal: dict) -> list[date]:
    """Period start dates (a null first start excluded): days that force a refit."""
    return [d for d in (_ymd(p.get("start"), "") for p in cal["periods"]) if d is not None]


def school_hours_for(cal: dict, weekday: int) -> tuple[time, time] | None:
    """(start, end) for a weekday (Mon=0), honoring overrides; None on non-school days."""
    sh = cal["school_hours"]
    if weekday not in sh["days"]:
        return None
    ov = (sh.get("overrides") or {}).get(str(weekday))
    src = ov if ov else sh
    return _hhmm(src["start"], "start"), _hhmm(src["end"], "end")


def in_school_hours(cal: dict, when: datetime, exclude_lunch: bool = False) -> bool:
    """True if `when` (naive KST) is a school day inside school hours and, when
    asked, outside lunch. Vacation periods count as no school."""
    if period_for(cal, when.date()) == "vacation":
        return False
    hours = school_hours_for(cal, when.weekday())
    if hours is None:
        return False
    t = when.time()
    if not (hours[0] <= t < hours[1]):
        return False
    if exclude_lunch and cal.get("lunch"):
        ls, le = _hhmm(cal["lunch"]["start"], ""), _hhmm(cal["lunch"]["end"], "")
        if ls <= t < le:
            return False
    return True

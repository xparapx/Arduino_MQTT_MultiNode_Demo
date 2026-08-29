"""Rule layer with hysteresis (Phase 3).

fan ON: regime in {human, mixed} and CO2 > 1000 / OFF: CO2 < 700
purifier ON: regime in {matter, mixed} and VOC > 200 / OFF: VOC < 120
Minimum run time 10 min; state persisted in actuator_state by analyst.py.
QC-excluded nodes are "hold" and the rule layer is not evaluated for them.
"""

from __future__ import annotations

from datetime import datetime, timedelta

TS_FMT = "%Y-%m-%d %H:%M:%S"
DEVICES = ("fan", "purifier")
HOLD = "hold"

# device -> (value key, on-threshold key, off-threshold key)
_DEVICE_VAR = {"fan": ("co2", "on_co2", "off_co2"), "purifier": ("voc", "on_voc", "off_voc")}


def _dt(s: str | None) -> datetime | None:
    return datetime.strptime(s, TS_FMT) if s else None


def decide_device(device: str, regime: str | None, value: float | None, prev: dict | None,
                  now: str, cfg: dict) -> dict:
    """action payload for one device. prev = {"state": int, "since": str} or None."""
    dev_cfg = cfg["rules"][device]
    var, on_key, off_key = _DEVICE_VAR[device]
    min_run = timedelta(minutes=cfg["rules"]["min_run_minutes"])
    prev_state = int(prev["state"]) if prev else 0
    prev_since = _dt(prev.get("since")) if prev else None
    now_dt = _dt(now)

    if regime is None or regime == HOLD or value is None:
        rule, desired = HOLD, prev_state
    elif regime in dev_cfg["on_regimes"] and value > dev_cfg[on_key]:
        rule = f"{var} > {dev_cfg[on_key]:g} in {'/'.join(dev_cfg['on_regimes'])}"
        desired = 1
    elif value < dev_cfg[off_key]:
        rule, desired = f"{var} < {dev_cfg[off_key]:g}", 0
    else:
        rule, desired = "keep (hysteresis band)", prev_state

    if desired != prev_state and prev_since is not None and now_dt - prev_since < min_run:
        rule = f"min_run {cfg['rules']['min_run_minutes']} min (wanted {desired})"
        desired = prev_state

    changed = desired != prev_state
    since_dt = now_dt if changed or prev_since is None else prev_since
    return {"device": device, "state": int(desired), "rule": rule,
            "values": {"regime": regime, var: value},
            "since": since_dt.strftime(TS_FMT),
            "hold_until": (since_dt + min_run).strftime(TS_FMT)}


def decide(regime: str | None, co2: float | None, voc: float | None, prev_state: dict | None,
           now: str, cfg: dict) -> dict[str, dict]:
    """{device: action payload} for fan and purifier. prev_state is
    {device: {"state", "since"}} as read from actuator_state (may be empty)."""
    prev_state = prev_state or {}
    return {"fan": decide_device("fan", regime, co2, prev_state.get("fan"), now, cfg),
            "purifier": decide_device("purifier", regime, voc, prev_state.get("purifier"),
                                      now, cfg)}

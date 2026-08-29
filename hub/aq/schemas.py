"""Payload contracts for the `analysis` table (plan section 6.1).

Each row of `analysis` has a `kind` and a JSON `payload`. The TypedDicts below
name the required keys per kind; ``validate(kind, payload)`` is the single
gate analyst.py passes every payload through before writing, and the
dashboard page 2 may use it to reject rows it does not understand.

Only presence and coarse type are checked -- value semantics (ranges,
regime names) belong to the modules that produce them.
"""

from __future__ import annotations

from typing import Any, TypedDict, get_type_hints


class SchemaError(ValueError):
    """Unknown kind, missing key, or wrong basic type."""


class QC(TypedDict):
    valid_co2_pct: float
    valid_voc_pct: float
    rows: int
    passed: bool
    reason: str


class RegimeNow(TypedDict):
    regime: str            # clean | matter | human | mixed | hold
    co2: float
    voc: float
    dwell_min: float
    dwell_censored: bool   # dwell is a lower bound (window edge)
    trail: list            # recent (bucket, regime) pairs


class Band(TypedDict):
    slots: list            # [{bucket, regime|null}], hourly mode


class Transition(TypedDict):
    matrix: dict           # regime -> regime -> probability
    counts: dict           # regime -> regime -> count
    gap_pairs: int         # consecutive pairs dropped (dt outside 5 +/- 2 min)
    valid_pairs: int
    dwell_median: dict     # regime -> minutes


class Action(TypedDict):
    device: str            # fan | purifier
    state: int             # 0 | 1
    rule: str
    values: dict
    since: str
    hold_until: str


class Forecast(TypedDict):
    horizon_min: int
    co2_pred: float
    voc_pred: float
    alert: bool


class OccCO2(TypedDict):
    spearman_rho: float
    n: int
    slope_ppm_per_person: float
    by_room: dict


class ModelEvent(TypedDict):
    candidate_ver: str
    decision: str          # keep | promote | reject | rollback
    centroid_shift: float
    loglik_delta: float
    reason: str


class Summary(TypedDict):
    lines: list            # <= summary.max_lines template sentences


KINDS: dict[str, type] = {
    "qc": QC,
    "regime_now": RegimeNow,
    "band": Band,
    "transition": Transition,
    "action": Action,
    "forecast": Forecast,
    "occ_co2": OccCO2,
    "model_event": ModelEvent,
    "summary": Summary,
}

# json.loads gives these Python types; int is accepted where float is declared,
# bool is NOT accepted where int is declared (bool is a subclass of int).
_ACCEPT: dict[type, tuple[type, ...]] = {
    float: (int, float),
    int: (int,),
    bool: (bool,),
    str: (str,),
    list: (list,),
    dict: (dict,),
}


def required_keys(kind: str) -> tuple[str, ...]:
    if kind not in KINDS:
        raise SchemaError(f"unknown analysis kind: {kind!r}")
    return tuple(get_type_hints(KINDS[kind]))


def validate(kind: str, payload: Any) -> None:
    """Raise SchemaError unless `payload` is a dict carrying every required key
    of `kind` with the declared basic type. Extra keys are allowed."""
    hints = get_type_hints(KINDS[kind]) if kind in KINDS else None
    if hints is None:
        raise SchemaError(f"unknown analysis kind: {kind!r}")
    if not isinstance(payload, dict):
        raise SchemaError(f"{kind}: payload must be a dict, got {type(payload).__name__}")
    missing = [k for k in hints if k not in payload]
    if missing:
        raise SchemaError(f"{kind}: missing keys {missing}")
    for key, typ in hints.items():
        val = payload[key]
        ok = _ACCEPT.get(typ, (typ,))
        if typ is int and isinstance(val, bool):
            raise SchemaError(f"{kind}.{key}: expected int, got bool")
        if not isinstance(val, ok):
            raise SchemaError(f"{kind}.{key}: expected {typ.__name__}, got {type(val).__name__}")

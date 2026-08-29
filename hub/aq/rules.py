"""Rule layer with hysteresis (Phase 3).

fan ON: regime in {human, mixed} and CO2 > 1000 / OFF: CO2 < 700
purifier ON: regime in {matter, mixed} and VOC > 200 / OFF: VOC < 120
Minimum run time 10 min; state persisted in actuator_state by analyst.py.
QC-excluded nodes are "hold" and the rule layer is not evaluated for them.
"""

from __future__ import annotations


def decide(regime: str, co2: float, voc: float, prev_state: dict, now: str, cfg: dict) -> dict:
    raise NotImplementedError("Phase 3")

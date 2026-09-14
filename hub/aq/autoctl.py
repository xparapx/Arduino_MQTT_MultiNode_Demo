"""Auto-control planning (추론 기반 자동 제어).

analyst.py hourly writes the desired device states to ``actuator_state``
(hysteresis + minimum-run already applied there). This module only READS that
table (invariant: analysis/actuator_state stay analyst.py's to write) and turns
it into a reconciliation plan against the live plug state plugwatch tracks.

plugwatch remains the single publisher: it calls ``desired_states`` +
``plan`` once a minute in auto mode and publishes only the differences, so a
plug that (re)joins is brought to the judged state within a minute and nothing
is re-sent while states already match. ``plan`` is pure for tests.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing

DB_TIMEOUT_S = 5


def desired_states(db_path: str, nodes_path: str) -> dict:
    """{room: {device: 0|1}} from actuator_state; env node -> room via nodes.json."""
    try:
        with open(nodes_path, encoding="utf-8") as f:
            labels = json.load(f)
    except (OSError, ValueError):
        return {}
    out: dict[str, dict[str, int]] = {}
    try:
        with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True,
                                     timeout=DB_TIMEOUT_S)) as con:
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "actuator_state" not in tables:
                return {}
            for node, dev, state in con.execute(
                    "SELECT node, device, state FROM actuator_state"):
                room = labels.get(node)
                if room:
                    out.setdefault(room, {})[dev] = int(state or 0)
    except sqlite3.Error:
        return {}
    return out


def plan(desired: dict, plugs_state: dict, mode: str) -> list[tuple]:
    """[(room, device, mac, "on"|"off"), ...] -- only in auto mode, only for
    plugs that are online with a known relay state, only where they differ
    from the judged state. Empty desired entry (no judgment yet) = no action."""
    if mode != "auto":
        return []
    acts = []
    for room, devs in plugs_state.items():
        for dev, s in devs.items():
            if not s or not s.get("online") or s.get("output") is None:
                continue
            want = desired.get(room, {}).get(dev)
            if want is None:
                continue
            if bool(want) != bool(s["output"]):
                acts.append((room, dev, s["mac"], "on" if want else "off"))
    return acts

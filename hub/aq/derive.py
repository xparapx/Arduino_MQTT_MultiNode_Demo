"""Pure derivations shared by the Streamlit page 2 (aq.plots) and the JSON API
(aq.webdata): action wording, plane label spreading, pooled transitions.

No streamlit, plotly or pandas here -- everything takes and returns plain
dicts / lists so the web front end and the tests can use it directly.
"""

from __future__ import annotations

from aq.regime import REGIMES

REGIME_KO = {"clean": "청정", "matter": "물질", "human": "인체", "mixed": "복합"}
HOLD = "hold"

# Action wording shown in B and E (one row per room). Provisional: to be aligned
# with the LED indicator wording once that is fixed -- change only this dict.
ACTION_WORDS = {"fan": "환기 필요", "purifier": "공기청정 필요", "both": "환기·공기청정 필요",
                "none": "조치 없음", "hold": "판정 보류", "keep": " (유지)"}
DEVICE_KO = {"fan": "환풍기", "purifier": "공청기"}

LABEL_SLOTS = ("top center", "bottom center", "middle right", "middle left",
               "top right", "bottom left", "top left", "bottom right")
LABEL_NEAR = 0.07       # axis-fraction distance under which two star labels would collide


def label_positions(pts: list[tuple[float, float]], near: float = LABEL_NEAR) -> list[str]:
    """One plotly textposition per point so that points closer than ``near``
    (in axis fractions) get different label slots. Greedy: every point takes the
    first slot none of its earlier neighbours uses; hover always has the full text."""
    out: list[str] = []
    for i, (x, y) in enumerate(pts):
        used = {out[j] for j, (px, py) in enumerate(pts[:i])
                if ((x - px) ** 2 + (y - py) ** 2) ** 0.5 < near}
        out.append(next((sl for sl in LABEL_SLOTS if sl not in used), LABEL_SLOTS[0]))
    return out


def action_kind(devs: dict) -> str:
    """fan | purifier | both | none | hold for one room's device payloads."""
    if not devs:
        return "none"
    if all(p["rule"] == HOLD for p in devs.values()):
        return "hold"
    on = [d for d in ("fan", "purifier") if devs.get(d, {}).get("state") == 1]
    return "both" if len(on) == 2 else on[0] if on else "none"


def action_summary(devs: dict) -> dict:
    """Collapse the fan / purifier action payloads of one room into one row:
    word (ACTION_WORDS), kind, reason, and -- for the devices that are ON -- since
    (latest switch-on, UTC) and hold_until (latest, UTC); both None when nothing
    is ON. ``kept`` when every ON device is only held by hysteresis / minimum
    run time."""
    if not devs:
        return {"word": "—", "kind": "none", "reason": "", "since": None,
                "hold_until": None, "kept": False}
    kind = action_kind(devs)
    if kind == "hold":
        word, kept = ACTION_WORDS["hold"], False
    else:
        on = [d for d in ("fan", "purifier") if devs.get(d, {}).get("state") == 1]
        word = ACTION_WORDS[kind]
        kept = bool(on) and all(devs[d]["rule"].startswith(("keep", "min_run")) for d in on)
        if kept:
            word += ACTION_WORDS["keep"]
    parts = []
    regime = next((p["values"].get("regime") for p in devs.values()), None)
    if regime in REGIME_KO:
        parts.append(f"레짐 {REGIME_KO[regime]}")
    for d, p in devs.items():
        var = "co2" if d == "fan" else "voc"
        val = p["values"].get(var)
        parts.append(f"{DEVICE_KO.get(d, d)} {'ON · ' if p['state'] == 1 else ''}{p['rule']}"
                     + (f" ({var} {val:.0f})" if isinstance(val, (int, float)) else ""))
    on_devs = [p for p in devs.values() if p["state"] == 1]
    return {"word": word, "kind": kind, "reason": " · ".join(parts), "kept": kept,
            "since": max(p["since"] for p in on_devs) if on_devs else None,
            "hold_until": max(p["hold_until"] for p in on_devs) if on_devs else None}


def pool_transitions(transitions: dict) -> dict:
    """Sum the per-node count matrices. Returns counts (regime -> regime ->
    n), gap_pairs, valid_pairs and per-regime rows: persistence, median dwell
    (median of node medians), most common next regime with its probability."""
    counts = {a: {b: 0 for b in REGIMES} for a in REGIMES}
    gap = valid = 0
    dwell: dict[str, list] = {r: [] for r in REGIMES}
    for p in transitions.values():
        gap += p["gap_pairs"]
        valid += p["valid_pairs"]
        for a in REGIMES:
            for b in REGIMES:
                counts[a][b] += p["counts"].get(a, {}).get(b, 0)
            if p["dwell_median"].get(a) is not None:
                dwell[a].append(p["dwell_median"][a])
    rows = []
    for a in REGIMES:
        tot = sum(counts[a].values())
        nxt = sorted(((counts[a][b], b) for b in REGIMES if b != a), reverse=True)
        n_c, n_b = nxt[0] if nxt and nxt[0][0] > 0 else (0, None)
        med = sorted(dwell[a])
        rows.append({"regime": a, "persist": None if tot == 0 else round(counts[a][a] / tot, 3),
                     "dwell_median": None if not med else round(_median(med)),
                     "next": n_b, "next_p": None if n_b is None else round(n_c / tot, 3),
                     "pairs": tot})
    return {"counts": counts, "gap_pairs": gap, "valid_pairs": valid, "rows": rows}


def _median(xs: list) -> float:
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2

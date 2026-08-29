"""Deterministic summary sentences (Phase 3). Template text only, max 5 lines, no LLM."""

from __future__ import annotations

from collections import Counter


def lines(results: dict, cfg: dict) -> list[str]:
    """`results` = {"labels": {node: room}, "regime_now": {node: payload},
    "action": {node: {device: payload}}, "qc": {node: payload},
    "forecast": {node: payload}}. Returns at most summary.max_lines lines,
    most actionable first."""
    labels = results.get("labels", {})
    name = lambda n: labels.get(n, n)  # noqa: E731
    out: list[str] = []

    regimes = Counter(p["regime"] for p in results.get("regime_now", {}).values())
    if regimes:
        parts = ", ".join(f"{r} {c}" for r, c in sorted(regimes.items(), key=lambda x: -x[1]))
        out.append(f"Regimes now: {parts} (nodes {sum(regimes.values())}).")

    on = [(name(n), dev) for n, devs in results.get("action", {}).items()
          for dev, p in devs.items() if p["state"] == 1]
    if on:
        out.append("ON: " + ", ".join(f"{room} {dev}" for room, dev in on) + ".")
    else:
        out.append("No actuator is on.")

    failed = [name(n) for n, p in results.get("qc", {}).items() if not p["passed"]]
    if failed:
        out.append("QC hold (excluded today): " + ", ".join(sorted(failed)) + ".")

    alerts = [(name(n), p) for n, p in results.get("forecast", {}).items() if p and p["alert"]]
    if alerts:
        items = ", ".join(f"{room} CO2 {p['co2_pred']:.0f} / VOC {p['voc_pred']:.0f}"
                          for room, p in alerts)
        out.append(f"Forecast alert (30 min): {items}.")

    worst = max(results.get("regime_now", {}).items(),
                key=lambda kv: (kv[1]["co2"] or 0), default=None)
    if worst:
        n, p = worst
        out.append(f"Highest CO2: {name(n)} {p['co2']:.0f} ppm, {p['regime']} for "
                   f"{'>=' if p['dwell_censored'] else ''}{p['dwell_min']:.0f} min.")

    return out[: cfg["summary"]["max_lines"]]

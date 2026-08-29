#!/usr/bin/env python3
"""analyst.py -- offline analysis runner for sensor_data.db (Phase 3).

    analyst.py run  --mode hourly|daily|weekly [--as-of UTC] [--db PATH] [--dry-run]
    analyst.py fit  [--window 28] [--as-of UTC] [--db PATH] [--dry-run]
    analyst.py show --kind KIND [--db PATH] [--limit N]

Reads readings / occupancy (read-only), writes only the analysis and
actuator_state tables -- and with --dry-run writes nothing at all: every row
that would be stored is printed as JSON on stdout. Logs go to stderr.

hourly : per node -> qc (today), regime_now, action (fan / purifier), forecast; summary
daily  : per node -> qc (each day), band, transition; occ_co2 over the window
weekly : candidate GMM fit on the training window -> model_event (governance in Phase 4)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

HUB = Path(__file__).resolve().parent
sys.path.insert(0, str(HUB))

from aq import config, db, forecast, occ_co2, qc, regime, rules, schemas, summary  # noqa: E402

TS_FMT = "%Y-%m-%d %H:%M:%S"
ADHOC = "adhoc"


def log(msg: str) -> None:
    print(f"[analyst] {msg}", file=sys.stderr, flush=True)


def fmt(dt: datetime) -> str:
    return dt.strftime(TS_FMT)


def load_labels(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


# ---- model ------------------------------------------------------------------------

def load_current_model(cfg: dict, models_dir: Path):
    """(model, labels, version) from models/current, or None if absent (Phase 4)."""
    link = models_dir / cfg["governance"]["current_link"]
    if not link.exists():
        return None
    import joblib

    target = link.resolve()
    model = joblib.load(target)
    meta = json.loads(target.with_suffix(".json").read_text(encoding="utf-8"))
    labels = {int(k): v for k, v in meta["labels"].items()}
    return model, labels, meta.get("version", target.stem)


def fit_candidate(conn, cfg: dict, as_of: datetime, window_days: int):
    """Fit a GMM on the last `window_days` of QC-passed rows. Returns
    (model, labels, meta, rows_used). Raises regime.AnchorError if rejected."""
    start = as_of - timedelta(days=window_days)
    raw = db.load_readings(conn, fmt(start), fmt(as_of))
    masked = qc.range_mask(raw, cfg)
    gate = qc.daily_gate(masked, cfg)
    clean = qc.apply_gate(masked, gate, cfg)
    model = regime.fit(clean, cfg)
    labels = regime.anchor_labels(model, cfg)
    meta = regime.model_meta(model, labels, cfg)
    meta.update({"window_days": window_days, "win_start": fmt(start), "win_end": fmt(as_of),
                 "rows": int(len(clean)), "labels": {str(k): v for k, v in labels.items()}})
    return model, labels, meta, len(clean)


def get_model(conn, cfg: dict, as_of: datetime, models_dir: Path, window_days: int):
    """Current promoted model, else an ad-hoc fit on the last `window_days`
    (version 'adhoc'). The ad-hoc path is what --dry-run uses before Phase 4.
    It must use the full training window: a 7-day fit on the fixture put two
    centroids in the same quadrant (AnchorError). Costs ~17 s on the board, so
    the hourly < 15 s budget applies to the models/current path (Phase 4+)."""
    cur = load_current_model(cfg, models_dir)
    if cur:
        return cur
    model, labels, meta, n = fit_candidate(conn, cfg, as_of, window_days)
    log(f"no models/current -> ad-hoc GMM on {n} rows ({window_days} d)")
    return model, labels, ADHOC


# ---- shared per-node preparation ------------------------------------------------------

def prepare(conn, cfg: dict, start: datetime, end: datetime):
    """(masked readings, gate) for the window. Gate rows exist for every node
    and every KST day in the window, so a silent node fails with 'no rows'."""
    raw = db.load_readings(conn, fmt(start), fmt(end))
    masked = qc.range_mask(raw, cfg)
    nodes = sorted(masked["node"].unique()) if not masked.empty else []
    off = timedelta(hours=cfg["time"]["tz_offset_hours"])
    days = sorted({(start + off + timedelta(days=i)).date()
                   for i in range((end - start).days + 2)
                   if start + off + timedelta(days=i) <= end + off})
    gate = qc.daily_gate(masked, cfg, nodes=nodes, days=days)
    return masked, gate


def row(kind: str, payload: dict, scope: str, win_start: datetime, win_end: datetime,
        model_ver: str | None, run_at: str) -> dict:
    schemas.validate(kind, payload)
    return {"run_at": run_at, "kind": kind, "scope": scope, "win_start": fmt(win_start),
            "win_end": fmt(win_end), "model_ver": model_ver, "payload": payload}


# ---- modes ------------------------------------------------------------------------

def run_hourly(conn, cfg: dict, labels_map: dict, as_of: datetime, model_pack,
               actuator_state: dict) -> list[dict]:
    model, labels, ver = model_pack
    run_at = fmt(as_of)
    start = as_of - timedelta(hours=cfg["run"]["hourly_window_hours"])
    masked, gate = prepare(conn, cfg, start, as_of)
    today = (as_of + timedelta(hours=cfg["time"]["tz_offset_hours"])).date()
    rows: list[dict] = []
    res = {"labels": labels_map, "regime_now": {}, "action": {}, "qc": {}, "forecast": {}}
    for node, g in masked.groupby("node", sort=True):
        g = g.reset_index(drop=True)
        qcp = qc.gate_payload(gate, node, today)
        res["qc"][node] = qcp
        rows.append(row("qc", qcp, node, start, as_of, None, run_at))
        last = g.iloc[-1]
        co2 = None if pd.isna(last["co2"]) else float(last["co2"])
        voc = None if pd.isna(last["voc"]) else float(last["voc"])
        if qcp["passed"]:
            pred = regime.predict(model, labels, g, cfg)
            sm = regime.smooth(pred, g["bucket"], cfg)
            dwell, censored = regime.current_dwell(sm, g["bucket"], cfg)
            now_regime = sm.iloc[-1]
            k = cfg["run"]["trail_buckets"]
            trail = [[b, r] for b, r in zip(g["bucket"].tail(k), sm.tail(k), strict=True)]
            reg_payload = {"regime": now_regime or rules.HOLD,
                           "co2": co2 if co2 is not None else float("nan"),
                           "voc": voc if voc is not None else float("nan"),
                           "dwell_min": dwell, "dwell_censored": censored, "trail": trail}
            rows.append(row("regime_now", reg_payload, node, start, as_of, ver, run_at))
            res["regime_now"][node] = reg_payload
            actions = rules.decide(now_regime, co2, voc, actuator_state.get(node), run_at, cfg)
            fc = forecast.fit_predict(g, cfg)
            if fc:
                rows.append(row("forecast", fc, node, start, as_of, None, run_at))
                res["forecast"][node] = fc
        else:
            actions = rules.decide(rules.HOLD, co2, voc, actuator_state.get(node), run_at, cfg)
        res["action"][node] = actions
        for act in actions.values():
            rows.append(row("action", act, node, start, as_of, ver, run_at))
    rows.append(row("summary", {"lines": summary.lines(res, cfg)}, "all", start, as_of, ver,
                    run_at))
    return rows


def band_slots(sm: pd.Series, buckets: pd.Series, cfg: dict) -> list[dict]:
    """Mode of the smoothed regime per band_slot_minutes slot (null when empty)."""
    slot = cfg["run"]["band_slot_minutes"]
    d = pd.DataFrame({"regime": list(sm), "t": pd.to_datetime(buckets)})
    d["slot"] = d["t"].dt.floor(f"{slot}min")
    out = []
    for s, g in d.groupby("slot", sort=True):
        vals = [v for v in g["regime"] if v is not None]
        out.append({"bucket": s.strftime(TS_FMT),
                    "regime": (pd.Series(vals).mode().iloc[0] if vals else None)})
    return out


def run_daily(conn, cfg: dict, labels_map: dict, as_of: datetime, model_pack) -> list[dict]:
    model, labels, ver = model_pack
    run_at = fmt(as_of)
    start = as_of - timedelta(days=cfg["run"]["daily_window_days"])
    masked, gate = prepare(conn, cfg, start, as_of)
    rows: list[dict] = []
    for r in gate.itertuples():
        rows.append(row("qc", qc.gate_payload(gate, r.node, r.date), f"{r.node}@{r.date}",
                        start, as_of, None, run_at))
    clean = qc.apply_gate(masked, gate, cfg)
    for node, g in clean.groupby("node", sort=True):
        g = g.reset_index(drop=True)
        pred = regime.predict(model, labels, g, cfg)
        sm = regime.smooth(pred, g["bucket"], cfg)
        rows.append(row("band", {"slots": band_slots(sm, g["bucket"], cfg)}, node, start, as_of,
                        ver, run_at))
        rows.append(row("transition", regime.transitions(sm, g["bucket"], cfg), node, start,
                        as_of, ver, run_at))
    occ = db.load_occupancy(conn, fmt(start), fmt(as_of))
    rows.append(row("occ_co2", occ_co2.spearman_by_room(clean, occ, labels_map, cfg), "all",
                    start, as_of, None, run_at))
    return rows


def run_weekly(conn, cfg: dict, as_of: datetime, models_dir: Path) -> list[dict]:
    run_at = fmt(as_of)
    window = cfg["governance"]["train_window_days"]
    start = as_of - timedelta(days=window)
    try:
        _model, _labels, meta, n = fit_candidate(conn, cfg, as_of, window)
        payload = {"candidate_ver": "candidate", "decision": "stored",
                   "centroid_shift": 0.0, "loglik_delta": 0.0,
                   "reason": f"Phase 3: candidate fitted on {n} rows; promotion is Phase 4",
                   "meta": meta}
    except regime.AnchorError as e:
        payload = {"candidate_ver": "candidate", "decision": "reject", "centroid_shift": 0.0,
                   "loglik_delta": 0.0, "reason": f"anchor: {e}"}
    return [row("model_event", payload, "all", start, as_of, None, run_at)]


# ---- CLI --------------------------------------------------------------------------

def parse_as_of(s: str | None) -> datetime:
    return datetime.strptime(s, TS_FMT) if s else datetime.now(UTC).replace(tzinfo=None)


def cmd_run(a) -> int:
    cfg = config.load(a.config)
    labels_map = load_labels(Path(a.nodes))
    as_of = parse_as_of(a.as_of)
    models_dir = HUB / cfg["governance"]["models_dir"]
    ro = db.connect_ro(a.db)
    t0 = datetime.now()
    if a.mode == "weekly":
        rows = run_weekly(ro, cfg, as_of, models_dir)
    else:
        pack = get_model(ro, cfg, as_of, models_dir, cfg["governance"]["train_window_days"])
        if a.mode == "hourly":
            state = db.read_actuator_state(ro)
            rows = run_hourly(ro, cfg, labels_map, as_of, pack, state)
        else:
            rows = run_daily(ro, cfg, labels_map, as_of, pack)
    ro.close()
    log(f"{a.mode}: {len(rows)} rows in {(datetime.now() - t0).total_seconds():.1f}s "
        f"(as_of {fmt(as_of)}, {'dry-run' if a.dry_run else 'write'})")
    if a.dry_run:
        json.dump(rows, sys.stdout, ensure_ascii=False, indent=1, default=_json_default)
        print()
        return 0
    rw = db.connect_rw(a.db)
    db.ensure_schema(rw)
    n = db.write_analysis(rw, rows)
    if a.mode == "hourly":
        for r in rows:
            if r["kind"] == "action":
                p = r["payload"]
                db.write_actuator_state(rw, r["scope"], p["device"], p["state"], p["since"])
    rw.close()
    log(f"wrote {n} analysis rows")
    return 0


def cmd_fit(a) -> int:
    cfg = config.load(a.config)
    as_of = parse_as_of(a.as_of)
    ro = db.connect_ro(a.db)
    try:
        model, labels, meta, n = fit_candidate(ro, cfg, as_of, a.window)
    except regime.AnchorError as e:
        log(f"candidate rejected: {e}")
        return 2
    finally:
        ro.close()
    ro = None
    meta["version"] = "candidate"
    if a.dry_run:
        json.dump(meta, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0
    import joblib

    models_dir = HUB / cfg["governance"]["models_dir"]
    models_dir.mkdir(exist_ok=True)
    stamp = as_of.strftime("%Y%m%d_%H%M")
    path = models_dir / f"gmm_candidate_{stamp}.joblib"
    joblib.dump(model, path)
    path.with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    log(f"candidate saved: {path} ({n} rows). Promotion is Phase 4.")
    return 0


def cmd_show(a) -> int:
    ro = db.connect_ro(a.db)
    rows = db.read_analysis(ro, a.kind, a.limit)
    ro.close()
    json.dump(rows, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


def _json_default(o):
    import numpy as np

    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=str(db.DEFAULT_DB))
    common.add_argument("--config", default=str(config.DEFAULT_CONFIG))
    common.add_argument("--nodes", default=str(HUB / "nodes.json"))
    common.add_argument("--as-of", dest="as_of", default=None, help="UTC 'YYYY-MM-DD HH:MM:SS'")
    common.add_argument("--dry-run", dest="dry_run", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", parents=[common])
    r.add_argument("--mode", choices=["hourly", "daily", "weekly"], required=True)
    r.set_defaults(fn=cmd_run)
    f = sub.add_parser("fit", parents=[common])
    f.add_argument("--window", type=int, default=28)
    f.set_defaults(fn=cmd_fit)
    s = sub.add_parser("show", parents=[common])
    s.add_argument("--kind", required=True, choices=sorted(schemas.KINDS))
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(fn=cmd_show)
    return p


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

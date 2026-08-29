"""Model governance (Phase 4): versioned GMM store + compare / promote / rollback.

Store layout (cfg governance.models_dir, default hub/models):
    gmm_v1.joblib + gmm_v1.json   (meta: regime.model_meta + labels + window)
    current  -> gmm_vN.joblib      symlink on Linux; on filesystems without
                                   symlinks a one-line pointer file with the
                                   same content (git checks it out that way on
                                   Windows), resolve_current() reads both.
Versions are never overwritten (save_version refuses an existing name).

Promotion (plan section 2): the candidate's four centroids must sit in four
different quadrants (anchor_labels already guarantees that for a fitted
candidate) AND (mean log-likelihood on the last eval_window_days improves by
>= loglik_gain_min, OR the largest centroid move, matched by regime, is
>= centroid_shift_min in scaled units). A calendar boundary inside the last
weekly interval forces promotion. Otherwise the candidate is kept on disk and
the decision is recorded as 'keep' with the numbers.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import numpy as np

from aq import regime

VERSION_RE = re.compile(r"^gmm_v(\d+)$")


class GovernanceError(RuntimeError):
    """Refused store operation (overwrite, unknown version, no current)."""


# ---- store ----------------------------------------------------------------------

def _joblib():
    import joblib

    return joblib


def list_versions(models_dir: Path) -> list[str]:
    """['gmm_v1', 'gmm_v2', ...] sorted numerically (only complete pairs)."""
    out = []
    for p in Path(models_dir).glob("gmm_v*.joblib"):
        m = VERSION_RE.match(p.stem)
        if m and p.with_suffix(".json").is_file():
            out.append((int(m.group(1)), p.stem))
    return [name for _, name in sorted(out)]


def next_version(models_dir: Path) -> str:
    nums = [int(VERSION_RE.match(v).group(1)) for v in list_versions(models_dir)]
    return f"gmm_v{max(nums, default=0) + 1}"


def save_version(model, meta: dict, models_dir: Path, name: str | None = None) -> str:
    """Write gmm_vN.joblib + gmm_vN.json. Never overwrites. Returns the name."""
    models_dir = Path(models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    name = name or next_version(models_dir)
    if not VERSION_RE.match(name):
        raise GovernanceError(f"bad version name {name!r} (want gmm_vN)")
    path = models_dir / f"{name}.joblib"
    if path.exists() or path.with_suffix(".json").exists():
        raise GovernanceError(f"{name} already exists; versions are never overwritten")
    _joblib().dump(model, path)
    meta = dict(meta, version=name)
    path.with_suffix(".json").write_text(json.dumps(meta, indent=1, ensure_ascii=False),
                                         encoding="utf-8")
    return name


def load_version(models_dir: Path, name: str):
    """(model, labels{int: regime}, meta) for gmm_vN."""
    path = Path(models_dir) / f"{name}.joblib"
    if not path.is_file():
        raise GovernanceError(f"unknown version {name}")
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    labels = {int(k): v for k, v in meta["labels"].items()}
    return _joblib().load(path), labels, meta


def resolve_current(models_dir: Path, link_name: str = "current") -> str | None:
    """Version name models/current points to (symlink or pointer file), or None."""
    link = Path(models_dir) / link_name
    if link.is_symlink():
        target = Path(os.readlink(link)).name
    elif link.is_file():
        target = link.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    else:
        return None
    return Path(target).stem


def set_current(models_dir: Path, name: str, link_name: str = "current") -> None:
    """Point models/current at gmm_vN.joblib. Symlink where possible, else a
    pointer file with the same content; replaced atomically-enough (unlink first)."""
    models_dir = Path(models_dir)
    if not (models_dir / f"{name}.joblib").is_file():
        raise GovernanceError(f"unknown version {name}")
    link = models_dir / link_name
    if link.is_symlink() or link.exists():
        link.unlink()
    try:
        link.symlink_to(f"{name}.joblib")
    except (OSError, NotImplementedError):
        link.write_text(f"{name}.joblib\n", encoding="utf-8")


def load_current(models_dir: Path, link_name: str = "current"):
    """(model, labels, meta) of the promoted model, or None when there is none."""
    name = resolve_current(models_dir, link_name)
    return load_version(models_dir, name) if name else None


# ---- comparison -----------------------------------------------------------------

def mean_loglik(model, df, cfg: dict) -> float | None:
    X, _ = regime.features(df, cfg)
    return float(np.mean(model.score_samples(X))) if len(X) else None


def centroid_shift(cur_meta: dict, cand_meta: dict) -> float:
    """Largest L2 move (scaled units) between centroids of the same regime."""
    cur = {c["regime"]: np.array(c["mu_scaled"]) for c in cur_meta["components"]}
    cand = {c["regime"]: np.array(c["mu_scaled"]) for c in cand_meta["components"]}
    moves = [float(np.linalg.norm(cand[r] - cur[r])) for r in cur if r in cand]
    return max(moves) if moves else float("inf")


def quadrants_distinct(meta: dict) -> bool:
    regs = [c["regime"] for c in meta["components"]]
    return len(regs) == 4 and len(set(regs)) == 4


def compare(current, candidate, recent, cfg: dict, forced: bool = False) -> dict:
    """model_event payload (without candidate_ver) deciding keep / promote / reject.
    current, candidate: (model, labels, meta) -- current may be None (first model).
    recent: DataFrame of the last eval_window_days (QC-passed rows)."""
    gov = cfg["governance"]
    if candidate is None:
        return {"decision": "reject", "centroid_shift": 0.0, "loglik_delta": 0.0,
                "reason": "candidate rejected: centroids share a quadrant"}
    cand_model, _, cand_meta = candidate
    if not quadrants_distinct(cand_meta):
        return {"decision": "reject", "centroid_shift": 0.0, "loglik_delta": 0.0,
                "reason": "candidate rejected: fewer than four distinct quadrants"}
    if current is None:
        return {"decision": "promote", "centroid_shift": 0.0, "loglik_delta": 0.0,
                "reason": "first model"}
    cur_model, _, cur_meta = current
    ll_cur, ll_cand = mean_loglik(cur_model, recent, cfg), mean_loglik(cand_model, recent, cfg)
    if ll_cur is None or ll_cand is None:
        delta = 0.0
    else:
        delta = (ll_cand - ll_cur) / abs(ll_cur) if ll_cur else 0.0
    shift = centroid_shift(cur_meta, cand_meta)
    ok_ll = delta >= gov["loglik_gain_min"]
    ok_shift = shift >= gov["centroid_shift_min"]
    detail = (f"loglik {ll_cur if ll_cur is None else round(ll_cur, 4)} -> "
              f"{ll_cand if ll_cand is None else round(ll_cand, 4)} ({delta:+.2%}, "
              f"need {gov['loglik_gain_min']:+.0%}); centroid shift {shift:.3f} "
              f"(need {gov['centroid_shift_min']})")
    if forced:
        return {"decision": "promote", "centroid_shift": round(shift, 4),
                "loglik_delta": round(delta, 4),
                "reason": f"calendar boundary: forced refit; {detail}"}
    if ok_ll or ok_shift:
        why = "log-likelihood gain" if ok_ll else "centroid shift"
        return {"decision": "promote", "centroid_shift": round(shift, 4),
                "loglik_delta": round(delta, 4), "reason": f"{why}; {detail}"}
    return {"decision": "keep", "centroid_shift": round(shift, 4),
            "loglik_delta": round(delta, 4), "reason": f"below both thresholds; {detail}"}


# ---- operations -----------------------------------------------------------------

def promote(models_dir: Path, name: str, cfg: dict) -> dict:
    """Point current at `name`. Returns a model_event payload."""
    prev = resolve_current(models_dir, cfg["governance"]["current_link"])
    set_current(models_dir, name, cfg["governance"]["current_link"])
    return {"candidate_ver": name, "decision": "promote", "centroid_shift": 0.0,
            "loglik_delta": 0.0, "reason": f"promoted {name} (was {prev or 'none'})"}


def rollback(models_dir: Path, name: str, cfg: dict) -> dict:
    """Point current back at an older version. Refuses unknown versions."""
    if name not in list_versions(models_dir):
        raise GovernanceError(f"cannot roll back to unknown version {name}")
    prev = resolve_current(models_dir, cfg["governance"]["current_link"])
    set_current(models_dir, name, cfg["governance"]["current_link"])
    return {"candidate_ver": name, "decision": "rollback", "centroid_shift": 0.0,
            "loglik_delta": 0.0, "reason": f"rolled back to {name} (was {prev or 'none'})"}

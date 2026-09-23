"""Daily plug-energy accumulation (pure functions; plugwatch owns the file).

plugwatch keeps a 24 h ring of 5-min apower buckets per device. Whenever a
bucket is *finalized* (its epoch is older than the bucket now being filled),
its mean power is converted to Wh and added to that KST day's total. The
running marker (`acc`) remembers the newest finalized bucket already counted,
so restarts never double-count; buckets missed while plugwatch was down are
simply lost (the ring itself survives restarts via plug_state.json).

The result file (plug_energy.json, written by plugwatch only) looks like:
    {"days": {"2026-09-23": {"CLASS_01": {"purifier": 12.4, "fan": 88.1}}},
     "acc":  {"CLASS_01": {"purifier": 1789000000, "fan": ...}}}
webdata serves it read-only under /api/plugs -> "energy".
"""

from __future__ import annotations

from datetime import UTC, datetime

BUCKET_S = 300
KEEP_DAYS = 200
TZ_HOURS = 9  # KST


def kst_date(bucket_epoch: int) -> str:
    """KST calendar date of a UTC bucket epoch."""
    return datetime.fromtimestamp(bucket_epoch + TZ_HOURS * 3600, UTC).strftime("%Y-%m-%d")


def accumulate(hist: list, marker: int, now_bucket: int) -> tuple[dict[str, float], int]:
    """Wh additions per KST date from finalized, not-yet-counted ring buckets.

    hist entries are plugwatch's in-memory ring rows [bucket_epoch, sum_W, n].
    A bucket counts when marker < epoch < now_bucket (the current bucket is
    still filling). Returns ({date: wh}, new_marker); marker is unchanged when
    nothing qualified.
    """
    out: dict[str, float] = {}
    new_marker = marker
    for b, tot, n in hist or []:
        if b <= marker or b >= now_bucket or not n:
            continue
        wh = (tot / n) * BUCKET_S / 3600.0
        day = kst_date(b)
        out[day] = out.get(day, 0.0) + wh
        if b > new_marker:
            new_marker = b
    return out, new_marker


def merge(doc: dict, room: str, dev: str, adds: dict[str, float], new_marker: int) -> None:
    """Fold `accumulate` output into the energy document in place."""
    days = doc.setdefault("days", {})
    for day, wh in adds.items():
        cur = days.setdefault(day, {}).setdefault(room, {})
        cur[dev] = round(cur.get(dev, 0.0) + wh, 2)
    doc.setdefault("acc", {}).setdefault(room, {})[dev] = new_marker


def prune(doc: dict, keep: int = KEEP_DAYS) -> None:
    """Drop day entries beyond the newest `keep` dates (in place)."""
    days = doc.get("days") or {}
    for day in sorted(days)[:-keep] if len(days) > keep else []:
        del days[day]

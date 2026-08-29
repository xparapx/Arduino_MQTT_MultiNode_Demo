"""Model governance (Phase 4): compare / promote / rollback of GMM versions.

Candidates are only stored; promotion requires distinct quadrants for all four
centroids and (log-likelihood +2 % on the last 7 days or max centroid shift >= 0.25).
models/current is a symlink; versions are never overwritten.
"""

from __future__ import annotations


def compare(current, candidate, recent7d, cfg: dict) -> dict:
    raise NotImplementedError("Phase 4")


def promote(candidate_ver: str, cfg: dict) -> dict:
    raise NotImplementedError("Phase 4")


def rollback(ver: str, cfg: dict) -> dict:
    raise NotImplementedError("Phase 4")

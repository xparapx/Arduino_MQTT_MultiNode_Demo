"""Deterministic summary sentences (Phase 3). Template text only, max 5 lines, no LLM."""

from __future__ import annotations


def lines(results: dict, cfg: dict) -> list[str]:
    raise NotImplementedError("Phase 3")

# multinode_aq — Claude Code entry point

Read `plan/CLAUDE_CODE_PLAN.md` (v2) first. It defines the phases, verification
commands, completion criteria and the invariants in section 2. Board facts live in
`docs/INVENTORY.md`; documented-vs-actual gaps in `docs/DRIFT.md` — both are authoritative
over README/manual.

Reference material:
- `plan/dashboard_mockup.html` — target layout, v2. Page 1 mirrors the current
  `hub/dashboard.py` (radar cards, stats, time series + vision crosshair, records,
  on-demand CSV export, reset). Page 2 = diagnosis A–I. Phase 1b optimizes page 1
  in place; Phase 5 splits into `pages/`.
- `docs/manual.html` — the "확장 과제" section is the methodological source.

Operating rules:
- Board (`ssh q`): never edit files there; deploy by `git pull` only.
- sudo on the board needs a password. Print any sudo / `systemctl restart|enable|daemon-reload`
  command for the user instead of running it. Read-only checks (`is-active`, `journalctl`, `curl`) are fine.
- No sqlite3 CLI on the board — use `.venv/bin/python -c "import sqlite3; ..."`. uv is `~/.local/bin/uv`.
- Never modify hub.py's write path or the readings/occupancy tables. `analysis`/`actuator_state` are analyst.py's only.
- Stop at the end of each phase and report; do not start the next phase without confirmation.

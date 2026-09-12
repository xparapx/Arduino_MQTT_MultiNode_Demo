# multinode_aq — Claude Code entry point

Read `docs/plan/CLAUDE_CODE_PLAN.md` (v2) first. It defines the phases, verification
commands, completion criteria and the invariants in section 2. Board facts live in
`docs/INVENTORY.md`; documented-vs-actual gaps in `docs/DRIFT.md` — both are authoritative
over README/manual.

Reference material:
- `docs/plan/dashboard_mockup_v2.html` — target layout, v2. Page 1 mirrors the current
  `hub/dashboard.py` (radar cards, stats, time series + vision crosshair, records,
  on-demand CSV export, reset). Page 2 = diagnosis A–I. Phase 1b optimizes page 1
  in place; Phase 5 splits into `pages/`.
- `docs/manual.html` — the "확장 과제" section is the methodological source.

Document structure (전역 규칙 적용, 2026-09-12):
- README.md = 프로젝트 소개 전용(무엇인지·구조·셋업). 작업 로그를 쌓지 않는다.
- 작업 이력·세션 인계 = `docs/WORKLOG.md` (구 PROGRESS.md, yyyy-mm 절, 최신이 위). 의미 있는 변경마다 갱신.
- CLAUDE.md = 작업 규칙·설계 결정·현재 상태 요약 전용. 상세 경위는 WORKLOG로.

Operating rules:
- Board (`ssh q`): never edit files there; deploy by `git pull` only.
- sudo on the board needs a password. Print any sudo / `systemctl restart|enable|daemon-reload`
  command for the user instead of running it. Read-only checks (`is-active`, `journalctl`, `curl`) are fine.
- No sqlite3 CLI on the board — use `.venv/bin/python -c "import sqlite3; ..."`. uv is `~/.local/bin/uv`.
- Never modify hub.py's write path or the readings/occupancy tables. `analysis`/`actuator_state` are analyst.py's only.
- Stop at the end of each phase and report; do not start the next phase without confirmation.

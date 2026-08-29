# multinode_aq — Claude Code entry point

Read `plan/CLAUDE_CODE_PLAN.md` first. It defines the phases, verification
commands, completion criteria and the invariants in section 2.

Reference material:
- `plan/dashboard_mockup.html` — target layout for the two-page dashboard
  (page 1 = monitoring, page 2 = diagnosis A–G). Open in a browser.
  Phase 5 reproduces this in Streamlit; SVG charts become Plotly, layout uses st.columns.
- `docs/manual.html` — existing build guide; the "확장 과제" section is the
  methodological source for the analysis pipeline.

Operating rules (repeated from the plan because they matter most):
- The board (`ssh q`) is the source of truth for code in Phase 0; edit only locally afterwards.
- Never modify the write path of hub*.py, or the readings/occupancy tables.
- Show any board command that deletes, restarts a service, or needs sudo before running it.
- Stop at the end of each phase and report; do not start the next phase without confirmation.

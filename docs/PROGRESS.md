# 진행 기록 (Phase별 판정·검증 출력)

PR 본문 대신 저장소에 남기는 기록. 각 Phase의 태그·검증 명령·결과·완료 기준 판정.
플랜: `docs/plan/CLAUDE_CODE_PLAN.md`, 드리프트: `docs/DRIFT.md`.

## Phase 0 — 실물 파악·현행화 · `v0.0-phase0` (PR #1)
INVENTORY/DRIFT 작성, 보드 코드 저장소 동기화, D-1 레이아웃(A) 적용. 상세는 DRIFT.

## Phase 1 — 워크플로우·하네스 · `v0.1-phase1` (PR #2, 2026-08-29)
- `uv run pytest -q` 14 passed · `ruff check` OK · `secret_scan.sh` OK · CI success
- `hub/hub.py` 1줄 변경 브랜치 `test/ci-hub-guard` → CI **failure**(의도), 브랜치 삭제
- `ssh q sudo true` → `Permission … denied` (저장소 루트 세션에서 확인)
- 픽스처 `fixtures/sample.db` 8.6 MB 커밋, 테스트 4건 사용
- 보드 `deploy.sh --apply` → `deployed: 0dd8760`, 보드 pytest 14 passed
- 발견: PreToolUse 훅 상대경로 → `$CLAUDE_PROJECT_DIR`로 수정

## Phase 1b — 대시보드 갱신·렌더링 최적화 · `v0.2-phase1b` (PR #3) + `v0.2.1-phase1b` (PR #4)
측정 도구: `hub/scripts/perf_probe.py` (bare 모드, 로더·figure별 시간 + 페이로드 바이트).

| 보드(UNO Q), 실 DB 114k행 | before (main@0dd8760) | PR #3 | PR #4 (cache_resource) |
|---|---:|---:|---:|
| 사이클 서버 시간 | 전체 재실행 **23.0 s** / 10 s | sec1 0.37 · sec2 0.55 · sec3+4 0.29 | **sec1 0.14 · sec2 0.19 · sec3+4 0.25** |
| 60 s 틱 합 (sec1 + sec3+4) | — | 0.66 s | **0.39 s** (probe) / **0.42 s** (AppTest 단일 세션) |
| 사이클당 페이로드 | **32,208 KB** | 187 KB | **187 KB** |
| ⑤ 내보내기 상시 비용 | 10.6 s / 21 MB | 0 | 0 |

실제 서비스 저널(`journalctl -u multinode_aq_dashboard | grep perf`)은 세션 수에 비례해 커진다: 탭 2개가 같은 초에 fragment를 돌리면 sec1 0.5~1.0 s, sec3+4 0.8~1.4 s(GIL 공유). 단일 세션 AppTest: sec1 0.13 s, sec2 0.19 s, sec3+4 0.26 s, 예외 0.

§5.4 완료 기준
- [x] 정상 사이클 < 0.5 s — 단일 세션 0.42 s (fragment 개별 최대 0.26 s)
- [x] 웹소켓 전송 < 200 KB — probe 상한 187 KB
- [x] 데이터 변화 사이클에서도 ⑤ 전송 0
- [x] 노드 선택 시 전체 깜빡임 없음 — 사용자 확인 2026-08-29 (①·② 유지)
- [x] 화면 구성·색·순서 동일 — 사용자 확인 2026-08-29 (의도된 차이: ② "last 28 days" 캡션, ⑤ Prepare 버튼, 이상치/과거점 표본화)

[ASK] 결정: 28일 창 채택 · 태블릿 체감 측정은 LED 인디케이터 부착·학생 수행 이후로 연기 · **WAL 전환 승인·적용**(2026-08-29 04:24 UTC, `delete → wal`, hub 무정지, ro 연결도 `wal` 확인, 전환 후 첫 새 행 04:25:22, hub `locked`/error 0) · 레이더 8개 → 폴라 서브플롯 1 figure (a)는 Phase 5.
DB: `ix_readings_node_ts`, `ix_occupancy_node_ts` 생성(2.36 s), hub `locked` 0.

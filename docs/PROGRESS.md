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

## Phase 2 — 데이터 계약 · `v0.3-phase2` (PR #6)
- `aq.db.ensure_schema()`(analysis / actuator_state), `aq.schemas`(kind 9종 + `explore`는 Phase 5), `config/analyst.toml`(§2 상수 전부), `calendar.json`(실제 학사 일정: 방학 7/17~8/10, 개학 8/11, 월~목 08:40~16:30, 금 ~15:30, 점심 12:30~13:30)
- 51 passed · CI에 `aq/` ALTER/DROP/DELETE 가드 추가. §6.4 3건 통과.

## Phase 3 — analyst.py 코어 · `v0.4-phase3` (PR #8)
- db 로더(5분 floor·버킷당 마지막 행) · qc(범위→NaN, KST 일 95% 게이트, `no rows`) · regime(고정 스케일 GMM 4, 분면 앵커링, 갭 단절 평활, 전이·체류) · rules(히스테리시스·10분) · forecast(shift −6 실측 타깃, 단일 Pipeline) · occ_co2(정확 조인, n≥25) · summary(≤5줄) · `analyst.py run|fit|show`, `scripts/plot_check.py`
- 90 passed, `aq` 커버리지 94%. 픽스처 dry-run: `gap_pairs>0`, QC 탈락 노드, 레짐 4종, GMM 4중심 4분면.
- 보드(모델 로드 경로): hourly 0.9 s · daily 5.2 s · RSS 224 MB (ad-hoc 경로 hourly 20 s → Phase 4로 해소). 7일 창 학습은 앵커링 거부 → 28일 창 필요 확인.
- [ASK] 미수행: 슬라이드 `실제분석사례_교실공기질` 정성 비교(파일 없음).

## Phase 4 — 모델 거버넌스 · `v0.5-phase4` (PR #9)
- `aq.governance`: 버전 저장소(덮어쓰기 거부), `current` 심링크/포인터, `compare`(4분면 ∧ (로그우도 +2% ∨ 중심 이동 ≥0.25) ∨ 경계일 강제) → keep/promote/reject, `promote`/`rollback`; `analyst.py` weekly·`fit`·`model list|promote|rollback`
- **v1**: 보드 실데이터 28일(8/1~8/29, 48,259행) — clean 538/71 · matter 447/131 · human 901/118 · mixed 1831/244. `models/gmm_v1.joblib`+메타 커밋, `models/current` = git 심링크 객체(보드에서 진짜 심링크로 체크아웃 확인)
- 101 passed, 95%. 보드 hourly(모델 로드) 0.8 s.

## Phase 5 — 대시보드 2페이지 · `v0.6-phase5` (PR #10)
- `aq/ui_common.py`로 80개 정의 바이트 그대로 이동(probe 동일) → 페이지 1: 레이더 2×4 폴라 서브플롯 1 figure, ② boxplot+막대, ③ 비전 전폭, 사이드바 상태 → `pages/2_diagnosis.py` A~I(`analysis`만 읽음, CI 가드) + 빈 상태 안내 · analyst daily에 `explore` kind
- 106 passed, 95%. 페이지 1 warm(PC) 0.004/0.007/0.011 s·131 KB (1b 기준선 이하). **보드 서비스 저널(재시작 후)**: sec1 0.08~0.10 s · sec2 0.10 s · sec3+4 0.20 s · 전체 재실행 0.51 s, 오류 0.
- 사용자 확인 2026-08-29: 화면·페이지 전환 OK(레이아웃 손질은 추후). 미결 [ASK]: 밴드 7일 → 28일 확장 여부.

## Phase 6 — 스케줄링·배포 · `v0.7-phase6` (PR #11, 설치 2026-08-29 05:43 UTC)
- 유닛 6개(`multinode_aq_analyst_{hourly,daily,weekly}.{service,timer}`), `systemd-analyze verify` 통과, 사용자가 설치·enable.
- `systemctl list-timers`: daily 06:00 · hourly *:05 · weekly Sun 06:30 UTC 예약.
- 수동 1회: daily **5.4 s / 80행**, hourly **0.7 s / 29행**, 둘 다 `Result=success`. `analysis` kind 9종(action 12 · band 7 · explore 1 · forecast 5 · occ_co2 1 · qc 70 · regime_now 5 · summary 1 · transition 7), `actuator_state` 12행.
- 실행 직후 readings 새 행(05:43:36) · journal wal · hub `locked`/error 0 · hub/dashboard active.
- 보드 AppTest: 페이지 2 예외 0(메트릭 5·표 6, I 절은 weekly 후), fragment 0.91 s; 페이지 1 예외 0.
- 첫 요약: "Regimes now: matter 3, clean 2 · ON: CLASS_03 purifier · QC hold: CLASS_06 · Forecast alert: CLASS_03 VOC 206 · Highest CO2: CLASS_04 529 ppm". 재실×CO₂ ρ=0.52 (n=1,171, CLASS_01·03).

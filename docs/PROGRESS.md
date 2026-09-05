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

## 대시보드 손질 — 합의 5항목 · (PR #13, 2026-08-29, 브랜치 `feat/dashboard-polish`)
Phase 6 후 화면 검토에서 합의한 항목. Phase 번호 없음(태그 없음), 보드는 `git pull`만.
1. 페이지 2 요약 카드 → "최근 hourly 판정 요약 — hh:mm KST"
2. E) 교실당 한 행: 교실 · **행동** · 근거 · 판정 시각(hourly run, KST) · 유지(ON 시작 시각 + 최소 동작 종료). B) 표의 환풍기/공청기 두 칸 → 행동 한 칸. 어휘 `plots.ACTION_WORDS`(환기 필요 / 공기청정 필요 / 환기·공기청정 필요 / 조치 없음 / 판정 보류, 히스테리시스·최소 동작 유지 시 "(유지)") — **임시**, LED 인디케이터 문구 확정 시 dict 한 곳만 교체
3. B) 평면 별 라벨: 축 비율 거리 0.07 미만인 이웃끼리 다른 textposition 슬롯(`plots.label_positions`), 호버는 그대로
4. G) "마지막 비전 버킷 (KST)" 열: analyst daily가 `db.last_occupancy_bucket()`(occupancy 전체 노드별 MAX(ts), 인덱스 사용)을 `occ_co2.by_room[room].last_bucket`에 저장, 비전 노드가 창 이전에 멈춘 교실도 n=0 행으로 남김 → 페이지가 `win_start`와 비교해 "· 중단"
5. 사이드바 "비전 노드 N / 5 (24h 내 수신)" — 총수는 `occupancy`에 기록된 노드, 환경 노드 총수는 `readings`에 기록된 노드(nodes.json 16개는 접두사가 없어 구분 불가, DRIFT 참조)

검증
- 로컬: `ruff check` OK · **112 passed**(신규 `tests/test_plots.py` 5건, `test_occ_co2` +1)
- 보드(머지 전, `git archive origin/feat/dashboard-polish` → `/tmp/aq_polish`, DB는 backup API 스냅샷, 작업 트리 무변경): 새 analyst daily **5.5 s / 80행**(프로세스 wall 13.9 s), `occ_co2.by_room` 5교실 — CLASS_01 08-28 21:55 · CLASS_03 08-23 23:30 · CLASS_02/05/08 창 이전(중단). 페이지 2 AppTest 예외 0, `page2 0.80 s`(Phase 6 0.91 s), 표 6·메트릭 5; 페이지 1 예외 0. 사이드바 "환경 노드 6 / 8 활성 · 비전 노드 1 / 5 (24h 내 수신)"
- 실 hourly(06:05 UTC) E 표: 조치 없음 4 · 판정 보류 2(CLASS_03 공청기 14:43부터 ON 유지, CLASS_06)

## Phase 8 — 웹 프런트엔드 (경로 C) · `v0.8-phase8` (PR #14, 배포 2026-08-29 07:43 UTC)
사용자 결정: C) 정적 HTML/JS + 보드 JSON API, 두 페이지 동시. 디자인 정본 = 캔버스 `multinode_aq 대시보드`(https://claude.ai/code/artifact/7fac2d40-6b82-4657-8098-9a059540a375).
- `webapp.py`(stdlib HTTP, 8502) · `aq/webdata.py`(읽기 전용, 버전 메모이즈) · `aq/derive.py`(plots.py 순수 로직 분리) · `web/`(HTML 2 · CSS · JS 4, 외부 라이브러리 없음) · `systemd/multinode_aq_web.service` · deploy.sh 재시작 매핑
- 픽스처(analyst hourly+daily 후) API 크기: status 0.4 KB · live 7.3 KB · stats 14.2 KB · series 7.2 KB · analysis 79.6 KB(gzip 전) · warm 캐시 ≤ 1 ms(PC)
- pytest **121 passed**(신규 `tests/test_webapp.py` 9건: 상수 동기화, 빈 DB, live/stats/series/status/analysis 번들, HTTP 엔드포인트, gzip, CSV 내보내기·reset 가드). e2e가 정적 경로 탈출 결함(`hub/web` 접두사 비교)을 잡아 수정.
- 로컬 미리보기(픽스처) 사용자 피드백 반영: A) QC 표를 노드당 1행 + 최근 7일 통과/탈락 점 띠로 축소 · 재실 탐지 지도 높이 320px 고정(4:3), 통계 4칸을 우측 열 상단으로 · 정적 파일 `no-cache`(배포 즉시 반영). 브랜치 fetch → `/tmp/aq_web` 보드 미리보기(:8503, 읽기 전용)도 사용자가 실행.
- 보드(머지 후, `deploy.sh --apply` → db7260a, 사용자가 유닛 설치·enable): `multinode_aq_hub/dashboard/web` 모두 active. API cold: status 0.20 s · live 0.28 s · **stats 1.16 s**(28일 스캔, 5분 버킷당 1회) · series 0.10 s · analysis 0.09 s; **warm: live 7 ms · stats 9 ms · analysis 16 ms · status 0.13 s**(readings COUNT(*) 전체 스캔). 크기: status 0.4 KB · live 7.5 KB · series 7.1 KB(→ 60 s 폴링분 ≈ 15 KB) · analysis 69.7 KB(gzip 6.6 KB). 웹 프로세스 RSS 216 MB. 저널 오류 0. Streamlit 8501 병행 유지.

§12.2 완료 기준
- [x] 페이지 1·2 API만으로 렌더, Streamlit과 내용 동등 + 캔버스 디자인 반영 — 로컬(픽스처)·보드(:8503 실데이터) 미리보기 사용자 확인, 피드백 3건 반영
- [x] 60 s 폴링분 ≈ 15 KB < 50 KB · analysis 70 KB < 200 KB · warm 캐시 ≤ 16 ms(보드, status만 0.13 s — COUNT(*) 캐시는 후속)
- [x] readings/occupancy `mode=ro`(reset 제외) · CI 가드 · e2e 9건
- [x] 보드 유닛 active, 두 페이지 200, 사용자 화면 확인 2026-08-29

후속 PR(2026-08-29): 행동 문구 색 칩(PR #16) · **공개 인스턴스** — `webapp.py --public`은 `/api/export`·`/api/reset`을 403으로 막고 `/api/status.public=true`로 페이지가 5·6절을 렌더하지 않음. 유닛 `multinode_aq_web_public.service`(8502, `--public`)를 8501(관리용) 옆에 추가, Tailscale Funnel은 **8502만** 공개(사용자 결정: 토큰 방식 대신 인스턴스 분리). e2e 1건 추가(10 passed).
결정 2026-08-29: **Streamlit(`multinode_aq_dashboard`) 정지**, 웹 서비스가 8501 인수(유닛 `--port 8501`). 코드 제거는 Phase 7 뒤 정리 PR. 미결:  · 호스팅은 Tailscale `serve`(테일넷) 우선, **Funnel은 `--public` 모드(reset 차단·export 제한·토큰) 이후로 보류**(사용자 결정 2026-08-29) · `/api/status`의 COUNT(*) 캐시.

## 웹 손질 + 실물 액추에이터 조사 + 비전 노드 안정성 진단 · (2026-09-01, main 직접 커밋)

웹 손질 (b0b74de, 803245b — 배포·확인 완료):
1. 페이지 1 비전 패널: `/api/series` occupancy에 `nodes`(비전 노드 전체의 마지막 버킷·`on` = 12분 내 수신) 추가, 버킷 추이 위 빈 공간에 ON/OFF 칩 렌더(`.vnodes/.vnc`). e2e 단언 3건 추가, 122 passed.
2. 페이지 2: h1 아래 설명 캡션 삭제, "최근 hourly 판정 요약" 패널 제거(+사용 안 하는 `.summary` CSS). analyst·`/api/analysis`의 summary는 그대로 — 화면만 제외.

실물 액추에이터 조사 (구현 전 — 사용자 결정 대기):
- 공청기 = 휴앤텍 SS-3631PW(52W). **통전 복구형 실물 테스트 통과**(재통전 시 자동모드 재개, 설명서 p.8). 12h 자동꺼짐 있음 → 플러그 사이클이 리셋하므로 플러그 제어가 오히려 필수. 환풍기 = 기계식, 문제 없음.
- 플러그 = Tapo 10A 에너지 모니터링. 로컬 제어 검증: python-kasa ≥0.7.4(KLAP) + **앱에서 기기별 "서드파티 제어" ON 필수**(fw 1.4.x부터 옵트인, 403 이슈의 해결책) + 펌웨어 자동업데이트 OFF + IP DHCP 예약.
- 확장(8교실) 대안 = Shelly Plug S: 공식 로컬 API(REST/WS/**MQTT 네이티브** → 허브 mosquitto에 직접), 클라우드 계정 불요, 국내 유통 약해 직구. `actuator.py`는 드라이버 계층 분리(kasa/MQTT)로 양쪽 대응 설계.
- 통합 원칙: actuator_state를 **읽기만** 하는 별도 서비스(불변식 유지). 에너지 모니터링 와트값으로 실동작 검증.

비전 노드 안정성 진단 (occupancy DB + 운용 펌웨어 `occ_node_portenta_cloud.ino`(manual.html 6-2) 정독):
- 증상: 한 시점에 1노드만 생존, 죽으면 전원 재인가 전까지 영구 다운(E647F1 ~8/23 → 44F2FB 8/25~28 → E1B3AA 8/31~). 생존 중엔 일일 255~288행(만점 288)으로 건강.
- **원인(확정적)**: `wd.start()`가 setup() 맨 끝인데 setup() 초반에 `while(1)` 데드엔드 2곳(cam.begin 실패, 관문1 실패). WDT 리셋(웜 리셋)은 HM0360 센서를 리셋하지 못해 cam.begin이 실패하기 쉽고, 그 시점엔 IWDG 미무장 → **워치독 없는 무한루프 = 벽돌**. 부차: TLS 협상 wd.kick 1회뿐(30s 초과 시 연결 중 WDT), NTP 1회 동기화(주당 수 분 표류·49.7d rollover), WiFi/MQTT 연속 실패 시 자가 복구 없음.
- 대책 2계층 (펌웨어 v3는 다음 세션):
  (1) 펌웨어: wd.start()를 setup() 첫 줄로 · 데드엔드 → 재시도 후 NVIC_SystemReset() · 3버킷 연속 발행 실패 시 자가 리셋 · NTP 6h 재동기화 · TLS 구간 wd.kick 보강.
  (2) 하드웨어: 비전 노드 USB 전원을 Tapo 플러그에 물리고 **매일 07:59 OFF / 08:00 KST ON**(카메라 이상은 전원 재인가만 확실). 1단계 = Tapo 앱 자체 스케줄(코드 0줄, 허브 무관), 2단계 = actuator.py + systemd 타이머(23:00 UTC)로 이관.

## SPA 재설계(모바일 dock) + 통계 확장 + "제어 판단" 개편 · (2026-09-04 ~ 09-05, main 직접 커밋 ~40건, 보드 배포·재시작 완료)

웹 전면 재구조 — 2페이지 → 단일 shell SPA (사용자 확정: 해시 라우터 / 인스턴스 분리 유지 / 컬러맵·CH.* 재사용):
- `web/router.js`(registry·go()·scroll 복원·admin 게이트) + `web/screens/{home,monitor,diagnosis,admin}.js`(page1/2 git mv 후 분할). `/diagnosis`는 302 → `/#dx-regime`. `AQ.store` = URL당 인터벌 1개·활성 화면만 fetch·버전 게이트·visibilitychange 재fetch·prime()(선제 워밍).
- 화면: #home(시스템상태 4색 카드·레짐/제어 표·경보요약·오늘 한눈에=summary 부활) · #mon-live(+/<node> 확대)·통계·시계열&비전·최근기록(admin) · #dx-regime(B+H+G)·밴드전이(C+D)·제어경보(E+F)·유효범위(A,admin)·모델이력(I,admin) · #admin(내보내기·초기화·상세).
- 모바일(<900px 단일 브레이크포인트): 하단 dock(56px+safe-area, 그룹 아이콘=격자/돋보기펄스/기어), 서브탭 = 균등폭 둥근사각(활성 폰트 15px + 색 스윕 애니메이션), 레이더 2열, 밴드 .scrollx, 터치 data-tip→toast.
- 라벨 계층: 탭=제목(단일 섹션 화면은 헤더 삭제, meta만) · 섹션 칩 = 무채색 320px 균일폭 · 해설 텍스트는 manual.html "대시보드 시각자료 해설" 표로 이관.
- 명명: 현재 레짐→**절대 레짐(FixedScaling)**(상대 레짐과 쌍) · 행동지침→**제어 판단**(스마트플러그 직접 제어 대비, 서브탭 "제어·경보") · 제어 카드 액션워드 행 삭제, 장치 ON/유지 칩 글로우 펄스.

통계 탭("전체통계"→"통계") 5단 재구성 — 전부 서버 집계본(`webdata.stats()`):
- ① 28일 일별 q1-med-q3 추이 밴드(+ON 임계선) ② 주간 비교(주별 IQR 막대, 월요일 기준) ③ 요일×시간 7×24 중앙값 히트맵(임계 초과 셀 빨간 테두리) ④ ON 임계 초과율 순위(EXCEED_THR=규칙 ON 임계, 평균 막대 대체) ⑤ 분포 박스 = **최근 7일**(BOX_DAYS), p99 축 절단 + ▲생략 주석, 한 카드 1행.
- 성능: stats 콜드 1.78 s(보드 실측, 5분 버킷마다 재빌드) → KST 일자를 SQL `date(ts,'+9h')`로 이동 + shell 기동 2.5 s 후 `store.prime("/api/stats")` + "계산 중" 플레이스홀더.

시각·정책:
- 히스테리시스 게이지/스트립 배경 = **turbo** 연속 컬러맵(게이지 가로 0.55 · 스트립 세로 0.32, OFF/ON 임계는 점선 유지). 레짐 스위칭 밴드 셀 불투명도 **0.75**(사용자 튜닝).
- 모델 거버넌스 **weekly → 격주**(1·3주 일요일 06:30 UTC, 타이머 OnCalendar 변경 — 보드 cp+daemon-reload 필요, §미결).
- 경보·이상: 문구 직관화("CO₂ 정상 측정 87.5%"), 항목당 1행(nowrap+ellipsis), meta에 판단 주기(경보·QC hourly / 수신 지연 15분 / 60 s).
- 임계 고정 근거 문답 확정: CO₂ 1000 = 학교 실내공기질 기준(건강 앵커), VOC 200 = 센서 지수 정의(베이스라인 2배) — "규칙은 건강 기준에 앵커, 적응은 ML 게이트·거버넌스가".

기타: 발표자료 `docs/pitch/`(deck+script)는 **gitignore·추적 해제**(로컬+바탕화면 사본만, 과거 이력엔 잔존). 테스트 `test_webapp.py` 10 passed 유지(라우트·stats 신규 키 단언 갱신).
미결: ① weekly 타이머 보드 반영 확인(`systemctl list-timers multinode_aq_analyst_weekly.timer`) ② `/api/status` COUNT(*) 캐시(이전부터) ③ 요일 히트맵/주간비교 실데이터 검토 후 필요 시 학사일정(방학) 마스킹.

## 비전 노드 펌웨어 v3 — 자가 복구 (2026-09-05, main 직접 커밋)

09-01 진단("워치독 없는 무한루프 = 벽돌")의 대책 1계층 구현. `firmware/occ_node_nicla_cloud.ino`(GC2145) + `firmware/occ_node_portenta_cloud.ino`(HM0360) — 종전엔 manual.html 내장 코드만 있었고 firmware/에 occ 파일 자체가 없었음(비대칭 해소). 두 판은 카메라 계층만 다르고 v3 변경은 동일:
1. **wd.start() = setup() 첫 줄** — cam.begin·관문1을 포함한 모든 초기화가 WDT 보호下. 종전엔 맨 끝이라 초기화 데드엔드 = 영구 다운.
2. **while(1) 데드엔드 제거** — cam.begin/관문1 실패는 3회 재시도(사이 settle) 후 `NVIC_SystemReset()`. 웜 리셋 대비 부팅 직후 3초 센서 안정화 대기.
3. **발행 자가 복구** — `endMessage()` 반환값 검사, 3버킷 연속 미전송(≈15분) → 자가 리셋(WiFi/MQTT 드라이버 고착 탈출).
4. **캡처 자가 복구** — 추론/grabFrame 6회 연속 실패(≈1분) → `cam.begin` 재초기화, 재초기화 2회 무효 → 자가 리셋. (종전엔 카메라 고착 시 s_n=0으로 발행만 조용히 멈추는 좀비 상태)
5. **NTP 재동기** — 확보 후 6h 주기·미확보 시 10분 재시도(종전 setup 1회뿐 → millis 49.7일 롤오버·표류 노출). 시계 후퇴 시 중복 발행 방지 가드(`bucket > curBucket`만 발행).
6. **wd.kick 보강**(WiFi 대기·NTP 루프·MQTT 성공 후) + 부팅 시 `mbed::ResetReason` 출력(전원/워치독/자가 리셋 구분 — 현장 시리얼 진단용).

발행 계약(JSON·토픽·버킷)·듀티(10s 단발) 불변 — hub/DB 영향 없음. 대책 2계층(Tapo 플러그 일일 전원 재인가 07:59/08:00 KST)은 별도 진행. 배포는 사용자가 Arduino IDE로 노드별 업로드(더블탭 부트로더), WIFI/MQTT 자격은 업로드 시 기입.

## 환경 노드(UNO R4) 펌웨어 v3 — 통신·시각 계층 자가 복구 (2026-09-05, main 직접 커밋)

`firmware/sensor_node_uno_r4_cloud.ino` 재검토. 발견: 레포 파일은 **v1 구판**(토픽 `multinode_sensor_demo`, 센서 건강감시 없음)이었고 실제 운용본은 manual 6-1의 **v2**(plausibleSEN 물리범위 필터 — 94.2℃/PM2378 동결 사례 대응, SCL 9펄스 I2C 복구, MCU 리셋)였음. 레포 파일을 v2 기반 + v3 통신 계층으로 갱신(드리프트 해소, 토픽 `multinode_aq` 정렬):
1. **브로커 재접속: 무한 블로킹 while → 10초 간격 1회 시도** — 장애 중에도 loop 유지(샘플링·센서 감시 지속), WiFiS3 고착 행 방지. 종전엔 통신 두절 = loop 정지 = "수집 중단" 패턴.
2. **시각: 매 loop `WiFi.getTime()` → epochBase+millis** — 초당 수백 회 모뎀 AT 왕복 제거, 순간 0 반환 시 1970 타임스탬프 오염 잠재 결함 차단(보드 DB 실사: 1970 행 0건 = 잠재). NTP 6h 재동기 + 미확보 10분 재시도 + 시계 후퇴 중복발행 가드.
3. **발행 3버킷 연속 실패(≈15분) → MCU 리셋** + `publish()` 반환 검사 + `setBufferSize(512)`(기본 256B는 240B 페이로드와 여유 <20B — 조용한 전량 미전송 위험) + `setSocketTimeout(5)`.
4. **하드웨어 WDT(RA4M1 최대 5592ms)를 setup 완료 후 무장** — Wire/WiFiS3 내부 행 회수. TLS connect >5.5s면 WDT 리셋 후 비무장 setup에서 재접속(부팅 루프 회피 설계). 
5. **부팅 시 죽은 센서 10분마다 재초기화, 1시간 지속 시 리셋**(종전엔 begin 실패 = 영구 좀비 — SCD30 죽으면 CO₂ 없어 QC 95% 게이트 제외 유형) + 정상 샘플 시 recoverCnt 청산 + loop 말미 delay(20).

발행 계약(11변수 JSON·5분 버킷) 불변. 비전 v3와 함께 **다음 주 노드 일괄 업데이트 예정**(사용자). 미결 추가: manual.html 6-1/6-2 내장 코드 목록을 firmware/ v3와 동기화할지 [ASK]. Nano ESP32 판(`aq_node_nano_esp32_cloud.ino`)도 동일 구판 — R4 검증 후 필요 시 동일 적용.

## manual.html 리디자인(라이트) + v3 코드 반영 + 운용 섹션 추가 (2026-09-05, main 직접 커밋)

교사 실습 매뉴얼(docs/manual.html)을 training_manual_v1/발표자료 디자인 컨셉으로 재스타일:
- **라이트 모드**: 토큰 = hub/web/app.css `[data-theme="light"]` 팔레트(+구판 변수 별칭 --primary/--accent/--warn 유지로 인라인 스타일 무수정), IBM Plex Sans KR/Mono(Pretendard/JetBrains 대체), 16:9 stage → 사이드바+콘텐츠 풀뷰 그리드, 섹션 칩 제목·레짐 팔레트 박스(why/tip/warn/ok/ai/key)·다크 코드블록 유지. 마크업 구조·패널 내비 상호작용은 원형 유지(흐름 보존).
- **최신 코드**: 6-1 R4 cloud / 6-2 Nicla·Portenta occ 내장 목록을 firmware/ v3 정본으로 교체(+v3 요지 박스), ESP32 cloud 판은 "v1 참고용" 경고. s8에 "현행 운영 = webapp.py SPA(8501/8502), Streamlit은 학습판" 안내, s9에 현행 systemd 구성표(hub/web·web_public/analyst hourly·daily·**격주** weekly), s12에 현행 진행 상황 박스.
- **신규 sAI 패널** "현행 개발 방식 — GitHub + 클로드 코드 운용"(끝 패널 앞): 운용 지도(노트북→GitHub→보드 pull→sudo는 사람), 역할 분담표, CLAUDE.md 규칙 요지, 표준 배포 사이클 6단계, 실전 프롬프트 예시, 수동 vs 클로드 코드 비교 — training 매뉴얼 마무리 파트의 현행 프로젝트판.
- 버그 수정: 사이드바 "비전 노드 (재실)" 클릭이 죽어 있던 order 배열 누락(sVIS) 복구.

## 핵심 변수 컬러맵 개편 — CO₂ = YlOrRd · VOC = matter (2026-09-05, 사용자 확정)

turbo 단일맵 → plotly 기준 변수별 시퀀셜 맵으로 교체(값 크기 매핑 전 지점): charts.js `CMAPS{co2,voc}` + `cmapDef`(그라디언트)/`cmapAt`(보간 샘플러). 적용: ① 제어 판단 게이지(0.55)·24h 스트립(0.32) — bandCfg에 key 추가 ② 요일×시간 히트맵 셀(투명도 램프 → 컬러맵, 0.92) ③ 임계 초과율 막대(pct/max → 컬러맵, 바닥 0.25) ④ howto 범례 스와치 2종(.sw.ylorrd/.sw.matter). 레짐 밴드(범주형 팔레트)는 불변. 10 passed, webtest로 stats·dx-action 확인. 정적 파일만 — 재시작 불요.

## 분포 boxen 전환 + 표시 계층 물리범위 필터 + 모바일 라이트 디폴트 (2026-09-05, 사용자 확정)

- **boxen(letter-value)**: 변수별 분포의 Tukey 박스+이상치 점 구름 → 중앙 50% 상자 + 75/87.5/93.75% 꼬리 세그먼트. webdata `box_stats`에 `lv`(4쌍)·`beyond_n` 추가(기존 키 유지 — 호환), charts `box(st, key)` 재작성: co2/voc 세그먼트 색 = 컬러맵의 구간 위치(값 클수록 깊은 색 — 게이지·히트맵과 문법 통일), 보조 변수 = 대표색 불투명도 단계. ▲n·max 주석 유지.
- **PLAUSIBLE 필터**: stats() 집계 한정, pm2.5<1000·pm10<2000·co2 300–5000·voc 1–500·temp/hum 물리범위 밖 → NaN (펌웨어 v2 필터 이전 적재분 오염 차단, mon-series 원시 뷰는 유지). PM 로그 축은 boxen 결과 보고 재판단.
- **변수 대표색 단일화**: charts `varColor(key)` (핵심=컬러맵 중앙값·보조=plotly 초이스) — monitor의 색 맵 제거.
- **모바일(<900px) 테마 디폴트 = 라이트** (저장된 선택 우선, 데스크톱 다크 유지) — index.html 프리페인트 + initTheme.
- 11 passed(단언 추가). **webdata.py 변경 → 웹 서비스 재시작 필요**.

## UI 폴리시 배치 — 컬러맵 체계 완성 + 상태 표기 정리 + 폰트 단일화 (2026-09-05 후반, main 직접 커밋 ~10건)

컬러맵 체계(322c925~): CO₂ YlOrRd·VOC matter 전면 적용(게이지/스트립/히트맵/초과율/단일색=중앙값), 보조 변수 plotly 4색(#636EFA/#AB63FA/#00CC96/#19D3F3), boxen 폭 -40%·모바일 2행4열·높이 -20%, 초과율 막대 = 진행 그라디언트+외곽선(두께 16), 히트맵 초과 셀 점멸, 게이지·스트립 불투명도 0.75 + 트레이스 2.2px 패널 케이싱 + 임계 점선 패널색, --chart-ink(라이트 차콜).
상태·레이아웃: 장치 ON=green 트랙(폭 8)·OFF=연회색(적색안은 철회), 구간 칩(.zc) 제거(정보는 수치 툴팁), 수치 = 카드 상단 우측. 헤더 정리: 데스크톱 메인 h1·meta 전체 삭제(사이드바 브랜드가 제목), 모바일 Home만 "교실 공기질 모니터" 중앙 밴드. 모바일: 라이트 디폴트, 테마 플로팅 버튼, 서브탭 13px 볼드 동일(활성=스윕만), 요일 히트맵 슬라이더 제거(컴팩트 지오메트리).
**타이포: IBM Plex Mono 전면 폐기 — 전 UI IBM Plex Sans KR 단일**(메타·수치·칩 포함, app.css 17곳).

# 대시보드 데이터 파이프라인 — 문제와 해결 이력

> 대상: `hub/dashboard.py` (Streamlit, 페이지 1). 언제: 2026-08-29, Phase 1b (`v0.2-phase1b`, `v0.2.1-phase1b`).
> 수치는 모두 보드(UNO Q) 실물 DB(readings 114,560행) 기준. 측정 도구: `hub/scripts/perf_probe.py`.
> 관련: `docs/plan/CLAUDE_CODE_PLAN.md` §5, `docs/DRIFT.md` "Phase 1b" 절, `docs/PROGRESS.md`.

## 0. 출발점 — 왜 버벅였나

대시보드는 **10초마다 화면 전체를 처음부터 다시 그리는** 구조였다. 한 번 그릴 때마다:

1. DB의 **모든 행(11만 4천 개)** 을 통째로 읽음 (`SELECT … FROM readings`, WHERE 없음)
2. 그 행 전부를 그래프 안에 담아 브라우저로 보냄 — boxplot 7.3 MB, 레짐 산점도 3.0 MB
3. 아무도 누르지 않은 **다운로드 버튼 4개용 CSV를 매번 미리 생성** — 21 MB, 10.6초
4. 위 작업을 10초마다 반복 (`st_autorefresh(10 s)`)

결과: 보드에서 한 사이클 **23.0초**, 브라우저 전송 **32 MB**. 갱신 주기(10초)보다 처리가 오래 걸리므로 밀릴 수밖에 없었다.

비유: 5분에 한 번 바뀌는 게시판을, 10초마다 서랍 전부를 꺼내 복사기로 다 복사해 배달하던 셈.

## 1. 측정부터 — 수정 전 기준선

- 각 구간 끝에 소요 시간을 로그로 남김: `[perf] sec1 0.12s` (stderr → `journalctl -u multinode_aq_dashboard | grep perf`)
- `hub/scripts/perf_probe.py`: Streamlit bare 모드로 로더·그래프별 시간과 **브라우저로 갈 바이트 수**를 표로 출력. 서비스 재시작 없이 보드에서 실행 가능
  (`ssh q 'cd ~/multinode_aq/hub && .venv/bin/python -' < hub/scripts/perf_probe.py`)
- 결론: 범인은 레이더 차트가 아니라 **CSV 상시 생성**과 **전체 이력 그래프**

| before (보드) | 초 | 전송 KB |
|---|---:|---:|
| 전체 재실행 1회 (warm) | **22.99** | **32,208** |
| ⑤ 전체 CSV + 기간 CSV | 3.66 + 3.70 | 9,961 + 9,961 |
| ⑤ 병합 CSV + 비전 CSV | 2.76 + 0.45 | 1 + 1,240 |
| 전체 테이블 읽기 | 2.94 | |
| ② boxplot / 레짐 산점도 | 0.38 / 0.59 | 7,336 / 3,006 |

## 2. 수정 6단계 (플랜 §5.2 순서, 각각 독립 커밋)

### ① CSV는 "달라고 할 때만" — `perf(dashboard): CSV export on demand`
- 전: 다운로드 버튼 4개가 항상 떠 있고 그 뒤의 CSV를 10초마다 새로 생성
- 후: **"Prepare …" 버튼**을 누를 때만 쿼리 + CSV 생성 → 결과를 세션에 보관 → 그 다음 다운로드 버튼 표시 (`export_slot()`)
- `load_df(limit=10_000_000)` 제거, 초기화(⑥) 백업은 캐시 없는 `query_all()`
- 효과: 사이클당 10.6초 / 21 MB → **0**

### ② 데이터가 안 바뀌었으면 다시 안 그리기 — `cache figures on data_version()`
- 갱신 키 `data_version()` = (가장 최근 행 id, 그 행의 **5분 버킷**). PK 조회 2번, 1 ms
- 통계 그래프 5개(`stats_figures(bucket)`): **5분 버킷이 바뀔 때만** 재생성
- 노드 카드 레이더·시계열: **그 노드에 새 행이 왔을 때만** (`recv_time` 키)
- 레짐 산점도 2종을 "배경(무거움, 캐시)" + "현재 위치 ★ 오버레이(가벼움, 매번)"로 분리
- 왜 `MAX(id)`만으로 안 되나: 8노드가 수 초마다 id를 올리므로 60초마다 캐시가 깨진다 → 무거운 것은 버킷으로

### ③ 계산은 서버에서, 브라우저엔 결과만 — `aggregate on the server, 28-day window`
- boxplot: 값 전부 대신 **다섯 숫자(q1·중앙값·q3·울타리) + 이상치 ≤ 300점** (`box_stats()`)
- 밀도 배경: 점 전부(`go.Histogram2d`) 대신 서버에서 **`np.histogram2d` 24×24 집계** → `go.Heatmap`
- 노드별 산점도 과거점: 시간 균등 표본 **≤ 1,500점**
- 통계 기간 상한 **최근 28일**(`STATS_DAYS`, 모델 학습 창과 동일) → 데이터가 쌓여도 비용이 늘지 않음
- 효과: 사이클당 전송 8 MB → **187 KB**

### ④ 부분 갱신 — `st.fragment partial refresh`
- 전: `st_autorefresh(10 s)` → 페이지 전체 재실행 (노드 하나 바꿔도 전체가 깜빡임)
- 후: 섹션별 독립 타이머
  - ① 노드 카드, ③④ 시계열·최근행: **60초** (`REFRESH_LIVE`)
  - ② 통계: **5분** (`REFRESH_STATS`)
  - ⑤ 내보내기: 버튼 눌렀을 때만
- 노드 선택 드롭다운은 ③ fragment 안 → 바꿔도 그 섹션만 다시 그림
- 주의: bare 모드(`python -c "import dashboard"`)에서는 fragment 본문이 실행되지 않는다 → probe가 `__wrapped__`로 직접 호출

### ⑤ DB 접근 정리 — `read-only URI connections`
- 읽기 12곳을 **읽기 전용 연결**(`file:sensor_data.db?mode=ro`, 잠금 대기 5초)로 → 대시보드가 수집 데이터를 실수로 쓸 수 없음. 초기화(⑥)만 쓰기 연결 유지
- `readings(node, ts)`, `occupancy(node, ts)` **인덱스 생성**(`aq.db.ensure_indexes`, 2.36초) → 노드별 조회가 전체 훑기에서 바로 찾기로

### ⑥ 정리 — `use_container_width -> width='stretch'`
- 지원 종료 예고된 옵션 9곳 교체. `components.html`(비전 패널) 경고는 대체재가 없어 Phase 5로

## 3. 후속 수정 — "캐시 꺼내기가 새로 만들기만큼 느림" (`v0.2.1-phase1b`)

- 배포 후 실측: 60초 틱 0.66초 — 기준(0.5초) 초과
- 보드 벤치마크로 원인 확인:
  - `st.cache_data`는 꺼낼 때 **unpickle → plotly 재검증**: 레이더 25 ms × 8, 통계 5개 280 ms — 새로 만드는 것(81 ms)과 같은 급
  - ★ 오버레이 `add_annotation` 16회: 매번 목록 전체를 재검증 → 293 ms
- 조치:
  - 그래프 캐시를 **`st.cache_resource`**(객체 그대로 보관, 꺼내기 ≈ 0 ms, `max_entries`로 메모리 상한)로
  - 오버레이는 `copy.deepcopy` 후 **`add_traces` 1회 + `layout.annotations` 1회 대입**으로 묶어서 (51 ms)

## 4. 결과 (보드 실물)

| | 전 | PR #3 | PR #4 (최종) |
|---|---:|---:|---:|
| 한 사이클 서버 처리 | **23.0 s** (10초마다) | sec1 0.37 · sec3+4 0.29 | **sec1 0.13 · sec3+4 0.26** (60초마다) |
| 통계 섹션 | 포함 | 0.55 s | **0.19 s** (5분마다) |
| 60초 틱 합계 | — | 0.66 s | **0.42 s** (단일 세션 AppTest) |
| 브라우저 전송량 | **32,208 KB** | 187 KB | **187 KB** |
| CSV 상시 생성 | 21 MB | 0 | 0 |

### 세션 수에 따른 주의
열린 탭(세션)마다 위 비용이 따로 들고, 같은 초에 겹치면 서로 기다린다(파이썬 GIL). 탭 2개일 때 서비스 로그에 sec1 0.5~1.0초, sec3+4 0.8~1.4초가 찍힌 것이 그 현상. 세션당 분당 ~0.4초 CPU이므로 태블릿 8대까지는 분당 3초 남짓 — 감당 범위.

## 5. 일부러 하지 않은 것
- **화면 디자인 변경 없음** — 목업(`docs/plan/dashboard_mockup_v2.html`) 반영은 Phase 5. 전/후 성능 비교를 공정하게 하려고 구조를 고정했다. 의도된 미세 차이: ② "Window: last 28 days" 캡션, ⑤ "Prepare …" 버튼, 이상치/과거점 표본화
- 레이더 8개를 폴라 서브플롯 1장으로 합치기 — 카드 테두리가 바뀌므로 Phase 5 (결정됨: 방식 (a))
- `PRAGMA journal_mode=WAL` — 승인 대기
- 교실 태블릿 체감 측정 — LED 인디케이터 부착·학생 수행 이후로 연기

## 6. 확인 명령
```
# 서비스 로그의 구간별 시간 (탭 1개 기준으로 볼 것)
ssh q 'journalctl -u multinode_aq_dashboard --since -10min --no-pager | grep perf | tail -12'
# 재시작 없이 보드에서 전체 표
ssh q 'cd ~/multinode_aq/hub && .venv/bin/python scripts/perf_probe.py'
# 인덱스 존재
ssh q 'cd ~/multinode_aq/hub && .venv/bin/python -c "import sqlite3;print(sqlite3.connect(\"file:sensor_data.db?mode=ro\",uri=True).execute(\"SELECT name FROM sqlite_master WHERE type=\x27index\x27\").fetchall())"'
```

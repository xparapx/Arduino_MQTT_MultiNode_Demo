# multinode_aq — 하이브리드 분석·진단 확장 작업 지침 (v2)

> 대상: Claude Code. 이 문서는 **작업 순서·검증 기준·금지 사항**을 정의한다.
> v2 변경: Phase 0 결과(`docs/INVENTORY.md`, `docs/DRIFT.md`)를 반영해 사전지식을 실물로 교체했고,
> 대시보드 **데이터 갱신·렌더링 최적화**(Phase 1b)를 추가했으며, 검증 명령을 보드 실물(sudo 비밀번호, sqlite3 CLI 없음, uv 경로)에 맞췄다.
> 각 Phase는 "완료 기준"을 모두 통과해야 다음 Phase로 넘어간다. 통과하지 못하면 멈추고 사용자에게 보고한다.

---

## 0. 작업 원칙 (모든 Phase 공통)

1. **추측 금지.** 경로·토픽·스키마·서비스명은 `docs/INVENTORY.md`가 정본이고, 그것과 다른 것을 발견하면 실물을 다시 읽고 `docs/DRIFT.md`에 추가한다.
2. **hub.py의 쓰기 경로는 건드리지 않는다.** 새 코드는 `readings`·`occupancy`를 **읽기만** 한다. 예외는 `analysis`·`actuator_state`(신규) 테이블이며 analyst.py만 쓴다.
3. **한 Phase = 한 브랜치 = 한 PR.** `feat/phase-N-<slug>` → 완료 기준 통과 → main 머지 → 보드는 main만 pull. 머지마다 태그 `v0.N-phaseN`.
4. **보드에서 직접 편집하지 않는다.** 편집은 로컬, 배포는 `git pull`.
5. **검증은 명령 실행 결과로.** 검증 명령을 실제로 실행하고 출력을 PR 본문에 붙인다.
6. **보드에서 sudo가 필요한 명령(서비스 파일 편집·daemon-reload·restart·enable)은 Claude Code가 실행하지 못한다.** 명령을 **그대로 출력**하고 사용자가 실행한 뒤 결과를 붙여넣도록 요청한다. sudo 없이 되는 확인 명령(`systemctl is-active`, `journalctl -u … --no-pager`, `curl`)은 직접 실행한다.
7. `[ASK]` 표시는 사용자 결정 지점. 임의로 정하지 않는다.
8. 코드 주석·docstring·커밋 메시지는 영문. PR 본문과 이 문서는 한국어.
9. 보드 명령 규약: `Q: <cmd>` = `ssh q '<cmd>'`. uv는 `~/.local/bin/uv` 절대경로. DB 조회는 sqlite3 CLI가 없으므로 `Q: cd ~/multinode_aq/hub && .venv/bin/python -c "import sqlite3;print(sqlite3.connect('sensor_data.db').execute('''<SQL>''').fetchall())"` 형태(아래 `PYSQL "<SQL>"`로 줄여 쓴다).

---

## 1. 프로젝트 컨텍스트 (Phase 0에서 확정된 실물 — `docs/INVENTORY.md` 요약)

| 항목 | 실물 값 |
|---|---|
| 허브 | UNO Q, Debian 13 aarch64, headless. `ssh q`(arduino@aqhub, Tailscale). RAM 3.6 GB, 4코어 |
| 작업 디렉터리 | `~/multinode_aq` — **현재 평면**(hub.py가 루트). D-1 결정에 따라 `~/multinode_aq/hub/`로 이동 예정 |
| Python / uv | 3.13.5, `~/.local/bin/uv`(비로그인 PATH 밖). `.venv`에 numpy·pandas 3·plotly 6·**scikit-learn 1.9**·streamlit **1.58**·streamlit-autorefresh |
| 수집 | `hub.py` 단일 파일 = HiveMQ Cloud TLS 8883. 토픽 `multinode_aq/+/env`, `multinode_aq/+/occ`. 계정은 `secrets.env`(EnvironmentFile) |
| DB | `sensor_data.db` 15 MB, journal **delete**, **인덱스 없음**. `readings` 114k행/8노드, `occupancy` 16k행/5노드 |
| ts | UTC 문자열. `t`를 보내는 2노드만 5분 정각 버킷, **6노드는 수신시각(초 단위)** → 분석 전 5분 버킷 floor 필수 |
| 품질 | 센서 이상값이 그대로 저장됨(co2 0, temp −98 등). 환경 노드 2개(CLASS_01 D0C12C, CLASS_08 B80DC8) 현재 다운 |
| nodes.json | 16항목: 환경 8 + 비전 8, 같은 교실은 **같은 라벨**(CLASS_01~08)로 페어링 |
| 대시보드 | `dashboard.py` 1,081줄, 단일 페이지 6섹션(아래 §1.1). `.streamlit/config.toml` 없음 — 테마는 파일 내 CSS |
| 서비스 | `multinode_aq_hub.service`, `multinode_aq_dashboard.service` (`/etc/systemd/system/`). sudo는 비밀번호 필요 |
| 저장소 | `hub/` 하위 구조. `hub/hub_cloud.py`, `hub/en/*`는 보드에 없는 참고용 구버전 [ASK 정리 시점] |

### 1.1 dashboard.py 실물 구조와 갱신 비용 (Phase 1b·5의 근거)

`st_autorefresh(10 s)` → 매 10초 스크립트 전체 재실행. 재실행 1회당 일어나는 일:

| 섹션 | 데이터 | 캐시 | 재실행마다 하는 일 | 비용 |
|---|---|---|---|---|
| ① 노드 카드 | `load_df()` 최근 5,000행 | ttl 5s | 노드당 레이더 1개(최대 8 figure) | 낮음 |
| ② 전체 통계 | `load_all_for_stats()` **전체 테이블 114k행** | 데이터만 ttl 300s, **figure는 캐시 없음** | boxplot 6개(`go.Box(y=전체 배열)` → 6×114k 값 브라우저 전송), corr, 노드별 막대 2, pooled 레짐 산점도(`Histogram2d(x,y=114k)` → 원본 전송 후 브라우저가 히스토그램 계산) | **높음, 데이터 증가에 비례** |
| ③ 시계열 + 비전 | `df.tail(60)`, `load_occ_*` ttl 5s | — | 시계열 1 figure, 노드별 레짐 산점도(114k dfa에서 노드 필터·RobustScaling), 비전 crosshair `components.html` | 중간 |
| ④ 최근 5행 | df | — | dataframe 5행 | 낮음 |
| ⑤ 내보내기 | `load_df(limit=10_000_000)` ttl 5s **전체 테이블**, `load_merged_analysis()` ttl 60s **전체 readings+occupancy 조인**, `load_occ_all()` **캐시 없음**, `query_range(lo,hi)` **캐시 없음·기본값이 전체 기간** | 부분 | **네 번의 전체 테이블 읽기 + 네 번의 `to_csv()` + download_button에 CSV 바이트 임베드** → 10초마다 수십 MB를 생성해 브라우저로 전송 | **매우 높음 — 버벅임의 주범** |
| ⑥ 초기화 | COUNT(*) | — | — | 낮음 |

결론: 체감 지연은 레이더(①)가 아니라 **⑤ 내보내기 섹션의 상시 CSV 생성**과 **② 전체 이력 figure 재생성**에서 온다. 둘 다 "5분에 한 번 바뀌는 데이터를 10초마다 통째로 다시 만드는" 구조다.

분석 방법론의 근거: `docs/manual.html`의 "확장 과제 — CO₂·VOC 레짐 분석 & 제어" 절과 슬라이드 `실제분석사례_교실공기질`. 이 결정을 §2에 승계한다.

---

## 2. 설계 불변 조건 (변경하려면 [ASK])

**시간·버킷**
- 모든 분석은 `ts`를 **5분 floor**로 버킷팅한 뒤 시작한다(수신시각 노드 6개 때문). 같은 (node, bucket)에 2행이면 마지막 행. 이 규칙은 `aq/db.py` 한 곳에만 둔다.
- readings ↔ occupancy 조인은 (label, bucket) 기준. 비전 노드는 정각 버킷이므로 floor 후 정확 조인.

**데이터 품질**
- QC 게이트: 노드×일 CO₂ 유효율 < 95% → 그날 그 노드 분석 제외(행 삭제 없음).
- 범위 규칙 → NaN: CO₂ 350~5,000 ppm, 온도 −10~50 ℃, 습도 0~100 %, VOC index 1~500, PM ≥ 0 이고 < 1,000.
- **보간 금지.** CO₂·VOC 중 하나라도 NaN인 행은 GMM 학습·판정에서 제거.
- PM 4종 완전 공선 → 분석은 PM2.5만.

**레짐 모델**
- 입력 2축 고정 스케일: `co2/400`, `voc/100`. 데이터 의존 스케일러 금지(재학습 시 군집 뒤집힘). 현재 dashboard.py의 RobustScaling 산점도는 **표시용 탐색 도구**로만 존속하며 판정에 쓰지 않는다.
- `GaussianMixture(n_components=4, covariance_type="full", random_state=0, n_init=5)`.
- 라벨 앵커링: 군집 중심(μ_co2, μ_voc)을 기준선(co2 700 ppm → 1.75, voc 120 → 1.2)과 비교해 clean/matter/human/mixed로 매핑. 두 군집이 같은 분면이면 후보 폐기.
- 평활: rolling mode 창 9(45분), center=True, 결측 단절에서 창을 끊는다.
- 전이행렬: 연속 쌍의 시간차가 5분 ± 2분을 벗어나면 제외, 제외 수를 `gap_pairs`로 기록. 체류시간은 관측 하한(censored)으로 표기.

**규칙층**
- 환풍기 ON: regime ∈ {human, mixed} ∧ CO₂ > 1000 / OFF: CO₂ < 700
- 공기청정기 ON: regime ∈ {matter, mixed} ∧ VOC > 200 / OFF: VOC < 120
- 최소 동작 10분. 히스테리시스 상태는 `actuator_state`에 저장. QC 미달 노드는 "판정 보류", 규칙층도 돌리지 않는다.

**모델 거버넌스**
- 주 1회(일 06:30 UTC) 최근 28일로 후보 학습 → **저장만**. 승격 조건(둘 다): ① 4중심이 서로 다른 분면, ② 최근 7일 평균 로그우도 +2% 이상 **또는** 중심 이동 L2 최대 ≥ 0.25. 아니면 유지·사유 기록.
- `calendar.json` 경계일엔 강제 refit. 모델은 `models/gmm_vN.joblib` + `.json` 메타, `models/current` 심링크. 덮어쓰기 금지.

**대시보드 갱신 (Phase 1b에서 확정, 이후 유지)**
- 데이터 변화가 없으면 figure를 다시 만들지 않는다(갱신 키 = `MAX(id)` 또는 행 수).
- 전체 테이블을 브라우저로 보내는 요소는 없어야 한다(CSV는 요청 시 생성, 산점도는 서버 집계본만 전송).
- 대시보드 안에서 GMM fit/predict, 전체 이력 통계 계산을 하지 않는다(analyst.py 몫).

**LLM** — 판단 루프에 넣지 않는다. 도입은 Phase 7 이후 [ASK].

---

## 3. Phase 0 — 실물 파악과 현행화 ✅ 완료 (1b2bde0 이후)

산출물: `docs/INVENTORY.md`, `docs/DRIFT.md`, `hub/` 실물 교체, `hub/secrets.env.example`, `.gitignore`, systemd 유닛 복사.

### 3.1 남은 항목 — D-1 보드 레이아웃 [ASK → 권장 (A)]
보드 `~/multinode_aq`는 평면, 저장소는 `hub/` 하위라 그대로 추적하면 서비스 경로가 어긋난다. **(A) `~/multinode_aq/hub/`를 런타임 디렉터리로** 전환한다.

Claude Code가 수행(sudo 불필요):
```
Q: cd ~/multinode_aq && git init 2>/dev/null; git remote add origin <url> 2>/dev/null; git fetch origin
Q: cd ~/multinode_aq && git checkout -b main --track origin/main      # 평면 파일은 untracked로 남음
Q: cd ~/multinode_aq && git status --short                             # 예상: 평면 hub.py/dashboard.py/… 가 ?? 로 표시
```
사용자가 수행(출력해 줄 것 — 수집 공백 수 초):
```
sudo systemctl stop multinode_aq_hub multinode_aq_dashboard
cd ~/multinode_aq && mv .venv pyproject.toml uv.lock .python-version sensor_data.db hub/ 2>/dev/null
mv secrets.env hub/ 2>/dev/null; mkdir -p _phase0_backup && mv hub.py dashboard.py nodes.json *.bak *.save _phase0_backup/ 2>/dev/null
sudo sed -i 's#/home/arduino/multinode_aq/#/home/arduino/multinode_aq/hub/#g; s#WorkingDirectory=.*#WorkingDirectory=/home/arduino/multinode_aq/hub#' /etc/systemd/system/multinode_aq_{hub,dashboard}.service
sudo sed -i '/^\[Service\]/a EnvironmentFile=/home/arduino/multinode_aq/hub/secrets.env' /etc/systemd/system/multinode_aq_hub.service
sudo sed -i 's/multinode_aq.service/multinode_aq_hub.service/' /etc/systemd/system/multinode_aq_dashboard.service
sudo systemctl daemon-reload && sudo systemctl start multinode_aq_hub multinode_aq_dashboard
```
`_phase0_backup/`는 `.gitignore`에 추가. 저장소 `hub/systemd/*.service`도 같은 경로로 갱신해 커밋.

### 3.2 완료 기준
- [x] INVENTORY·DRIFT 존재, 비밀값 분리, 저장소 hub/ = 보드 실물
- [ ] D-1 적용 후: `Q: cd ~/multinode_aq && git status --short` 가 비어 있음(untracked는 `hub/.venv hub/sensor_data.db hub/secrets.env _phase0_backup` 뿐이며 모두 gitignore)
- [ ] `Q: systemctl is-active multinode_aq_hub multinode_aq_dashboard` 둘 다 active, `curl -s -o /dev/null -w '%{http_code}' localhost:8501` = 200
- [ ] 재기동 후 5분 내 새 행: `PYSQL "SELECT MAX(ts) FROM readings"`
- [ ] `git log -p origin/main | grep -i "hivemq.cloud\|MQTT_PASSWORD=" ` 에 실제 값 없음

---

## 4. Phase 1 — 워크플로우·하네스

**목표**: 이후 모든 Phase가 "로컬 편집 → CI → PR → main → 보드 pull → deploy"로 돌고, 위험 행동은 **지시가 아니라 메커니즘**으로 막힌다.

### 4.1 디렉터리 구조 (목표)
```
hub/
  hub.py                         # 변경 없음
  dashboard.py                   # Phase 1b 최적화 → Phase 5 페이지 1
  pages/2_diagnosis.py           # Phase 5
  aq/  __init__ config db qc regime rules governance forecast summary plots ui_common
  analyst.py  deploy.sh
  config/analyst.toml  calendar.json  nodes.json  secrets.env(.example)
  models/   systemd/   tests/   fixtures/sample.db
.claude/settings.json  .github/workflows/ci.yml  plan/  docs/
```

### 4.2 작업
1. `hub/aq/` 뼈대, `tests/`, `uv add --dev pytest pytest-cov ruff`.
2. **하네스** — 다음을 코드로 넣는다:
   - `.claude/settings.json`: `deny`에 `Bash(ssh q *sudo*)`, `Bash(ssh q *systemctl restart*)`, `Bash(ssh q *rm -rf*)`, `Bash(git push --force*)`; `allow`에 `Bash(uv run pytest*)`, `Bash(ssh q git *)`, `Bash(ssh q systemctl is-active*)`, `Bash(ssh q journalctl*)`.
   - `.github/workflows/ci.yml`: PR마다 `ruff`, `pytest`, `grep -rn "FROM readings\|FROM occupancy" hub/pages/`(결과 있으면 실패), `git diff origin/main -- hub/hub.py`(변경 있으면 실패), 비밀값 패턴 스캔.
   - `.git/hooks/pre-commit` 대신 `uv run pre-commit`은 쓰지 않고, Claude Code hooks(`PreToolUse` on `git commit` → `uv run pytest -q`)로.
3. `hub/deploy.sh`: `git pull --ff-only` → `~/.local/bin/uv sync --frozen` → `python -c "import aq, dashboard"` import 검사 → **재시작 명령은 출력만**(sudo). 인자 없으면 dry-run.
4. `tests/make_fixture.py`: 보드 DB에서 최근 30일, 노드 ID 익명화, **두 다운 노드와 E04537의 이상값 행을 그대로 포함**해 `fixtures/sample.db`(< 20 MB). 보드에서 실행 후 scp.
5. `readings(node, ts)`, `occupancy(node, ts)` 인덱스 생성 스크립트 `aq/db.py: ensure_indexes()` — **DDL이지만 스키마 변경이 아니므로 허용**. hub가 쓰는 중에도 안전(CREATE INDEX는 짧은 쓰기 락). 실행은 Phase 1b에서.

### 4.3 검증
```
uv run pytest -q ; uv run ruff check hub/
gh pr checks <n>                                   # CI 통과
Q: cd ~/multinode_aq/hub && ./deploy.sh            # dry-run: 변경 파일·재시작 대상 출력
Q: cd ~/multinode_aq/hub && git status --short     # clean
```
### 4.4 완료 기준
- [ ] CI가 PR에서 실제로 돌고, 일부러 `hub/hub.py`를 한 줄 바꾼 테스트 PR이 **실패**함(그 PR은 닫는다)
- [ ] `.claude/settings.json` deny 항목이 동작함(`ssh q sudo true` 시도가 차단되는 것을 로그로 확인)
- [ ] `fixtures/sample.db` 커밋, 테스트가 이를 사용

---

## 5. Phase 1b — 대시보드 갱신·렌더링 최적화 (핫픽스)

**목표**: 구조 변경 없이 현재 단일 페이지의 버벅임을 없앤다. Phase 5 리팩터 전에 **측정 가능한 기준**으로 체감을 해결하고, 그 결과를 Phase 5의 회귀 기준선으로 삼는다.

### 5.1 측정 먼저
- `dashboard.py` 상단에 `_t0 = perf_counter()`, 섹션 경계마다 `print(f"[perf] sec{n} {perf_counter()-_t0:.2f}s", file=sys.stderr)`. `journalctl -u multinode_aq_dashboard -f`로 한 사이클 기록 → PR에 "before" 표.
- 브라우저 DevTools Network에서 웹소켓 메시지 크기 1사이클 합계 기록(PC에서). 교실 태블릿에서도 체감 기록 [ASK].

### 5.2 변경 (우선순위 순, 각각 독립 커밋)
1. **⑤ 내보내기를 요청 시 생성으로.** 세 개의 상시 `download_button`을 없애고 `st.button("CSV 준비")` → 눌렀을 때만 쿼리·`to_csv` → `st.session_state["csv_all"]`에 보관 → 그 다음에 `download_button` 표시. `query_range`도 "조회" 버튼 뒤로. `load_df(limit=10_000_000)` 호출 제거. 초기화(⑥)의 백업 경로는 그대로.
2. **② figure 캐시.** `@st.cache_data(ttl=300)`로 감싼 `stats_figures(max_id, sel)`가 `load_all_for_stats()`를 내부에서 호출해 5개 figure를 반환. 캐시 키는 `PYSQL "SELECT MAX(id) FROM readings"`(1 ms) 값. 현재 위치(★) 마커는 캐시된 figure에 `add_trace`로 얹는다(figure는 `copy.deepcopy` 후).
3. **② 전송량.** boxplot은 pandas로 `q1/median/q3/lowerfence/upperfence`를 계산해 `go.Box(q1=…, median=…, q3=…, …)`로 전달(원본 배열 전송 0). pooled 산점도의 `Histogram2d`는 `np.histogram2d(24×24)`로 서버 집계 후 `go.Heatmap(z=…)`. `load_all_for_stats()`에 `WHERE ts >= datetime('now','-28 days')` 상한 [ASK 28일].
4. **갱신 주기.** `REFRESH_MS` 10 s → 60 s. Streamlit 1.58이므로 `st.fragment(run_every="60s")`로 ①·③·④만 부분 갱신하고 `st_autorefresh` 제거. ②는 5분 fragment. 사용자 조작(노드 선택)은 fragment 밖 상태로 유지.
5. **DB.** `ensure_indexes()` 1회 실행(Phase 1 §4.2.5). `PRAGMA journal_mode=WAL` 전환은 [ASK] — 승인 시 사용자가 hub 정지 없이 `PYSQL "PRAGMA journal_mode=WAL"` 1회 실행(이후 영구). 읽기 연결은 `sqlite3.connect("file:sensor_data.db?mode=ro", uri=True, timeout=5)`.
6. `use_container_width` deprecation 경고 정리(`width="stretch"`), dashboard 유닛의 잘못된 `After=` 수정(D-1에서 함께).

### 5.3 검증
```
# after 표: [perf] 로그 1사이클, 웹소켓 바이트 합계
Q: journalctl -u multinode_aq_dashboard --since -10min --no-pager | grep perf | tail -12
Q: journalctl -u multinode_aq_hub --since -1h --no-pager | grep -ci "locked"      # 0
PYSQL "SELECT name FROM sqlite_master WHERE type='index'"                          # 두 인덱스 존재
```
### 5.4 완료 기준
- [ ] 정상 사이클(데이터 변화 없음)의 서버 처리 시간 < 0.5 s, 웹소켓 전송 < 200 KB (before 대비 수치 첨부)
- [ ] 데이터 변화 사이클에서도 ⑤ 섹션의 전송량 0 (CSV 버튼을 누르기 전까지)
- [ ] 노드 선택 조작 시 화면이 통째로 깜빡이지 않음(fragment) — 사용자 확인 [ASK]
- [ ] 화면 구성·색·순서는 변경 전과 동일(스크린샷 비교)

---

## 6. Phase 2 — 데이터 계약

### 6.1 `analysis` 테이블 (analyst.py만 쓰기)
```sql
CREATE TABLE IF NOT EXISTS analysis (
  id INTEGER PRIMARY KEY, run_at TEXT NOT NULL, kind TEXT NOT NULL, scope TEXT,
  win_start TEXT, win_end TEXT, model_ver TEXT, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_analysis_kind_run ON analysis(kind, run_at);
CREATE TABLE IF NOT EXISTS actuator_state (node TEXT, device TEXT, state INTEGER, since TEXT, PRIMARY KEY(node, device));
```
kind별 payload 필수 키(`aq/schemas.py` TypedDict):
`qc`: valid_co2_pct, valid_voc_pct, rows, passed, reason ·
`regime_now`: regime, co2, voc, dwell_min, dwell_censored, trail ·
`band`: slots[{bucket, regime|null}] (시간 단위 mode) ·
`transition`: matrix, counts, gap_pairs, valid_pairs, dwell_median ·
`action`: device, state, rule, values, since, hold_until ·
`forecast`: horizon_min, co2_pred, voc_pred, alert ·
`occ_co2`: spearman_rho, n, slope_ppm_per_person, by_room ·
`model_event`: candidate_ver, decision, centroid_shift, loglik_delta, reason ·
`summary`: lines[]
### 6.2 `calendar.json` — [ASK] 실제 학사 일정. 형식: `{"periods":[{"name":"vacation","start":"2026-07-17","end":"2026-08-19"},{"name":"term","start":"2026-08-20","end":null}],"school_hours":{"start":"08:30","end":"17:00","days":[0,1,2,3,4]}}` (KST)
### 6.3 `config/analyst.toml` — §2의 모든 상수. 코드에 매직넘버 금지.
### 6.4 완료 기준
- [ ] `ensure_schema()` 픽스처·빈 DB 양쪽에서 두 번 실행 무오류
- [ ] schemas 테스트: kind별 샘플 통과, 필수 키 누락 실패
- [ ] `grep -rn "ALTER\|DROP\|DELETE FROM readings\|DELETE FROM occupancy" hub/aq` 결과 없음

---

## 7. Phase 3 — analyst.py 코어

| 모듈 | 함수 | 테스트로 보장 |
|---|---|---|
| db | `load_readings(start,end)`(5분 floor 포함), `load_occupancy`, `write` | 수신시각 행이 정각 버킷으로 정렬, ro 연결 |
| qc | `range_mask`, `daily_gate` | E04537 이상값 행 NaN, 다운 노드 게이트 탈락, 경계 95.0% 포함 |
| regime | `fit`, `anchor_labels`, `predict`, `smooth`, `transitions` | 4분면 1:1, random_state 재현, 결측 단절에서 창 끊김, Δt 초과 쌍 제외·gap_pairs |
| rules | `decide` | 1001→ON, 999→유지, 699→OFF, 10분 미만 OFF 불가, 제외 노드 hold |
| forecast | `fit_predict(horizon=30)` | 타깃 shift −6 실측, Pipeline 동일, 누수 없음 |
| occ_co2 | `spearman_by_room` | (label, bucket) 정확 조인, n≥25 필터 |
| summary | `lines` | 템플릿 문장 ≤ 5줄 |

CLI: `analyst.py run --mode hourly|daily|weekly [--as-of] [--db] [--dry-run]`, `fit --window 28`, `show --kind`. `--dry-run`은 저장 없이 JSON stdout — **모든 검증은 dry-run 출력으로**.

검증: `uv run pytest -q --cov=aq`(≥80%), 픽스처 dry-run에서 `gap_pairs>0`, QC 탈락 노드 존재, regime 이름 4종만; `scripts/plot_check.py`로 밴드·평면 PNG → 슬라이드 결과와 정성 비교 [ASK]. 보드: `Q: cd ~/multinode_aq/hub && /usr/bin/time -v .venv/bin/python analyst.py run --mode daily --dry-run` daily < 60 s, hourly < 15 s, RSS < 400 MB.
완료 기준: 위 전부 + **systemd 등록·analysis 실제 쓰기 없음**.

---

## 8. Phase 4 — 모델 거버넌스
`governance.py: compare / promote / rollback`. 초기 v1은 보드 실데이터 28일. 시나리오 테스트 4종(keep / promote / reject / rollback). `Q: … analyst.py fit --window 28 --dry-run` 후보 메타의 분면 매핑 4개 상이. 완료: 테스트 통과, v1 메타 JSON 커밋, `models/current` 존재.

---

## 9. Phase 5 — 대시보드 2페이지 리팩터

목표 레이아웃: `plan/dashboard_mockup.html`(v2). 페이지 1은 Phase 1b 결과의 **성능 기준선을 유지**한 채 구조만 바꾼다.

### 9.1 순서
1. 테마 상수·`METRICS`·`NODE_PALETTE`·DB 헬퍼·레이더·시계열·비전 패널을 `aq/ui_common.py`로 **이동만**. 스크린샷 비교.
2. 페이지 1에서 ②의 corr 히트맵·pooled 레짐 산점도, ③의 노드별 레짐 산점도를 제거. ②는 boxplot + CO₂/VOC 노드별 막대만 남김. 비전 crosshair는 ③에 유지.
3. `pages/2_diagnosis.py` 신설 — 섹션 A~H(목업 순서). 데이터는 **`analysis` 테이블만** 읽음. `run_every="5m"` fragment. RobustScaling 산점도 2종은 H "탐색 시각화"로 옮기되 analyst.py가 저장한 집계본을 그린다.
4. `analysis` 비었을 때 안내 화면(오류 아님).
5. 사이드바에 서비스 상태(hub 최신 행 시각, analyst 마지막 run_at, 모델 버전).
### 9.2 검증·완료 기준
- [ ] 페이지 1 `[perf]` 수치가 Phase 1b 기준선 이하, 시각 회귀 없음 [ASK]
- [ ] 페이지 2 빈/채운 analysis 양쪽 렌더, `grep -n "FROM readings\|FROM occupancy" hub/pages/` 결과 없음(CI 강제)
- [ ] 페이지 전환 시 선택 상태 유지, 10초 깜빡임 없음

---

## 10. Phase 6 — 스케줄링·배포
타이머 3개(`hourly *:05`, `daily 06:00`, `weekly Sun 06:30`, 모두 UTC·oneshot·`TimeoutStartSec=300`·`EnvironmentFile` 불필요). hub/dashboard 유닛은 수정하지 않는다. 유닛 파일 설치·enable은 **사용자가 실행**(명령 출력). WAL은 Phase 1b에서 끝났어야 하며 아니면 여기서 [ASK].
검증: `Q: systemctl list-timers 'multinode_aq*' --no-pager`, 수동 1회 `sudo systemctl start …daily`(사용자) 후 `PYSQL "SELECT kind,COUNT(*),MAX(run_at) FROM analysis GROUP BY kind"`, hub 로그 `locked` 0, 5분 내 새 readings 행.

---

## 11. Phase 7 — 48h 운영 검증·문서
hourly 성공 48±1, 5분 판정 대비 평활 판정 전이 수 비율, `actuator_state` 재시작 후 유지, `systemd-cgtop` 3회. 문서: manual.html "10) 분석 서비스" 절, README(경로·토픽·서비스명 DRIFT 반영), `docs/DECISIONS.md`. LLM 요약 도입 여부 [ASK].

---

## 부록 A — 롤백
`Q: cd ~/multinode_aq && git checkout v0.N-phaseN && hub/deploy.sh` 후 재시작 명령은 사용자. `DELETE FROM analysis`는 수집·표시 무영향. `analyst.py model rollback --to vN`.
## 부록 B — 금지 목록
readings/occupancy 스키마·행 변경 · hub.py 로직 수정 · 데이터 의존 스케일러/보간/k≠4/노드ID·시간대 GMM 입력 · 보드 직접 편집 · force push · 비밀값 커밋 · 대시보드 내 GMM fit/predict · 전체 테이블 CSV 상시 생성 · `.venv`/DB 이동을 사용자 승인 없이.
## 부록 C — PR 본문 템플릿
```
## Phase N — <제목>
### 변경
### 검증 출력 (명령 + 결과)
### 완료 기준 체크
### DRIFT / ASK
```

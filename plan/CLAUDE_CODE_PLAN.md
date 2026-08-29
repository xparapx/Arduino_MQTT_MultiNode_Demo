# multinode_aq — 하이브리드 분석·진단 확장 작업 지침

> 대상: Claude Code. 이 문서는 **작업 순서·검증 기준·금지 사항**을 정의한다.
> 각 Phase는 "완료 기준"을 모두 통과해야 다음 Phase로 넘어간다. 통과하지 못하면 멈추고 사용자에게 보고한다.

---

## 0. 작업 원칙 (모든 Phase 공통)

1. **추측 금지.** 파일 경로·토픽명·테이블 스키마·서비스명은 반드시 실물을 읽어 확인한 뒤 사용한다. 문서(README·manual.html)와 보드 실물이 다르면 **보드 실물이 정답**이고, 차이를 `docs/DRIFT.md`에 기록한다.
2. **hub.py의 쓰기 경로는 건드리지 않는다.** 수집 파이프라인(MQTT → readings/occupancy INSERT)은 이 작업의 범위 밖이다. 새 코드는 DB를 **읽기만** 한다. 단 하나의 예외는 `analysis` 테이블(신규)에 대한 쓰기이며, 이는 analyst.py만 수행한다.
3. **한 Phase = 한 브랜치 = 한 PR.** `feat/phase-N-<slug>` 브랜치에서 작업하고, 완료 기준 통과 후 main에 머지한다. 보드에는 main만 pull한다.
4. **보드에서 직접 편집하지 않는다.** 모든 편집은 로컬 저장소에서, 배포는 `git pull`로만. Phase 0 이후 보드의 작업 디렉터리는 항상 clean이어야 한다.
5. **검증은 명령 실행 결과로.** "될 것 같다"는 완료가 아니다. 각 Phase의 검증 명령을 실제로 실행하고 출력을 PR 본문에 붙인다.
6. **서비스 재시작 전에 반드시** `python -c "import <module>"` 수준의 import 검사와 `--dry-run`(있으면)을 통과시킨다. 대시보드가 죽으면 교실 화면이 꺼진다.
7. **사용자 확인이 필요한 결정**은 Phase 본문에 `[ASK]`로 표시했다. 임의로 정하지 말고 질문한다.
8. 코드 주석·docstring·커밋 메시지는 영문(보드 붙여넣기 시 한글 깨짐 이슈가 있었음). PR 본문과 이 문서는 한국어.

---

## 1. 프로젝트 컨텍스트 (사전 지식 — Phase 0에서 실물로 재확인)

| 항목 | 알려진 값 | 확인 필요 |
|---|---|---|
| 허브 | Arduino UNO Q, Debian 계열, headless, SSH 운용, App Lab 미사용 | OS/arch: `uname -a`, `cat /etc/os-release` |
| 작업 디렉터리 | `~/multinode_aq` (README는 `multinode_sensor_demo`로 기재 — **불일치**) | 실물 경로 |
| Python 환경 | uv 가상환경 `.venv`, 의존성 paho-mqtt pandas plotly streamlit streamlit-autorefresh | `pyproject.toml`, `uv.lock` 존재 여부 |
| 수집 | `hub.py`(로컬 mosquitto) 또는 `hub_cloud.py`(HiveMQ TLS 8883) | 어느 쪽이 서비스에 등록됐는지 |
| MQTT 토픽 | `multinode_aq/+/env`, `multinode_aq/+/occ` (README는 `multinode_sensor_demo/...`) | hub 소스의 TOPIC 상수 |
| DB | `sensor_data.db` (SQLite). 테이블 `readings`(11변수 + n), `occupancy`(occ/occ_med/occ_max/occ_last/c/w/n) | `.schema` 출력 |
| 시각 | `t` = UTC, 5분 버킷, NTP 정각 정렬 | 샘플 행의 ts 형식 |
| 대시보드 | `dashboard.py` 단일 페이지 5섹션, `nodes.json` 이름표, `.streamlit/config.toml` 다크 테마 | 현재 섹션 구성 (②에 히트맵·레짐 산점도 있음) |
| 서비스 | `multinode_aq_hub.service`, `multinode_aq_dashboard.service` (README는 `multinode_sensor_demo_*`) | `systemctl list-units 'multinode*'` |
| 노드 | 환경 노드 최대 8, 비전 노드(Nicla Vision FOMO) 일부 | `SELECT DISTINCT node FROM readings` |

분석 방법론의 근거 문서: `docs/manual.html`의 "확장 과제 — CO₂·VOC 레짐 분석 & 제어" 절, 그리고 슬라이드 `실제분석사례_교실공기질`. 이 두 문서의 결정을 **설계 불변 조건(§2)**으로 승계한다.

---

## 2. 설계 불변 조건 (변경하려면 [ASK])

**데이터 품질**
- QC 게이트: 노드×일 단위 CO₂ 유효율 < 95% → 그날 그 노드는 분석 제외 (DB 행은 삭제하지 않음).
- 범위 규칙: CO₂ 350~5,000 ppm, 온도 −10~50 ℃ 이탈 → NaN. VOC index 1~500 밖 → NaN.
- **보간 금지.** CO₂·VOC 중 하나라도 NaN인 행은 GMM 학습·판정에서 제거.
- PM 4종은 완전 공선 → 분석에는 PM2.5만.

**레짐 모델**
- 입력 2축만: `co2/400`, `voc/100` (외기 기준 **고정 스케일**). 데이터 의존 스케일러(Standard/Robust) 금지 — 재학습 시 군집이 뒤집힌다.
- `GaussianMixture(n_components=4, covariance_type="full", random_state=0, n_init=5)`.
- **라벨 앵커링**: 학습 후 각 군집 중심 (μ_co2, μ_voc)을 기준선(co2 = 700ppm → 1.75, voc = 120 → 1.2)과 비교해 4분면에 매핑. 이름 = clean / matter / human / mixed. 두 군집이 같은 분면에 떨어지면 **모델 후보 폐기** 후 경고.
- 평활: rolling mode, 창 = 9 (45분), center=True. 결측 단절 지점에서 창을 끊는다.
- 전이행렬: 연속 쌍의 실제 시간차가 5분 ± 2분을 벗어나면 **쌍에서 제외**. 제외된 수를 `gap_pairs`로 기록.
- 체류시간은 "관측 하한(censored)"으로 표기.

**규칙층 (행동지침)**
- 환풍기 ON: regime ∈ {human, mixed} ∧ CO₂ > 1000 / OFF: CO₂ < 700
- 공기청정기 ON: regime ∈ {matter, mixed} ∧ VOC > 200 / OFF: VOC < 120
- 최소 동작시간 10분. 히스테리시스 상태는 `analysis` 테이블에 저장하여 재시작 후에도 유지.
- 제외 노드(QC 미달)는 행동지침 "판정 보류". 규칙층도 돌리지 않는다.

**모델 거버넌스**
- 재학습 주기: 주 1회(일요일 06:00), 학습 창 = 최근 28일.
- 후보 모델은 **저장만** 한다. 승격 조건 (둘 다 만족): ① 4개 중심이 각각 서로 다른 분면, ② 최근 7일 데이터에 대한 평균 로그우도가 현행 모델 대비 +2% 이상 **또는** 중심 이동 L2 최대값 ≥ 0.25. 아니면 현행 유지, 사유 기록.
- `calendar.json`의 기간 경계(학기/방학) 도달 시 강제 refit + 승격 검토.
- 모델 파일은 `models/gmm_vN.joblib` + `models/gmm_vN.json`(메타: 학습 창, 중심, 분면 매핑, 지표). `models/current` 심링크가 운영 모델. 버전은 절대 덮어쓰지 않는다.

**LLM**
- 판단 루프에 넣지 않는다. 사용한다면 "이번 주 핵심 요약" 문장 생성 **한 곳**만이며 Phase 7 이후 [ASK].

---

## 3. Phase 0 — 실물 파악과 현행화 (보드 → Git)

**목표**: 보드에서 실제로 돌고 있는 코드를 Git의 정본으로 만든다. 문서와의 괴리를 기록한다.

### 3.1 실행 환경 확인
Claude Code가 어디서 실행되는지 먼저 판별한다.
- 보드에서 직접 실행 중이면 `$HOME/multinode_aq`가 존재해야 한다.
- 개발 PC에서 실행 중이면 SSH 별칭이 필요하다. [ASK] 호스트명·사용자·키. `~/.ssh/config`에 `Host q` 항목을 만들고 `ssh q true`로 확인.
이후 이 문서의 `Q:` 접두 명령은 보드에서 실행함을 뜻한다.

### 3.2 인벤토리 수집 (읽기만)
```
Q: uname -a; cat /etc/os-release | head -3; python3 --version; which uv; uv --version
Q: ls -la ~/multinode_aq; cat ~/multinode_aq/pyproject.toml
Q: systemctl list-units --type=service 'multinode*' --all; systemctl cat multinode_aq_hub multinode_aq_dashboard 2>/dev/null || systemctl cat 'multinode*'
Q: sqlite3 ~/multinode_aq/sensor_data.db ".schema"
Q: sqlite3 ~/multinode_aq/sensor_data.db "SELECT node, COUNT(*), MIN(ts), MAX(ts) FROM readings GROUP BY node;"
Q: sqlite3 ~/multinode_aq/sensor_data.db "SELECT COUNT(*) FROM occupancy;" 2>&1
Q: grep -n 'TOPIC\|BROKER\|DB ' ~/multinode_aq/hub*.py
Q: cat ~/multinode_aq/nodes.json; cat ~/multinode_aq/.streamlit/config.toml
Q: free -m; df -h ~; nproc
```
결과를 `docs/INVENTORY.md`로 정리한다 (비밀번호·브로커 계정은 **마스킹**).

### 3.3 Git 현행화
1. 로컬에서 GitHub 저장소 clone. 보드의 `hub/` 상당 파일(`hub*.py`, `dashboard.py`, `nodes.json`, `.streamlit/`, `systemd/*.service`, `pyproject.toml`, `uv.lock`)을 `scp`/`rsync`로 가져와 저장소의 `hub/`에 **덮어쓴다**.
2. `git diff --stat`로 문서 코드와 실물 코드의 차이를 확인하고 `docs/DRIFT.md`에 요약(어떤 파일이, 어떤 방향으로 달랐는지).
3. `.gitignore`에 추가: `sensor_data.db`, `*.db-journal`, `.venv/`, `models/*.joblib`, `backup_*.csv`, `hub/secrets.env`.
4. **첫 커밋 전에** 비밀값을 제거한다. `hub_cloud.py`의 브로커 계정을 `hub/secrets.env`(gitignore) + `os.environ` 읽기로 분리한다(로직 변경은 그 줄들뿐). `git add` 전에 `grep -rn "password\|passwd\|MQTT_PASS" hub/`로 남은 값이 없음을 확인. 공개 저장소 히스토리에 한 번 들어가면 되돌리기 어렵다.
5. 커밋·푸시: `chore(phase0): sync board code as source of truth`.
6. 보드를 git 작업 트리로 전환한다. **폴더를 지우고 clone하지 않는다** (`.venv`·`sensor_data.db`가 그 안에 있다).
   ```
   Q: cd ~/multinode_aq && git init && git remote add origin <url> && git fetch origin
   Q: git diff --stat origin/main        # 비밀값 줄 외에 차이가 없어야 함. 있으면 3~5 재수행
   Q: git checkout -b main --track origin/main
   Q: git status                          # untracked = sensor_data.db, .venv, secrets.env 만
   ```
   `secrets.env`를 보드에 생성(값은 기존 hub_cloud.py에서 옮김). hub 서비스는 env 파일을 읽도록 `EnvironmentFile=` 한 줄만 추가 후 재시작 — 이 재시작은 Phase 0에서 유일하게 허용되는 서비스 조작이며, 재시작 후 5분 내 새 행 유입을 확인한다.

### 3.4 완료 기준
- [ ] `docs/INVENTORY.md`, `docs/DRIFT.md` 존재
- [ ] 저장소 `hub/` 파일이 보드 실물과 `diff -r`로 동일 (비밀값 제외)
- [ ] 토픽명·서비스명·경로의 정본 값이 INVENTORY에 확정됨
- [ ] `readings`의 노드별 행 수·기간, `occupancy` 유무가 확인됨
- [ ] 보드 `~/multinode_aq`가 main을 추적하는 git 트리이고 `git status`가 clean (untracked 3종 제외)
- [ ] `git log -p origin/main | grep -i pass` 결과 없음

---

## 4. Phase 1 — 저장소 구조와 배포 워크플로우

**목표**: 이후 모든 Phase가 "로컬 편집 → PR → main → 보드 pull → 서비스 재시작"으로 돌아가게 한다.

### 4.1 디렉터리 구조 (목표)
```
hub/
  hub.py  hub_cloud.py            # 변경 없음
  dashboard.py                    # Phase 5에서 page 1로 축소
  pages/2_diagnosis.py            # Phase 5
  aq/                             # 신규 패키지 (분석 로직, 대시보드와 공유)
    __init__.py  config.py  db.py  qc.py  regime.py  rules.py  governance.py  plots.py
  analyst.py                      # Phase 3. CLI 진입점
  config/analyst.toml  calendar.json  nodes.json
  models/                         # gitignore (joblib) / json 메타는 커밋
  systemd/*.service  *.timer
  tests/  fixtures/sample.db
docs/  firmware/
```

### 4.2 작업
1. `hub/aq/` 패키지 뼈대와 `tests/` 생성. pytest 추가: `uv add --dev pytest`.
2. `hub_cloud.py`의 브로커 계정을 `hub/secrets.env`(gitignore) + `python-dotenv`로 분리. **단, 로직 변경은 계정 읽는 3줄뿐.** 보드에 `secrets.env`를 수동 배치 [ASK 값].
3. 배포 스크립트 `hub/deploy.sh`: `git pull --ff-only` → `uv sync` → import 검사 → `systemctl restart` 대상만 재시작. 인자 없이 실행하면 dry-run.
4. 픽스처 DB 생성 스크립트 `tests/make_fixture.py`: 보드 DB에서 **최근 30일, 노드 이름 익명화** 후 `fixtures/sample.db`로. 크기 < 20MB. 결측·고착·노드다운 구간이 포함돼야 한다 (없으면 인위 삽입하고 주석).

### 4.3 검증
```
uv run pytest -q                      # 뼈대 테스트 통과
Q: cd ~/multinode_aq && git status    # clean
Q: ./deploy.sh                        # dry-run 출력에 hub/dashboard 재시작 예정 없음
Q: ./deploy.sh --apply && systemctl is-active multinode_aq_hub multinode_aq_dashboard
Q: curl -s -o /dev/null -w '%{http_code}' http://localhost:8501   # 200
Q: sqlite3 sensor_data.db "SELECT MAX(ts) FROM readings"           # 재배포 후 5분 이내 새 행 유입
```

### 4.4 완료 기준
- [ ] 보드가 `git pull`만으로 갱신되고, 두 서비스가 재배포 후 정상
- [ ] 비밀값이 저장소에 없음 (`git log -p | grep -i password` 없음)
- [ ] `fixtures/sample.db`가 커밋되어 있고 테스트가 이를 사용

---

## 5. Phase 2 — 데이터 계약

**목표**: analyst.py와 대시보드가 공유할 저장 형식을 코드보다 먼저 확정한다.

### 5.1 `analysis` 테이블 (sensor_data.db 내, analyst.py만 쓰기)
```sql
CREATE TABLE IF NOT EXISTS analysis (
  id        INTEGER PRIMARY KEY,
  run_at    TEXT NOT NULL,        -- UTC ISO
  kind      TEXT NOT NULL,        -- qc | regime_now | band | transition | action | forecast | model_event | summary
  scope     TEXT,                 -- node id or 'all'
  win_start TEXT, win_end TEXT,   -- analysis window (UTC)
  model_ver TEXT,                 -- e.g. v7 (NULL for qc)
  payload   TEXT NOT NULL         -- JSON
);
CREATE INDEX IF NOT EXISTS ix_analysis_kind_run ON analysis(kind, run_at);
CREATE TABLE IF NOT EXISTS actuator_state (      -- hysteresis memory
  node TEXT, device TEXT, state INTEGER, since TEXT, PRIMARY KEY(node, device)
);
```
payload 스키마는 `hub/aq/schemas.py`에 `TypedDict`로 명시하고, 대시보드는 그 키만 읽는다. 각 kind별 필수 키:
- `qc`: `valid_co2_pct, valid_voc_pct, rows, passed(bool), reason`
- `regime_now`: `regime, co2, voc, dwell_min, dwell_censored(bool), trail[[co2,voc,ts]…]`
- `band`: `slots[{ts, regime|null}]` (시간 단위 mode)
- `transition`: `matrix[4][4], counts[4][4], gap_pairs, valid_pairs, dwell_median{regime:min}`
- `action`: `device, state, rule, values{co2,voc}, since, hold_until`
- `forecast`: `horizon_min, co2_pred, voc_pred, alert(bool)`
- `model_event`: `candidate_ver, decision(promote|keep|reject), centroid_shift, loglik_delta, reason`
- `summary`: `lines[str]` (결정론적 템플릿 문장)

### 5.2 `calendar.json`
```json
{"periods":[{"name":"vacation","start":"2026-07-17","end":"2026-08-19"},
            {"name":"term","start":"2026-08-20","end":null}],
 "school_hours":{"start":"08:30","end":"17:00","days":[0,1,2,3,4]}}
```
[ASK] 실제 학사 일정.

### 5.3 `config/analyst.toml`
QC 임계·스케일 상수·규칙 임계·히스테리시스·refit 주기·승격 조건을 전부 여기에. 코드에 매직넘버 금지. §2 값으로 초기화.

### 5.4 검증·완료 기준
- [ ] `aq/db.py`의 `ensure_schema()`가 픽스처 DB와 빈 DB 양쪽에서 idempotent (두 번 실행해도 오류 없음)
- [ ] `schemas.py`에 대한 테스트: 각 kind 샘플 payload가 검증 통과, 필수 키 누락 시 실패
- [ ] readings·occupancy 테이블에 대한 ALTER/DROP이 코드베이스 어디에도 없음 (`grep -rn "ALTER\|DROP" hub/aq`)

---

## 6. Phase 3 — analyst.py 코어

**목표**: 픽스처 DB에서 슬라이드의 분석 결과와 **같은 종류의 산출물**을 재현하는 배치 분석기.

### 6.1 모듈별 사양과 단위 테스트
| 모듈 | 함수 | 테스트로 보장할 것 |
|---|---|---|
| `db.py` | `load_readings(start,end)`, `load_occupancy`, `write(kind, …)` | UTC 파싱, 읽기 전용 연결(`?mode=ro`), 5분 버킷 정렬 |
| `qc.py` | `range_mask`, `daily_gate(df) -> DataFrame[node,date,valid_pct,passed]` | 30~70ppm 고착 노드가 탈락, 99% 노드 통과, 게이트 경계 95.0% 포함 |
| `regime.py` | `fit(df)->Model`, `anchor_labels(model)->dict`, `predict(model, df)`, `smooth(series, gaps)` | 라벨이 4분면에 1:1 매핑, 같은 데이터 두 번 fit해도 이름이 같음(random_state), 결측 단절에서 평활 창이 끊김 |
| `regime.py` | `transitions(series, ts) -> matrix, counts, gap_pairs` | 시간차 7분 초과 쌍이 제외되고 gap_pairs에 집계, 행 합 = 1 |
| `rules.py` | `decide(regime, co2, voc, prev_state, now) -> Action` | 1001→ON, 999→유지(ON 상태면), 699→OFF, 10분 미만은 OFF 불가, 제외 노드는 hold |
| `forecast.py` | `fit_predict(df, horizon=30)` | 타깃이 미래 실측값(shift −6), 학습·추론에 같은 Pipeline, 테스트는 형상과 누수 없음만 |
| `summary.py` | `lines(results) -> list[str]` | 템플릿 문장, 숫자 포맷, 최대 5줄 |

### 6.2 CLI
```
analyst.py run  --mode hourly|daily|weekly [--as-of ISO] [--db PATH] [--dry-run]
analyst.py fit  --window 28 [--promote-if-ok]
analyst.py show --kind regime_now
```
- `hourly`: QC(오늘), regime_now, action, forecast → 저장
- `daily`: band(28일), transition(28일), summary
- `weekly`: fit 후보 → governance 판단(Phase 4)
- `--dry-run`: 저장하지 않고 payload를 stdout에 JSON으로. **모든 검증은 dry-run 출력으로 한다.**
- 실패 시 exit code ≠ 0, 로그는 stderr, 부분 결과라도 kind 단위로 원자적 저장(트랜잭션).

### 6.3 검증 (픽스처)
```
uv run pytest -q tests/                                # 전부 통과
uv run python analyst.py run --mode daily --db fixtures/sample.db --dry-run > /tmp/daily.json
jq '.transition.gap_pairs, .transition.valid_pairs' /tmp/daily.json   # gap_pairs > 0 (픽스처에 결측 있음)
jq '.qc[] | select(.passed==false)' /tmp/daily.json                   # 고착/다운 노드가 제외됨
jq '.regime_now[].regime' /tmp/daily.json | sort | uniq -c            # 4개 이름만 등장
```
추가로 **사람 눈 검증**: `scripts/plot_check.py`로 픽스처의 밴드·평면 PNG를 `/tmp`에 저장하고, 슬라이드의 형태(방학 전후 인체 레짐 소멸, 물질 레짐 잔존)와 정성적으로 일치하는지 PR에 첨부해 사용자 확인 [ASK].

### 6.4 성능 기준 (보드)
```
Q: time uv run python analyst.py run --mode daily --dry-run
```
- daily 60초 이내, hourly 15초 이내, 최대 RSS < 400MB (`/usr/bin/time -v`). 초과 시 리샘플 단계를 SQL로 내리는 것을 먼저 시도.

### 6.5 완료 기준
- [ ] 단위 테스트 전부 통과, 커버리지 `aq/` 80% 이상
- [ ] 픽스처 dry-run 산출물이 §5.1 스키마 검증 통과
- [ ] 보드에서 daily/hourly dry-run이 시간·메모리 기준 통과
- [ ] 아직 **systemd 등록·analysis 테이블 실제 쓰기 없음** (Phase 6에서)

---

## 7. Phase 4 — 모델 거버넌스

**목표**: 재학습이 레짐 정의를 몰래 바꾸지 못하게 한다.

### 7.1 작업
- `governance.py`: `compare(current, candidate, recent7d) -> Decision`, `promote(candidate)`(심링크 교체 + model_event 기록), `rollback(ver)`.
- `models/gmm_vN.json` 메타에 반드시: 학습 창, 행 수, 4 중심(원 스케일 ppm/idx로도), 분면 매핑, 가중치, 최근7일 로그우도, 이전 버전 대비 shift.
- 초기 모델 v1: 픽스처가 아니라 **보드 실데이터 최근 28일**로 학습. 학습 창에 학기·방학이 섞여 있어도 GMM은 무방(레짐은 상태이지 기간이 아님) — 단 메타에 창 구성 기록.
- `calendar.json` 경계일에는 weekly 스케줄과 무관하게 fit 실행.

### 7.2 검증
```
uv run pytest tests/test_governance.py
# 시나리오 테스트: (a) 동일 데이터 → keep, (b) 중심 하나를 인위 이동한 후보 → promote,
#                 (c) 두 군집이 같은 분면 → reject, (d) rollback 후 current가 이전 버전
Q: uv run python analyst.py fit --window 28 --dry-run     # 실데이터 후보 메타 출력, 분면 매핑 4개 모두 상이
```

### 7.3 완료 기준
- [ ] 위 4 시나리오 테스트 통과
- [ ] 보드 실데이터 v1 메타 JSON이 저장소에 커밋됨 (joblib은 보드 로컬)
- [ ] `models/current` 심링크 존재, `analyst.py show --kind model_event`가 v1 생성 이벤트를 출력

---

## 8. Phase 5 — 대시보드 2페이지 리팩터

**목표**: 목업(`docs/dashboard_mockup.html`)의 구조를 Streamlit 멀티페이지로. 페이지 1은 **회귀 없이** 유지.

### 8.1 작업 순서 (중요 — 이 순서로)
1. `dashboard.py`에서 테마 상수·DB 헬퍼·노드 색상·게이지 함수를 `aq/ui_common.py`로 **이동만** (동작 변화 없음). 이동 후 페이지 1 스크린샷을 이전과 비교.
2. 페이지 1에서 ②의 상관 히트맵·레짐 산점도를 제거. 나머지는 그대로.
3. `pages/2_diagnosis.py` 신설. 섹션 A~G는 목업과 동일 순서. **데이터는 오직 `analysis` 테이블**에서 읽는다 (readings를 직접 읽어 계산하지 않는다 — 계산은 analyst.py 몫). 자동갱신은 5분.
4. `analysis`가 비어 있을 때의 빈 화면: "analyst.py가 아직 실행되지 않았습니다 — `analyst.py run --mode daily`" 안내. 오류가 아니라 안내.
5. 페이지 2 상단 A 블록(유효 범위)은 접히지 않는 고정 영역.
6. `.streamlit/config.toml`의 테마를 두 페이지가 공유하는지 확인.

### 8.2 검증
```
uv run streamlit run hub/dashboard.py --server.headless true &   # 로컬, 픽스처 DB 지정 (env AQ_DB)
# 브라우저 또는 playwright로 두 페이지 스크린샷 → docs/screens/ 에 저장
# 페이지 1: 이전 커밋 스크린샷과 시각 비교(레이아웃·색·게이지 6개)
# 페이지 2: 픽스처 dry-run 결과를 analysis 테이블에 임시 적재한 뒤 A~G가 모두 렌더링
Q: 배포 후 curl 200, 10분간 journalctl -u multinode_aq_dashboard -f 에 Traceback 없음
```

### 8.3 완료 기준
- [ ] 페이지 1 시각 회귀 없음 (사용자 확인 [ASK])
- [ ] 페이지 2가 빈 analysis / 채워진 analysis 양쪽에서 예외 없이 렌더
- [ ] 페이지 2는 readings/occupancy를 읽지 않음 (`grep -n "FROM readings" pages/` 결과 없음)
- [ ] 10초 자동갱신이 페이지 2 재계산을 유발하지 않음 (페이지 2는 별도 스크립트이므로 구조적으로 보장 — 확인만)

---

## 9. Phase 6 — 스케줄링과 배포

**목표**: analyst.py를 세 번째 서비스로 무인 운영.

### 9.1 systemd
- `multinode_aq_analyst_hourly.service` + `.timer` (`OnCalendar=*:05`, `RandomizedDelaySec=60`)
- `multinode_aq_analyst_daily.service` + `.timer` (`OnCalendar=*-*-* 06:00`)
- `multinode_aq_analyst_weekly.service` + `.timer` (`OnCalendar=Sun 06:30`)
- 세 서비스 모두 `Type=oneshot`, `User=arduino`, `WorkingDirectory`·`ExecStart` 절대경로 한 줄, `TimeoutStartSec=300`.
- hub/dashboard 서비스 파일은 **수정하지 않는다.**

### 9.2 SQLite 동시성
- hub.py는 계속 INSERT 중. analyst.py는 `PRAGMA journal_mode` 확인 후, WAL이 아니면 [ASK] 후 WAL 전환(1회, hub 정지 없이 가능하나 확인 후). `busy_timeout=5000`.
- analysis 쓰기는 짧은 트랜잭션으로. 읽기는 `mode=ro`.

### 9.3 검증
```
Q: ./deploy.sh --apply
Q: sudo systemctl enable --now multinode_aq_analyst_{hourly,daily,weekly}.timer
Q: systemctl list-timers 'multinode_aq*'
Q: sudo systemctl start multinode_aq_analyst_daily.service && journalctl -u multinode_aq_analyst_daily -n 50
Q: sqlite3 sensor_data.db "SELECT kind, COUNT(*), MAX(run_at) FROM analysis GROUP BY kind"
Q: sqlite3 sensor_data.db "SELECT MAX(ts) FROM readings"   # 분석 실행 중에도 수집 끊김 없음 (5분 내 새 행)
```

### 9.4 완료 기준
- [ ] 세 타이머 활성, 수동 1회 실행 성공, analysis 테이블에 kind별 행 존재
- [ ] 실행 중 hub INSERT 지연·오류 없음 (journalctl -u hub에 `database is locked` 없음)
- [ ] 대시보드 페이지 2가 실데이터 결과를 표시

---

## 10. Phase 7 — 운영 검증(48h)과 문서

### 10.1 48시간 soak
- 매 hourly 실행이 성공했는지: `journalctl -u multinode_aq_analyst_hourly --since -48h | grep -c "run ok"` = 48 ± 1
- `regime_now`의 레짐 이름이 시간에 따라 튀지 않는지(채터링): 5분 판정 대비 평활 판정의 전이 수 비율 기록
- 행동지침 히스테리시스가 재시작 후 유지되는지: hourly 서비스 사이에 `actuator_state` 값 확인
- 메모리·CPU: `systemd-cgtop` 스냅샷 3회

### 10.2 문서
- `docs/manual.html`에 "10) 분석 서비스 — analyst.py" 절 추가 (설치·타이머·config·모델 이력 읽는 법). 기존 절 번호 유지.
- `README.md`: 폴더 구조·서비스 표에 analyst 추가, 토픽/서비스명 불일치 수정(Phase 0 DRIFT 반영).
- `docs/DECISIONS.md`: §2 불변 조건과 그 근거(슬라이드 페이지 참조)를 옮겨 적는다.

### 10.3 완료 기준
- [ ] 48h 지표가 PR에 첨부되고 사용자 승인 [ASK]
- [ ] 문서 3종 갱신
- [ ] 이 시점에서 LLM 요약 도입 여부를 사용자에게 질문 (도입 시 별도 Phase 8)

---

## 부록 A — 롤백
- 어떤 Phase든 배포 후 문제 시: `Q: git checkout <prev-tag> && ./deploy.sh --apply`. 각 Phase 머지 시 `v0.N-phaseN` 태그를 남긴다.
- analysis 테이블은 삭제해도 수집·표시에 영향 없음: `DELETE FROM analysis` 후 daily 재실행.
- 모델 롤백: `analyst.py model rollback --to vN`.

## 부록 B — 금지 목록
- `readings`, `occupancy` 스키마 변경·행 수정
- hub*.py 로직 수정 (env 분리 3줄 제외)
- 데이터 의존 스케일러, 보간, k≠4, 노드ID·시간대를 GMM 입력에 포함
- 보드에서 직접 편집, `git push --force`, 비밀값 커밋
- 대시보드 내에서 GMM fit/predict 실행

## 부록 C — 각 PR 본문 템플릿
```
## Phase N — <제목>
### 변경
### 검증 출력 (명령 + 결과 그대로)
### 완료 기준 체크
- [ ] …
### DRIFT / ASK
```

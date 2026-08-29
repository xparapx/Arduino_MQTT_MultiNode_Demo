# DRIFT — 문서/저장소 vs 보드 실물 (Phase 0)

원칙: 보드 실물이 정답. 아래는 저장소(main @ 1b2bde0) 및 README/manual 기재와 실물의 차이.

## 코드 파일 (저장소 `hub/` ← 보드 `~/multinode_aq/`)
| 파일 | 방향 | 요약 |
|---|---|---|
| `hub/hub.py` | 보드 → 저장소 **교체** | 저장소본은 로컬 mosquitto(1883, 토픽 `multinode_sensor_demo/+/env`, readings만). 보드본은 HiveMQ TLS 8883, 토픽 `multinode_aq/+/env` + `multinode_aq/+/occ`, `occupancy` 테이블·`store_occ()` 추가 (132줄 vs 91줄). 브로커 계정은 `os.environ`(MQTT_BROKER/PORT/USERNAME/PASSWORD)으로 분리 — 변경 줄은 import 1줄 + 상수 4줄뿐 |
| `hub/hub_cloud.py` | 유지 (참고용) | 보드에 없음. 보드 hub.py의 전신(자리표시 계정, 토픽 `multinode_sensor_demo`, occupancy 없음). 문서가 참조하므로 Phase 0에서는 삭제하지 않음 → [ASK] 정리 시점 |
| `hub/en/hub.py`, `hub/en/dashboard.py` | 유지 (참고용) | 보드에 없음. 저장소 옛 버전과 동일 내용의 "영문판". 위와 동일 처리 |
| `hub/dashboard.py` | 보드 → 저장소 **교체** | 803줄 → 1,081줄. 6변수 시계열, 노드별 레짐 산점도, 비전 occupancy crosshair 맵, 환경↔비전 라벨 페어링 추가 |
| `hub/nodes.json` | 보드 → 저장소 **교체** | 3항목 한글 샘플 → 16항목(CLASS_01~08 × 환경/비전) |
| `hub/systemd/*.service` | 이름 변경 | `multinode_sensor_demo_{hub,dashboard}.service` 삭제 → `multinode_aq_{hub,dashboard}.service` (경로 `/home/arduino/multinode_aq`). dashboard 유닛 `After=multinode_aq.service`는 존재하지 않는 유닛 참조(실물 그대로 둠) |
| `hub/pyproject.toml`, `hub/uv.lock`, `hub/.python-version` | 신규 | 저장소에 없던 파일. 의존성에 numpy·scikit-learn이 이미 포함 |
| `hub/secrets.env.example` | 신규 | 실제 값은 보드 `hub/secrets.env`(gitignore) |
| `.gitignore` | 추가 | `sensor_data.db`, `*.db-journal/-wal/-shm`, `models/*.joblib`, `backup_*.csv`, `secrets.env`, `*.bak`, `*.save` |

## 문서 기재 vs 실물
| 항목 | README / 플랜 사전지식 | 실물 |
|---|---|---|
| 작업 디렉터리 | `~/multinode_sensor_demo` | `~/multinode_aq` |
| 토픽 | `multinode_sensor_demo/+/env` | `multinode_aq/+/env`, `multinode_aq/+/occ` |
| 서비스명 | `multinode_sensor_demo_*` | `multinode_aq_hub`, `multinode_aq_dashboard` |
| 수집 스크립트 | `hub.py`(로컬) 또는 `hub_cloud.py`(클라우드) 택일 | `hub.py` 하나이며 클라우드(HiveMQ) 버전 |
| 대시보드 테마 | `.streamlit/config.toml` 다크 테마 | 파일 없음. CSS/plotly 템플릿을 dashboard.py에 내장 |
| 의존성 | paho-mqtt pandas plotly streamlit streamlit-autorefresh | + numpy, scikit-learn |
| DB journal | (플랜 §9.2에서 WAL 확인 예정) | `delete` 모드 → **2026-08-29 Phase 1b에서 `wal`로 전환**(사용자 승인, `PRAGMA journal_mode=WAL` 1회, 영구) |
| ts 형식 | 5분 버킷 정각 정렬 | 노드가 `t`를 보내는 2노드만 정각 버킷, 나머지 6노드는 수신 시각(초 단위) — 분석 시 5분 버킷 리샘플 필요 |
| sqlite3 CLI | 플랜 검증 명령이 `sqlite3` 사용 | 미설치 → python `sqlite3` 모듈로 대체 |
| uv | `uv` 명령 | 비로그인 셸 PATH 밖 (`~/.local/bin/uv`) |
| 보드 git | 없음 가정 | `uv init`이 만든 빈 `.git`(커밋 0, remote 없음) — `git init` 재실행 무해 |
| sudo | (플랜은 서비스 재시작을 Claude가 수행 가정) | 비밀번호 필요 → 사용자가 실행 |
| `docs/dashboard_mockup.html` (CLAUDE.md) | `docs/` | 실제 위치 `plan/dashboard_mockup.html` |

## D-1 [ASK] 보드 레이아웃 (Phase 0 §3.3.6 진행 전 결정 필요)
보드 `~/multinode_aq`는 평면(`hub.py`가 루트)이고 저장소는 `hub/` 하위 구조다. `~/multinode_aq`를 저장소 루트로 전환하면 코드가 `~/multinode_aq/hub/hub.py`에 놓여 현행 서비스 `ExecStart`·상대경로(`sensor_data.db`, `nodes.json`)와 어긋난다. 선택지:

- **(A) 권장** `~/multinode_aq/hub/`를 uv 프로젝트·런타임 디렉터리로: 보드에서 `.venv`, `sensor_data.db`, `pyproject.toml`, `uv.lock`, `.python-version`을 `hub/`로 `mv`, 두 유닛의 `WorkingDirectory`/`ExecStart`를 `/home/arduino/multinode_aq/hub/...`로 수정 + `EnvironmentFile=/home/arduino/multinode_aq/hub/secrets.env`. 저장소 `hub/` == 보드 `hub/` 가 그대로 성립하고 Phase 1 `hub/deploy.sh`, Phase 6 유닛 파일과 일관됨. 비용: hub 서비스 정지 → 이동 → 기동 (수 초 수집 공백).
- (B) 저장소를 평면으로 재구성(`hub/` 내용을 루트로): 플랜 §4.1 구조와 충돌.
- (C) 보드에 심링크(`~/multinode_aq/hub.py → hub/hub.py` 등): untracked 항목 증가, DB 경로 혼란.

**결정 (플랜 v2 §3.1): (A) 채택.** 저장소 `hub/systemd/*.service`는 `hub/` 경로 + `EnvironmentFile=` + dashboard `After=multinode_aq_hub.service`(오타 수정)로 갱신. 보드 평면 파일은 `_phase0_backup/`(gitignore)로 이동. 보드의 uv 기본 `.gitignore`도 저장소 `.gitignore`와 충돌하므로 같은 백업 폴더로 이동.

## 플랜 v2 반영 후 추가 드리프트
| 항목 | 기재 | 실물 |
|---|---|---|
| 플랜 위치 | CLAUDE.md·플랜 §4.1: `plan/CLAUDE_CODE_PLAN.md`, `plan/dashboard_mockup.html` | 실제 파일은 `docs/plan/CLAUDE_CODE_PLAN.md`, `docs/plan/dashboard_mockup_v2.html` (2026-08-29 이동) |
| 저장소 `.gitignore` `*.db` | (기존 규칙) | `fixtures/sample.db`(Phase 1)를 커밋하려면 예외 규칙 `!fixtures/sample.db` 필요 |
| 저장소 히스토리 | 비밀값 없음 | `docs/manual.html` 2826·3205행(펌웨어 예제)에 실제 HiveMQ 클러스터 **호스트명**이 main 히스토리에 있음(계정·비밀번호는 없음). 처리 시점 [ASK] |

## Phase 1 — 플랜 §4와 실제 구현의 차이
| 항목 | 플랜 | 실제 | 사유 |
|---|---|---|---|
| CI 트리거 | PR마다 | PR + **모든 브랜치 push** | `gh` CLI가 없어 PR을 Claude Code가 열 수 없음 → push만으로 hub.py 가드 실패를 확인 가능하게 함. hub.py 가드는 `origin/main...HEAD` 비교라 main push에서는 자동 통과 |
| `.claude/settings.json` | Claude Code가 작성 | **사용자가 작성** | 자동 모드 분류기가 권한 파일 쓰기(직접·`update-config` 스킬 모두)를 차단. 내용은 PR 본문에 첨부 |
| 비밀값 스캔 범위 | (명시 없음) | `hub/` 하위만 (`hub/scripts/secret_scan.sh`) | `docs/manual.html`의 기존 호스트명 때문에 docs/를 포함하면 모든 PR이 실패. docs는 Phase 7 문서 작업에서 정리 |
| ruff 범위 | `ruff check hub/` | 동일하되 `hub.py dashboard.py hub_cloud.py en/` 제외(pyproject `extend-exclude`) | 보드 코드는 바이트 동일 유지 원칙(§0.2), 구버전 참고 파일은 정리 시점 [ASK] |
| deploy.sh import 검사 | `import aq, dashboard` | 동일 + `py_compile hub.py` | 보드 bare 모드에서 `import dashboard`가 동작함을 확인(경고만 출력) |
| 픽스처 노드 ID | 익명화 | `env_01..08`, `vis_01..05` + `fixtures/nodes.json`(라벨 CLASS_xx 유지) | 환경↔비전 페어링을 라벨로 보존해야 (label, bucket) 조인 테스트 가능 |
| `ssh q` 호출 | deny 패턴 `Bash(ssh q *sudo*)` | `~/.ssh/config`에 `BatchMode yes`를 넣어 Claude가 `ssh q '…'` 형태만 쓰도록 통일 | `ssh -o BatchMode=yes q …` 형태는 deny 패턴과 매치되지 않음 |
| Claude Code 작업 디렉터리 | 저장소 루트 가정 (`.claude/settings.json`, `CLAUDE.md`) | Phase 0~1 세션은 상위 폴더 `c:\Users\phlox\PRJ`에서 실행됨 → 저장소의 `.claude/settings.json`(deny·hook)과 `CLAUDE.md`가 **로드되지 않음**. 2026-08-29 검증에서 `ssh q sudo true`가 차단되지 않은 원인 | 이후 세션은 반드시 `Arduino_MQTT_MultiNode_Demo/`를 작업 디렉터리로 시작한다. deny·hook 동작 확인은 그 세션에서 재실행 |
| PreToolUse 훅 명령 | `python .claude/hooks/precommit_tests.py`(상대경로) | `python "$CLAUDE_PROJECT_DIR/.claude/hooks/precommit_tests.py"` | Bash 도구의 셸 cwd는 호출 간에 유지되므로 `cd hub` 뒤에는 상대경로가 깨져 **모든 Bash 호출이 훅 오류로 차단**됐다(2026-08-29 검증 중 발견). 절대경로 환경변수로 교체. 훅 스크립트 자체는 `__file__` 기준이라 변경 없음 |
| deny 동작 확인 | Phase 1 완료 기준 §4.4-2 | 저장소 루트에서 시작한 세션(2026-08-29)에서 `ssh q sudo true` → `Permission to use Bash with command ssh q sudo true has been denied.` | 확인 완료. 위 행(상위 폴더 세션)의 미차단 원인이 작업 디렉터리였음을 재확인 |
| PR 개설 | Claude Code가 `gh pr create` | **사용자가 compare URL로 개설**(PR 본문은 Claude가 작성해 전달) | `gh` 미설치, `GH_TOKEN`/`GITHUB_TOKEN` 없음. `gh pr checks` 대신 GitHub REST API(`/actions/runs`) 무인증 조회로 CI 결과 확인 |

## Phase 1b — 플랜 §5와 실제 구현의 차이
| 항목 | 플랜 | 실제 | 사유 |
|---|---|---|---|
| before 측정 방법 | 배포 후 `journalctl`의 `[perf]` 로그 + 브라우저 DevTools 웹소켓 바이트 | `hub/scripts/perf_probe.py`(bare 모드)로 **배포·재시작 없이** 보드에서 측정. 페이로드는 figure JSON / CSV 바이트로 근사 | 재시작(sudo) 없이 before를 얻기 위해. 브라우저 DevTools 수치는 없음 — Streamlit은 변경 없는 요소를 재전송하지 않으므로 probe 수치는 상한 |
| ② 캐시 키 | `MAX(id)` | `data_version()` = (`MAX(id)`, 최신 행의 5분 버킷). 무거운 28일 통계는 **버킷**으로, 라이브 figure는 노드별 `recv_time`으로 키 | `MAX(id)`는 8노드가 수 초마다 바꾸므로 60 s 주기마다 캐시 미스 → 통계는 버킷당 1회만 재생성 |
| ② figure 캐시 종류 | `@st.cache_data` | **`@st.cache_resource`**(ttl 300, `max_entries`) | 보드 벤치마크: `cache_data` 히트 = unpickle → plotly 재검증(레이더 25 ms×8, ②의 5개 280 ms)으로 새로 만드는 것과 같은 비용. `cache_resource`는 같은 객체를 돌려줘 히트 ≈ 0 ms. `st.plotly_chart`는 읽기만 함 |
| ② ★ 마커 오버레이 | `copy.deepcopy` 후 `add_trace` | 플랜대로 deepcopy **+ 배치 추가**(`add_traces` 1회, `layout.annotations` 1회 대입) | 공유 객체라 deepcopy 필수. `add_annotation` 16회는 매번 전체 목록 재검증 → 293 ms, 배치 51 ms |
| ③ 노드별 산점도 과거점 | "서버 집계본만 전송" | 밀도 배경은 `np.histogram2d` 집계, 과거점은 **시간 균등 표본 ≤ 1,500점**(`SCATTER_MAX_POINTS`) | 점을 없애면 화면이 달라짐. 표본화로 모양 유지, 페이로드 634 KB → 49 KB |
| ② boxplot 이상치 | (언급 없음) | `boxpoints="outliers"` 대신 순위 균등 표본 ≤ 300점 scatter | 사전 집계 `go.Box(q1=…)`에는 이상치 인자가 없음 |
| bare 모드 검사 | `deploy.sh`의 `import dashboard` | fragment 본문은 bare 모드에서 실행되지 않음(Streamlit이 컨텍스트 없으면 `None` 반환) → `perf_probe.py`가 `__wrapped__`로 호출 | import 검사만으로는 섹션 코드가 실행되지 않으므로 probe를 배포 후 검증에 사용 |
| `components.html` | (없음) | `st.components.v1.html` 2026-06-01 이후 제거 예고(1.58에선 경고). `st.iframe`은 URL 전용, `st.html`은 iframe 격리 없음 → **Phase 5**에서 처리 | 시각 동일 기준 유지 |
| dashboard 유닛 `After=` | 1b에서 수정 | Phase 0 D-1에서 이미 `multinode_aq_hub.service`로 수정됨 | — |
| 태블릿 체감 기록 [ASK] | 1b | **연기** — 행동 지침용 LED 인디케이터 부착·학생 수행 후 | 사용자 결정 2026-08-29 |

## Phase 2 — 플랜 §6과 실제 구현의 차이
| 항목 | 플랜 | 실제 | 사유 |
|---|---|---|---|
| `calendar.json` 형식 | `periods` + `school_hours{start,end,days}` | + `school_hours.overrides{"4":{…}}`(금요일 08:40~15:30), `lunch{12:30~13:30}`, `timezone` | 실제 학사 일정(2026-08-29 사용자 제공): 방학 7/17~8/10, 개학 8/11, 월~목 08:40~16:30, 금 ~15:30, 점심 12:30~13:30. 요일별 예외·점심을 담을 자리가 없었음 |
| 기간 경계 | (형식만) | 기간은 **빈틈·겹침 없이 연속**해야 함(`validate_calendar`), 첫 기간만 `start=null`, 마지막만 `end=null` | 경계일 refit·재실 판정이 날짜 하나도 빠뜨리지 않도록 |
| §6.4 grep 기준 | 수동 grep | CI 단계 `aq/ must never alter or delete collector data`로 강제 | 지시가 아니라 메커니즘으로(Phase 1 원칙) |
| `analyst.toml` 키 | §2 상수 목록 | `[schedule]`(Phase 6 타이머 문자열), `[qc.range].pm_max_exclusive/pm_column`, `[governance].weekly_day/weekly_time_utc/models_dir/current_link` 추가 | §2·§10의 문자열 상수도 코드 밖으로 |

## Phase 3 — 플랜 §7과 실제 구현의 차이
| 항목 | 플랜 | 실제 | 사유 |
|---|---|---|---|
| QC 유효율 분모 | "노드×일 CO₂ 유효율" (분모 미명시) | **그날 실제 수신한 행** 기준. 행이 0개인 (노드, 일)은 `no rows`로 탈락 | 기대치(288행/일) 기준이면 반나절 다운 노드가 유효 데이터까지 버리게 됨. 다운 노드는 `no rows`로 잡힘 |
| "일"의 기준 | (미명시) | **KST 날짜**(`[time].tz_offset_hours = 9`) | 학교 일과·학사 일정이 KST이므로 게이트도 같은 날짜 기준 |
| 분석 창 | (미명시) | `[run]` 신설: hourly 24 h, daily 7 d, forecast 최소 48 버킷, trail 12, band 슬롯 60 min | §2에 없던 상수 → 코드 대신 config에. 값은 Claude 제안 [ASK-lite] |
| 모델 없을 때 | (Phase 4에서 v1) | `models/current`가 없으면 **ad-hoc GMM**(28일, `model_ver="adhoc"`)을 매 실행마다 학습 | Phase 3 검증이 dry-run만이라 모델 파일 없이 돌아야 함. 보드: ad-hoc 경로 hourly 20 s·daily 24 s·fit 27 s(28일 48k행 × n_init 5), **모델 로드 경로 hourly 0.9 s·daily 5.2 s**. §7의 hourly < 15 s는 모델 로드 경로 기준 |
| ad-hoc 창 축소 시도 | — | hourly만 7일 창으로 줄이면 픽스처에서 두 중심이 같은 분면(`mixed`) → `AnchorError`. **28일 유지** | 28일 학습 창이 분면 분리에 실제로 필요함을 확인 |
| 전이 Δt 판정 | 원 ts 기준 5 ± 2 min | **버킷 기준**(floor 후 dt는 5의 배수 → 사실상 dt == 5). `transition_dt_tolerance`는 config에 유지 | 모든 분석이 버킷 위에서 돌아 원 ts 차이는 의미 없음 |
| `plot_check.py` 출력 | PNG | **HTML**(plotly `write_html`) | PNG는 kaleido가 필요하고 aarch64 휠 부재로 보드 `uv sync`가 깨질 위험 |
| 슬라이드 정성 비교 [ASK] | `실제분석사례_교실공기질`와 비교 | **미수행** — 슬라이드 파일이 저장소에 없음 | 사용자가 파일 위치를 주면 수행. 매뉴얼 "확장 과제" 절의 집 테스트 결과(4군집, 지속확률 0.86~0.97)와는 정합: 픽스처 전이행렬 대각 0.96~0.99 |
| 예측 모델 | "Pipeline 동일, 타깃 shift −6" | `StandardScaler → Ridge` 다중출력, feature = 현재값·lag 1~3·1차 차분, 5분 격자 재색인(보간 없음) | 최소 구성. 값 범위 클리핑 없음(픽스처에서 co2_pred 264 등 물리 하한 아래 예측 관측) → Phase 7 운영 검증에서 재검토 |
| 보드 측정 | 배포 후 `/usr/bin/time -v` | 머지 전 `/tmp` 사본으로 in-process 측정(`resource.getrusage`) | `/usr/bin/time` 부재 가능, 배포 전 검증 |

## Phase 4 — 플랜 §8과 실제 구현의 차이
| 항목 | 플랜 | 실제 | 사유 |
|---|---|---|---|
| 후보 저장 | "후보 학습 → 저장만" | 후보는 항상 다음 번호 `gmm_vN`으로 저장(덮어쓰기 거부), 승격 시 `current`만 이동 | 버전 이력이 곧 감사 기록. 별도 candidate 파일명 불필요 |
| `models/current` | 심링크 | git에 **심링크 객체(mode 120000)** 로 커밋 → 보드(Linux)는 심링크, Windows 체크아웃은 "gmm_v1.joblib" 한 줄 파일. `governance.resolve_current()`가 둘 다 읽음 | Windows 개발 PC엔 심링크 권한이 없음 |
| v1 joblib | (커밋 여부 미명시) | `hub/models/gmm_v1.joblib`(1.9 KB) + `.json` 커밋(`.gitignore` 예외). 이후 버전은 보드에서만 생성·보관(gitignore) | 보드가 `git pull`만으로 v1을 받게 |
| 로그우도 기준 | "+2% 이상" | 상대 개선 `(ll_cand − ll_cur) / |ll_cur| ≥ 0.02` (최근 7일 QC 통과 행, `score_samples` 평균) | 로그우도는 음수라 절대값 기준 상대 비율로 |
| 중심 이동 | "L2 최대 ≥ 0.25" | 같은 레짐 이름끼리 매칭한 스케일 좌표 L2의 최대 | 분면 앵커가 이름을 고정하므로 이름 매칭이 곧 대응 |
| 경계일 강제 refit | "calendar.json 경계일엔" | 경계일이 **as_of 이전 7일 안**에 있으면 승격 강제(`forced=True`) | 주 1회 실행이라 경계일 당일에 정확히 돌지 않음 |
| 첫 모델 | (v1 초기 학습) | `current`가 없으면 후보를 무조건 승격("first model"); `fit` 명령도 첫 버전은 자동 승격 | 부트스트랩 |
| `--models-dir` | (없음) | 모든 명령에 추가 | 테스트·보드 사전 검증이 저장소 밖 디렉터리를 쓰도록 |
| v1 학습 데이터 | 보드 28일 | 2026-08-01 05:05 ~ 08-29 05:05 UTC, 48,259행(QC 통과), 중심 clean 538/71 · matter 447/131 · human 901/118 · mixed 1831/244 | 보드 `/tmp` 사본에서 학습 후 저장소로 복사 |

## Phase 5 — 플랜 §9·목업 v2와 실제 구현의 차이
| 항목 | 플랜/목업 | 실제 | 사유 |
|---|---|---|---|
| `ui_common.py` 이동 | "이동만" | ast 줄 범위로 80개 정의를 **바이트 그대로** 이동, probe 수치 동일. 이동 코드는 옛 스타일이라 ruff 제외(`extend-exclude`) | 검증 가능한 이동. 새 페이지 2 코드는 `aq/plots.py`·`aq/analysis_view.py`·`pages/`(린트 대상) |
| H "analyst가 저장한 집계본" | (kind 미정의) | 새 kind **`explore`**(Spearman 상관 + RobustScaling 밀도 pooled 24×24 / 노드 20×20 + median·IQR) — daily가 저장, 페이지 2가 그림 | 페이지 2가 readings를 읽지 않으려면 집계가 analysis에 있어야 함. §6.1 kind 목록에 추가(Phase 2 스키마 확장) |
| 레이더 | 카드 8개 | **폴라 서브플롯 2×4 1 figure**(결정 (a)). 카드 테두리 → 서브플롯 제목 | 요소 8→1. 사용자 결정 2026-08-29 |
| ③ 오른쪽 열 [ASK] | 비전 패널 전폭 또는 재실×CO₂ 미니 산점도 | **비전 패널 전폭** | 재실×CO₂는 페이지 2 G가 다룸; 페이지 1은 "지금 상태"만 |
| C 밴드 범위 | 목업 "28일 × 6교실" | **7일**(`[run].daily_window_days`) | daily 창이 7일. 28일로 늘리면 daily 실행이 4배(보드 5 s → ~20 s); 필요 시 [ASK] |
| 사이드바 상태 | hub 최신 행·analyst run_at·모델 버전 | + 활성 노드 수(15분 내 행), 비전 노드 최근(24h), readings 행 수, journal 모드 | `analysis_view.service_status()`가 readings/occupancy를 읽음 — `pages/`가 아니라 `aq/`에 있어 CI 가드 범위 밖(의도) |
| D 표 | 목업 "가장 흔한 다음 전이" | 노드별 count 행렬을 **합산**한 pooled 행렬로 지속확률·다음 전이, 체류는 노드 중앙값의 중앙값 | 페이지가 재계산하지 않고 저장된 count만 합산 |
| I 모델 이력 표 | 버전·학습 창·행·중심 이동·로그우도Δ·결정·사유 | `model_event` 행 20개 + `models/` 버전 목록 | weekly 실행 전에는 v1 목록만 보임 |
| 빈 상태 | 안내 화면 | `analysis` 없음/비었을 때 안내 + 나타날 섹션 목록 + dry-run 명령. 지금 보드가 이 상태 | — |
| ruff E501 | 100자 | `pages/*.py`, `aq/plots.py`, `aq/analysis_view.py`는 E501 제외 | 한글 캡션(CJK 2폭) |
| `components.html` 경고 | Phase 5에서 처리 | **미처리** — `st.iframe`은 URL 전용, `st.html`은 iframe 격리 없음 | 대체재 없음. Streamlit 제거 시점에 재검토 |

## Phase 6 — 플랜 §10과 실제 구현의 차이
| 항목 | 플랜 | 실제 | 사유 |
|---|---|---|---|
| 유닛 옵션 | oneshot · `TimeoutStartSec=300` · EnvironmentFile 불필요 | + `Nice=10`, `Persistent=true`, `After=multinode_aq_hub.service` | 대시보드 응답성 우선, 부팅 중 놓친 슬롯은 다음 부팅에 실행 |
| 첫 채움 | 수동 1회 `start …daily` | daily + **hourly**도 수동 1회 | 페이지 2 B/E/F(hourly kind)가 06:05까지 비어 있지 않도록 |
| 검증 방식 | `list-timers`·PYSQL·hub 로그 | + 보드 AppTest로 페이지 1·2 실데이터 렌더(예외 0) | 화면 확인을 기계적으로 |
| 관찰 (모델) | — | `regime_now`에서 voc 94, co2 448인 노드가 `matter` — GMM 배정은 분면 임계가 아니라 군집 확률이라 앵커선 근처에선 이름과 사분면이 어긋날 수 있음. matter 중심(447,131)·human 중심(901,118) 모두 voc 앵커(120) 근처 | Phase 7 운영 검증에서 라벨 안정성 관찰 항목으로 |
| 관찰 (예측) | — | CLASS_03 co2_pred 330(물리 하한 350 미만) | Phase 3 DRIFT의 "클리핑 없음" 재확인 → Phase 7에서 결정 |

## 대시보드 손질(PR #13) — 합의 항목과 실제 구현의 차이
| 항목 | 합의 | 실제 | 사유 |
|---|---|---|---|
| 사이드바 노드 총수 | "N / 5" | 비전 총수 = `occupancy`에 한 번이라도 쓴 노드 수(5), 환경 총수 = `readings`의 노드 수(8). **nodes.json으로는 못 센다** — 보드 nodes.json은 16개 `node_XXXXXX`(환경 8 + 비전 8)이고 픽스처만 `env_`/`vis_` 접두사 | Phase 5 코드의 `startswith("vis")`가 픽스처에서만 맞았음(보드는 "환경 노드 n / 16"으로 표시되고 있었음) |
| E) 판정 시각 | "판정 시각" | hourly `run_at`(KST). 장치 상태 시작 시각(`since`)은 "유지" 칸에 "mm-dd hh:mm부터 (· 최소 ~hh:mm)"로 | `since`는 상태가 바뀐 시각이라 판정 시각이 아님(첫 실행 05:43에 초기화된 값이 모든 행에 같이 찍혔음) |
| E) 판정 보류 + 장치 ON | (미논의) | 행동 "판정 보류", 근거에 "공청기 ON · hold" 로 표시, 유지에 ON 시작 시각 | hold는 이전 상태를 유지하므로 장치가 켜진 채 보류될 수 있음(CLASS_03 실사례) |
| G) 창 밖 교실 | "중단 표시" | `last_bucket`은 창이 아니라 **전체 이력**의 마지막 버킷(`db.last_occupancy_bucket`), 페이지가 `win_start`와 비교해 "· 중단" | 언제 멈췄는지가 "중단"보다 유용. occupancy 창 밖 조회는 analyst의 읽기 전용 쿼리(인덱스 `ix_occupancy_node_ts`) |
| B) 라벨 겹침 | 오프셋 또는 호버 전용 | 이웃 라벨을 8개 슬롯에 분산(greedy), 호버 유지 | 라벨을 없애면 평면에서 교실을 못 찾음 |

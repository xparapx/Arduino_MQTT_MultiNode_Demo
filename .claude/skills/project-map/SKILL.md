---
name: project-map
description: 코드 저장소나 설계 문서를 읽고 "프로젝트 설계 맵(큰 그림) + 스크립트 연결 지도 + DB 스키마"를 한 장의 인터랙티브 HTML 로 만드는 스킬. 사용자가 구조도, 아키텍처 다이어그램, 호출 관계, 어떤 파일이 어디서 불리는지, DB 테이블 관계, 스키마 도식, "전체 그림을 보고 싶다", "이 코드가 어떻게 연결되는지" 라고 말하면 — 명시적으로 "지도"나 "다이어그램"이라 하지 않아도 — 반드시 이 스킬을 쓴다. Python/FastAPI/SQLite/systemd 프로젝트에 최적화되어 있지만 데이터 JSON 만 채우면 어떤 스택이든 렌더링된다.
---

# project-map

세 가지 뷰를 하나의 HTML 로 만든다 (빌드 도구 없음, 파일 하나, 오프라인 동작):

1. **설계 맵** — 축(lane)별 데이터 흐름. "누가 만들고 → 어디에 놓이고 → 누가 읽는가"를 한 줄씩.
2. **스크립트 연결 지도** — 열 = 실행 주체 → 스크립트 → 공용 모듈 → 데이터 파일 → API → 브라우저. 노드 클릭 시 역할 요약 + 호출/import/읽기/쓰기 관계.
3. **DB 스키마** — DB 파일마다 writer 하나 + readers, 테이블 클릭 시 컬럼과 조인 키.
4. **핵심 기술 · 용어 탭** — 그 프로젝트가 **채택한 핵심 구현 기술(무엇을, 왜 그 선택인지)** 과 도메인 용어 정리. `glossary_html` 로 반드시 프로젝트 맞춤 내용을 작성한다(작성하지 않으면 일반 API/엔드포인트 해설이 기본으로 나온다). 탭 이름은 `glossary_label` 로 바꿀 수 있고 `glossary:false` 로 숨긴다.

## 절차

### 1. 입력을 고른다
- **저장소가 있으면**: `python scripts/scan.py <repo_root> draft.json` 로 초안을 뽑는다. Python import·`@router.get` 경로·`CREATE TABLE`·systemd `ExecStart/OnCalendar`·JS 의 `/api/...` fetch 를 자동 추출한다.
- **설계 문서만 있으면**(계획서·CLAUDE.md·README): 문서를 읽고 `examples/mealboard.json` 을 본떠 직접 JSON 을 쓴다.
- 둘 다 있으면 scan 초안 위에 문서 내용을 얹는다. **문서가 코드보다 앞선 계획(아직 없는 파일)이면 노드 설명에 "(계획)" 을 붙인다.**

### 2. JSON 을 채운다 — 스키마는 `references/schema.md`
scan 초안에서 사람이(=Claude 가) 반드시 채워야 하는 것:
- 각 노드의 `d` — **한두 문장, 그 파일이 무엇을 하고 왜 있는지**. 기능 나열이 아니라 역할. 설계 원칙(예: "이 DB 의 유일한 writer", "순수 함수라 sqlite 없이 테스트")이 있으면 그것을 적는다.
- `overview.lanes` — 4~7개 축. 축 하나 = 한 데이터 흐름(실시간/배치/외부 API/관리/배포 등).
- `dbs[].writer`·`readers`, `dbs[].name` 을 실제 파일명으로. 테이블에 `d` 를 붙여도 된다.
- `rels` — 파일 안/파일 간 조인 키. 외래키가 없어도 코드에서 같은 값으로 잇는 관계를 적는다.
- `edges` 의 `wr`/`rd` 구분을 확인한다(scan 은 휴리스틱). **한 파일에 writer 가 둘 이상 나오면 그 자체가 발견이니 사용자에게 알린다.**
- 열(`columns`)은 프로젝트에 맞게 바꿔도 된다. 노드의 `c` 는 열 id.
- 정렬: 같은 흐름에 속한 노드는 같은 `row` 를 주면 가로로 한 줄에 놓여 읽기 쉽다. 생략하면 열 안에서 차례로 쌓인다.
- `glossary_html` — **핵심 기술 · 용어 탭의 본문(필수)**. 템플릿의 클래스를 재사용해 세 부분으로 쓴다:
  ① `.flow` 카드 한 줄 = 이 프로젝트를 관통하는 설계 문법(4~5장, 핵심 카드에 `.hl`),
  ② `table.cols` = 채택 기술 카드 — 왼쪽 기술 이름, 오른쪽 "무엇을 하고 **왜 이 선택**인지" 한두 문장(기능 나열 금지, 트레이드오프·원칙 위주),
  ③ 두 번째 `table.cols` = 도메인 용어(사용자·심사자가 화면에서 마주치는 단어들).
  마무리 `.note` 한 개로 가장 오해하기 쉬운 개념 하나를 짚는다.

### 3. 렌더링하고 확인한다
```
python scripts/render.py data.json out.html
```
render 는 없는 노드를 가리키는 edge/rel 을 경고로 알려준다. 가능하면 헤드리스 브라우저로 캡처해 열이 잘리지 않는지, 노드가 겹치지 않는지 본다(노드 45개·열 6개 기준으로 맞춰져 있다. 노드가 훨씬 많으면 열을 늘리거나 서브시스템별로 JSON 을 나눈다).

### 3b. archify 다이어그램 — 설계 맵·연결 흐름 고품질판
전역 스킬 **archify** 가 설치되어 있으면(`node ~/.claude/skills/archify/bin/archify.mjs doctor` 로 확인) 설계 맵(큰 그림)과 연결 흐름 플로우차트는 archify 로도 만든다. 미설치면 이 단계를 건너뛰고 기존 경로만 쓴다.

- **설계 맵(큰 그림)** → archify `architecture` 타입. `overview.lanes` 를 경계(boundary)로, 실행 주체·핵심 모듈·DB 를 **12개 이하 주요 노드**로 집약한다.
- **연결 흐름 플로우차트** → 데이터 파이프라인 성격이면 `dataflow`, 절차·게이트 성격이면 `workflow`(신규는 schema v2).
- project-map JSON 의 nodes/edges/dbs 는 **사실 근거로만** 쓴다. archify 스펙은 archify SKILL.md 의 fast authoring path 를 따라 새로 작성한다(타입별 schema + 예시 1개 읽기 → 후보 작성 → validate → deliver). 45개 노드를 기계적으로 옮기지 말 것 — showcase 검증에 실패하고, 상세도는 어차피 out.html 담당이다.
- 명령:
  ```
  node ~/.claude/skills/archify/bin/archify.mjs validate <type> <spec>.json --quality showcase --json
  node ~/.claude/skills/archify/bin/archify.mjs deliver <type> <spec>.json <out>.html --quality showcase --json
  ```
  showcase 통과(아티팩트 체크 9개, composition 오류·경고 0) 후 deliver 가 최종 승인. 실패 시 진단된 subject 만 고쳐 재시도한다.
- 산출물은 데이터 JSON 옆에 둔다: `docs/project-map-arch.html` + `docs/project-map-arch.json`(설계 맵), `docs/project-map-flow.html` + `docs/project-map-flow.json`(연결 흐름).
- **역할 분담**: archify 판 = 발표·문서용 한눈 요약(정적·기하 검증). 노드 클릭 상세·DB 스키마·용어 탭은 여전히 `render.py` 의 out.html 이 담당한다. 둘 다 전달한다.
- **단일 파일 번들**: 사용자가 파일 하나로 받길 원하면 데이터 JSON 에 `embeds` 를 선언한다 — archify HTML 이 out.html 의 추가 탭(iframe srcdoc, 첫 방문 시 lazy 로드)으로 내장되어 오프라인 단일 파일이 유지된다:
  ```json
  "embeds": [
    { "id": "arch", "label": "아키텍처 뷰", "file": "project-map-arch.html" },
    { "id": "flow", "label": "파이프라인 뷰", "file": "project-map-flow.html" }
  ]
  ```
  `file` 은 데이터 JSON 기준 상대경로. archify 산출물을 갱신했으면 render 를 다시 돌려야 내장본도 갱신된다.

### 4. 전달
- `out.html` 을 사용자에게 준다. 저장소가 있으면 `docs/` 에 넣고, 데이터 JSON 도 옆에 두어(`docs/project-map.json`) 다음에 갱신할 수 있게 한다. archify 산출물(3b)이 있으면 함께 전달한다.
- 만들면서 발견한 구조적 문제(writer 중복, 어디서도 부르지 않는 스크립트, 문서와 코드 불일치)를 짧게 보고한다. 이것이 이 지도의 진짜 가치다.

## 갱신할 때
기존 `project-map.json` 이 있으면 새로 만들지 말고 그 파일을 고친다. 노드 id 를 유지해야 사용자가 익숙한 배치가 흔들리지 않는다. archify 스펙(`project-map-arch.json` 등)도 같은 원칙 — 기존 스펙의 노드 id 를 유지한 채 고치고 validate→deliver 를 다시 돈다.

## 파일
- `scripts/scan.py` — 저장소 → 초안 JSON
- `scripts/render.py` — JSON → HTML
- `assets/template.html` — 렌더 템플릿 (색·레이아웃은 여기서)
- `references/schema.md` — 데이터 JSON 필드 설명
- `examples/mealboard.json` — 완성 예시 (46 노드, 4 DB)

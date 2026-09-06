# project-map 데이터 JSON

```jsonc
{
 "title": "제목", "subtitle": "부제(선택)",
 "overview": { "intro": "한 문단", "lanes": [ {"label": "축 이름", "items": ["이름|한 줄 설명", "..."]} ] },
 "columns": [ {"id": "timer", "label": "실행 주체"}, ... ],      // 왼쪽→오른쪽 순서. 6개가 기본
 "nodes": {
   "node_id": { "c": "열 id", "n": "표시 이름(파일 경로)", "s": "한 줄 부제", "d": "역할 요약 1~2문장", "row": 0 /*선택*/ }
 },
 "edges": [ ["from_id", "to_id", "call|imp|wr|rd|http", "선 위 라벨"] ],
 "dbs": [
   { "id": "queue", "name": "queue.db", "writer": "유일 writer", "readers": ["..."],
     "tables": [ { "n": "samples", "pk": "ts", "d": "선택", "cols": [["컬럼", "타입 · 설명"]] } ],
     "x": 30, "y": 60 /*선택: 생략 시 3열 자동 배치*/ }
 ],
 "rels": [ ["dbid.table", "dbid.table", "조인 키 라벨"] ],
 "glossary": true,             // false 면 탭 숨김
 "glossary_label": "핵심 기술 · 용어",  // 탭 이름 (기본 "핵심 기술 · 용어")
 "glossary_html": "<h2>…</h2>",  // 탭 본문 — 프로젝트 핵심 구현 기술(왜 이 선택인지) + 도메인 용어.
                                // 비우면 일반 API/엔드포인트 해설이 기본으로 나온다.
                                // 쓸 수 있는 클래스: .flow(카드 흐름, .hl 강조) · table.cols · .note
 "embeds": [                    // 선택 — 외부 단일 HTML(예: archify 다이어그램)을 내장
   { "id": "arch", "label": "아키텍처 뷰", "file": "project-map-arch.html", "into": "ov" }
 ]                              // file 은 이 JSON 기준 상대경로. render 시 iframe srcdoc 으로
                                // 본문에 흡수되어 산출물은 여전히 오프라인 파일 하나다.
                                // into: 기존 탭 section id("ov"/"map"/"db"/"gloss") 상단에 삽입(권장).
                                // into 생략 시 별도 탭으로 추가된다.
                                // hide: CSS 셀렉터 — 내장본에서만 display:none (예: 중복 타이틀).
                                // css: 자유 CSS — 자리를 지켜야 하면 ".header{visibility:hidden}" 처럼
                                //      hide 대신 이걸 쓴다(archify 는 툴바가 겹치므로 css 권장).
}
```

간선 종류의 의미
- `call` 실행 주체가 프로세스를 띄움 (systemd → python -m …, 프로세스 → 서브프로세스)
- `imp` 같은 프로세스 안에서 import 해 함수를 씀
- `wr` 파일/DB 쓰기 — **파일당 하나만 있어야 정상**
- `rd` 파일/DB 읽기
- `http` HTTP·소켓·SSE 등 네트워크 경계

노드 `c` 값은 `columns[].id` 중 하나. 열 색은 순서대로 6가지가 정해져 있다.

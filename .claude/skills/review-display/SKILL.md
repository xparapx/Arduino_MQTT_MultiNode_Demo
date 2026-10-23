---
name: review-display
description: 키오스크(/kiosk)나 대시보드 화면을 가독성·모션·등급 색 정직성·문구 기준으로 감수한 제안 목록을 받는다. 사용자 호출 전용.
disable-model-invocation: true
---

인자(`$ARGUMENTS`): 화면 경로(예: `/kiosk`, `/kiosk?interval=5&debug=1`, `/#energy`). 비어 있으면 `/kiosk`.

Agent 도구로 `display-reviewer` 서브에이전트(subagent_type: "display-reviewer")를 띄운다.
프롬프트: "감수 대상: <인자>. webtest 미리보기를 1920×1080 으로 띄워 6개 점검 항목을 보고, 확정 결정을 바꾸는 제안은 [ASK] 로 표시해 줘."

주의: `.claude/launch.json` 의 `webtest` 픽스처 경로가 없으면 먼저 사용자에게 알리고 멈춘다(픽스처 재생성은 별도 작업).
보고서를 그대로 보여준다. [ASK] 항목은 사용자 결정 전에 반영하지 않는다. 나머지도 사용자가 "반영해" 라고 할 때만 고친다.

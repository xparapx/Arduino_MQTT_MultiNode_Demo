---
name: review-invariants
description: 현재 변경분(또는 지정한 커밋 범위)이 저장소 불변 조건(수집 경로·공개 403·허용 목록·키오스크 정직성·무의존·커밋 위생)을 지키는지 검토 보고를 받는다. 사용자 호출 전용.
disable-model-invocation: true
---

인자(`$ARGUMENTS`): 커밋 범위(예: `HEAD~3..HEAD`, `9ebec37..`). 비어 있으면 작업트리·스테이지 변경분.

Agent 도구로 `invariant-reviewer` 서브에이전트(subagent_type: "invariant-reviewer")를 띄운다.
프롬프트: "검토 대상: <인자 또는 '현재 diff'>. 체크리스트 9개 항목을 모두 판정하고 pytest·ruff 숫자를 포함해 보고해 줘."

보고서를 그대로 보여준 뒤, 위반이 있으면 "고칠까요?" 라고 묻고 멈춘다. 사용자 확인 없이 고치지 않는다.

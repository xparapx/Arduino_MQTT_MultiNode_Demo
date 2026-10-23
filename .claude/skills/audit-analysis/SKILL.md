---
name: audit-analysis
description: analyst 산출(레짐·판정·밴드·예측·모델)이 analyst.toml 규칙·허용 목록·플러그 실측과 맞는지 검산 보고를 받는다. 사용자 호출 전용.
disable-model-invocation: true
---

인자(`$ARGUMENTS`): 로컬 DB 경로(예: `hub/fixtures/sample.db`). 비어 있으면 보드 공개 API + 보드 DB 읽기(ssh q, 읽기 전용).

Agent 도구로 `analysis-auditor` 서브에이전트(subagent_type: "analysis-auditor")를 띄운다.
프롬프트: "검산 대상: <인자 또는 '보드'>. 8개 항목을 모두 판정하고 숫자와 불일치 방 목록을 포함해 보고해 줘."

보고서를 그대로 보여준다. 불일치가 있어도 analyst.py·DB·모델은 사용자 확인 없이 건드리지 않는다. 격주 거버넌스 결정(모델 승격 등)은 사용자 몫이다.

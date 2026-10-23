---
name: doctor
description: aqhub 보드 서비스·수집 신선도·공개 주소(aq/aq-kiosk/aq-admin.kjhs-lab.com) 상태를 읽기 전용 점검해 숫자 보고서로 받는다. 사용자 호출 전용.
disable-model-invocation: true
---

Agent 도구로 `board-doctor` 서브에이전트(subagent_type: "board-doctor")를 띄운다.
프롬프트: "보드와 공개 주소를 정의된 순서대로 점검하고 보고서를 돌려줘. 로컬 origin/main 은 <git log -1 --oneline origin/main 결과> 이다."

돌아온 보고서를 **그대로** 사용자에게 보여준다(요약·윤색 금지). 비정상 항목이 있으면 그 아래에 사용자가 직접 실행할 명령(sudo·restart 가 필요한 것)을 bash 블록으로 적는다. 메인 세션은 재시작·pull·수정을 하지 않는다.

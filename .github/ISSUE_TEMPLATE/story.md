---
name: Story
about: 사용자 관점의 결과와 검증 예제
title: "[STORY] "
labels: "kind:story,status:backlog,stage:requirements"
---

## 상위 에픽

에픽을 연결하고 GitHub Parent와 milestone을 지정한다.

## 사용자 결과와 범위

누가 무엇을 할 수 있어야 하는가?

## 완료 조건

- [ ] 하위 태스크를 마치고 성공·실패 예제를 재현한다.
- [ ] 버전·환경·실제 결과·미지원/미확인 조건을 남긴다.

## BDD 시나리오와 미결정 사항

시나리오 ID·feature 경로·구현 대상 행동과 합성 예시를 적는다. 정상·실패·반례를 Given–When–Then으로 설명하고 미결정 정책·수치·기술을 구분한다. 언어·실행 환경·CI·공급원별 지원 차이와 이식성 검증 조건을 적는다.

```gherkin
Scenario: BDD-XXX-000 기대하는 사용자 행동
  Given 합성 대상과 확인할 사전 조건이 있다
  When 사용자가 동작을 요청한다
  Then 관측 가능한 결과와 근거를 확인한다
```

## 선행 조건과 태스크

선행 결정·실험을 적고 실제 Sub-issues로 태스크를 연결한다.

## 검증과 산출물

사용자 결과를 확인할 방법과 근거 위치를 적는다.

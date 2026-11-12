# JJAM-TONG Platform 위키

이 위키는 JJAM-TONG Platform의 목표·요구사항·설계 결정·검증 결과를 정리한다. JJAM-TONG은 **가시성을 자동으로 유지하고, 그 근거로 에이전트와 SRE 담당자의 분석·운영을 돕는 플랫폼**을 목표로 한다. SRE는 서비스의 신뢰성을 관리하는 엔지니어링 활동이다.

현재는 사용자 행동을 시나리오로 정리하는 BDD 방식으로 요구사항을 작성·검토하고, 제한된 비교 실험을 수행하는 단계다. 아래에서 제품 목표, 설계 제안, 채택한 결정, 실제 검증 결과를 구분해 찾아볼 수 있다.

## 분야별 문서

| 분야 | 이 페이지에서 찾을 것 |
| --- | --- |
| [제품 비전과 전체 범위](Product-and-Scope.md) | 왜 만드는가, 누구를 위한 것인가, 코드·인프라·CMDB·SIEM의 구현 범위 |
| [요구사항과 게시판 시나리오](Requirements-and-Scenarios.md) | BDD, 버전별 호출 관계, GitHub 자동 등록, 장애·보안 분석 질문 |
| [아키텍처와 설계 결정](Architecture-and-Decisions.md) | 논리 경계, 버전·근거 계약, 주기 확인과 알림의 비교, 설계 결정 기록(ADR)과 미결 선택 |
| [OSS 조사와 비교 실험](Research-and-Experiments.md) | Backstage·Flux 등 오픈소스 소프트웨어(OSS)의 비교 자료, 재현 방법, 성공·실패·미검증 근거 |
| [로드맵과 기록 규칙](Roadmap-and-Workflow.md) | 에픽·스토리·태스크, 현재 작업, 논의→결정→구현→검증 추적 |

## 처음 읽는 순서

프로젝트를 이해하려면 **제품 비전 → 게시판 시나리오 → 아키텍처**를 읽는다. 기술 선택을 토론하려면 **OSS 조사 → 실험 결과 → 설계 결정**을 읽는다. 작업을 시작하려면 **로드맵과 기록 규칙 → 해당 이슈 → 연결된 명세·근거**를 확인한다.

## 근거를 따라가는 방법

사용자 질문을 [BDD 원본](../requirements/README.md)과 작업 이슈에 연결하고, 대안은 [설계 토론](../DISCUSSIONS.md), 선택은 [ADR](../decisions/0001-reconciliation-baseline.md), 실제 판정은 [실험 결과](../experiments/HYBRID-RESULTS.md)에서 확인한다. 예를 들어 관계 자동 갱신은 [S03 #10](https://github.com/DDINGJOO/JJAM-TONG/issues/10) → [비교 실험 S10 #34](https://github.com/DDINGJOO/JJAM-TONG/issues/34) → ADR 0001 → 결과와 [PR #39](https://github.com/DDINGJOO/JJAM-TONG/pull/39)로 이어진다. 제한된 실험이 통과했더라도 제품 BDD 전체를 검증한 것으로 판단하지 않는다.

상세 명세·결정·결과의 원본은 저장소 문서이고, 작업 상태의 기준은 [GitHub Issues](https://github.com/DDINGJOO/JJAM-TONG/issues)다. 위키는 이를 연결하는 입구다. [위키 원본과 발행 방법](README.md)에서 갱신 규칙을 확인한다.

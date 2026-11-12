# OSS 조사와 비교 실험

[위키 홈](Home.md) · 원본: [후보 조사](../RESEARCH.md), [OSS 아키텍처 비교](../OSS-ARCHITECTURE-COMPARISON.md)

## 오픈소스에서 무엇을 가져올 것인가

Backstage의 카탈로그, Flux의 원본 확인, Crossplane의 자원 제어, 관측·코드 분석·보안 생태계를 같은 사용자 질문과 반례로 비교한다. 제품 목록이나 화면 유사성만으로 채택하지 않는다. **버전이 맞는 근거 연결·지속 갱신·에이전트 조회에서 우리가 책임질 부분**을 검토한다.

| 자료 | 확인할 내용 |
| --- | --- |
| [OSS 구조 비교](../OSS-ARCHITECTURE-COMPARISON.md) | 12개 계열의 책임·경계, 재사용 후보, 게시판 검증 계획 |
| [공식 원문·버전·라이선스 스냅샷](../OSS-SOURCE-SNAPSHOT.md) | 관련 15개 저장소의 조사 시점과 미확인 항목 |
| [후보 조사](../RESEARCH.md) | 정적 분석·계측·관측 도구와 확인할 호환성·비용 |
| [실험 계획](../experiments/ARCHITECTURE-EXPERIMENTS.md) | 같은 입력·계약·판정으로 방법론과 아키텍처를 비교하는 조건 |

조사 시점의 근거와 현재 릴리스는 다를 수 있다. 실제 채택 전에는 공식 원문·지원 버전·라이선스·운영 조건을 다시 확인한다. 조사 문서와 실험 코드의 존재는 제품 채택을 뜻하지 않는다.

## 실행한 비교와 한계

갱신 전략은 주기 확인, 변경 알림, 두 방식의 결합을 비교한다. 두 번째 실험에서는 같은 프로세스 안에서 실행하는 구성과 별도 프로세스를 한 번 띄워 실행하는 구성도 비교한다.

| 실험 | 재현·결과 | 검증 범위 |
| --- | --- | --- |
| 합성 공급원 갱신 전략 | [실험실](../../experiments/architecture_lab/README.md), [결과](../experiments/RESULTS.md), [T19 #35](https://github.com/DDINGJOO/JJAM-TONG/issues/35) | 16개 시나리오 × 3방식, 48회 실행·66개 체크포인트·목표 미달 13개. 같은 SQLite의 로컬 합성 비교 |
| 원본 재확인·알림·실행 경계 | [실험실](../../experiments/reconciliation_lab/README.md), [설계·판정](../experiments/HYBRID-RECONCILIATION.md), [결과](../experiments/HYBRID-RESULTS.md), [T20 #36](https://github.com/DDINGJOO/JJAM-TONG/issues/36) | 실제 임시 Git, 같은 장비 안에서 주고받는 loopback HTTP, 공개 GitHub GET. 갱신 전략 3개 × 실행 구성 2개 × 3회 반복, 총 18회 실행·144개 체크포인트·목표 미달 24개 |

두 번째 비교에서 두 전략을 결합한 hybrid는 정해진 체크포인트의 현재 상태 목표를 충족했지만, **세 방식 모두 일부 중간 커밋을 관측하지 못해 이력에 공백이 남았다.** 반복된 체크포인트는 독립적인 실제 장애나 운영 서비스 수준 목표(SLO)를 입증하는 표본이 아니다. HTTP 429(호출 제한)·부분 응답은 같은 컴퓨터 안에서 통신하는 테스트 서버에 주입했고, 연결 회수는 로컬 설정 전환으로 재현했다. 실제 GitHub 웹훅 등록이나 App 권한 회수, 클라우드 환경을 검증한 결과와는 구분한다.

테스트 결과와 도구 버전·명령·판정 원본은 각 결과 문서에 있다. 실제 메서드 분석·계측, 빌드 정보와 요청 추적 기록(trace)의 연결, AWS/Kubernetes·CMDB·SIEM 지원, 전체 BDD의 수락은 아직 검증하지 않았다.

## 후속 비교

- [T21 #37](https://github.com/DDINGJOO/JJAM-TONG/issues/37): 실제 공급원별 수집·권한·복구 정책, 호출 예산과 상시 worker.
- [T22 #38](https://github.com/DDINGJOO/JJAM-TONG/issues/38): 버전 근거의 보관·과거 조회, 실제 코드 분석과 계측의 비교 조건.

새 실험은 기대 결과·실패 판정·버전·입력·명령·실제 결과·한계를 남기고 [설계 결정](Architecture-and-Decisions.md)과 다음 이슈에 연결한다. 성공한 항목만 골라 기록하지 않는다.

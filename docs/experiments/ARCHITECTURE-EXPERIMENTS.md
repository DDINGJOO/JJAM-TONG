# 구현 방법론·아키텍처 비교 실험

상태: **첫 로컬 비교 구현·실행 / 제품 아키텍처 미채택 · 2026-11-12**.

작업 계층: [E05 #33](https://github.com/DDINGJOO/JJAM-TONG/issues/33) → [S10 #34](https://github.com/DDINGJOO/JJAM-TONG/issues/34) → [실험실 T19 #35](https://github.com/DDINGJOO/JJAM-TONG/issues/35) / [실제 연동 후속 T20 #36](https://github.com/DDINGJOO/JJAM-TONG/issues/36). 기존 요구사항 이슈와 별도 실험 milestone으로 관리한다.

사용자 요청은 다양한 방법론과 아키텍처를 같은 시나리오에 대입해 구축·비교하는 것이다. 제품의 전체 범위와 모노레포 방향을 유지하며, 대안별 실행 결과·한계·미검증 조건으로 기술 선택을 토론한다. 이번에는 자동 갱신을 세 가지 방식으로 구현했고 나머지 비교 축은 후속 실험으로 분리했다.

## 방법론을 적용하는 책임

| 방법론·설계 방식 | 적용할 역할 | 확인할 산출물 |
| --- | --- | --- |
| BDD·ATDD | 사용자 시나리오와 정상·실패·반례의 독립 기대값을 먼저 명세 | BDD ID, 합성 입력, 판정, 실제·기대 차이 |
| DDD의 영역 경계 | 코드·배포·자산·보안의 식별·소유권·용어를 구분 | 논리 서비스·build·artifact·resource·탐지의 별도 의미 |
| 포트·어댑터 분리 | 공급원·트리거를 바꾸면서 조회 의미를 비교 | 같은 Source/Store/조회 계약으로 동작하는 세 갱신 전략 |
| 트랜잭션·durable inbox | 수신 완료와 반영 완료를 구분하고 재시작에 대응 | 저장 직후·트랜잭션 도중 프로세스 종료와 재처리 결과 |
| 진화적 설계·비교용 spike | 한 축씩 구현해 가설을 수정하고 ADR 근거 축적 | 교체 가능한 실험, 입력 hash, 결과·제약·다음 질문 |

위 방식들은 서로 다른 책임에 적용한다. 이번 실험은 전체 도메인 모델이나 플러그인 프레임워크를 구현한 것이 아니다. CQRS는 읽기/쓰기 모델 분리를 다루고 이벤트 소싱은 변경 이력을 상태의 원장으로 삼는 선택이다. 이벤트 수신기를 두었다는 사실만으로 완전한 이벤트 소싱을 구현했다고 보지 않는다. [CQRS 공식 설명](https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs), [Event Sourcing 공식 설명](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing).

## 비교 축과 구축 순서

| 축 | 대안 | 같은 조건에서 비교할 시나리오 | 현재 근거 |
| --- | --- | --- | --- |
| 자동 갱신 | 주기적 전체 조회 / 이벤트 / 이벤트와 원본 재확인 | 누락·중복·역순·부분 조회·조회 장애·재시작·짧은 중간 변경 | **세 방식 구현·16개 시나리오 실행** |
| 근거 보관·조회 | 중앙 보관 / 원본 연합 조회 / 최소 이력과 원본 adapter | 원본 중단·만료·권한 회수·과거 재현·조회 지연 | [OSS 구조 비교](../OSS-ARCHITECTURE-COMPARISON.md)의 A/B/C 대안과는 별도 축; 미실행 |
| 프로세스·플러그인 | 모듈형 단일 backend / 독립 worker / 영역별 서비스 | plugin 장애·업그레이드·독립 확장·분산 context·자원 상한 | 모노레포에서 모두 구성 가능; 분산 비교 미실행 |
| 관계 저장 | 버전 테이블·관계 인덱스 / 그래프 저장 / 혼합 | 다중 hop·과거 시점·공유 자원·삭제·권한 필터·재색인 | 현재 SQLite 하나를 통제 조건으로 사용; DB간 비교 미실행 |
| 코드 분석·계측 | 정적 분석기별 호출 후보 / OTel 확장 등 실제 실행 계측 / 프로파일 결합 | private/self-call·인터페이스·reflection·async·동일 commit의 다른 artifact | 현재 코드 지도·trace는 합성 입력; 실제 계측 비교 미실행 |
| 인프라·보안 수집 | 원본 API / 현장 agent·collector / 기존 inventory·SIEM adapter | EKS·ECS·일반 Kubernetes·온프레미스·권한 차이·연결 단절 | 소스의 의미만 합성; 실제 환경 미실행 |
| 운영 실행 | 작업 큐 / 지속 workflow / 상태 재조정 controller | 중복 요청·부분 실행·재시도·승인·취소·감사·되돌리기 | 실행 계약을 추가 명세할 단계; 실제 변경 미실행 |

처음부터 모든 조합을 곱하지 않는다. 공통 계약을 고정하고 한 축을 바꾸어 원인을 분리한 뒤, 유망한 조합을 같은 게시판 흐름으로 통합한다. 실제 OSS를 설치할 실험에서는 버전·라이선스·설정·의존 서비스·권한·자원 예산을 먼저 적고 채택 결정과 실험 환경을 구분한다.

## 첫 실험의 공통 조건

- 구현: [architecture_lab](../../experiments/architecture_lab/README.md), Python 표준 라이브러리와 로컬 SQLite. 세 방식은 같은 Source·Store·조회 코드, 최초 snapshot과 입력을 사용한다.
- 주기: 5 logical tick마다 전체 원본 조회. tick은 시뮬레이션 순서이며 실제 초나 SLO로 환산하지 않는다. 원본 page 크기는 2개다.
- `poll`: 원본 조회로만 자동 갱신한다. 최초 snapshot 이후 이벤트를 소비하지 않는다.
- `events`: 최초 snapshot 이후 이벤트를 durable inbox에 기록해 반영한다. 유실된 이벤트의 원본 조회 fallback을 몰래 추가하지 않는다.
- `hybrid`: 같은 이벤트 경로와 같은 주기의 원본 재확인을 함께 사용한다. 추가 조회 비용과 이력 복구의 한계도 기록한다.
- 각 실행은 별도 SQLite 파일을 쓰고 부하 입력·조회 주기·최종 갱신 예산을 동일하게 둔다. 데이터량·권한 모델·스토리지·분석 알고리즘을 동시에 바꾸지 않는다.

원본 이벤트 revision은 합성 공급원의 순서 번호다. Git commit에 숫자 순서가 있다고 가정하지 않는다. 실제 공급원의 snapshot watermark·원본 참조·계보·동시 쓰기 충돌은 후속 계약이다.

## 입력·판정과 시간 의미

합성 게시판의 두 서비스, 같은 commit의 두 build·artifact, 코드 지도·실행·배포, 공유 DB·담당자·보안 탐지 입력을 사용한다. [시나리오 JSON](../../experiments/architecture_lab/fixtures/scenarios.json)에 각 조작과 독립 기대값을 보관한다. 공급원과 빌드 관련 ID는 실제 자원이나 코드 분석 결과가 아니다.

판정을 두 종류로 나눈다.

1. **안전성·계약 위반**: 다른 build 결합, 중복 오염, 부분 조회의 잘못된 공개, 현재 권한을 넘는 조회 등은 assertion으로 실행을 실패시킨다. 정상 서비스 등록과 두 build의 성공 조회도 강제한다. 빈 결과만 반환해 통과할 수 없다.
2. **갱신·이력 목표 미달**: 체크포인트의 독립 기대값과 실제 관측 결과를 비교해 그대로 보고한다. 주기 전 반영 지연이나 유실된 중간 변경을 숨기지 않으며, 목표 미달을 모두 코드 버그로 간주하지 않는다.

`event_before`는 원본 event 시각으로 제한하고 `known_before`는 플랫폼 기록 시각으로 제한한다. 기록에 없는 중간 상태를 만들어내지 않는다. 반환값은 필터 조건에서 확인한 마지막 근거이며 실제 자산 상태의 연속적인 유효 구간을 증명하지 않는다. 이 실험에서 이력 완전성을 인증하거나 모든 bitemporal 요구를 구현한 것은 아니다.

삭제는 명시적인 tombstone만 반영한다. 완전한 snapshot의 부재를 자동 삭제로 판정하는 기능은 구현하지 않았다. 권한은 합성 scope 단위이며 연결 수집 범위와 조회 범위를 따로 둔다. 실제 GitHub 권한 확인, field/edge 수준의 권한 전파, 다중 tenant 운영은 후속 실험이다.

## 실행 결과와 결론 범위

[실제 결과표](RESULTS.md)와 [입력 hash·환경·관측값 JSON](run-snapshot.json)을 공개한다. 16개 시나리오 × 3개 방식 = **48개 실행**, 별도 계약·장애·판정 테스트 **9개**를 수행했다. 17개 기존 BDD ID의 일부 조건을 연결했으며 **BDD 47개 전체를 실행·통과한 결과는 아니다**.

- 정상 이벤트는 이벤트·혼합 방식에서 즉시 반영됐다. 주기적 조회는 설정한 주기가 지난 뒤 반영됐다.
- 이벤트 하나가 유실되면 원본 조회가 있는 방식은 현재 상태를 회복했다. 원본 조회가 중단돼도 이벤트가 도착하는 경우에는 이벤트 경로가 갱신을 이어갔다.
- 조회 사이에 나타났다 사라진 담당자 변경은 현재 snapshot만 읽는 방식에서 확인하지 못했다. 이벤트도 함께 유실되면 **혼합 방식 역시 중간 이력을 복원하지 못했다**. 감사 원장·재전송 보존·이력 API가 추가로 필요한지 판단할 근거다.
- 동일 입력의 로컬 200회 변경에서 원본 조회/페이지 수는 poll 42/210, events 1/5, hybrid 42/210이었다. 보존한 근거 revision은 각각 51·210·210개다. 이 수치는 해당 입력과 일정의 관측값이며 외부 API 요금·실제 시스템 성능으로 환산하지 않는다.
- 체크포인트 목표 미달은 총 13개다. 원인은 주기 전 지연, 원본 조회 장애, 누락 이벤트, 복원할 수 없는 중간 이력으로 결과표에 드러난다. 혼합 방식의 목표 미달도 그대로 남겼다.

시나리오의 restart는 SQLite 연결과 engine 객체 재생성이다. 추가 테스트에서는 실제 자식 프로세스를 `os._exit`로 종료하고, 부모 프로세스가 inbox 저장 직후와 미커밋 projection을 복구하는지 확인했다. OS 재부팅·전원 장애·디스크 손상·다중 worker 경합·분산 broker의 exactly-once 보장은 시험하지 않았다.

SQLite transaction은 실험 내 inbox와 projection 처리 완료를 원자적으로 묶는 데 사용했다. 외부 API 호출까지 같은 transaction으로 보장한 것이 아니다. [SQLite 트랜잭션 공식 설명](https://www.sqlite.org/transactional.html).

## 후속 실험의 선택 기준

다음 비교는 실제 공급원 연결과 실행 경계를 한 축씩 바꾸는 작업이다. 원본 재확인·이력 손실을 먼저 드러냈으므로, 실제 GitHub adapter와 수신·worker 분리에서 같은 X01~X16 입력을 재생할 수 있는 계약을 우선 검토한다. 이후 동일 질문으로 데이터 보관·조회 방식과 코드 분석·계측을 비교한다. 구체적인 제품·언어·DB·broker는 아직 선택하지 않았다.

후속 실험마다 다음을 채운다.

- 가설·반대 가설, 대안별 통과해야 할 질문과 유리·불리한 장애 조건.
- 공급원·버전·라이선스·지원 환경·설치 및 제거 절차·실제 설정·소요 자원.
- 독립 기대 관계·누락·오연결·권한 누출, 복구 지연·보존량·원본 호출량·앱 영향.
- 반복 측정의 조건·표본·노이즈, 실패·미지원·미실행 결과와 재현 명령.
- 실험 결과로 수정할 요구사항과 ADR 후보. 문서상 예상과 실측값을 별도로 표기.

모든 영역의 기능 요구는 유지한다. 이 실험의 Python·SQLite·수신 패턴을 제품 스택으로 확정하지 않는다. 현재 정식 아키텍처 합의나 우위 입증은 없으며 다음 대안을 제외하지 않는다.

## 공식 참고 근거

- Kubernetes controller는 현재 상태를 관측하고 목표 상태와 가까워지도록 동작하는 제어 루프다. 원본 재확인의 설계 참고이며 JJAM-TONG이 Kubernetes에서만 실행된다는 결정은 아니다. [Controllers](https://kubernetes.io/docs/concepts/architecture/controller/) (2026-11-12 확인).
- GitHub는 실패한 webhook을 자동 재전송하지 않는다고 설명한다. 유실·재전송·원본 재확인을 비교하는 실제 동기다. [Redelivering webhooks](https://docs.github.com/en/webhooks/testing-and-troubleshooting-webhooks/redelivering-webhooks) (2026-11-12 확인).
- Backstage는 단일 backend에 여러 plugin을 두거나 여러 backend로 나누는 구성을 설명한다. 모노레포·모듈·프로세스 경계를 별도 축으로 비교하는 참고다. [Backend Plugins](https://backstage.io/docs/backend-system/architecture/plugins/) (2026-11-12 확인).
- SootUp callgraph의 진입점·type hierarchy·CHA/RTA와 OTel Java agent 확장 방식은 실제 코드 분석·계측의 비교 입력이다. 이번 합성 코드 지도는 해당 제품을 실행한 결과가 아니다. [SootUp callgraphs](https://soot-oss.github.io/SootUp/latest/callgraphs/), [OTel extensions](https://opentelemetry.io/docs/zero-code/java/agent/extensions/) (2026-11-12 확인).

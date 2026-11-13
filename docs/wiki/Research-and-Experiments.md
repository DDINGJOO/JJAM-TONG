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

[버전별 메서드 근거 저장 공통부](../experiments/VERSIONED-EVIDENCE-STORE.md)는 DB 비교 후 진행한 첫 로컬 구현이다. [ADR 0005](../decisions/0005-local-versioned-evidence-store.md)에 따라 PostgreSQL에 원본 분석과 분석기별 관계를 원자적으로 보관하고 그래프 조회 계약을 분리했다. 계약·실제 PostgreSQL 경로·기존 trace 회귀 시험 38개가 통과했다. 두 Java 빌드 × 두 분석기의 그래프를 원본 관계와 대조했고, 기존 trace가 이전 빌드에서만 연결됨을 확인했다. DB 재시작 후 재조회도 수행했다. 기업 인증·인가·대체 그래프 엔진·지속 수용량은 앞으로 검증한다. [구현·명령](../../tools/evidence_store/README.md)과 [원시 결과](../experiments/versioned-evidence-store-replay.json)를 연결한다.

[버전별 코드 그래프 규모 비교](../experiments/GRAPH-SCALE-COMPARISON.md)는 PostgreSQL과 Neo4j에 빌드당 메서드 1만·10만 개, 기본 호출 2개·6개, 이전·새 빌드를 넣어 조회했다. 두 조회 방식과 동시 클라이언트 1·4·8개를 실행했고, 최종 실행의 순차 조회 3,888건·동시 조회 1,248건이 정답과 일치했다. [구현·재현 명령](../../experiments/graph_scale_lab/README.md)과 [원시 결과](../experiments/graph-scale-run.json)를 연결한다. 빌드당 10만 메서드·기본 호출 6개 조건에서 진입점 6단계의 넓은 순차 조회는 PostgreSQL이, 내부 메서드 12단계의 직접 조회와 여섯 질문을 섞은 짧은 동시 조회는 Neo4j가 더 낮은 지연을 보였다. 이 결과는 10만 메서드 조건 전체나 지속 부하의 우위를 뜻하지 않으므로 질문별로 판단한다. 첫 실행의 시간 초과 코드 분류 실패와 수정·전체 재실행도 남겼다. 합성 관계·단일 노드·서로 다른 클라이언트·재사용한 볼륨의 짧은 표본이며 제품 DB 채택·실제 코드 그래프·지속 수용량은 앞으로 검증한다.

[원본 책임별 구성 비교](../experiments/STORAGE-TOPOLOGY-COMPARISON.md)는 PostgreSQL을 필수 원장으로 두었던 가정을 제거하고, 네 DB의 단독 구성 4개와 방향별 두 DB 조합 12개를 모두 실행했다. 각 원본 DB의 스냅샷에서 조회 모델을 복원했으며, 기능·복구 판정 260개와 조회 정확성 판정 240개가 통과했다. [구현·재현 명령](../../experiments/storage_topology_lab/README.md)과 [원시 결과](../experiments/storage-topology-run.json)에서 실제 중단·재처리·버전 혼입·동시 발행 시험을 확인할 수 있다. 단일 발행자 기능 판정과 여러 발행자의 고유성 보장은 분리한다. 고유성 시험은 12개 구성이 통과했고, ClickHouse 원본 4개 구성은 현재 일반 MergeTree 어댑터에서 `unsupported`로 기록했다. 별도 단위 시험은 기존 23개·추가 13개로 총 36개가 통과했다. 작은 합성 입력·정상 중단/재시작·전체 데이터 대조 방식의 실험이며, 전체 플랫폼의 수용량·고가용성·권한·물리 삭제와 DB 채택은 앞으로 검증한다.

[버전 근거·그래프·검색·집계의 DB 비교](../experiments/STORAGE-ENGINE-COMPARISON.md)는 PostgreSQL·Neo4j·Elasticsearch·ClickHouse를 같은 합성 입력으로 실행한다. [구현과 재현 명령](../../experiments/storage_lab/README.md), [원시 표본](../experiments/storage-engine-run.json)에서 버전 분리·관계 조회·검색·집계·짧은 동시 부하와 실제 중단·복구를 확인할 수 있다. PostgreSQL 원장과 세 읽기 모델의 재처리, PostgreSQL·Neo4j·Elasticsearch 통합 조회도 시험했다. 제품 DB 채택·기업 권한 격리·지속 수용량·고가용성은 앞으로 검증한다. 기존 보관 방식 비교 T24나 라이브러리 적용 T25의 완료와는 구분한다.

이 비교는 단일 노드·공유 호스트에서 수행했다. 서버의 CPU 상한은 1개로 맞췄지만 메모리 상한은 384~1,536 MiB로 다르며, PostgreSQL은 Psycopg 연결, 나머지는 HTTP 어댑터를 썼다. 동시 조회도 1·4·8개 클라이언트가 각각 12회 수행한 짧은 표본이므로 엔진 성능 순위나 지속 수용량을 입증하지 않는다.

기존 엔진 비교의 결과는 같은 실행 ID·커밋·소스 해시와 필수 시험의 완료 여부를 확인한 뒤 묶는다. 재구축 전에는 기존 소비자의 완료 위치를 무효화하고 새 소비자의 완료 위치와 실제 데이터를 함께 확인한다. 이 실험의 통합 조회는 요청과 원장의 artifact 일치만 확인한다. 후속 구성 비교에서는 조회 모델에 다른 artifact를 넣는 반례도 실행하며, 이를 기존 통합 조회 경로의 검증으로 소급하지 않는다.

갱신 전략은 주기 확인, 변경 알림, 두 방식의 결합을 비교한다. 두 번째 실험에서는 같은 프로세스 안에서 실행하는 구성과 별도 프로세스를 한 번 띄워 실행하는 구성도 비교한다.

| 실험 | 재현·결과 | 검증 범위 |
| --- | --- | --- |
| 합성 공급원 갱신 전략 | [실험실](../../experiments/architecture_lab/README.md), [결과](../experiments/RESULTS.md), [T19 #35](https://github.com/DDINGJOO/JJAM-TONG/issues/35) | 16개 시나리오 × 3방식, 48회 실행·66개 체크포인트·목표 미달 13개. 같은 SQLite의 로컬 합성 비교 |
| 원본 재확인·알림·실행 경계 | [실험실](../../experiments/reconciliation_lab/README.md), [설계·판정](../experiments/HYBRID-RECONCILIATION.md), [결과](../experiments/HYBRID-RESULTS.md), [T20 #36](https://github.com/DDINGJOO/JJAM-TONG/issues/36) | 실제 임시 Git, 같은 장비 안에서 주고받는 loopback HTTP, 공개 GitHub GET. 갱신 전략 3개 × 실행 구성 2개 × 3회 반복, 총 18회 실행·144개 체크포인트·목표 미달 24개 |

두 번째 비교에서 두 전략을 결합한 hybrid는 정해진 체크포인트의 현재 상태 목표를 충족했지만, **세 방식 모두 일부 중간 커밋을 관측하지 못해 이력에 공백이 남았다.** 반복된 체크포인트는 독립적인 실제 장애나 운영 서비스 수준 목표(SLO)를 입증하는 표본이 아니다. HTTP 429(호출 제한)·부분 응답은 같은 컴퓨터 안에서 통신하는 테스트 서버에 주입했고, 연결 회수는 로컬 설정 전환으로 재현했다. 실제 GitHub 웹훅 등록이나 App 권한 회수, 클라우드 환경을 검증한 결과와는 구분한다.

테스트 결과와 도구 버전·명령·판정 원본은 각 결과 문서에 있다. 위 두 갱신 실험은 메서드 분석·계측이나 빌드와 요청 추적 기록(trace)의 연결을 검증하지 않는다. 그 후속 실험은 아래에 구분한다. AWS/Kubernetes·CMDB·SIEM 지원과 전체 BDD 수락은 아직 검증하지 않았다.

## 후속 비교

- [T21 #37](https://github.com/DDINGJOO/JJAM-TONG/issues/37): 실제 공급원별 수집·권한·복구 정책, 호출 예산과 상시 worker.
- [T22 #38](https://github.com/DDINGJOO/JJAM-TONG/issues/38): [버전 근거의 보관·과거 조회](../experiments/VERSIONED-EVIDENCE-COMPARISON.md), [실제 코드 분석·계측 후보와 비교 조건](../experiments/CODE-ANALYSIS-COMPARISON.md).

세 보관 방식의 보존 범위와 같은 커밋의 다른 빌드·원본 중단·권한 회수 등을 [합성 입력·20개 사례의 예상 판정](../experiments/evidence-query-cases.json)으로 정했다. 예상 응답 60개는 실제 실행 결과가 아니다. 코드 후보는 고정 버전의 공식 원문·라이선스·호환성 조건을 확인했으며, 파서의 선언 해석과 호출 그래프, 기본 자동 계측과 선택 메서드 계측을 구분한다. 일부 후보의 실제 구현·측정은 아래 후속 결과로 연결하며 제품 채택은 미결이다.

실제 실행은 [보관·조회 비교 T24 #43](https://github.com/DDINGJOO/JJAM-TONG/issues/43)과 [외부 프로젝트의 라이브러리 로컬 검증 T25 #44](https://github.com/DDINGJOO/JJAM-TONG/issues/44)로 이어간다. 첫 구현물은 재사용할 라이브러리와 연동 도구이며, 관측 대상 앱은 별도 저장소에서 관리한다. 두 태스크의 상태와 선행 조건은 이슈에서 관리한다.

새 실험은 기대 결과·실패 판정·버전·입력·명령·실제 결과·한계를 남기고 [설계 결정](Architecture-and-Decisions.md)과 다음 이슈에 연결한다. 성공한 항목만 골라 기록하지 않는다.

## 첫 라이브러리 구현

[빌드 식별 계약 라이브러리](../../libraries/evidence-contract-java/README.md)는 외부 의존성 없는 Java JAR로 만들었다. JDK 17·21에서 각 23개 계약 검증을 통과했으며, JDK 17 JAR을 JDK 21 소비자가 사용하는 검증도 통과했다. [ADR 0002](../decisions/0002-experimental-build-identity.md)와 [실행 기록](../experiments/library-contract-results.json)에 범위와 조건을 남긴다. 메타데이터의 일치를 확인하는 공통부이며 자동 메서드 분석·실행 수집 완료를 뜻하지 않는다. 사용자 요청에 따라 실제 Kafka·Redis·PostgreSQL을 쓰는 합성 MSA 대상도 별도 로컬 저장소에 만들었다. [외부 앱 적용·장애 복구 9개 시나리오와 실행 한계](../experiments/LOCAL-MSA-TARGET.md)를 확인할 수 있다.

가상 스레드·Netty·Kafka를 함께 다루는 [실행 모델과 이벤트 경계 조건](../experiments/CODE-ANALYSIS-COMPARISON.md#실행-모델과-이벤트-경계도-함께-검증한다) 중 일부를 [별도 모듈의 21개 로컬 검증](../experiments/EXECUTION-MODEL-RESULTS.md)으로 실행했다. 수동 문맥 유지·누락 탐지, Kafka 재시도·중복, DB 대기·작업 상한과 타임아웃을 확인했다. 별도 JDK 21·25 입력의 pinning 결과도 남겼다. [ADR 0003](../decisions/0003-execution-model-comparison.md)에 실험 경계를 기록하며, 기존 게시판 9개 검증·자동 계측·전체 BDD와 구분한다.

## 정적 후보와 자동 실행 근거의 첫 연결

[JavaParser·WALA 어댑터](../../tools/java-call-analysis/README.md)와 [버전별 근거 연결 CLI](../../tools/method_evidence/README.md)를 만들고, 별도 Java 대상에서 [124개 기능 실행·30회 비용 측정·빌드/이력 반례](../experiments/METHOD-OBSERVABILITY-RESULTS.md)를 확인했다. private 호출·비동기 문맥·재귀·오류를 관측하고 정적 후보와 실제 부모 관계를 따로 보관한다. OTel의 descriptor 부재로 정확한 overload 실행 선언은 미해결이며, 실제 부분 재분석과 전체 BDD 통과로 처리하지 않는다. [ADR 0004](../decisions/0004-method-evidence-comparison.md)는 이번 비교와 제품 채택을 구분한다.

별도로 [실제 Boot·가상 스레드·Netty·Kafka의 3개 흐름](../experiments/METHOD-OBSERVABILITY-RESULTS.md#실제-boot가상-스레드nettykafka에도-적용했다)에도 OTel을 붙였다. 테스트 앱의 trace 플래그 파서를 수정한 새 빌드에서 앱 처리는 성공했으나, HTTP→예약 outbox 발행의 SDK 추적은 분리됐다. Redis 왕복 성공과 Redis 전용 span 미관측도 구분해 남겼다.

## 적용 전후 성능은 얼마나 다른가

같은 Boot 빌드에서 미적용·기본 추적·메서드 추적을 [27회 반복 비교](../experiments/EXECUTION-PERFORMANCE-RESULTS.md)했다. 지연·처리량·CPU·메모리·기동 시간, 원시 측정값과 한계를 남겼다. 기존 버전 계약·수동 검증 코드가 공통으로 있는 앱에 OTel을 추가한 비용이며, 전체 플랫폼 비용이나 운영 SLO를 확정한 결과는 아니다.

## 서비스와 플랫폼은 어디까지 감당하는가

[수용량·과부하·복구 검증 계획](../experiments/CAPACITY-VALIDATION.md)은 업무 서비스의 계측 전후 한계와 JJAM-TONG의 수집·분석·조회 한계를 나누어 검증할 요구다. 부하 발생기의 제한, 데이터·버전 규모, 적체·신선도·유실, 정상 부하로 낮춘 뒤의 복구를 포함한다. [BDD-SRE-005~008](../../specs/features/05-sre-analysis.feature)과 [T10 #19](https://github.com/DDINGJOO/JJAM-TONG/issues/19)·[T25 #44](https://github.com/DDINGJOO/JJAM-TONG/issues/44)에 연결하며, 수치 목표와 수용량 실측은 아직 없다.

[엔터프라이즈 운영 조건](../requirements/ENTERPRISE.md)을 수용량 설정에 추가한다. 여러 조직의 혼합 부하에서 권한·암호화·감사를 유지하고, 장애 영역 중단·별도 환경 복원·순차 업그레이드·사이트 재연결을 검증할 계획이다. [BDD-ENT-001~009](../../specs/features/11-enterprise-operations.feature)는 아직 실행하지 않은 명세다.

[자동 확장·축소 검증 조건](../requirements/AUTOSCALING.md)은 고정 용량과 부하 반응형·사전 확보를 같은 입력·목표·기업 정책·공통 예산으로 비교한다. 지표 오류·실제 자원 확보·후속 병목·축소 중 인계/재균형·반복 증감·0개 축소·조직별 영향과 대상 자원 교체의 버전 연결을 포함한다. [BDD-ASC-001~009](../../specs/features/12-autoscaling.feature)는 명세이며 자동 확장·Kubernetes/ECS 배포나 새 부하 실험은 수행하지 않았다.

# OSS 조사와 비교 실험

[위키 홈](Home.md) · 원본: [후보 조사](../RESEARCH.md), [OSS 아키텍처 비교](../OSS-ARCHITECTURE-COMPARISON.md)

## 오픈소스에서 무엇을 가져올 것인가

Backstage의 카탈로그, Flux의 원본 확인, Crossplane의 자원 제어, 관측·코드 분석·보안 생태계를 같은 사용자 질문과 반례로 비교한다. 제품 목록이나 화면 유사성만으로 채택하지 않는다. **버전이 맞는 근거 연결·지속 갱신·에이전트 조회에서 우리가 책임질 부분**을 검토한다.

| 자료 | 확인할 내용 |
| --- | --- |
| [OSS 구조 비교](../OSS-ARCHITECTURE-COMPARISON.md) | 12개 계열의 책임·경계, 재사용 후보, 게시판 검증 계획 |
| [Datadog·Elastic 비교](../OSS-ARCHITECTURE-COMPARISON.md#9-datadog과-elastic은-코드와-실행을-어떻게-연결하는가) | 소스·배포 버전 연결, 메서드 계측·추정의 차이, 가상 스레드·Graph·과거 조회의 조건 |
| [공식 원문·버전·라이선스 스냅샷](../OSS-SOURCE-SNAPSHOT.md) | 관련 15개 저장소의 조사 시점과 미확인 항목 |
| [후보 조사](../RESEARCH.md) | 정적 분석·계측·관측 도구와 확인할 호환성·비용 |
| [실험 계획](../experiments/ARCHITECTURE-EXPERIMENTS.md) | 같은 입력·계약·판정으로 방법론과 아키텍처를 비교하는 조건 |

조사 시점의 근거와 현재 릴리스는 다를 수 있다. 실제 채택 전에는 공식 원문·지원 버전·라이선스·운영 조건을 다시 확인한다. 조사 문서와 실험 코드의 존재는 제품 채택을 뜻하지 않는다.

## 실행한 비교와 한계

[서비스 소스 탐색](../../tools/service_analysis/README.md)은 API·메서드별 정적 후보를 읽는 로컬 경로다. 수집한 선언은 보존하되 기본 목록에서는 생성자·단순 접근자·고립된 비 API 선언을 숨기고, private 표시는 화면에서 전환한다. 호출 위치의 분기 문맥은 실행 사실과 구분한다. 작업과 검증 근거는 [#83](https://github.com/DDINGJOO/JJAM-TONG/issues/83)에 연결한다. 이 경로는 소스 선언의 분석본을 조회하며 배포 산출물·실행 기록과의 일치를 보장하지 않는다.

[빌드 명세·기준선 비교](../experiments/BUILD-INVENTORY-RESULTS.md)는 정적 후보 발견과 파일 검증, 선언 의존 관계 비교를 분리한다. 단위 시험 44개와 합성·공개 대상 판정 15건을 통과했다. 완전한 컴파일 입력이 없는 두 공개 빌드는 부분 상태로 남겼다. [도구](../../tools/build_inventory/README.md)·[계약](../requirements/BUILD-INVENTORY.md)·[#78](https://github.com/DDINGJOO/JJAM-TONG/issues/78)을 연결하며 실제 배포·Trace나 과거 정답표 전체의 검증으로 확대하지 않는다.

[근거의 식별자·시간 모델 실험](../experiments/EVIDENCE-MODEL-RESULTS.md)은 현재 PostgreSQL의 세 테이블과 별도로 코드·실행·배포·자원의 논리 계약을 검증했다. 새 단위 시험 21개와 기대값이 독립적인 합성 시나리오 13개가 통과했다. 기존 합성 Java 분석 두 개를 읽기 전용 트랜잭션으로 원본 전체와 대조하고, 빌드·분석·설정이 다른 선택 16건을 거부했다. 연결부는 여섯 종류의 메타데이터 참조만 만들며 제공되지 않은 서비스·배포·실행은 생성하지 않는다. [논리 모델](../requirements/EVIDENCE-MODEL.md)·[ADR 0012](../decisions/0012-evidence-identity-time-model.md)·[합성 판정](../experiments/evidence-model-results.json)·[DB 읽기 판정](../experiments/evidence-model-store-verification.json)을 연결한다. 실제 인증·인가·수집·용량·저장소 이관과 화면 연결은 앞으로 검증한다.

[버전별 메서드 근거 저장 공통부](../experiments/VERSIONED-EVIDENCE-STORE.md)는 DB 비교 후 진행한 첫 로컬 구현이다. [ADR 0005](../decisions/0005-local-versioned-evidence-store.md)에 따라 PostgreSQL에 원본 분석과 분석기별 관계를 원자적으로 보관하고 그래프 조회 계약을 분리했다. 계약·실제 PostgreSQL 경로·기존 trace 회귀 시험 38개가 통과했다. 두 Java 빌드 × 두 분석기의 그래프를 원본 관계와 대조했고, 기존 trace가 이전 빌드에서만 연결됨을 확인했다. DB 재시작 후 재조회도 수행했다. 기업 인증·인가·대체 그래프 엔진·지속 수용량은 앞으로 검증한다. [구현·명령](../../tools/evidence_store/README.md)과 [원시 결과](../experiments/versioned-evidence-store-replay.json)를 연결한다.

[버전별 코드 그래프 규모 비교](../experiments/GRAPH-SCALE-COMPARISON.md)는 PostgreSQL과 Neo4j에 빌드당 메서드 1만·10만 개, 기본 호출 2개·6개, 이전·새 빌드를 넣어 조회했다. 두 조회 방식과 동시 클라이언트 1·4·8개를 실행했고, 최종 실행의 순차 조회 3,888건·동시 조회 1,248건이 정답과 일치했다. [구현·재현 명령](../../experiments/graph_scale_lab/README.md)과 [원시 결과](../experiments/graph-scale-run.json)를 연결한다. 빌드당 10만 메서드·기본 호출 6개 조건에서 진입점 6단계의 넓은 순차 조회는 PostgreSQL이, 내부 메서드 12단계의 직접 조회와 여섯 질문을 섞은 짧은 동시 조회는 Neo4j가 더 낮은 지연을 보였다. 이 결과는 10만 메서드 조건 전체나 지속 부하의 우위를 뜻하지 않으므로 질문별로 판단한다. 첫 실행의 시간 초과 코드 분류 실패와 수정·전체 재실행도 남겼다. 합성 관계·단일 노드·서로 다른 클라이언트·재사용한 볼륨의 짧은 표본이며 제품 DB 채택·실제 코드 그래프·지속 수용량은 앞으로 검증한다.

[원본 책임별 구성 비교](../experiments/STORAGE-TOPOLOGY-COMPARISON.md)는 PostgreSQL을 필수 원장으로 두었던 가정을 제거하고, 네 DB의 단독 구성 4개와 방향별 두 DB 조합 12개를 모두 실행했다. 각 원본 DB의 스냅샷에서 조회 모델을 복원했으며, 기능·복구 판정 260개와 조회 정확성 판정 244개가 통과했다. [구현·재현 명령](../../experiments/storage_topology_lab/README.md)과 [원시 결과](../experiments/storage-topology-run.json)에서 실제 중단·재처리·버전 혼입·동시 발행 시험을 확인할 수 있다. 단일 발행자 기능 판정과 여러 발행자의 고유성 보장은 분리한다. 고유성 시험은 12개 구성이 통과했고, ClickHouse 원본 4개 구성은 현재 일반 MergeTree 어댑터에서 `unsupported`로 기록했다. 별도 단위 시험은 기존 23개·추가 13개로 총 36개가 통과했다. 작은 합성 입력·정상 중단/재시작·전체 데이터 대조 방식의 실험이며, 전체 플랫폼의 수용량·고가용성·권한·물리 삭제와 DB 채택은 앞으로 검증한다.

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

## GitHub의 코드 변경을 DB 이력으로 가져온다

[별도 Playground](https://github.com/DDINGJOO/JJAM-TONG-playground)의 `method-fixture`를 Actions에서 분석하고, 로컬 수집기가 성공한 실행의 결과를 검증해 PostgreSQL에 저장하는 경로를 연결했다. 커밋별 메서드 추가·이름 변경·삭제와 이전 관계 보존의 실제 판정은 [검증 결과](../experiments/GITHUB-EVIDENCE-SYNC.md)에 있다. [실행 명령](../../tools/github_evidence_sync/README.md)과 [ADR 0006](../decisions/0006-github-method-evidence-pull.md)을 함께 읽는다.

DB는 로컬 루프백에 두고 Actions에는 DB 접속 권한을 주지 않는다. 수집기는 실행 회차·커밋·artifact와 내부 색인의 해시를 대조하며 최신 버전으로 대체하지 않는다. 첫 연결은 일반 Java JAR의 정적 후보이며, Spring Boot 서비스 전체 분석·trace의 지속 수집·화면 자동 갱신과 구분한다.

## 실제 Boot 서비스의 메서드와 요청을 연결한다

[실제 게시판의 로컬 연결](../experiments/BOOT-METHOD-EVIDENCE.md)에서 Boot 실행 JAR 두 빌드를 분석하고, 실제 등록 요청의 메서드 기록을 같은 빌드의 PostgreSQL 색인과 대조했다. Controller·Service·private 메서드의 유일 후보 연결, 다른 실제 빌드·해시 거부를 확인했다. 같은 이름의 `validate` 시그니처 두 개는 실행 단계에서 미해결로 남겼다. 중첩 타입 식별자 오류를 수정한 새 분석 ID와 재실행 근거도 보존했다. [ADR 0007](../decisions/0007-local-boot-method-evidence.md)과 [구조화한 결과](../experiments/boot-method-evidence-results.json)를 연결한다.

가상 시작점으로 얻은 정적 후보와 실제 span은 구분한다. trace는 외부 부모가 수집되지 않아 `PARTIAL`이며, Boot CI 발행·지속 수집·화면 갱신은 다음 검증 범위다.

## 실제 근거를 화면에서 확인한다

[로컬 근거 화면](../../tools/evidence_web/README.md)에서 DB의 분석본을 선택하고 메서드·정적 호출 후보·저장된 실제 Trace를 확인한다. [화면 시나리오와 QA](../experiments/LOCAL-EVIDENCE-WORKSPACE.md)는 버전 전환·부분 수집·불일치와 크기별 가독성을 함께 검증한다. Trace는 서버 시작 파일의 고정 캡처이며 지속 수집·실시간 갱신과 구분한다. 기존 JJAM-TONG 프로토타입 HTML의 디자인과 메뉴를 실제 조회 화면에 재사용했으며 전체 제품 시안은 `/demo`에서 제공한다. [재사용 QA](../experiments/local-platform-reuse-qa.json)는 실제 조회와 합성 데이터의 구분, 메뉴 탐색과 선택 보존을 확인한다.

## 적용 전후 성능은 얼마나 다른가

같은 Boot 빌드에서 미적용·기본 추적·메서드 추적을 [27회 반복 비교](../experiments/EXECUTION-PERFORMANCE-RESULTS.md)했다. 지연·처리량·CPU·메모리·기동 시간, 원시 측정값과 한계를 남겼다. 기존 버전 계약·수동 검증 코드가 공통으로 있는 앱에 OTel을 추가한 비용이며, 전체 플랫폼 비용이나 운영 SLO를 확정한 결과는 아니다.

## 서비스와 플랫폼은 어디까지 감당하는가

[수용량·과부하·복구 검증 계획](../experiments/CAPACITY-VALIDATION.md)은 업무 서비스의 계측 전후 한계와 JJAM-TONG의 수집·분석·조회 한계를 나누어 검증할 요구다. 부하 발생기의 제한, 데이터·버전 규모, 적체·신선도·유실, 정상 부하로 낮춘 뒤의 복구를 포함한다. [BDD-SRE-005~008](../../specs/features/05-sre-analysis.feature)과 [T10 #19](https://github.com/DDINGJOO/JJAM-TONG/issues/19)·[T25 #44](https://github.com/DDINGJOO/JJAM-TONG/issues/44)에 연결하며, 수치 목표와 수용량 실측은 아직 없다.

[엔터프라이즈 운영 조건](../requirements/ENTERPRISE.md)을 수용량 설정에 추가한다. 여러 조직의 혼합 부하에서 권한·암호화·감사를 유지하고, 장애 영역 중단·별도 환경 복원·순차 업그레이드·사이트 재연결을 검증할 계획이다. [BDD-ENT-001~009](../../specs/features/11-enterprise-operations.feature)는 아직 실행하지 않은 명세다.

[자동 확장·축소 검증 조건](../requirements/AUTOSCALING.md)은 고정 용량과 부하 반응형·사전 확보를 같은 입력·목표·기업 정책·공통 예산으로 비교한다. 지표 오류·실제 자원 확보·후속 병목·축소 중 인계/재균형·반복 증감·0개 축소·조직별 영향과 대상 자원 교체의 버전 연결을 포함한다. [BDD-ASC-001~009](../../specs/features/12-autoscaling.feature)는 명세이며 자동 확장·Kubernetes/ECS 배포나 새 부하 실험은 수행하지 않았다.

## 대규모 코드와 복잡 구조의 분석

[정확 입력 재사용 실험](../experiments/ANALYSIS-REUSE-RESULTS.md)은 실제 JavaParser·WALA로 최초·재사용·변경·독립 전체 분석을 대조한다. 10만 줄의 동일 입력은 재사용했고, 30만 줄 단일 입력은 기존 힙 상한에서 실패했다. 별도 작은 예제에서는 다형성·순환 호출·오버로드·브리지를 구분하고, 리플렉션·람다·메서드 참조의 해석 공백을 확인했다. 독립 단위 세 개의 성공은 실제 얽힌 전체 그래프의 분할 성공과 구분한다. [복잡 구조 요구](../requirements/CODE-ANALYSIS-SCALE.md), [ADR 0008](../decisions/0008-exact-input-analysis-reuse.md), [#61](https://github.com/DDINGJOO/JJAM-TONG/issues/61)에서 다음 검증을 연결한다.

[파서 메모리 후속 검증](../experiments/JAVA-PARSER-MEMORY.md)은 분석기 0.2.1에서 소스 위치를 보존하며 같은 1 GiB 힙으로 30만 줄 합성 입력을 완료했다. 이전 분석기의 기준 본문과 대조했고 패키지·소스 배치를 바꾼 회귀 검사도 수행했다. 40만 줄은 10 MiB 출력 상한으로 발행되지 않았다. 조회 캐시의 32개 제한은 전체 구문 트리·힙·프로세스 메모리의 상한이 아니다. 선택과 탈락한 설정은 [ADR 0009](../decisions/0009-java-parser-retention.md), 작업과 후속 검증은 [#63](https://github.com/DDINGJOO/JJAM-TONG/issues/63)·[#64](https://github.com/DDINGJOO/JJAM-TONG/issues/64)·[#65](https://github.com/DDINGJOO/JJAM-TONG/issues/65)·[#66](https://github.com/DDINGJOO/JJAM-TONG/issues/66)으로 연결한다. 실제 상태는 각 이슈에서 관리한다.

[분석 작업·발행 계약 실험](../experiments/ANALYSIS-JOB-CONTRACT.md)은 같은 합성 근거 6만 건의 단일 파일·분할 발행과 원본 대조, 실패·부분 완료·재시도·시간 초과를 검증했다. 파일당 10 MiB의 단일 파일은 실패했고 분할 방식과 파일당 상한을 바꾼 단일 파일은 성공했다. 전체 예산에는 완료 메타데이터도 포함한다. [ADR 0010](../decisions/0010-analysis-job-publication.md)·[#64](https://github.com/DDINGJOO/JJAM-TONG/issues/64)와 실제 생산자·소비자·화면 전환 [#68](https://github.com/DDINGJOO/JJAM-TONG/issues/68)을 구분한다.

[Java v1 발행 보완](../experiments/JAVA-RESULT-PUBLICATION.md)은 [#68](https://github.com/DDINGJOO/JJAM-TONG/issues/68)의 첫 하위 작업 [#70](https://github.com/DDINGJOO/JJAM-TONG/issues/70)이다. 분석기 0.2.2는 전체 출력을 추가 문자열·바이트 배열로 복제하지 않고 저장 도중 10 MiB를 검사한다. JDK 17/21의 새 발행 검사와 기존 오라클, 실제 합성 Java 결과의 기존 색인 호환과 상한 초과 시 이전 파일 보존을 확인했다. 분할 형식·상한 확대·DB·화면 전환은 아직 완료하지 않았다.

[실제 Java 저장 표현 비교](../experiments/JAVA-PUBLICATION-COMPARISON.md)는 같은 401,023줄 분석의 단일 파일 상한 확대·공백 제거·분할 결과를 비교한다. 생산자 상한만 늘리면 색인에서 다시 실패했고, 공백을 줄인 분석·색인은 기존 10 MiB 이하가 됐다. 분할 결과도 같은 논리 내용과 색인 해시로 복원했다. [ADR 0011](../decisions/0011-java-compact-publication.md)은 로컬 구현에서 공백 제거를 선택했으며, [#72](https://github.com/DDINGJOO/JJAM-TONG/issues/72)의 비교와 [#73](https://github.com/DDINGJOO/JJAM-TONG/issues/73)의 실제 DB·브라우저 검증을 구분한다.

[실제 Java 통합 검증](../experiments/JAVA-COMPACT-INTEGRATION.md)은 분석기 0.2.3으로 각각 401,023줄인 합성 이전·새 빌드의 색인 저장·DB 발행·재조회와 브라우저 탐색을 연결했다. 역사적 생산자의 커밋·기준 해시를 고정해 전체 JSON·소스 위치를 대조하고, 전체 실행 의존성도 기록했다. 화면에서는 메서드 검색·목록 더 보기·상한·빈 결과·해시 오류와 복구·다른 빌드 거부를 직접 확인했다. [원시 결과·화면 판정](../experiments/java-compact-integration-results.json)의 Trace는 QA용 합성 입력이며 실제 요청이나 지속 수집을 뜻하지 않는다. GitHub 모듈 허용 범위와 기존 단계별 예산은 유지한다.

# 오픈소스·인프라 조사

조사 기준일: 2026-11-12. 공식 문서 기반 조사다. 현재는 [요구사항·BDD](requirements/README.md)의 작성·토론과 OSS 아키텍처 비교 단계다. 의존성 채택·실행 실험·호환성·성능·재배포 적합성·보안 감사는 완료하지 않았다.

## 전체 플랫폼의 구조 비교

[OSS 아키텍처 비교](OSS-ARCHITECTURE-COMPARISON.md)에 Backstage·OpenChoreo·OTel·SkyWalking·SootUp·Pyroscope·Cartography·NetBox·Crossplane·Flux·Wazuh·Falco의 책임·흐름·확장·운영 부담을 정리했다. AppMap Java는 추가 라이선스 조건이 있는 별도 참고 사례다. [15개 저장소의 릴리스·라이선스 기록](OSS-SOURCE-SNAPSHOT.md)은 문서 확인과 실행 검증을 구분한다.

우선 검증할 안은 교체 가능한 도구와 JJAM-TONG이 소유하는 버전·시간·권한의 근거 계약이다. 제품 채택을 뜻하지 않는다. 게시판 두 빌드·자동 갱신·자산/보안 이력·권한 반례를 기존 BDD와 연결하고, 제품 기반 확장·전체 중앙 적재·최소 근거와 원본 조회의 대안을 비교했다. 선택은 [D08](DISCUSSIONS.md#d08-oss의-어떤-구조를-재사용하고-무엇을-직접-소유할-것인가)에서 토론한다.

## 조사 질문

기존 도구가 에이전트·SRE의 분석 질문에 필요한 정적 관계·실제 호출·버전·출처·시점·수집 범위를 기계 조회로 제공할 수 있는지 확인한다. 직접 구현할 부분과 연동할 부분, 필요한 운영 인프라를 같은 fixture와 질문으로 비교한다. 화면 기능만으로 적합성을 판단하지 않는다.

## 후보와 근거

| 후보 | 참고·재사용을 검토할 부분 | 확인할 경계 |
| --- | --- | --- |
| AppMap Java | 메서드 호출·코드 구조·요청 기록과 개발·CI 지도 | 미실행 경로의 정적 후보 관계, 상시 운영 수집, 기본 기록 데이터와 라이선스 조건 |
| Apache SkyWalking | agent·수집·APM backend·조회 화면의 통합 | 서비스/endpoint 토폴로지와 전체 메서드 정적 그래프를 구분, 정확한 source/build 연결 |
| SootUp | JVM 정적 분석과 CHA/RTA 호출 그래프 | classpath·진입점·알고리즘별 결과, DI·프록시·reflection의 한계 |
| WALA | 호출 그래프·pointer analysis 비교 후보 | 분석 설정·입력·동적 기능 처리와 현재 앱 조합의 재현성 |
| OTel Java agent·확장 | 기존 라이브러리 계측·context와 앱 메서드 확장 | 기본 계측의 범위, 확장 API 버전, 중복 span·SDK 공존 |
| Byte Buddy 기반 agent | 앱 메서드의 bytecode 계측을 직접 제어하는 기반 | context·classloader·재귀·비동기·오버헤드의 구현 책임 |

AppMap은 가까운 참고 사례지만 문서만으로 이 프로젝트의 정적·운영·버전 결합 요구를 모두 충족한다고 판단하지 않는다. Byte Buddy는 완성된 관측 제품과 구분한다.

## 공식 출처

- AppMap: [Java agent 문서](https://appmap.io/docs/reference/appmap-java), [개발·CI 흐름](https://appmap.io/how-it-works), [Java v1.30.2 라이선스 원문](https://github.com/getappmap/appmap-java/blob/v1.30.2/LICENSE.txt).
- SkyWalking: [공식 구조 설명](https://skywalking.apache.org/docs/main/latest/en/concepts-and-designs/overview/), [저장소](https://github.com/apache/skywalking).
- SootUp: [호출 그래프 문서](https://soot-oss.github.io/SootUp/latest/callgraphs/), [저장소·라이선스](https://github.com/soot-oss/SootUp).
- WALA: [호출 그래프 API](https://wala.github.io/javadoc/com/ibm/wala/ipa/callgraph/package-summary.html), [저장소·라이선스](https://github.com/wala/WALA).
- OTel: [Java agent 확장](https://opentelemetry.io/docs/zero-code/java/agent/extensions/), [메서드 계측](https://explorer.opentelemetry.io/java-agent/instrumentation/methods), [저장소·라이선스](https://github.com/open-telemetry/opentelemetry-java-instrumentation).
- Byte Buddy: [저장소·라이선스](https://github.com/raphw/byte-buddy).

AppMap Java v1.30.2의 원문은 MIT에 **Commons Clause 조건**을 더하므로 단순 MIT 후보로 분류하지 않는다. 다른 후보의 조사상 라이선스 표기는 SkyWalking·OTel·Byte Buddy가 Apache-2.0, SootUp이 LGPL-2.1, WALA가 EPL-2.0이다. 실제 채택 버전과 배포 방식의 조건을 원문·의존성 트리에서 다시 확인한다. 이 표기는 재배포 허용 판단이나 프로젝트 자체의 라이선스 선택을 대신하지 않는다.

## 비교 실험

[T22 #38](https://github.com/DDINGJOO/JJAM-TONG/issues/38)의 [실제 후보 고정 버전·호환성·코드 반례](experiments/CODE-ANALYSIS-COMPARISON.md)와 [버전 근거 보관·조회 조건](experiments/VERSIONED-EVIDENCE-COMPARISON.md)을 추가했다. 공식 원문 확인과 공통 입력·예상 판정 설계이며, 후보 설치·실행이나 기술 채택을 뜻하지 않는다. 파서의 선언 해석과 호출 그래프 분석, 기본 자동 계측과 선택 메서드 계측을 서로 다른 능력으로 비교한다.

| 질문 | 같은 fixture에서 확인할 것 |
| --- | --- |
| 어떤 관계를 찾는가? | overload·private/self-call·인터페이스 구현체·재귀·reflection의 정답/후보/미해결 |
| 실제 실행을 어떻게 얻는가? | 범위 지정, 동기·비동기 부모/링크, 오류, 원래 결과·예외 보존 |
| 코드가 바뀌면 유지되는가? | 메서드 추가·삭제·이름 변경 후 전체 재생성과 차이 |
| 버전이 섞이지 않는가? | 같은 이름의 메서드가 있는 두 빌드와 이전 배포의 동시 조회 |
| 에이전트가 근거를 읽을 수 있는가? | trace·메서드·빌드·소스의 구조화된 조회, 원본 참조·권한·응답 상한 |
| 결과를 얼마나 믿을 수 있는가? | 수집 시점·freshness·coverage·sampling·미해결·가설 구분, 누락 시 설명 |
| 유지할 수 있는가? | 실행 시간·메모리·수집량·설정·업그레이드 부담과 누락 표시 |

JDK 21과 선택한 프레임워크·agent·분석기의 실제 조합은 별도 PoC에서 확인한다. 프로젝트의 활동성·릴리스·라이선스·알려진 보안 이슈도 채택 후보 버전을 고정할 때 갱신한다. 문서의 `latest`가 검증한 실행 버전을 뜻하지 않는다.

## 인프라 비교 방향

첫 PoC의 후보는 버전별 snapshot과 제한된 실행 기록으로 두 버전의 결합과 근거 조회를 입증하는 구성이다. 중앙 보관과 원본 연합 조회의 대안도 비교한다. 공유 보관이 필요하면 snapshot 조회·보존·권한과 trace 저장·전송의 비용을 평가한다. 아직 구조를 선택하지 않았다.

SkyWalking 같은 통합 제품을 활용하면 해당 backend·UI·저장소의 운영 부담도 함께 평가한다. 분리된 분석기와 OTel 생태계를 결합하면 버전 매칭·조회 계층의 구현 부담을 평가한다. 어느 쪽도 현재 채택하지 않았다.

Neo4j·Kafka·Kubernetes는 현재 필수 구성으로 정하지 않는다. 그래프 크기·탐색 깊이·변경 빈도·이벤트량·보존 기간·접근 통제와 비용을 측정한 뒤 필요성을 판단한다.

## 카탈로그·환경별 식별의 공식 참고

관측 지원 대상은 AWS EKS·ECS와 일반 Kubernetes, 카탈로그 매핑 대상은 온프레미스·AWS 자원이다. 다음은 지원 계약을 설계하기 위한 문서 확인이며 connector 구현·실행 호환성이나 제품 채택의 증거가 아니다.

| 공식 근거 | 확인한 내용 | 프로젝트에서 검토할 요구 |
| --- | --- | --- |
| [EKS 개요](https://docs.aws.amazon.com/eks/latest/userguide/what-is-eks.html) | AWS가 제공하는 관리형 Kubernetes 서비스 | Kubernetes 객체 식별과 AWS 자원 참조를 함께 보존하고 동일 대상의 여러 수집 근거 연결 |
| [ECS 개요](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/Welcome.html), [Task API](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_Task.html) | ECS의 서비스·task·task definition, EC2·Fargate 등의 실행 방식과 task·cluster 참조 | ECS 실행과 빌드·이미지의 연결, 실행 방식별 가시성·미수집·해당 없음 구분 |
| [Fargate의 실행 제약](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-security-considerations.html) | EC2 방식과 다른 런타임·권한 제약 | 호스트 접근·계측 방식의 가능 여부를 실제 지원 조합에서 검증; 임의 호스트 관계 생성 방지 |
| [Kubernetes 객체 이름과 UID](https://kubernetes.io/docs/concepts/overview/working-with-objects/names/) | 이름과 객체 생애를 구분하는 UID | 등록된 클러스터·객체 UID·출처로 같은 이름과 재생성을 구분 |
| [Backstage 시스템 모델](https://backstage.io/docs/features/software-catalog/system-model/) | 소프트웨어 Component·API·Resource와 System·소유 조직의 모델 | 카탈로그의 논리 서비스와 실제 자원의 경계 비교; 사고 시점·매핑 이력·권한 계약은 별도로 검토 |

Backstage는 모델 참고 대상이며 설치·의존성·필수 제품으로 채택하지 않았다. 기존 카탈로그 연동과 자체 관리의 비교에는 동기화·외부 식별·권한·운영 비용·라이선스·버전별 최소 재현이 필요하다. 카탈로그 선언과 실제 실행 관계는 서로 다른 근거로 유지하는 안을 [D07](DISCUSSIONS.md#d07-카탈로그와-실제-자원의-매핑을-어떻게-유지할-것인가)에서 토론한다.

## 결정 전 산출물

1. 버전·공식 근거·라이선스·활동성·미확인 항목을 포함한 후보 비교표.
2. 같은 fixture의 정적·실행 결과와 누락·오연결 반례.
3. 코드·빌드·메서드·분석기·schema·설정 식별 및 출처·시점·freshness·coverage·불확실성을 포함한 근거 조회 계약 후보.
4. 재사용/직접 구현 경계, 파이프라인·인프라 대안과 비용·미결 선택을 기록한 토론 자료. 채택한 결정만 별도 ADR로 구분.

먼저 요구사항과 BDD의 기대 결과·반례·미결 질문을 함께 검토하고, 그것을 판정 기준으로 후속 PoC를 설계한다. PoC 이후 아키텍처 ADR과 구현 순서를 논의한다. 현재 모든 후보·파이프라인은 미채택 상태이며 [DISCUSSIONS](DISCUSSIONS.md)에 대안과 판별 실험을 둔다.

인프라·CMDB·SIEM도 구현 대상이다. [전체 구조 비교](OSS-ARCHITECTURE-COMPARISON.md)에 자산 수집·동기화·제어와 보안 이벤트 분석의 후보를 추가했다. 실제 공급원별 기능·권한·보존·관계 이력·운영 비용은 해당 BDD의 후속 PoC로 검증한다. 설치 환경과 관측 대상 환경, 지원 언어·런타임, CI 종속성, connector 교체·데이터 이동 시 정보 및 권한 보존, 제거·장애 격리 비용은 계속 비교할 항목이다.

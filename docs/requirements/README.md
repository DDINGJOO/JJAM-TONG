# BDD 요구사항 초안

상태: **행동 명세 Draft / 논의용**. 코드 관측성·에이전트 근거 조회·SRE·MSA·Kubernetes·인프라·CMDB·SIEM은 모두 구현 대상이다. 사용자 목표를 Given–When–Then으로 구체화한 세부 행동은 함께 검토할 초안이며, 승인된 아키텍처·현재 지원 기능이나 실행 테스트 통과를 뜻하지 않는다. 기능 파일은 현재 실행기 없는 명세이며 Cucumber 등 도구·의존성은 채택하지 않았다.

목적은 에이전트가 빠르고 정확한 분석에 필요한 근거를 얻고 SRE가 전체 상황을 파악하도록 돕는 것이다. 코드 관계의 수동 유지 부담을 줄이면서 **어떤 코드·배포의 어떤 시점에서 무엇을 확인했고 무엇이 빠졌는지** 설명해야 한다.

## 범위와 추적성

| 스토리 | 명세 | 시나리오 ID | 구현 범위 |
| --- | --- | --- | --- |
| S01 메서드 관계 | [01-code-relations.feature](../../specs/features/01-code-relations.feature) | BDD-REL-001~004 | 구현 대상 |
| S02 분석·실행 버전 | [02-version-identity.feature](../../specs/features/02-version-identity.feature) | BDD-VER-001~003 | 구현 대상 |
| S03 자동 갱신 | [03-graph-refresh.feature](../../specs/features/03-graph-refresh.feature) | BDD-UPD-001~018 | 구현 대상 |
| S04 에이전트 근거 조회 | [04-agent-evidence.feature](../../specs/features/04-agent-evidence.feature) | BDD-AGT-001~004 | 구현 대상 |
| S05 SRE 분석 | [05-sre-analysis.feature](../../specs/features/05-sre-analysis.feature) | BDD-SRE-001~008 | 구현 대상 |
| S06 인프라 문맥 | [06-infrastructure.feature](../../specs/features/06-infrastructure.feature) | BDD-INF-001~006 | 구현 대상 |
| S07 자산·소유권 | [07-cmdb.feature](../../specs/features/07-cmdb.feature) | BDD-CMDB-001~003 | 구현 대상 |
| S08 보안 상관 분석 | [08-security.feature](../../specs/features/08-security.feature) | BDD-SEC-001~003 | 구현 대상 |
| S09 카탈로그 기반 자원 매핑 | [09-catalog-mapping.feature](../../specs/features/09-catalog-mapping.feature) | BDD-CAT-001~006 | 구현 대상 |
| S03·S09 공통 자동 온보딩 | [10-automated-onboarding.feature](../../specs/features/10-automated-onboarding.feature) | BDD-ONB-001~010 | 구현 대상 |
| 전체 영역 공통 기업 운영 | [11-enterprise-operations.feature](../../specs/features/11-enterprise-operations.feature) | BDD-ENT-001~009 | 구현 대상 |
| 전체 영역 공통 자동 확장·축소 | [12-autoscaling.feature](../../specs/features/12-autoscaling.feature) | BDD-ASC-001~009 | 구현 대상 |
| 전체 영역 공통 식별과 시간 | [13-evidence-model.feature](../../specs/features/13-evidence-model.feature) | BDD-MDL-001~013 | 구현 대상 |

[자동화 제품 기획](AUTOMATION.md)은 GitHub 기반 발견·등록·지속 갱신과 운영 자동화의 흐름, 확인한 방향·세부 제안·미결 정책을 구분한다. 온보딩 10개 시나리오는 기존 S03·S09의 명세·검증 태스크에 연결한다. 전체 명세는 13개 feature·96개 시나리오로 구성되어 있으며 실행기 없는 Draft다. 새 스토리·태스크를 중복 생성하지 않는다.

[수용량 검증 계획](../experiments/CAPACITY-VALIDATION.md)의 BDD-SRE-005~008은 업무 서비스의 계측 전후 수용량, 플랫폼의 수집·분석·조회와 데이터 규모, 과부하 복구와 서비스별 격리를 명세한다. T10 #19에서 목표·판정 조건을 검토하고 T25 #44의 로컬 적용 비교에 연결한다. 현재 수치 목표와 수용량 실측은 없다.

[기업 운영 요구](ENTERPRISE.md)의 BDD-ENT-001~009는 조직 격리·신원·최소 권한·기업 정책을 유지한 수용량·고가용성·실제 복원·업그레이드·감사·보존/삭제·확장 작업의 경계를 명세한다. 기존 #14/#15/#19/#26/#29/#37/#43/#44에 연결하며 세부 구조·수치 목표·운영 검증은 미결이다.

[자동 확장·축소 요구](AUTOSCALING.md)의 BDD-ASC-001~009는 플랫폼의 단계별 확장 신호·기동과 배치·후속 병목·작업 인계·정책 충돌·0개 축소·예산·관측 대상의 버전 연결을 명세한다. #19/#37에서 검토하고 #43/#44와 연결하며 제어기·설치 환경·목표·실험 결과는 미결이다.

각 스토리는 요구사항·미결정 사항 검토 태스크와 검증 계획 태스크에 연결한다. 실제 이슈 번호·부모 관계·상태는 [ROADMAP](../../ROADMAP.md)의 GitHub 링크에서 확인한다. 시나리오 파일이나 이슈를 만들었다는 이유로 기능을 완료 처리하지 않는다.

전체 영역의 구현 범위는 유지한다. 구현 순서·지원 조합·검증 규모는 의존성과 설계 토론으로 정하며, 우선순위와 현재 구현 유무를 범위 포함 여부로 해석하지 않는다. 모든 기능 파일의 `@required`는 구현 대상을, `@draft`는 세부 행동이 검토 중임을 나타낸다.

## 관측 지원 대상과 카탈로그 매핑

사용자가 지정한 관측 지원 대상은 **AWS EKS·ECS와 일반 Kubernetes**다. 카탈로그에서 **온프레미스·AWS 자원**으로 매핑한다. 대상 범위는 구현 요구이며, 지원 버전·권한·수집 방식과 플랫폼 자체의 설치 환경은 별도로 정한다. 현재 실행 지원이 완료된 상태는 아니다.

| 관측·매핑 대상 | 보존할 식별·관계 후보 | 지원 차이와 검증할 조건 |
| --- | --- | --- |
| AWS EKS | 등록된 클러스터 식별·Kubernetes 객체 UID, AWS 클러스터·자원 참조 | 일반 Kubernetes 관계와 AWS 관계를 연결하고 여러 수집원이 같은 대상을 관측한 근거 보존 |
| AWS ECS | cluster·service·task 참조, task definition revision, 실제 이미지·빌드 근거 | EC2·Fargate 등 실행 방식별 수집 가능 범위와 호스트 가시성; Pod 관계를 필수로 요구하지 않음 |
| 일반 Kubernetes | 수집원이 등록한 클러스터 식별, namespace·객체 UID·환경별 워크로드 관계 | AWS 계정·ARN을 필수로 요구하지 않으며 이름 재사용·여러 클러스터 구분 |
| 온프레미스 자원 | 공급원·사이트·안정적인 자산 식별, 호스트·VM·클러스터·DB 관계 | hostname·IP 재사용, 단절·지연·수동 등록과 자동 수집의 출처 구분 |
| AWS 자원 | 공급원·partition·계정·해당하는 경우 리전, ARN 또는 서비스별 자원 식별 | EC2·RDS·S3 등은 자원 유형 예시; 실제 지원 유형·API·권한과 전역 자원의 범위는 별도 검토 |

카탈로그는 논리 서비스·시스템·소유자·저장소·선언한 의존성의 기준점을 제공한다. 환경별 배포·실제 실행·실제 자원은 별도 식별한다. 예를 들어 합성 `board-service`가 AWS EKS·ECS와 온프레미스에 배포되고, 다른 서비스와 같은 DB 자원을 공유하는 관계를 표현한다. 카탈로그의 서비스와 Kubernetes Service, ECS service 같은 공급원 객체는 각 식별 공간과 의미를 구분한다.

매핑의 행동 초안은 다음과 같다.

- 한 논리 서비스의 여러 환경·배포와 여러 서비스가 공유하는 자원을 표현한다. 논리 서비스 식별과 실물 자원 식별을 하나로 합치지 않는다.
- 관계에는 원본 참조·출처·대상 범위·유효 시간·수집 시점과 카탈로그·매핑 revision을 남겨 사고 당시 관계를 조회한다. 코드·빌드·분석 버전과도 별도로 추적한다.
- 명시적 선언, 자동 수집 사실, 이름·태그·IaC 등의 매칭 후보를 구분한다. 확정 기준·충돌 우선순위는 토론하며 근거 없이 후보를 확정하지 않는다.
- 이름이 같거나 같은 자원이 여러 수집원에 나타나도 출처 범위·원본 식별과 확인된 동일성으로 판단한다. 충돌과 중복 근거를 보존한다.
- 카탈로그 미등록 자원과 아직 자원에 연결되지 않은 서비스를 표현한다. 공급원 장애·권한 거절·태그 누락만으로 서비스·자원·기존 매핑을 삭제하지 않는다.
- 조회 권한을 카탈로그와 자원·관계 양쪽에 적용한다. 상위 카탈로그를 볼 수 있다는 이유로 제한된 자원이나 보안 근거를 공개하지 않는다.

등록 형식, 기존 카탈로그 연동과 자체 관리의 경계, 최초 발견·갱신·재조정 방식, 관계 확정 권한과 이력 보존 정책은 [D07](../DISCUSSIONS.md#d07-카탈로그와-실제-자원의-매핑을-어떻게-유지할-것인가)에서 토론한다. 제품·저장소·수집 파이프라인 채택은 미결이다.

## 공통 품질 요구: 이식성

플랫폼을 다른 환경에 설치하는 능력과 다른 환경의 대상을 관측하는 능력을 구분한다. 예를 들어 플랫폼이 Kubernetes에서 실행되더라도 관측 대상이 Kubernetes라는 전제를 요구할지 별도로 정한다. 다음은 지원 계약과 검증을 위한 초안이며 특정 구조·도구 채택이나 모든 환경 지원의 약속은 아니다.

| 축 | 원하는 행동과 판정 후보 | 연결 시나리오·태스크 |
| --- | --- | --- |
| 언어·런타임 | 언어별 분석기·계측기가 지원 수준을 선언하고 미지원 메서드 관측을 빈 그래프나 정상 수집으로 바꾸지 않음 | BDD-REL-004 · T01/T02 |
| CI·빌드 환경 | 같은 빌드 입력·분석 설정으로 CI 공급원을 바꾸어도 버전 연결과 의미상 관계가 일치함; 실행 ID·시각은 별도 | BDD-UPD-004 · T05/T06 |
| 수집 도구·공급원 | 관측·CMDB·SIEM 연결을 교체할 때 원본 식별·출처·시간·권한을 보존하거나 변환 불가를 설명함 | BDD-AGT-004 · T07/T08/T14/T16 |
| 업무 서비스와 격리 | 수집 경로 중단이 업무 결과·예외를 바꾸지 않고 버퍼·재시도 자원이 제한됨 | BDD-SRE-004 · T10 |
| 관측 대상 환경 | AWS EKS·ECS·일반 Kubernetes와 온프레미스에서 공통 서비스·빌드 근거와 환경 전용 관계를 구분함 | BDD-INF-004~006 · T11/T12 |

추가로 플랫폼의 로컬·서버·클러스터 설치, 업그레이드·제거, 데이터 export/import와 스키마 호환성, 비밀·권한 설정의 이관을 논의한다. 지원 조합·앱 수정량·필요 권한·의존 인프라·자원 예산·이식 비용을 표로 정한 뒤 실제 실험으로 확인한다. 이 항목들의 세부 행동과 자동 검증 계획은 아직 미결이며, 현재 시나리오가 모든 이식 과정을 검증하는 것은 아니다. 대안은 [D06 설계 토론](../DISCUSSIONS.md#d06-이식성의-책임과-지원-범위를-어떻게-나눌-것인가)에 있다.

## 공통 용어와 합성 예제

- **정적 후보 관계**는 분석 범위와 조건에서 가능한 호출이다. 실제 호출 증거와 구분한다.
- **실행 근거**는 관측한 호출 occurrence·부모/링크·시간·상태다. 기록 부재를 미실행으로 확정하지 않는다.
- **분석 식별**은 대상 repository·commit·build·module과 analysis run·index·analyzer/schema/config를 구분한다. 정확한 필드·정규화는 미결이다.
- **근거 응답**은 원본 참조·출처·대상 시간·수집 시점·수집 범위·신선도와 불확실성을 설명한다. 구체적 wire format은 미결이다.
- `com.example.shop`, `board-service`, `build-A`, `build-B`, `팀-A`, `팀-B`는 합성 fixture다. 빌드 이름을 실제 commit SHA 또는 배포 검증으로 해석하지 않는다.
- 메서드 예시는 `PlaceOrderController → OrderService.place → OrderService.validate(private) → InventoryRepository.reserve`다. 입력·반환 본문·개인정보·비밀은 예제와 기본 수집 대상에 넣지 않는다.

## 먼저 논의할 미결정 사항

1. 첫 에이전트·SRE 질문과 성공 판정은 무엇인가? “배포 이후 왜 느려졌는가?”에 필요한 근거와 허용할 수 없는 오판을 먼저 고른다.
2. private/self-call·interface·proxy·reflection·비동기 중 첫 지원 범위는 어디까지인가? 제외·미해결·샘플링을 어떻게 설명할 것인가?
3. 실제 빌드·배포와 분석을 일치시키는 필수 식별 필드, unknown/dirty 빌드와 재분석·보존 정책은 무엇인가?
4. 에이전트의 읽기 인터페이스·인증·대상별 권한·조회 예산·페이지/응답 상한·출처 감사는 어떻게 정할 것인가?
5. 소스 코드·메서드명·예외 유형의 공개/수집 경계는 어디인가? 공급원 만료·거절·충돌을 어떻게 노출할 것인가?
6. freshness·수집 한도·계측 비용·응답 시간의 예산과 측정 조건은 무엇인가? 현재 수치 SLO나 보편적인 성능 배수는 정하지 않았다.
7. 모두 구현 대상인 인프라·CMDB·SIEM의 식별·시간·권한 계약과 공급원은 무엇인가? 전체 범위를 유지하면서 어떤 의존성 순서로 구현·검증할 것인가?
8. 플랫폼 설치 환경과 관측 대상 환경, 언어·런타임·CI·수집 도구의 지원 조합은 무엇인가? 서비스 수정량과 데이터·설정 이동 비용을 어떻게 측정할 것인가?

아키텍처·정적 분석기·계측 방식·스토리지·CI 이벤트·에이전트 프로토콜은 위 행동과 반례를 놓고 비교한다. 대안은 [설계 토론](../DISCUSSIONS.md), 후보 근거는 [오픈소스 조사](../RESEARCH.md)에서 관리한다.

## 명세 검토와 검증 계획

시나리오마다 원하는 행동, 반례, 합성 입력, 관측 가능한 판정, 아직 모르는 조건을 함께 검토한다. 다음으로 어떤 fixture·테스트 층·원본 근거로 확인할지 정하고, 그 뒤 구현 태스크를 만든다.

이 디렉터리의 전체 BDD 검증은 파일별 태그·고유 ID·Given/When/Then 구조와 스토리 매핑에 한정한다. 별도 [비교 실험](../experiments/ARCHITECTURE-EXPERIMENTS.md)에서는 17개 BDD ID의 일부 조건을 16개 합성 시나리오에 연결해 세 갱신 전략을 실행했다. 전체 BDD의 실행 통과·실제 공급원 호환성·분산 성능 검증과 구분한다.

후속 [원본 재확인 실험](../experiments/HYBRID-RECONCILIATION.md)은 H01~H14의 파일·blob 갱신 계약과 실제 Git·공개 REST 읽기·loopback 수신·단일 머신 실행 경계를 확인한다. 메서드 분석·build/trace·AWS/Kubernetes·CMDB·SIEM 전체 행동의 실행 수락과 별도로 집계한다.

## 대규모 코드 분석

[복잡 구조 요구](CODE-ANALYSIS-SCALE.md)는 정리된 예제 밖의 호출 관계와 분석 공백을 다룬다. BDD-UPD-005~010과 [#61](https://github.com/DDINGJOO/JJAM-TONG/issues/61)에서 재사용·변경 전파·실패 경계를 검증한다. [실측 결과](../experiments/ANALYSIS-REUSE-RESULTS.md)와 전체 BDD의 Draft 상태를 구분한다.

BDD-UPD-011·012와 [#63](https://github.com/DDINGJOO/JJAM-TONG/issues/63)은 최적화 전후의 소스 위치·관계 보존과 패키지·소스 배치가 다른 입력을 명세한다. [후속 실측](../experiments/JAVA-PARSER-MEMORY.md)은 한정된 Java 분석 도구의 결과다. 작업 공통 계약·빌드 발견·HTTP와 이벤트의 근거 계약은 [#64](https://github.com/DDINGJOO/JJAM-TONG/issues/64)·[#65](https://github.com/DDINGJOO/JJAM-TONG/issues/65)·[#66](https://github.com/DDINGJOO/JJAM-TONG/issues/66)으로 이어가며, 범용 지원 완료로 취급하지 않는다.

[분석 작업 공통 계약](ANALYSIS-JOB.md)과 BDD-UPD-013~018은 입력·시도·단계·자원·완료·실패의 의미를 구분한다. [발행 계약 실험](../experiments/ANALYSIS-JOB-CONTRACT.md)과 실제 Java·소비자·화면 전환 [#68](https://github.com/DDINGJOO/JJAM-TONG/issues/68)을 구분한다.

## 코드와 실행의 근거 모델

[근거의 식별과 시간 모델](EVIDENCE-MODEL.md)과 [BDD-MDL-001~013](../../specs/features/13-evidence-model.feature)은 빌드·서비스·배포·자원을 구분하고 정적 후보·관측·선언·추론, 지연 수집·정정·철회·충돌·조회 제한을 명세한다. [#76](https://github.com/DDINGJOO/JJAM-TONG/issues/76)은 #65의 첫 하위 작업이다. [작은 실행 실험](../../experiments/evidence_model_lab/README.md)의 판정은 이 feature 파일을 실행한 수락 결과나 전체 도메인 수집 완료를 의미하지 않는다.

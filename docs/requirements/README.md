# BDD 요구사항 초안

상태: **Draft / 논의용**. 사용자가 요청한 행동을 Given–When–Then으로 구체화한 제안이다. 승인된 요구사항·아키텍처·지원 기능이나 실행 테스트 통과를 뜻하지 않는다. 기능 파일은 현재 실행기 없는 명세이며 Cucumber 등 도구·의존성은 채택하지 않았다.

목적은 에이전트가 빠르고 정확한 분석에 필요한 근거를 얻고 SRE가 전체 상황을 파악하도록 돕는 것이다. 코드 관계의 수동 유지 부담을 줄이면서 **어떤 코드·배포의 어떤 시점에서 무엇을 확인했고 무엇이 빠졌는지** 설명해야 한다.

## 범위와 추적성

| 스토리 | 명세 | 시나리오 ID | 제안 범위 |
| --- | --- | --- | --- |
| S01 메서드 관계 | [01-code-relations.feature](../../specs/features/01-code-relations.feature) | BDD-REL-001~003 | 초기 |
| S02 분석·실행 버전 | [02-version-identity.feature](../../specs/features/02-version-identity.feature) | BDD-VER-001~003 | 초기 |
| S03 자동 갱신 | [03-graph-refresh.feature](../../specs/features/03-graph-refresh.feature) | BDD-UPD-001~003 | 초기 |
| S04 에이전트 근거 조회 | [04-agent-evidence.feature](../../specs/features/04-agent-evidence.feature) | BDD-AGT-001~003 | 초기 |
| S05 SRE 분석 | [05-sre-analysis.feature](../../specs/features/05-sre-analysis.feature) | BDD-SRE-001~003 | 초기 |
| S06 인프라 문맥 | [06-infrastructure.feature](../../specs/features/06-infrastructure.feature) | BDD-INF-001~003 | 미래 |
| S07 자산·소유권 | [07-cmdb.feature](../../specs/features/07-cmdb.feature) | BDD-CMDB-001~003 | 미래 |
| S08 보안 상관 분석 | [08-security.feature](../../specs/features/08-security.feature) | BDD-SEC-001~003 | 미래 |

각 스토리는 요구사항·미결정 사항 검토 태스크와 검증 계획 태스크에 연결한다. 실제 이슈 번호·부모 관계·상태는 [ROADMAP](../../ROADMAP.md)의 GitHub 링크에서 확인한다. 시나리오 파일이나 이슈를 만들었다는 이유로 기능을 완료 처리하지 않는다.

## 공통 용어와 합성 예제

- **정적 후보 관계**는 분석 범위와 조건에서 가능한 호출이다. 실제 호출 증거와 구분한다.
- **실행 근거**는 관측한 호출 occurrence·부모/링크·시간·상태다. 기록 부재를 미실행으로 확정하지 않는다.
- **분석 식별**은 대상 repository·commit·build·module과 analysis run·index·analyzer/schema/config를 구분한다. 정확한 필드·정규화는 미결이다.
- **근거 응답**은 원본 참조·출처·대상 시간·수집 시점·수집 범위·신선도와 불확실성을 설명한다. 구체적 wire format은 미결이다.
- `com.example.shop`, `build-A`, `build-B`, `팀-A`, `팀-B`는 합성 fixture다. 빌드 이름을 실제 commit SHA 또는 배포 검증으로 해석하지 않는다.
- 메서드 예시는 `PlaceOrderController → OrderService.place → OrderService.validate(private) → InventoryRepository.reserve`다. 입력·반환 본문·개인정보·비밀은 예제와 기본 수집 대상에 넣지 않는다.

## 먼저 논의할 미결정 사항

1. 첫 에이전트·SRE 질문과 성공 판정은 무엇인가? “배포 이후 왜 느려졌는가?”에 필요한 근거와 허용할 수 없는 오판을 먼저 고른다.
2. private/self-call·interface·proxy·reflection·비동기 중 첫 지원 범위는 어디까지인가? 제외·미해결·샘플링을 어떻게 설명할 것인가?
3. 실제 빌드·배포와 분석을 일치시키는 필수 식별 필드, unknown/dirty 빌드와 재분석·보존 정책은 무엇인가?
4. 에이전트의 읽기 인터페이스·인증·대상별 권한·조회 예산·페이지/응답 상한·출처 감사는 어떻게 정할 것인가?
5. 소스 코드·메서드명·예외 유형의 공개/수집 경계는 어디인가? 공급원 만료·거절·충돌을 어떻게 노출할 것인가?
6. freshness·수집 한도·계측 비용·응답 시간의 예산과 측정 조건은 무엇인가? 현재 수치 SLO나 보편적인 성능 배수는 정하지 않았다.
7. 미래 인프라·CMDB·SIEM의 식별·시간·권한 계약과 공급원은 무엇인가? 초기 기능과 같은 단계의 구현 약속으로 취급하지 않는다.

아키텍처·정적 분석기·계측 방식·스토리지·CI 이벤트·에이전트 프로토콜은 위 행동과 반례를 놓고 비교한다. 대안은 [설계 토론](../DISCUSSIONS.md), 후보 근거는 [오픈소스 조사](../RESEARCH.md)에서 관리한다.

## 명세 검토와 검증 계획

시나리오마다 원하는 행동, 반례, 합성 입력, 관측 가능한 판정, 아직 모르는 조건을 함께 검토한다. 다음으로 어떤 fixture·테스트 층·원본 근거로 확인할지 정하고, 그 뒤 구현 태스크를 만든다.

현재 검증은 파일별 태그·고유 ID·Given/When/Then 구조와 스토리 매핑에 한정한다. 실행 검증·성능 측정·지원 호환성은 아직 수행하지 않았다.

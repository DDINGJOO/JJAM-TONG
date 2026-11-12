# 요구사항 로드맵

현재는 **BDD 초안 → 함께 토론 → 검증 계획** 단계다. 기능 구현·아키텍처·파이프라인은 확정하지 않았다. 명세와 구현의 완료를 구분한다.

프로젝트 홈: [#1 JJAM-TONG Platform — 에이전트 분석과 SRE를 위한 근거 기반](https://github.com/DDINGJOO/JJAM-TONG/issues/1). 처음 검토할 초안: [#4 메서드 관계 BDD 초안 검토와 미결정 정리](https://github.com/DDINGJOO/JJAM-TONG/issues/4).

[시나리오 인덱스](docs/requirements/README.md) · [프로젝트 정의](docs/PROJECT.md) · [설계 토론](docs/DISCUSSIONS.md) · [작업 규칙](CONTRIBUTING.md)

실제 상태는 GitHub의 open/closed·단일 상태 라벨·Parent/Sub-issues·milestone이 기준이다. 아래 목록은 바로가기이며 상태를 중복 관리하지 않는다.

| 보기 | GitHub |
| --- | --- |
| 에픽 | [열기](https://github.com/DDINGJOO/JJAM-TONG/issues?q=is%3Aopen+label%3A%22kind%3Aepic%22) |
| 스토리 | [열기](https://github.com/DDINGJOO/JJAM-TONG/issues?q=is%3Aopen+label%3A%22kind%3Astory%22) |
| 검토 중 | [열기](https://github.com/DDINGJOO/JJAM-TONG/issues?q=is%3Aopen+label%3A%22status%3Ain-review%22) |
| 대기 | [열기](https://github.com/DDINGJOO/JJAM-TONG/issues?q=is%3Aopen+label%3A%22status%3Abacklog%22) |
| 착수 가능 | [열기](https://github.com/DDINGJOO/JJAM-TONG/issues?q=is%3Aopen+label%3A%22status%3Aready%22) |
| 진행 중 | [열기](https://github.com/DDINGJOO/JJAM-TONG/issues?q=is%3Aopen+label%3A%22status%3Ain-progress%22) |
| 막힘 | [열기](https://github.com/DDINGJOO/JJAM-TONG/issues?q=is%3Aopen+label%3A%22status%3Ablocked%22) |
| 닫힌 이슈 | [열기](https://github.com/DDINGJOO/JJAM-TONG/issues?q=is%3Aclosed) |

## 명세 구간

| 구간 | 목표 |
| --- | --- |
| [R1 — 코드 관계·버전 요구사항](https://github.com/DDINGJOO/JJAM-TONG/milestone/1) | 메서드 관계와 분석·실행 버전의 행동 명세·반례·미결정 사항을 검토한다. |
| [R2 — 자동 갱신·에이전트 근거 요구사항](https://github.com/DDINGJOO/JJAM-TONG/milestone/2) | 그래프 갱신과 기계 조회 근거의 행동·실패 조건을 명세한다. |
| [R3 — SRE·인프라 요구사항](https://github.com/DDINGJOO/JJAM-TONG/milestone/3) | SRE 분석과 AWS EKS·ECS·일반 Kubernetes의 환경별 식별·실행·이식성을 명세한다. |
| [R4 — 카탈로그·CMDB·SIEM 요구사항](https://github.com/DDINGJOO/JJAM-TONG/milestone/4) | 카탈로그의 온프레미스·AWS 자원 매핑과 자산·소유권·보안 연결의 출처·시간·권한을 명세한다. 현재는 명세·검증 계획 단계다. |

S01~S09는 코드·관측성·에이전트·SRE·MSA·Kubernetes·인프라·CMDB·SIEM의 전체 구현 범위다. 관측 지원 대상은 AWS EKS·ECS·일반 Kubernetes이며 카탈로그에서 온프레미스·AWS 자원으로 매핑한다. 구현 순서·지원 조합·일정은 의존성과 설계 토론으로 정한다. 세부 행동 시나리오는 모두 논의용 Draft이며 이식성을 공통 품질 요구로 다룬다.

## E01 · [#2 메서드 관계·분석 버전 요구사항](https://github.com/DDINGJOO/JJAM-TONG/issues/2)

관계의 의미와 올바른 버전 연결을 행동으로 명세한다.

### S01 · [#3 정적 관계와 실제 실행을 구분해 이해한다](https://github.com/DDINGJOO/JJAM-TONG/issues/3)

에이전트와 개발자가 가능한 호출과 관측한 실행의 차이를 판단한다. (구현 대상 · 행동 초안 명세)

[BDD 원본](specs/features/01-code-relations.feature) · BDD-REL-001, BDD-REL-002, BDD-REL-003, BDD-REL-004

- [#4 메서드 관계 BDD 초안 검토와 미결정 정리](https://github.com/DDINGJOO/JJAM-TONG/issues/4)
- [#5 관계 분석·계측 검증 fixture 계획](https://github.com/DDINGJOO/JJAM-TONG/issues/5) · 선행: [#4](https://github.com/DDINGJOO/JJAM-TONG/issues/4)

### S02 · [#6 분석·실행의 코드 버전과 출처를 안다](https://github.com/DDINGJOO/JJAM-TONG/issues/6)

다른 빌드의 기록이 잘못된 지도에 연결되지 않게 요구한다. (구현 대상 · 행동 초안 명세)

[BDD 원본](specs/features/02-version-identity.feature) · BDD-VER-001, BDD-VER-002, BDD-VER-003

- [#7 분석·실행 버전과 출처의 BDD 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/7)
- [#8 버전 오연결·누락·보존 검증 계획](https://github.com/DDINGJOO/JJAM-TONG/issues/8) · 선행: [#7](https://github.com/DDINGJOO/JJAM-TONG/issues/7)

## E02 · [#9 자동 갱신·에이전트 근거 조회 요구사항](https://github.com/DDINGJOO/JJAM-TONG/issues/9)

지도를 수동 유지하지 않고 에이전트가 신뢰 가능한 근거를 조회하도록 명세한다.

### S03 · [#10 코드 변경이 관계 지도에 자동 반영된다](https://github.com/DDINGJOO/JJAM-TONG/issues/10)

추가·삭제·이름 변경과 실패·재시도의 결과를 구분한다. (구현 대상 · 행동 초안 명세)

[BDD 원본](specs/features/03-graph-refresh.feature) · BDD-UPD-001, BDD-UPD-002, BDD-UPD-003, BDD-UPD-004

- [#11 관계 지도 자동 갱신의 성공·실패 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/11)
- [#12 두 버전·삭제·동시 갱신 검증 예시](https://github.com/DDINGJOO/JJAM-TONG/issues/12) · 선행: [#11](https://github.com/DDINGJOO/JJAM-TONG/issues/11)

### S04 · [#13 에이전트가 출처와 한계를 가진 근거를 조회한다](https://github.com/DDINGJOO/JJAM-TONG/issues/13)

분석 질문에 버전·시점·커버리지·근거를 확인할 수 있는 응답을 요구한다. (구현 대상 · 행동 초안 명세)

[BDD 원본](specs/features/04-agent-evidence.feature) · BDD-AGT-001, BDD-AGT-002, BDD-AGT-003, BDD-AGT-004

- [#14 에이전트 질문과 기계 조회 근거 계약 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/14)
- [#15 에이전트의 근거 누락·충돌·권한 반례](https://github.com/DDINGJOO/JJAM-TONG/issues/15) · 선행: [#14](https://github.com/DDINGJOO/JJAM-TONG/issues/14)

## E03 · [#16 SRE 분석·인프라 문맥 요구사항](https://github.com/DDINGJOO/JJAM-TONG/issues/16)

지연·오류와 운영 문맥을 증거로 연결하는 SRE 행동을 명세한다.

### S05 · [#17 지연·오류를 코드 실행 근거로 조사한다](https://github.com/DDINGJOO/JJAM-TONG/issues/17)

SRE가 느린 구간·혼합 성공/실패·부분 수집을 구분한다. (구현 대상 · 행동 초안 명세)

[BDD 원본](specs/features/05-sre-analysis.feature) · BDD-SRE-001, BDD-SRE-002, BDD-SRE-003, BDD-SRE-004

- [#18 지연·오류·비동기 SRE 행동 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/18)
- [#19 비용·상한·부분 수집의 검증 계획](https://github.com/DDINGJOO/JJAM-TONG/issues/19) · 선행: [#18](https://github.com/DDINGJOO/JJAM-TONG/issues/18)

### S06 · [#20 서비스·배포·워크로드 문맥을 연결한다](https://github.com/DDINGJOO/JJAM-TONG/issues/20)

AWS EKS·ECS와 일반 Kubernetes에서 시점이 맞는 배포·실행·자원 근거를 탐색한다. (구현 대상 · 행동 초안 명세)

[BDD 원본](specs/features/06-infrastructure.feature) · BDD-INF-001, BDD-INF-002, BDD-INF-003, BDD-INF-004, BDD-INF-005, BDD-INF-006

- [#21 서비스·배포·워크로드 관계 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/21)
- [#22 인프라 관계의 누락·오연결 반례](https://github.com/DDINGJOO/JJAM-TONG/issues/22) · 선행: [#21](https://github.com/DDINGJOO/JJAM-TONG/issues/21)

## E04 · [#23 카탈로그·CMDB·SIEM 통합 요구사항](https://github.com/DDINGJOO/JJAM-TONG/issues/23)

카탈로그의 논리 서비스를 온프레미스·AWS 자원과 연결하고 자산·소유권·보안 이벤트의 권한·출처·시간을 명세한다.

### S07 · [#24 자산·소유권·관계 이력을 근거로 조회한다](https://github.com/DDINGJOO/JJAM-TONG/issues/24)

관측 대상과 CMDB 자산·담당자 간 연결의 유효성을 판단한다. (구현 대상 · 행동 초안 명세)

[BDD 원본](specs/features/07-cmdb.feature) · BDD-CMDB-001, BDD-CMDB-002, BDD-CMDB-003

- [#25 CMDB 자산·소유권·유효 시간 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/25)
- [#26 CMDB 갱신 지연·충돌·조회 권한 반례](https://github.com/DDINGJOO/JJAM-TONG/issues/26) · 선행: [#25](https://github.com/DDINGJOO/JJAM-TONG/issues/25)

### S08 · [#27 관련 보안 이벤트를 권한 안에서 연결한다](https://github.com/DDINGJOO/JJAM-TONG/issues/27)

SIEM 근거를 같은 서비스·배포·자산의 운영 증거와 함께 조회한다. (구현 대상 · 행동 초안 명세)

[BDD 원본](specs/features/08-security.feature) · BDD-SEC-001, BDD-SEC-002, BDD-SEC-003

- [#28 보안 이벤트 상관 분석 행동 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/28)
- [#29 보안 조회 누락·민감정보·자동 대응 경계](https://github.com/DDINGJOO/JJAM-TONG/issues/29) · 선행: [#28](https://github.com/DDINGJOO/JJAM-TONG/issues/28)

### S09 · [#30 카탈로그의 서비스를 온프레미스·AWS 자원에 매핑한다](https://github.com/DDINGJOO/JJAM-TONG/issues/30)

논리 서비스·시스템·소유자와 실제 자원의 다중 환경·공유 관계를 출처·유효 시간·revision과 함께 조회한다. (구현 대상 · 행동 초안 명세)

[BDD 원본](specs/features/09-catalog-mapping.feature) · BDD-CAT-001, BDD-CAT-002, BDD-CAT-003, BDD-CAT-004, BDD-CAT-005, BDD-CAT-006

- [#31 카탈로그 모델과 환경별 자원 매핑 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/31)
- [#32 매핑 갱신·이동·중복·권한의 검증 계획](https://github.com/DDINGJOO/JJAM-TONG/issues/32) · 선행: [#31](https://github.com/DDINGJOO/JJAM-TONG/issues/31)

## 다음 단계

제품 중심을 자동 발견·등록·지속 갱신과 근거 기반 분석·운영 자동화로 확인했다. [자동화 제품 기획](docs/requirements/AUTOMATION.md)과 [온보딩 BDD 10개](specs/features/10-automated-onboarding.feature)를 S03의 #10·#11·#12와 S09의 #30·#31·#32에 연결한다. 기존 이슈·상태·부모 관계를 유지하며 세부 동작·정책은 Draft다. 다음 검토는 GitHub 연결로 게시판의 두 서비스를 발견하고 중복·역순·누락·권한 회수에도 관계를 정확히 유지하는 행동이다.

토론 입력으로 [12개 OSS 계열의 아키텍처 비교](docs/OSS-ARCHITECTURE-COMPARISON.md)와 [관련 저장소의 릴리스·라이선스 기록](docs/OSS-SOURCE-SNAPSHOT.md)을 추가했다. 게시판의 두 빌드·다중 환경·공유 DB·보안 이벤트·권한 반례를 기존 BDD·검증 태스크에 연결했다. 문서 조사이며 제품 채택·PoC 통과·요구사항 합의를 뜻하지 않는다.

각 시나리오의 원하는 결과·반례·미결정 사항을 함께 검토한다. 그다음 실제 검증 fixture와 판정을 정하고, OSS·인프라 PoC와 설계 대안·ADR을 논의한 뒤 구현 이슈를 만든다.

현재 feature는 실행기 없는 명세다. 시나리오 파일과 이슈 생성은 실행 수락 테스트 통과나 기능 완료를 의미하지 않는다.

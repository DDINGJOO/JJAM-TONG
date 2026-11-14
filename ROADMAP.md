# 요구사항 로드맵

현재는 **BDD·토론·검증 계획과 제한된 비교 실험** 단계다. 제품 아키텍처·파이프라인은 확정하지 않았다. 명세·비교 실험과 실제 기능 지원의 완료를 구분한다.

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

[정확 입력 재사용·대규모 및 복잡 구조 검증 #61](https://github.com/DDINGJOO/JJAM-TONG/issues/61)은 #44의 하위 작업이며 [BDD-UPD-005~010](specs/features/03-graph-refresh.feature)에 연결한다. 실제 상태는 해당 이슈를 따른다.

### S04 · [#13 에이전트가 출처와 한계를 가진 근거를 조회한다](https://github.com/DDINGJOO/JJAM-TONG/issues/13)

분석 질문에 버전·시점·커버리지·근거를 확인할 수 있는 응답을 요구한다. (구현 대상 · 행동 초안 명세)

[BDD 원본](specs/features/04-agent-evidence.feature) · BDD-AGT-001, BDD-AGT-002, BDD-AGT-003, BDD-AGT-004

- [#14 에이전트 질문과 기계 조회 근거 계약 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/14)
- [#15 에이전트의 근거 누락·충돌·권한 반례](https://github.com/DDINGJOO/JJAM-TONG/issues/15) · 선행: [#14](https://github.com/DDINGJOO/JJAM-TONG/issues/14)

## E03 · [#16 SRE 분석·인프라 문맥 요구사항](https://github.com/DDINGJOO/JJAM-TONG/issues/16)

지연·오류와 운영 문맥을 증거로 연결하는 SRE 행동을 명세한다.

### S05 · [#17 지연·오류를 코드 실행 근거로 조사한다](https://github.com/DDINGJOO/JJAM-TONG/issues/17)

SRE가 느린 구간·혼합 성공/실패·부분 수집을 구분한다. (구현 대상 · 행동 초안 명세)

[BDD 원본](specs/features/05-sre-analysis.feature) · BDD-SRE-001~008

- [#18 지연·오류·비동기 SRE 행동 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/18)
- [#19 비용·상한·부분 수집의 검증 계획](https://github.com/DDINGJOO/JJAM-TONG/issues/19) · 선행: [#18](https://github.com/DDINGJOO/JJAM-TONG/issues/18)

[수용량·과부하·복구 계획](docs/experiments/CAPACITY-VALIDATION.md)은 #19의 요구사항 검토와 #44의 계측 적용 비교에 연결한다. 수치 목표·수용량은 아직 검증하지 않았다.

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

## E05 · [#33 구현 방법론·아키텍처 비교 실험](https://github.com/DDINGJOO/JJAM-TONG/issues/33)

[X1 비교 실험 milestone](https://github.com/DDINGJOO/JJAM-TONG/milestone/10) · [방법론·비교 축](docs/experiments/ARCHITECTURE-EXPERIMENTS.md) · [첫 실행 결과](docs/experiments/RESULTS.md)

[원본 재확인·변경 알림 결과](docs/experiments/HYBRID-RESULTS.md) · [관계 갱신 검증 기본안 ADR](docs/decisions/0001-reconciliation-baseline.md)

### S10 · [#34 같은 시나리오로 자동 갱신 구조와 실행 경계를 비교한다](https://github.com/DDINGJOO/JJAM-TONG/issues/34)

주기적 원본 조회·이벤트·혼합을 같은 계약과 입력으로 구현하고, 실제 공급원·분리 실행의 후속 비교로 이어간다. 전체 범위는 유지하며 어떤 제품 스택도 채택하지 않았다.

- [#35 세 갱신 전략과 독립 판정 실험실 구현·검증](https://github.com/DDINGJOO/JJAM-TONG/issues/35) · X01~X16, 48회 합성 실행과 별도 테스트 9개; 목표 미달 13개도 공개.
- [#36 실제 공급원 adapter와 분리 worker 비교 조건 구체화](https://github.com/DDINGJOO/JJAM-TONG/issues/36) · 선행: [#35](https://github.com/DDINGJOO/JJAM-TONG/issues/35); 실제 Git·공개 GitHub GET·loopback 수신·두 실행 경계의 18회 비교와 테스트 17개. 제품 스택·운영 지원과 구분.
- [#37 공급원별 수집·복구 정책과 상시 worker 검증](https://github.com/DDINGJOO/JJAM-TONG/issues/37) · 선행: [#36](https://github.com/DDINGJOO/JJAM-TONG/issues/36); 실제 권한·연결·list/watch·호출 예산·보존과 장기 실행 복구.
- [#38 버전 근거 보관·조회와 실제 코드 분석의 비교 조건 구체화](https://github.com/DDINGJOO/JJAM-TONG/issues/38) · 선행: [#36](https://github.com/DDINGJOO/JJAM-TONG/issues/36); 과거 시점·원본 중단·권한, 실제 정적 분석·계측의 판정과 실험 조건.
- [#43 버전 근거 보관·조회 3대안의 동일 질문 실행 비교](https://github.com/DDINGJOO/JJAM-TONG/issues/43) · 선행: [#38](https://github.com/DDINGJOO/JJAM-TONG/issues/38); 공통 예상값과 실제 응답·보관량·원본 호출·예산 제한을 대조.
- [#44 외부 프로젝트에 적용할 관측성 라이브러리와 로컬 최소 검증](https://github.com/DDINGJOO/JJAM-TONG/issues/44) · 선행: [#38](https://github.com/DDINGJOO/JJAM-TONG/issues/38)과 [#4](https://github.com/DDINGJOO/JJAM-TONG/issues/4)의 관련 검토; 대상 앱을 별도 저장소에 유지하며 [실제 메서드 분석·계측·빌드 연결](docs/experiments/METHOD-OBSERVABILITY-RESULTS.md)을 비교. 정확한 overload 식별·부분 재분석 등 남은 조건은 이슈에서 관리.

#44의 범용 분석 후속 작업은 다음과 같이 나눈다. 아래 목록은 선행 관계이며 실제 진행 상태는 각 이슈가 기준이다.

| 하위 작업 | 검증할 결과 | 선행 |
| --- | --- | --- |
| [#63 Java 분석 메모리와 소스 위치 보존](https://github.com/DDINGJOO/JJAM-TONG/issues/63) | 같은 입력의 선언·관계·소스 위치를 보존하며 파서 메모리 부담을 줄임 | #61 |
| [#64 분석 작업 공통 계약](https://github.com/DDINGJOO/JJAM-TONG/issues/64) | 도구별 입력·지원 범위·자원·완료·실패 의미를 구분함 | #63 |
| [#65 빌드·모듈 발견과 변경 영향](https://github.com/DDINGJOO/JJAM-TONG/issues/65) | 모듈·공통 라이브러리·산출물·배포 서비스와 변경 영향을 구분함 | #64 |
| [#76 코드·실행·자원 근거의 식별과 시간 모델](https://github.com/DDINGJOO/JJAM-TONG/issues/76) | #65의 첫 하위 작업. 타입·버전·시간·출처·충돌을 명세하고 기존 분석의 메타데이터 연결을 검증함 | #64·#68 |
| [#66 HTTP·이벤트 관계의 근거 계약](https://github.com/DDINGJOO/JJAM-TONG/issues/66) | 정적 후보·설정 추론·실제 Trace를 출처와 버전으로 연결함 | #65 |
| [#68 실제 결과 발행·소비자·화면 전환](https://github.com/DDINGJOO/JJAM-TONG/issues/68) | Java 분석 결과의 표현·상한·버전·저장과 조회 화면을 실제 경로에서 검증함 | #64 |
| [#70 Java v1 제한 스트림 발행](https://github.com/DDINGJOO/JJAM-TONG/issues/70) | #68의 첫 하위 작업. 기존 v1을 저장하면서 출력 상한·이전 파일 보존·소비자 호환을 검증함 | #64 |

기존 32개 요구사항 이슈의 완료 조건·상태·부모 관계를 유지하며, 별도 실험 에픽·스토리·태스크를 추가했다. 실제 진행 상태는 GitHub에서 확인한다.

## 다음 단계

[엔터프라이즈 운영 요구](docs/requirements/ENTERPRISE.md)와 [BDD-ENT-001~009](specs/features/11-enterprise-operations.feature)는 여러 조직·팀의 격리·권한·감사·수용량·가용성·복원·업그레이드 검증을 기존 #14/#15/#19/#26/#29/#37/#43/#44에 연결한다. 제품 구조·수치 목표·운영 적합성은 아직 검증하지 않았다.

[자동 확장·축소 요구](docs/requirements/AUTOSCALING.md)와 [BDD-ASC-001~009](specs/features/12-autoscaling.feature)는 지표 오류·실제 자원 확보·후속 병목·축소 중 인계·반복 증감·0개 축소·조직별 공정성과 예산·관측 대상의 자원 교체를 #19/#37과 연결한다. 제어기·설치 환경·수치 목표는 미결이며 자동 확장 검증을 완료한 상태는 아니다.

문서 탐색과 기록 규칙은 [프로젝트 위키](docs/wiki/Home.md)에서 확인한다. [T23 #40 위키형 문서 허브](https://github.com/DDINGJOO/JJAM-TONG/issues/40)는 기존 요구사항·실험 이슈의 상태와 계층을 보존하는 별도 문서 작업이며, [P1 문서·지식 기반](https://github.com/DDINGJOO/JJAM-TONG/milestone/11)에서 관리한다.

제품 중심을 자동 발견·등록·지속 갱신과 근거 기반 분석·운영 자동화로 확인했다. [자동화 제품 기획](docs/requirements/AUTOMATION.md)과 [온보딩 BDD 10개](specs/features/10-automated-onboarding.feature)를 S03의 #10·#11·#12와 S09의 #30·#31·#32에 연결한다. 기존 이슈·상태·부모 관계를 유지하며 세부 동작·정책은 Draft다. 다음 검토는 GitHub 연결로 게시판의 두 서비스를 발견하고 중복·역순·누락·권한 회수에도 관계를 정확히 유지하는 행동이다.

토론 입력으로 [12개 OSS 계열의 아키텍처 비교](docs/OSS-ARCHITECTURE-COMPARISON.md)와 [관련 저장소의 릴리스·라이선스 기록](docs/OSS-SOURCE-SNAPSHOT.md)을 추가했다. 게시판의 두 빌드·다중 환경·공유 DB·보안 이벤트·권한 반례를 기존 BDD·검증 태스크에 연결했다. 문서 조사이며 제품 채택·PoC 통과·요구사항 합의를 뜻하지 않는다.

각 시나리오의 원하는 결과·반례·미결정 사항을 함께 검토한다. 그다음 실제 검증 fixture와 판정을 정하고, OSS·인프라 PoC와 설계 대안·ADR을 논의한 뒤 구현 이슈를 만든다.

현재 feature는 실행기 없는 명세다. 시나리오 파일과 이슈 생성은 실행 수락 테스트 통과나 기능 완료를 의미하지 않는다.

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
| [R3 — SRE·인프라 요구사항](https://github.com/DDINGJOO/JJAM-TONG/milestone/3) | SRE 분석 질문과 현재/미래 인프라 문맥의 범위를 구분해 명세한다. |
| [R4 — CMDB·SIEM 미래 요구사항](https://github.com/DDINGJOO/JJAM-TONG/milestone/4) | 자산·보안 연결의 출처·시간·권한 경계를 미래 명세로 정리한다. 구현 단계가 아니다. |

일정·릴리스 버전은 정하지 않았다. 첫 제품 후보는 S01~S05, 인프라·CMDB·SIEM의 S06~S08은 미래 명세다. 각 시나리오는 모두 논의용 Draft다.

## E01 · [#2 메서드 관계·분석 버전 요구사항](https://github.com/DDINGJOO/JJAM-TONG/issues/2)

관계의 의미와 올바른 버전 연결을 행동으로 명세한다.

### S01 · [#3 정적 관계와 실제 실행을 구분해 이해한다](https://github.com/DDINGJOO/JJAM-TONG/issues/3)

에이전트와 개발자가 가능한 호출과 관측한 실행의 차이를 판단한다. (초기 명세)

[BDD 원본](specs/features/01-code-relations.feature) · BDD-REL-001, BDD-REL-002, BDD-REL-003

- [#4 메서드 관계 BDD 초안 검토와 미결정 정리](https://github.com/DDINGJOO/JJAM-TONG/issues/4)
- [#5 관계 분석·계측 검증 fixture 계획](https://github.com/DDINGJOO/JJAM-TONG/issues/5) · 선행: [#4](https://github.com/DDINGJOO/JJAM-TONG/issues/4)

### S02 · [#6 분석·실행의 코드 버전과 출처를 안다](https://github.com/DDINGJOO/JJAM-TONG/issues/6)

다른 빌드의 기록이 잘못된 지도에 연결되지 않게 요구한다. (초기 명세)

[BDD 원본](specs/features/02-version-identity.feature) · BDD-VER-001, BDD-VER-002, BDD-VER-003

- [#7 분석·실행 버전과 출처의 BDD 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/7)
- [#8 버전 오연결·누락·보존 검증 계획](https://github.com/DDINGJOO/JJAM-TONG/issues/8) · 선행: [#7](https://github.com/DDINGJOO/JJAM-TONG/issues/7)

## E02 · [#9 자동 갱신·에이전트 근거 조회 요구사항](https://github.com/DDINGJOO/JJAM-TONG/issues/9)

지도를 수동 유지하지 않고 에이전트가 신뢰 가능한 근거를 조회하도록 명세한다.

### S03 · [#10 코드 변경이 관계 지도에 자동 반영된다](https://github.com/DDINGJOO/JJAM-TONG/issues/10)

추가·삭제·이름 변경과 실패·재시도의 결과를 구분한다. (초기 명세)

[BDD 원본](specs/features/03-graph-refresh.feature) · BDD-UPD-001, BDD-UPD-002, BDD-UPD-003

- [#11 관계 지도 자동 갱신의 성공·실패 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/11)
- [#12 두 버전·삭제·동시 갱신 검증 예시](https://github.com/DDINGJOO/JJAM-TONG/issues/12) · 선행: [#11](https://github.com/DDINGJOO/JJAM-TONG/issues/11)

### S04 · [#13 에이전트가 출처와 한계를 가진 근거를 조회한다](https://github.com/DDINGJOO/JJAM-TONG/issues/13)

분석 질문에 버전·시점·커버리지·근거를 확인할 수 있는 응답을 요구한다. (초기 명세)

[BDD 원본](specs/features/04-agent-evidence.feature) · BDD-AGT-001, BDD-AGT-002, BDD-AGT-003

- [#14 에이전트 질문과 기계 조회 근거 계약 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/14)
- [#15 에이전트의 근거 누락·충돌·권한 반례](https://github.com/DDINGJOO/JJAM-TONG/issues/15) · 선행: [#14](https://github.com/DDINGJOO/JJAM-TONG/issues/14)

## E03 · [#16 SRE 분석·인프라 문맥 요구사항](https://github.com/DDINGJOO/JJAM-TONG/issues/16)

지연·오류와 운영 문맥을 증거로 연결하는 SRE 행동을 명세한다.

### S05 · [#17 지연·오류를 코드 실행 근거로 조사한다](https://github.com/DDINGJOO/JJAM-TONG/issues/17)

SRE가 느린 구간·혼합 성공/실패·부분 수집을 구분한다. (초기 명세)

[BDD 원본](specs/features/05-sre-analysis.feature) · BDD-SRE-001, BDD-SRE-002, BDD-SRE-003

- [#18 지연·오류·비동기 SRE 행동 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/18)
- [#19 비용·상한·부분 수집의 검증 계획](https://github.com/DDINGJOO/JJAM-TONG/issues/19) · 선행: [#18](https://github.com/DDINGJOO/JJAM-TONG/issues/18)

### S06 · [#20 서비스·배포·워크로드 문맥을 연결한다](https://github.com/DDINGJOO/JJAM-TONG/issues/20)

MSA/Kubernetes 확장 때 시점이 맞는 인프라 근거를 탐색한다. (미래 명세)

[BDD 원본](specs/features/06-infrastructure.feature) · BDD-INF-001, BDD-INF-002, BDD-INF-003

- [#21 서비스·배포·워크로드 관계의 미래 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/21)
- [#22 인프라 관계의 누락·오연결 반례](https://github.com/DDINGJOO/JJAM-TONG/issues/22) · 선행: [#21](https://github.com/DDINGJOO/JJAM-TONG/issues/21)

## E04 · [#23 CMDB·SIEM 통합의 미래 요구사항](https://github.com/DDINGJOO/JJAM-TONG/issues/23)

자산·소유권·보안 이벤트를 권한·출처·시간 기준으로 연결하도록 명세한다.

### S07 · [#24 자산·소유권·관계 이력을 근거로 조회한다](https://github.com/DDINGJOO/JJAM-TONG/issues/24)

관측 대상과 CMDB 자산·담당자 간 연결의 유효성을 판단한다. (미래 명세)

[BDD 원본](specs/features/07-cmdb.feature) · BDD-CMDB-001, BDD-CMDB-002, BDD-CMDB-003

- [#25 CMDB 자산·소유권·유효 시간 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/25)
- [#26 CMDB 갱신 지연·충돌·조회 권한 반례](https://github.com/DDINGJOO/JJAM-TONG/issues/26) · 선행: [#25](https://github.com/DDINGJOO/JJAM-TONG/issues/25)

### S08 · [#27 관련 보안 이벤트를 권한 안에서 연결한다](https://github.com/DDINGJOO/JJAM-TONG/issues/27)

SIEM 근거를 같은 서비스·배포·자산의 운영 증거와 함께 조회한다. (미래 명세)

[BDD 원본](specs/features/08-security.feature) · BDD-SEC-001, BDD-SEC-002, BDD-SEC-003

- [#28 보안 이벤트 상관 분석의 미래 행동 명세](https://github.com/DDINGJOO/JJAM-TONG/issues/28)
- [#29 보안 조회 누락·민감정보·자동 대응 경계](https://github.com/DDINGJOO/JJAM-TONG/issues/29) · 선행: [#28](https://github.com/DDINGJOO/JJAM-TONG/issues/28)

## 다음 단계

각 시나리오의 원하는 결과·반례·미결정 사항을 함께 검토한다. 그다음 실제 검증 fixture와 판정을 정하고, OSS·인프라 PoC와 설계 대안·ADR을 논의한 뒤 구현 이슈를 만든다.

현재 feature는 실행기 없는 명세다. 시나리오 파일과 이슈 생성은 실행 수락 테스트 통과나 기능 완료를 의미하지 않는다.

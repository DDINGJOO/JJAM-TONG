# 요구사항과 게시판 시나리오

[위키 홈](Home.md) · 원본: [BDD 인덱스](../requirements/README.md), [자동화 제품 기획](../requirements/AUTOMATION.md)

## 게시판을 기준으로 묻는 질문

아래는 **검증할 합성 시나리오**다. 실제 게시판 서비스·클러스터가 구현되거나 수락 테스트가 통과한 것으로 읽지 않는다.

| 상황 | 확인하려는 결과 | 명세와 작업 |
| --- | --- | --- |
| GitHub 모노레포를 연결했더니 게시판 API와 백그라운드 작업 서비스가 발견됨 | 등록 조건을 충족한 서비스 선언과 코드 구조에서 추정한 서비스 후보를 구분하고 중복 등록을 막음 | [온보딩](../../specs/features/10-automated-onboarding.feature), [S03 #10](https://github.com/DDINGJOO/JJAM-TONG/issues/10), [S09 #30](https://github.com/DDINGJOO/JJAM-TONG/issues/30) |
| `Controller → Service → private 검증 → Repository` | 코드상 호출 가능 관계와 실제 요청에서 실행된 관계를 따로 표현 | [메서드 관계](../../specs/features/01-code-relations.feature), [S01 #3](https://github.com/DDINGJOO/JJAM-TONG/issues/3) |
| 새 코드가 올라왔지만 운영은 이전 빌드 | 해당 요청이 실행한 빌드·소스·분석 버전을 찾아 연결 | [버전 식별](../../specs/features/02-version-identity.feature), [S02 #6](https://github.com/DDINGJOO/JJAM-TONG/issues/6) |
| 메서드 삭제·이름 변경, 알림 중복·역순·누락 | 자동 갱신과 실패·오래된 결과·수집 공백을 설명 | [관계 갱신](../../specs/features/03-graph-refresh.feature), [S03 #10](https://github.com/DDINGJOO/JJAM-TONG/issues/10) |
| 배포 뒤 게시글 조회가 느려짐 | 느린 실행과 비교 조건·누락을 조회하고 원인 가설과 사실을 구분 | [에이전트 근거](../../specs/features/04-agent-evidence.feature), [SRE 분석](../../specs/features/05-sre-analysis.feature), [S04 #13](https://github.com/DDINGJOO/JJAM-TONG/issues/13), [S05 #17](https://github.com/DDINGJOO/JJAM-TONG/issues/17) |
| 요청·수집 부하와 코드·버전 규모가 늘거나 한 서비스가 폭주함 | 업무와 플랫폼의 목표 충족 부하, 적체·신선도·서비스별 격리와 부하 감소 후 복구를 각각 검증 | [수용량 계획](../experiments/CAPACITY-VALIDATION.md), [BDD-SRE-005~008](../../specs/features/05-sre-analysis.feature), [T10 #19](https://github.com/DDINGJOO/JJAM-TONG/issues/19) |
| 여러 조직·팀이 사용하며 권한 회수·장애·복원·업그레이드를 수행함 | 조직 격리와 현재 권한·감사·기업 운영 목표를 유지하고 검증 수준과 미측정을 설명 | [기업 운영 요구](../requirements/ENTERPRISE.md), [BDD-ENT-001~009](../../specs/features/11-enterprise-operations.feature) |
| 입력 폭주·자동 확장·축소와 자원 교체가 발생함 | 단계별 신호·기동·인계·후속 병목·예산을 판정하고 대상의 당시 배포/빌드 연결을 보존 | [자동 확장 요구](../requirements/AUTOSCALING.md), [BDD-ASC-001~009](../../specs/features/12-autoscaling.feature), [#19](https://github.com/DDINGJOO/JJAM-TONG/issues/19)·[#37](https://github.com/DDINGJOO/JJAM-TONG/issues/37) |
| EKS·ECS·일반 Kubernetes 배포가 같은 DB를 사용 | 서비스·배포·실제 자원·공유 관계를 시점과 출처로 구분 | [인프라](../../specs/features/06-infrastructure.feature), [카탈로그 매핑](../../specs/features/09-catalog-mapping.feature), [S06 #20](https://github.com/DDINGJOO/JJAM-TONG/issues/20), [S09 #30](https://github.com/DDINGJOO/JJAM-TONG/issues/30) |
| 자산 소유자가 바뀌고 관련 보안 이벤트가 발견됨 | 당시 소유권·관계 이력과 허용된 보안 근거를 연결 | [CMDB](../../specs/features/07-cmdb.feature), [보안](../../specs/features/08-security.feature), [S07 #24](https://github.com/DDINGJOO/JJAM-TONG/issues/24), [S08 #27](https://github.com/DDINGJOO/JJAM-TONG/issues/27) |

## BDD를 읽는 규칙

BDD는 사용자의 행동과 기대 결과를 시나리오로 표현하는 방식이다. 전체 명세는 **기능 명세 파일 12개와 시나리오 83개**로 구성되어 있고, 모두 `@draft @required`로 표시한다. `@required`는 구현 대상을, `@draft`는 검토 중인 세부 행동을 뜻한다. 현재는 시나리오를 실행하는 테스트 도구가 없으므로 명세를 작성한 것과 수락 테스트를 통과한 것을 구분한다. 시나리오 ID와 상위 스토리·검증 태스크의 연결 관계는 [원본 인덱스](../requirements/README.md)와 [로드맵](../../ROADMAP.md)에서 확인한다.

새 요구는 먼저 사용자·전제·행동·기대 결과를 쓰고, 정상 예와 함께 누락·충돌·권한·버전 불일치 반례를 붙인다. 기존 시나리오에 연결할 수 있으면 중복 이슈를 만들지 않는다. 구현 전에는 검증용 예제와 입력(fixture), 판정 방법, 아직 정하지 않은 정책을 이슈에 남긴다.

## 계속 지켜야 할 구분

- 정적 호출 후보와 실제 관측 호출을 구분한다. 관측하지 못했다고 호출 불가능으로 단정하지 않는다.
- 소스 commit, 실제 build/artifact, 배포, 분석기·스키마·설정 버전을 구분한다.
- 선언한 자원 관계와 수집한 사실, 추정 매핑과 확인한 매핑을 구분한다.
- 연결·조회 권한을 배포·수정·보안 대응 실행 권한으로 확대하지 않는다.

아직 정하지 않은 API 필드·보존 정책·계측 범위·비용 상한은 [설계 토론](../DISCUSSIONS.md)에서 검토한다.

[대규모 레거시 코드 분석 요구](../requirements/CODE-ANALYSIS-SCALE.md)는 공통 모듈 집중·순환·다형성·생성 코드·프레임워크와 이벤트를 검증 대상으로 둔다. [BDD-UPD-005~010](../../specs/features/03-graph-refresh.feature)은 정확 입력 재사용, 무효화, 손상·동시 요청·자원 실패와 복잡 구조의 후보·해석 공백을 명세한다. 한정된 CLI 검증과 전체 제품 수락 테스트는 구분한다.

같은 명세의 BDD-UPD-011·012는 최적화 전후에 소스 위치·관계를 보존하고 패키지·소스 배치가 다른 입력을 처리하도록 요구한다. [파서 메모리 검증](../experiments/JAVA-PARSER-MEMORY.md)은 그중 한정된 Java 도구의 실제 결과다. 분석 작업·빌드 발견·서비스 간 근거의 공통 계약은 후속 이슈에서 검증하며, 두 시나리오는 실행기 없는 Draft 상태를 유지한다.

[분석 작업 공통 계약](../requirements/ANALYSIS-JOB.md)과 BDD-UPD-013~018은 입력 버전·실행 시도·필수 단계·자원·완료·실패를 구분한다. 같은 내용의 단일 파일·분할 발행은 [로컬 계약 실험](../experiments/ANALYSIS-JOB-CONTRACT.md)에서 비교했으며 기존 Java·DB·화면 전환은 #68로 연결한다.

# JJAM-TONG Platform

**가시성을 자동으로 유지하고, 그 근거로 분석과 운영을 자동화하는 플랫폼**을 만든다. 코드·실행·배포·인프라·자산·보안의 근거를 연결해 에이전트와 SRE의 빠르고 정확한 분석을 지원한다.

목표는 “배포 이후 왜 느려졌는가?” 같은 질문에 **trace → 실행된 메서드 → 일치하는 빌드·소스 → 배포·인프라 → 관련 자산·보안 이벤트**의 근거를 기계가 조회할 수 있게 제공하는 것이다. 확인한 사실과 분석 가설, 아직 없는 근거를 구분한다.

이 저장소는 **BDD 요구사항·OSS 비교 실험과 첫 라이브러리·연동 도구 구현**을 진행한다. [버전 근거 계약 Java 라이브러리](libraries/evidence-contract-java/README.md)는 빌드 정보의 일치·불일치·누락을 비교한다. [정적 호출 후보·자동 메서드 계측의 로컬 구현](docs/experiments/METHOD-OBSERVABILITY-RESULTS.md)도 검증했으며, 정확한 overload 실행 식별·부분 재분석과 통합 플랫폼 구현은 남아 있다.

[에이전트 적용 전후의 HTTP 성능](docs/experiments/EXECUTION-PERFORMANCE-RESULTS.md)은 같은 Boot 앱에서 미적용·기본 추적·메서드 추적을 27회 비교했다. 지연·처리량·CPU·메모리·기동 시간과 원시값을 함께 남긴다.

[수용량·과부하·복구 검증 계획](docs/experiments/CAPACITY-VALIDATION.md)은 업무 서비스와 JJAM-TONG의 처리 한계를 구분한다. 목표를 만족하는 지속 부하, 수집·분석·조회 적체, 데이터 규모와 부하 감소 후 복구를 검증할 요구이며 수용량 실측 결과는 아직 없다.

[엔터프라이즈 운영 요구](docs/requirements/ENTERPRISE.md)는 기업의 여러 조직·팀과 다중 환경을 기준으로 격리·권한·감사·고가용성·재해복구·업그레이드를 명세한다. 현재는 품질 요구와 검증 계획이며 운영 적합성이나 지원 규모를 입증한 상태는 아니다.

첫 개발 목표는 **별도로 관리하는 프로젝트에 도입할 코드 관측성 라이브러리와 필요한 연동 도구**다. 대상 앱은 별도 저장소에 유지하고, 로컬에서 라이브러리를 적용해 정적 호출 후보·실제 실행·빌드 버전의 연결을 검증한다. 상세 범위는 [첫 개발 단계](docs/PROJECT.md#첫-개발-단계-외부-프로젝트에-도입할-라이브러리)에 있다. 별도 로컬 MSA 대상에 이 JAR을 적용했고, [Kafka·Redis·DB 장애와 복구의 9개 시나리오](docs/experiments/LOCAL-MSA-TARGET.md)를 실행했다. 실제 RDS·Kubernetes 지원은 아직 검증하지 않았다.

자동 갱신은 [비교 실험실](experiments/architecture_lab/README.md)에서 세 방식으로 구현해 실행했다. [16개 시나리오의 결과](docs/experiments/RESULTS.md)와 [방법론·아키텍처 비교 계획](docs/experiments/ARCHITECTURE-EXPERIMENTS.md)을 공개한다. 합성 공급원·동일 SQLite의 로컬 실험이며 실제 GitHub·코드 계측·AWS 통합이나 전체 BDD 통과를 뜻하지 않는다.

다음 [원본 재확인 실험](experiments/reconciliation_lab/README.md)은 실제 Git 원본·loopback 웹훅·공개 GitHub REST 읽기와 in-process/one-shot worker를 비교한다. [주기적 확인과 변경 알림의 결합](docs/decisions/0001-reconciliation-baseline.md)을 관계 갱신의 검증 기본안으로 기록했으며, [실행 결과](docs/experiments/HYBRID-RESULTS.md)에서 실측·주입 장애·미실행을 구분한다. 이 갱신 실험의 색인은 파일·blob 관계다. 메서드 근거는 별도 [분석 어댑터](tools/java-call-analysis/README.md)와 [버전별 연결 도구](tools/method_evidence/README.md)로 비교한다.

```sh
python3 -m unittest discover -s experiments/architecture_lab -p 'test_*.py' -v
python3 -m experiments.architecture_lab.lab --output results/architecture-lab --changes 200
python3 -m unittest experiments.reconciliation_lab.test_reconciliation -v
python3 -m experiments.reconciliation_lab.run --repetitions 3
```

## 명세할 문제와 기대 결과

- 코드에서 메서드와 **호출 가능 관계**를 분석한다.
- 애플리케이션에서 **실제로 실행된 호출 흐름·시간·오류**를 관측한다.
- 코드 변경 시 분석 결과를 자동으로 다시 만들고, 분석마다 코드·빌드·분석기 버전을 남긴다.
- 배포된 버전의 코드 지도에 해당 실행 기록을 연결하고 에이전트가 조회할 수 있는 구조화된 근거로 제공한다.
- MSA·Kubernetes·인프라 관계와 CMDB의 자산·소유권·변경 이력, SIEM의 보안 이벤트를 같은 대상·시점의 근거로 연결한다.

관계를 수동으로 계속 수정하거나 에이전트가 매번 원본을 다시 추측하는 부담을 줄이는 것이 첫 문제다. 모든 근거에 버전·출처·수집 시점·신선도·수집 범위·불확실성을 담는 요구를 검토한다. 정적 후보 관계와 실제 호출을 구분하고, 미관측을 호출 불가능으로 판단하지 않는다. 화면은 이 근거를 이용하는 조회 채널 중 하나다.

진행 순서는 **요구사항·BDD 초안 → 함께 토론·검증 기준 정리 → 오픈소스·인프라 PoC → 아키텍처 ADR → 구현**이다. 현재 이슈는 명세·논의·검증 계획을 위한 작업이며 기능 구현 계획을 확정한 것이 아니다.

첫 온보딩은 **GitHub 연결 → 서비스 발견·등록 → 변경 자동 갱신 → 근거 기반 분석 → 정책에 따른 운영 실행**으로 구체화한다. 유효한 선언의 자동 반영과 추정 후보의 확인, 모노레포의 여러 서비스, 이벤트 누락·권한 회수는 [자동화 제품 기획](docs/requirements/AUTOMATION.md)의 BDD 초안으로 검토한다. 코드·실제 배포·런타임·자산·보안의 연결 상태를 각각 설명하며, GitHub 연결만으로 모든 영역을 수집한다고 약속하지 않는다.

## 전체 구현 범위

| 영역 | 확인할 사용자 결과 |
| --- | --- |
| 코드 관측성 | 메서드 관계와 실제 실행을 같은 버전의 근거로 조회; Java fixture부터 분석 방식 검증 제안 |
| MSA·인프라 | AWS EKS·ECS와 일반 Kubernetes의 실행·배포 문맥을 연결 |
| 카탈로그·CMDB | 서비스·시스템·소유자를 온프레미스·AWS 자원에 매핑하고 관계의 변경 이력을 조회 |
| 보안·SIEM | 운영 문제와 관련 보안 이벤트의 근거를 함께 탐색 |

위 영역은 모두 구현 대상이다. 구현 순서·지원 조합·도구의 재사용 범위는 의존성과 설계 토론으로 정한다. 현재 요구사항을 작성하는 상태이며 기능 구현이나 운영 준비가 완료된 것은 아니다.

이식성도 공통 품질 요구로 다룬다. 플랫폼의 설치 환경과 관측 대상 환경을 구분하고, 언어·CI·수집 도구를 바꿀 때 보존할 근거 계약과 지원 차이를 [BDD 요구사항](docs/requirements/README.md)에 명세한다.

관측 지원 대상은 **AWS EKS·ECS와 일반 Kubernetes**, 카탈로그 매핑 대상은 **온프레미스·AWS 자원**이다. 카탈로그의 논리 서비스와 환경별 배포·실제 자원을 구분해 다중 환경·공유 자원을 표현한다. 수동 선언과 수집한 사실, 매핑 후보·확정·충돌을 출처·시점과 함께 구분하는 행동을 검토한다. 플랫폼 자체의 설치 환경·지원 버전·수집 방식은 별도로 논의하며 현재 실행 구현은 없다.

## 프로젝트 문서

[프로젝트 Wiki](https://github.com/DDINGJOO/JJAM-TONG/wiki)에서 비전·게시판 시나리오·아키텍처와 결정·OSS 비교·실험 결과·작업 이슈를 분야별로 탐색한다. [저장소 원본](docs/wiki/Home.md)에서도 읽을 수 있다. 상세 근거는 기존 문서, 진행 상태는 GitHub Issues가 기준이다.

| 문서 | 내용 |
| --- | --- |
| [비전](docs/VISION.md) | 풀려는 문제와 전체 통합 범위 |
| [프로젝트 정의](docs/PROJECT.md) | 플랫폼 범위·성공 조건·진행 규칙 |
| [요구사항·BDD](docs/requirements/README.md) | 시나리오·요구사항 이슈·미결 질문 |
| [자동화 제품 기획](docs/requirements/AUTOMATION.md) | GitHub 발견·등록·지속 갱신·실패 복구와 기존 이슈 연결 |
| [아키텍처 비교 실험](docs/experiments/ARCHITECTURE-EXPERIMENTS.md) | 방법론·비교 축·첫 실행 결과·다음 판별 실험 |
| [구조 제안](docs/ARCHITECTURE.md) | 분석·실행·버전 결합의 책임과 데이터 계약 |
| [설계 토론](docs/DISCUSSIONS.md) | 열려 있는 대안·트레이드오프·판별 실험 |
| [오픈소스·인프라 조사](docs/RESEARCH.md) | 후보·공식 근거·확인할 한계 |
| [OSS 아키텍처 비교](docs/OSS-ARCHITECTURE-COMPARISON.md) | 12개 OSS 계열의 구조·재사용 경계·차별화 가설과 게시판 검증 계획 |
| [릴리스·라이선스 근거](docs/OSS-SOURCE-SNAPSHOT.md) | 관련 15개 저장소의 버전·원문·미검증 항목 |
| [로드맵](ROADMAP.md) | 에픽·스토리·태스크와 다음 작업 |
| [기여 가이드](CONTRIBUTING.md) | 작업·검증·완료 조건 |

실제 상태는 [GitHub Issues](https://github.com/DDINGJOO/JJAM-TONG/issues)의 부모·자식 관계, milestone, 상태 라벨로 관리한다. 개인 진행 태스크는 동시에 1개로 제한한다.

## 아직 결정하지 않은 것

현재 관계 갱신은 [원본 재확인과 변경 알림을 결합하는 검증 기본안](docs/decisions/0001-reconciliation-baseline.md)을 사용한다. 전체 제품 아키텍처·파이프라인·스택은 함께 토론할 제안이다. 정적 분석기, 계측 방식, 근거 조회 계약·저장소·화면·배포 환경과 라이선스는 대안 비교·실험·ADR을 거쳐 결정한다. 퍼블릭 저장소라는 사실만으로 별도의 사용·재배포 라이선스를 부여하지 않는다.

블로그 글 작성·발행은 프로젝트 목표에 포함하지 않는다. 공개 예제와 검증 자료에는 합성 데이터를 사용한다.

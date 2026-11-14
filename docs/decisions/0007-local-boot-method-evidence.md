# ADR 0007 Spring Boot 메서드 근거의 로컬 연결

- 상태: 로컬 검증 경로에 적용. 전체 플랫폼 기술 채택은 미결이다.
- 날짜: 2026-11-14
- 관련 작업: [T25 #44](https://github.com/DDINGJOO/JJAM-TONG/issues/44)
- 선행 결정: [ADR 0004](0004-method-evidence-comparison.md), [ADR 0005](0005-local-versioned-evidence-store.md), [ADR 0006](0006-github-method-evidence-pull.md)

## 결정

별도 Playground의 실제 `board-api` 실행 JAR을 정적 분석하고, 실제 HTTP 요청의 OpenTelemetry 실행 기록을 같은 빌드의 PostgreSQL 색인과 대조한다. 기존 일반 Java 검증 모듈의 GitHub 수집 경로는 유지하며, 이번 Boot 경로는 로컬에서 검증한다.

배포 식별자는 원본 실행 JAR의 해시를 사용한다. 분석을 위해 `BOOT-INF/classes`만 일반 JAR로 재구성하고 그 해시를 별도로 남긴다. `BOOT-INF/lib` 안의 라이브러리는 원래 경로와 해시를 보존하며 타입 해석에만 쓴다. 소스·커밋·빌드·모듈·분석기와 설정도 기존 불변 색인에 함께 기록한다. 재구성한 JAR을 배포 산출물로 바꾸어 표시하지 않는다.

## 선택 이유와 대안

| 방법 | 장점 | 한계와 판단 |
| --- | --- | --- |
| 기존 `main()` 시작 분석 유지 | 입력·분석 경계가 작고 기존 검증 모듈에 적합하다 | Spring이 호출하는 Controller를 `main()`의 앱 내부 호출만으로 찾기 어렵다 |
| 원본 JAR을 보존하고 모든 포함 메서드를 가상 시작점으로 분석 | 프레임워크 호출 모델을 먼저 구현하지 않아도 실제 앱의 메서드 후보 관계를 조회할 수 있다 | 실행 가능성을 넓게 추정한다. 이번 한정된 경로로 선택한다 |
| Spring의 라우팅·빈 선택·프록시를 정밀하게 분석 | 프레임워크의 호출 조건을 더 구체적으로 설명할 수 있다 | 프레임워크 버전별 모델과 정확성 검증이 추가로 필요하다. 별도 후속 검증으로 둔다 |

WALA의 클래스 계층 분석(CHA)은 가능한 호출 대상을 만든다. 포함 범위의 본문이 있는 메서드를 각각 시작점으로 삼되, 생성자·클래스 초기화 메서드·컴파일러가 생성한 메서드도 포함한다. 이 시작점은 분석 가정이며 실제 API 등록이나 실행을 뜻하지 않는다. 라이브러리는 WALA의 `Extension` 영역에 넣고 앱 클래스와 구분한다. 이 구성에서는 라이브러리가 앱을 호출하는 관계를 복원하지 않는다.

## 결과와 제약

[실제 검증 결과](../experiments/BOOT-METHOD-EVIDENCE.md)에서 두 Boot 빌드의 정적 색인, 게시글 등록 요청과 같은 빌드의 조회, 다른 빌드·다른 해시 거부를 확인했다. 중첩 타입의 JVM 이름 표기 오류를 수정하고 새 분석 ID로 재검증했다.

빌드 부속 정보와 깨끗한 체크아웃의 일치는 로컬 검증이다. 서명된 빌드 출처 증명이나 원격 실행 인증을 대신하지 않는다. OpenTelemetry 메서드 span에는 JVM descriptor가 없어 같은 이름의 여러 시그니처를 실행 단계에서 확정하지 않는다. 정적 후보·관측한 부모 관계·미해결 후보를 구분한다.

분석 입력과 임시 추출량, JVM 힙·실행 시간·결과 크기에 상한을 둔다. 원시 실행 로그는 무시되는 `.local` 아래에만 남기고, 공개 결과는 허용 필드만 추린다. 이번 입력 하나의 성공은 모든 Boot 앱의 호환성이나 기업 규모 수용량을 보장하지 않는다.

## 후속 검증

Boot 결과의 CI 발행·주기 수집 계약, trace 지속 수집, 정확한 overload 식별, 실제 부분 재분석과 프레임워크별 호출 모델을 각각 검증한다. outbox의 추적 문맥 연결·Redis 관측 공백·전송 유실·수용량 검증도 기존 열린 요구로 유지한다.

## 공식 구현 근거

고정한 WALA의 [scope 구성](https://github.com/wala/WALA/blob/ab3bd3b2b9291e047b203cddd248cbbcfcff6f1e/core/src/main/java/com/ibm/wala/core/util/config/AnalysisScopeReader.java), [시작점](https://github.com/wala/WALA/blob/ab3bd3b2b9291e047b203cddd248cbbcfcff6f1e/core/src/main/java/com/ibm/wala/ipa/callgraph/impl/DefaultEntrypoint.java), [CHA 구현](https://github.com/wala/WALA/blob/ab3bd3b2b9291e047b203cddd248cbbcfcff6f1e/core/src/main/java/com/ibm/wala/ipa/callgraph/cha/CHACallGraph.java)과 JavaParser의 [JAR 타입 해석기](https://github.com/javaparser/javaparser/blob/e72889831e5e06532f2185ec9ae16531237f9f69/javaparser-symbol-solver-core/src/main/java/com/github/javaparser/symbolsolver/resolution/typesolvers/JarTypeSolver.java)를 확인했다. 새 의존성은 추가하지 않았다.

# 실제 Spring Boot 메서드와 실행 기록을 같은 빌드로 조회한다

2026-11-14, 별도 Playground의 `board-api`에서 **실행 JAR 분석 → 실제 게시글 등록 → OpenTelemetry 메서드 기록 → PostgreSQL의 같은 빌드 조회**를 연결했다. 기존 GitHub 수집 경로의 작은 검증용 코드에서 실제 Boot 서비스 한 모듈로 로컬 검증 범위를 넓혔다.

[구조화한 결과](boot-method-evidence-results.json) · [ADR 0007](../decisions/0007-local-boot-method-evidence.md) · [분석 도구](../../tools/java-call-analysis/README.md) · [T25 #44](https://github.com/DDINGJOO/JJAM-TONG/issues/44)

## 무엇을 실행했나

대상은 [별도 Playground](https://github.com/DDINGJOO/JJAM-TONG-playground)의 커밋 `0ea6a6845550a86114c28bcbf660723ac3575561`이다. 같은 소스에서 빌드 ID가 다른 실제 Boot 산출물 두 개를 만들었다. 코드 변경 전후 비교는 앞선 [GitHub 갱신 실험](GITHUB-EVIDENCE-SYNC.md)에서 수행했고, 이번에는 같은 소스의 다른 빌드도 구분하는지 확인했다.

| 항목 | 첫 빌드 | 비교 빌드 |
| --- | --- | --- |
| 빌드 ID | `boot-evidence-b1` | `boot-evidence-b2` |
| 모듈 | `board-api` | `board-api` |
| 최종 분석 ID | `boot-local-b1-r2` | `boot-local-b2-r2` |
| 원본 실행 JAR SHA-256 | `1689e0349f44095f206e90b48a50173ee00a0a8ef5bb7c17f6e07055c3332187` | `7f91607e1d91ba5d044311e14251ed8e217b12e544a4f4bb6b900fd3c0d7d188` |
| 정적 색인의 고유 메서드 | 70개 | 70개 |

Spring Boot 4.1.2의 앱을 기존 JDK 21 Maven 이미지로 빌드했다. 분석은 로컬 Corretto `21.0.11`, 실제 앱은 digest로 고정한 Temurin `21.0.13_9` 런타임 이미지에서 실행했다. JavaParser·SymbolSolver 3.28.2, WALA 1.9.0, OpenTelemetry Java agent 2.33.1을 재사용했다. 새 의존성은 추가하지 않았다.

별도 Compose 프로젝트에 게시판·소비자 서비스와 PostgreSQL·Redis·Kafka를 띄웠다. 기존 실행 컨테이너 12개의 ID가 종료 후에도 같음을 확인했다. DB 저장 공통부도 별도 루프백 PostgreSQL을 그대로 사용했다.

## 실행 JAR의 내부 구조를 구분한다

Boot 실행 JAR은 앱 클래스가 `BOOT-INF/classes`, 의존 라이브러리가 `BOOT-INF/lib`에 있다. 분석 도구는 앱 클래스만 일반 JAR로 재구성하고, 원본 실행 JAR 해시와 재구성한 클래스 JAR 해시를 따로 기록한다. 두 빌드의 클래스 해시는 같고 원본 실행 JAR 해시는 다르다. 라이브러리 83개의 원래 경로와 해시도 색인에 보존했다.

JavaParser는 소스 선언의 호출 대상을 해석하고, WALA는 클래스 계층 분석(CHA)으로 가능한 대상을 구한다. 라이브러리는 타입 해석에만 쓰며 앱 그래프의 메서드로 합치지 않는다.

Spring이 호출하는 Controller는 앱의 `main()`에서 시작하는 호출 분석만으로 놓칠 수 있다. 이번 모드는 포함 범위의 본문이 있는 메서드 67개를 각각 **가상 시작점**으로 삼는다. 생성자·클래스 초기화 메서드·컴파일러가 생성한 메서드도 포함한다. 이는 후보 관계를 넓게 찾는 분석 가정이며, 모든 메서드가 실제 요청으로 실행될 수 있다는 뜻은 아니다.

## 실제 판정

| 조건과 행동 | 실제 결과 |
| --- | --- |
| 첫 빌드로 `POST /posts`를 호출한다 | HTTP 201, outbox 발행과 Kafka 소비 효과 1건을 확인했다 |
| 같은 빌드의 색인으로 요청을 조회한다 | Controller·Service의 `create`, private 메서드 `normalizeTitle`·`appendEvent`를 하나의 메서드로 연결했다 |
| 같은 클래스에 `validate` 시그니처가 두 개 있다 | 관측한 span 3개 모두 후보 2개를 남기고 `UNRESOLVED_CODE_SYMBOL`로 반환했다 |
| 실제 요청을 다른 실제 빌드의 색인으로 조회한다 | `MISMATCH`, 연결한 span 0개를 반환했다 |
| 수집한 실행 기록의 빌드 ID를 바꾸어 조회한다 | `MISMATCH`로 거부했다. 실제 다른 빌드 시험과 별도의 변조 반례다 |
| 분석 ID는 그대로 두고 색인 해시를 바꾼다 | `VersionMismatch`로 거부했다 |
| 같은 Controller에서 분석기별 그래프를 조회한다 | JavaParser는 메서드 7개·호출 7개, WALA는 메서드 13개·호출 16개를 반환했다 |

이 요청에서 수집한 span은 10개이며, 그중 클래스·메서드 식별자가 있는 span은 7개다. 그중 4개는 클래스·이름에 해당하는 후보가 하나여서 연결했고, `validate` span 3개는 정확한 시그니처를 확정하지 않았다. 이 연결은 같은 색인의 유일한 이름 후보에서 JVM descriptor를 가져온 결과이며, 실행기가 descriptor를 직접 관측한 결과와 구분한다.

요청에 전달한 외부 부모 span은 로컬 로그에 없으므로 trace 상태는 `PARTIAL`, 이유는 `PARENT_EXTERNAL_OR_NOT_COLLECTED`다. span 부모 관계도 관측한 추적 문맥이며 소스의 동기 호출을 증명하지 않는다.

정적 분석 전체에서는 JavaParser가 선언 42개·호출 53개, WALA가 메서드 70개·호출 66개를 만들었다. JavaParser에는 메서드 목록에 없는 끝점으로 향하는 호출 27개와 미해결 항목 4개가 있다. 생성된 record 접근자 등의 후보를 원본에 남기되 조회용 노드를 새로 만들지 않아 저장한 호출은 26개다. WALA의 미해결 항목은 3개다. 두 그래프 모두 `PARTIAL`을 유지하며, 이 집계는 위 요청에서 공백이 있는 경로를 실제 실행했다는 뜻은 아니다.

## 첫 실행에서 찾은 식별자 오류

첫 분석에서 JavaParser가 중첩 타입을 `BoardController/WriteRequest`로 표현했고, 바이트코드는 `BoardController$WriteRequest`를 사용했다. 같은 Controller 메서드가 서로 다른 후보 두 개로 잡혔다. JVM의 이진 클래스 이름으로 descriptor를 만들도록 고치고, 중첩 참조 배열·제네릭의 타입 소거도 컴파일한 WALA 결과와 대조하는 회귀 검사를 추가했다.

이전 색인은 덮어쓰지 않았다. 새 분석 ID 두 개를 만들고 HTTP 시험을 다시 실행해 Controller까지 유일 후보로 연결됨을 확인했다. 첫 실행의 분석 ID·해시·증상은 결과 JSON의 `earlierRun`에 남겼다.

## 재현 순서

`TARGET_ROOT`는 별도 Playground 체크아웃, `JDK_21`은 설치된 JDK 21 경로다. 아래 빌드 ID와 분석 ID는 재현할 때 새 값으로 바꾼다. 기존 분석은 덮어쓰지 않는다.

```sh
python3 tools/java-call-analysis/build.py
python3 tools/java-call-analysis/verify.py --java-home "$JDK_21"
python3 libraries/evidence-contract-java/build.py
python3 "$TARGET_ROOT/scripts/build.py" \
  --library "$PWD/libraries/evidence-contract-java/build/evidence-contract.jar" \
  --build-id boot-evidence-b1 --build-id boot-evidence-b2

python3 -m tools.boot_evidence --target "$TARGET_ROOT" \
  --module board-api --build-id boot-evidence-b1 \
  --include-package io.jjamtong.sandbox.board --java-home "$JDK_21" \
  --run-id boot-local-b1-r2 --output .local/boot-evidence/index-b1-r2
python3 -m tools.boot_evidence --target "$TARGET_ROOT" \
  --module board-api --build-id boot-evidence-b2 \
  --include-package io.jjamtong.sandbox.board --java-home "$JDK_21" \
  --run-id boot-local-b2-r2 --output .local/boot-evidence/index-b2-r2
```

그다음 [기존 DB 안내](../../tools/evidence_store/README.md)에 따라 로컬 저장소를 준비하고, Psycopg 3.2.12가 있는 Python 환경에서 실행한다. `JJAMTONG_EVIDENCE_DSN`에는 해당 로컬 DB 연결 정보를 설정한다. 새 출력 경로는 제품 저장소에서 무시하는 `.local` 아래에 있어야 한다.

```sh
python3 -m experiments.boot_evidence_smoke --target "$TARGET_ROOT" \
  --index .local/boot-evidence/index-b1-r2/boot-local-b1-r2.json \
  --other-index .local/boot-evidence/index-b2-r2/boot-local-b2-r2.json \
  --agent .local/method-observability/opentelemetry-javaagent-2.33.1.jar \
  --output "$PWD/.local/boot-evidence/smoke-02"
```

[실행 도구](../../experiments/boot_evidence_smoke.py)는 원본 산출물 해시를 대조한 뒤 격리한 앱을 띄우고, 같은 빌드·다른 빌드의 DB 조회까지 판정한다. 종료 시 자기 Compose 프로젝트만 내리고 기존 컨테이너 ID를 다시 확인한다. 원시 로그는 공개하지 않고, 공개 결과에는 허용한 메서드·버전·추적 식별자와 시각·오류 여부·해시만 남긴다.

## 완료 범위와 다음 검증

이번 결과는 실제 Boot 게시판 모듈의 **로컬 정적 분석과 단일 요청 조회**다. DB에는 정적 색인을 보관하고, trace는 비공개 로컬 파일을 읽어 조회했다. 상시 trace 저장·GitHub의 Boot 결과 발행·화면 자동 갱신은 다음 연결 범위다. 기존 CI bundle v1과 수집기는 여전히 `method-fixture`를 대상으로 한다.

일반 Java 분석은 기존 `plain`·`main` 기본값을 유지한다. Boot 분석은 `spring-boot`·`all-included-methods`를 함께 지정하며 혼합 설정을 거부한다. 원본 JAR·추출량·힙·시간·출력 상한과 회귀 검사 조건은 [분석 도구 안내](../../tools/java-call-analysis/README.md)에 있다. 중첩 JAR 자체의 바이트 상한은 그 내부 전체 압축 해제량의 상한을 뜻하지 않는다.

빌드 부속 정보는 호출자가 제공한 근거를 로컬에서 대조한 것이며 원격 빌드 출처 인증이 아니다. 정확한 overload 실행 식별, 부분 재분석, HTTP→예약 outbox의 추적 문맥, Redis 관측 공백·실제 전송 유실·지속 수용량·운영 권한은 열린 검증 항목으로 유지한다. 같은 요청의 trace에 Kafka 후속 처리가 이어졌다고 주장하지 않는다.

## 검증과 검토 기록

Python 회귀 검사 69개가 모두 통과했으며, 실제 PostgreSQL 경로 17개가 포함된다. JDK 21에서는 기존 호출 분석 검사와 새 Boot 입력 경계 검사를 실행했다. 중첩 타입·배열·제네릭 식별, 잘못된 정책 조합, 압축 파일의 경로·중복·bytecode 경계, 실패한 출력의 보존과 공개 경로의 원시 로그 차단을 확인했다. 이 작업에서 JDK 17은 다시 실행하지 않았으며 기존 검증 이력과 구분한다.

독립 코드 검토의 필수 수정 3건을 반영한 뒤 남은 구체적 결함 0건을 확인했다. LSP 진단 도구가 없어 코드 검토 판정은 `COMMENT`이며, 구조 재검토는 `CLEAR`다. 별도 AI의 국문 편집 검토가 요청한 4개 확인 사항도 문장과 최신 근거에 맞춰 정리해 재검 `PASS`를 받았다. 이는 실제 학위를 가진 사람의 검토를 뜻하지 않는다.

Python 구문·공백 검사, 문서 상대 링크 132개와 위키 8개 파일의 내보내기도 통과했다. GitHub Wiki용 원본을 같은 PR에 갱신했으며, 공개 Wiki 발행은 main 반영 후의 별도 절차다.

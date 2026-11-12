# 정적 관계·실제 실행 비교 조건

상태: **공식 원문 확인·후속 실험 설계 / 분석기·계측기 실행 및 제품 채택 전 · 2026-11-12**.

[T22 #38](https://github.com/DDINGJOO/JJAM-TONG/issues/38) · [근거 보관·조회 비교 조건](VERSIONED-EVIDENCE-COMPARISON.md) · [후보 조사](../RESEARCH.md)

게시판의 같은 메서드가 보여도 다른 빌드의 실행을 연결하면 잘못된 분석이 된다. 먼저 같은 입력과 기대 관계를 정하고, **코드에서 가능한 호출을 찾는 정적 분석**과 **요청에서 실제 호출을 기록하는 실행 계측**을 따로 비교한다. 현재 실험의 Git 파일·blob 인덱스는 두 기능의 구현이 아니다.

## 후보별로 확인한 사실과 실행할 비교

아래 버전은 조사 시점에 확인한 릴리스다. 링크의 고정 커밋으로 원문을 대조했으며 패키지를 설치하거나 지원 조합을 실행하지 않았다. 라이선스는 해당 저장소의 원문 표기다. 전이 의존성·전체 보안 이력·재배포 적합성의 검토나 JJAM-TONG의 라이선스 결정을 대신하지 않는다.

| 후보·고정 버전 | 공식 원문에서 확인한 내용 | 같은 입력에서 비교할 책임 |
| --- | --- | --- |
| JavaParser·JavaSymbolSolver **3.28.2** | Java 1~25 구문 파싱을 표기한다. SymbolSolver는 구문에서 참조한 선언을 찾는다. 라이선스는 Apache-2.0 또는 LGPL-3.0 선택형이다. [릴리스](https://github.com/javaparser/javaparser/releases/tag/javaparser-parent-3.28.2), [고정 README](https://github.com/javaparser/javaparser/blob/e72889831e5e06532f2185ec9ae16531237f9f69/readme.md), [LICENSE](https://github.com/javaparser/javaparser/blob/e72889831e5e06532f2185ec9ae16531237f9f69/LICENSE) | 소스의 직접 호출과 overload 선언 해석을 비교한다. 선언 해석만으로 실행 가능한 모든 구현체의 호출 그래프를 얻었다고 판단하지 않는다. |
| WALA **1.9.0** | 실행 JVM은 17 이상이다. 호출 그래프 분석에는 시작 메서드인 진입점과 reflection 정책 등 설정이 있다. reflection은 실행 중 이름 등으로 호출 대상을 찾는 기능이다. 고정 LICENSE는 EPL-2.0이다. [릴리스](https://github.com/wala/WALA/releases/tag/v1.9.0), [고정 README](https://github.com/wala/WALA/blob/ab3bd3b2b9291e047b203cddd248cbbcfcff6f1e/README.md), [분석 설정](https://github.com/wala/WALA/blob/ab3bd3b2b9291e047b203cddd248cbbcfcff6f1e/core/src/main/java/com/ibm/wala/ipa/callgraph/AnalysisOptions.java), [LICENSE](https://github.com/wala/WALA/blob/ab3bd3b2b9291e047b203cddd248cbbcfcff6f1e/LICENSE) | 같은 의존 클래스 목록(classpath)·진입점에서 구현체 후보와 미해결 호출을 비교한다. 읽을 수 있는 바이트코드 형식과 라이브러리 전체를 정확히 분석하는 능력은 구분한다. |
| OpenTelemetry Java agent **2.33.1** | Java 8 이상을 대상으로 한다. 선택한 메서드는 `otel.instrumentation.methods.include`로 추가 계측한다. Apache-2.0이다. [릴리스](https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/tag/v2.33.1), [고정 README](https://github.com/open-telemetry/opentelemetry-java-instrumentation/blob/d9045e02e0711837d54f0fd058cd55f77742506d/README.md), [메서드 설정](https://opentelemetry.io/docs/zero-code/java/agent/annotations/), [LICENSE](https://github.com/open-telemetry/opentelemetry-java-instrumentation/blob/d9045e02e0711837d54f0fd058cd55f77742506d/LICENSE) | agent 없음·기본 계측·선택 메서드 추가 계측을 나눈다. 기본 계측을 모든 앱 메서드의 실행 그래프로 표현하지 않는다. |
| Byte Buddy **1.18.17** | 고정 README의 일반 1.18.7 이상 계열은 최소 JVM 8, Java 25 이상 지원을 표기한다. 계측을 구현하는 라이브러리이며 Apache-2.0이다. [릴리스](https://github.com/raphw/byte-buddy/releases/tag/byte-buddy-1.18.17), [고정 README](https://github.com/raphw/byte-buddy/blob/b85b6d407a793f37ea4a62f1bae8831aee21be23/README.md), [LICENSE](https://github.com/raphw/byte-buddy/blob/b85b6d407a793f37ea4a62f1bae8831aee21be23/LICENSE) | 자체 선택 계측의 구현 책임과 비용을 비교할 후보다. trace 식별·비동기 연결·내보내기·손실 처리를 갖춘 완성 관측 제품으로 간주하지 않는다. |

WALA는 실행 JVM과 소스 빌드 조건도 다르다. 고정 빌드 안내는 Gradle 실행 JVM 21 이상을 요구한다. 소스 컴파일에 사용하는 JDK(toolchain)는 27, 생성 결과의 Java 호환 대상(release)은 17로 지정한다. JDK 17·21이 설치돼 있다는 사실만으로 이 소스를 빌드할 수 있다고 판단하지 않는다. [빌드 안내](https://github.com/wala/WALA/blob/ab3bd3b2b9291e047b203cddd248cbbcfcff6f1e/README-Gradle.md), [빌드 설정](https://github.com/wala/WALA/blob/ab3bd3b2b9291e047b203cddd248cbbcfcff6f1e/build-logic/src/main/kotlin/com/ibm/wala/gradle/java.gradle.kts).

OTel의 고정 메서드 계측 코드는 Byte Buddy를 사용한다. 두 도구를 독립적인 완성 제품 두 개로 비교하기보다, 기존 agent를 확장하는 책임과 계측을 직접 구현하는 책임을 비교한다. 해당 코드는 접근 제한자 조건 없이 메서드 이름을 매칭하고 생성자를 제외한다. 이름이 같은 overload의 선택과 각 실행의 식별은 별도 문제다. private/self-call 지원 여부는 실제 입력에서 확인한다. [고정 계측 코드](https://github.com/open-telemetry/opentelemetry-java-instrumentation/blob/d9045e02e0711837d54f0fd058cd55f77742506d/instrumentation/methods/javaagent/src/main/java/io/opentelemetry/javaagent/instrumentation/methods/MethodInstrumentation.java).

**다음 실험의 우선 비교안**은 JavaParser의 선언 해석과 WALA의 호출 후보 분석, OTel 기본 계측과 선택 메서드 계측이다. 해결되지 않은 요구가 있으면 Byte Buddy 자체 계측과도 비교한다. 이는 비교 순서 제안이며 기술 채택이 아니다. 기존 SootUp·AppMap·SkyWalking 후보를 제외하는 결정도 아니다.

## 같은 게시판 입력과 독립 기대값

fixture는 비교에 사용하는 고정 입력이며, oracle은 도구 출력과 별도로 작성하는 기대 결과다. 다음 표는 **별도 대상 프로젝트에서 로컬로 재현할 검증 조건**이다. JJAM-TONG은 도입할 라이브러리와 필요한 연동 도구를 구현하고, 대상 앱 코드는 별도 저장소에서 관리한다. 아직 라이브러리 적용·빌드·실행 로그를 만든 결과는 아니다. `fixture.board`는 합성 시나리오의 패키지 표기이며 실제 대상의 포함 패키지는 로컬 검증 계획에서 정한다. 공개 자료에는 실제 소스·인수·반환 본문·개인정보를 넣지 않는다. 보관·조회 비교 JSON은 합성 조회 입력이고, 아래 C01~C12는 실제 Java 분석·실행에서 대조할 조건이다.

합성 예시에서는 `Controller.list`가 `Service.list`를 호출한다. `Service.list`는 같은 클래스의 private `validate`를 호출하고, 반환을 받은 뒤 `Repository.find`를 호출한다. 두 호출의 부모는 모두 `Service.list`다. `JdbcRepository`와 `CachedRepository`가 별도 구현체이며 한 요청에는 지정한 구현체 하나만 사용한다. 직접 호출의 필수 관계, 인터페이스의 선언·구현 후보, 실제 실행한 경로를 각각 기대값으로 보관한다. 실제 대상 프로젝트의 대응 경로와 재현 가능한 조건은 로컬 검증 계획에 기록하며, 재현하지 못한 조건은 미검증으로 구분한다.

| ID·입력 | 정적 분석의 기대값 | 실행 계측의 기대값·실패 판정 |
| --- | --- | --- |
| C01 정상 조회와 거부 분기 | 기본 직접 호출과 거부 분기를 후보로 유지 | 정상 요청은 validate와 선택한 repository를 관측. 실행하지 않은 거부 분기를 관측으로 표시하면 실패 |
| C02 private self-call | `Service.list → validate`의 같은 클래스 호출을 구분 | 포함 범위의 validate 진입·부모 관계를 확인. 누락 시 계측 범위·지원 여부를 명시 |
| C03 overload | `find(String)`과 `find(String,int)`를 다른 선언으로 식별 | 두 번째만 호출한 요청이 첫 번째에 연결되면 실패. JVM descriptor로 인수·반환 타입을 구분 |
| C04 인터페이스 | 선언 해석과 가능한 구현체 집합을 구분. 집합의 포함 근거·미해결 상태를 기록 | 실제 선택한 구현체 하나를 관측. 정적 후보 모두를 실행된 것으로 반환하면 실패 |
| C05 reflection | 설정에서 이름을 읽어 호출하는 대상의 해석 여부와 가정을 기록 | 대상 메서드가 계측 범위라면 실행 기록과 비교. 정적 미해결을 호출 불가능으로 바꾸면 실패 |
| C06 비동기 조회 | 작업 제출과 작업 본문의 정적 관계를 별도로 표현 | 문맥이 전달되면 부모 또는 명시한 link로 연결. 문맥이 없으면 연결 미확인으로 남기고 동기 부모를 추측하지 않음 |
| C07 재귀와 예외 | 재귀 후보·예외 경로를 보존 | 호출 인스턴스·깊이를 구분하고 원래 결과·예외가 agent 없는 실행과 같아야 함 |
| C08 제외·표본 수집·native | 분석 미지원과 Java 바이트코드 본문이 없는 native 메서드의 경계를 표시 | 범위 제외·표본 수집(sampling)·전송 손실·native 미지원 이유를 구분. 기록 없음만으로 미실행이라고 단정하면 실패 |
| C09 같은 commit의 두 build | 의존성·생성 코드·빌드 설정이 다른 A/B의 입력과 결과를 별도 보관 | A의 실행은 A의 artifact·분석에만 연결. 같은 이름이나 commit만으로 B에 연결하면 실패 |
| C10 같은 artifact 재분석 | 분석기·근거 형식(schema)·설정이 다른 실행과 index digest를 별도 보관 | 지정한 분석 실행으로 조회. 나중 결과로 과거 근거를 덮어쓰면 실패 |
| C11 메서드 삭제·이름 변경 | 이전 선언과 제거·추가를 구분하고 호출자 영향도 재분석 | 이전 배포는 이전 지도에 연결. 이름 변경을 입증하지 못하면 삭제+추가로 기록 |
| C12 이력 누락·언어 미지원 | 수집하지 않은 중간 commit과 미지원 언어의 결과를 명시 | 최신 지도로 누락된 과거를 채우거나 미지원을 빈 그래프로 표시하면 실패 |

이 표는 [BDD-REL-001~004](../../specs/features/01-code-relations.feature), [BDD-VER-001~003](../../specs/features/02-version-identity.feature), [BDD-UPD-001~004](../../specs/features/03-graph-refresh.feature)의 일부 조건을 구체화한다. 기존 Draft 명세를 바꾸거나 전체 수락 테스트를 통과시킨 것은 아니다. 도구의 보수적인 추가 후보와 틀린 버전 연결은 같은 오류율로 합산하지 않는다.

## 실행 모델과 이벤트 경계도 함께 검증한다

사용자 추가 요구에 따라 Spring Boot 4 계열의 가상 스레드와 Netty 기반 실행을 C06 비동기·C07 오류·C08 부분 수집 조건에 함께 대입한다. **아래 조건 중 수동 문맥 전달·재처리·작업 상한·타임아웃과 별도 JDK pinning 입력을 먼저 실행했다.** [구성별 7개 로컬 결과와 미실행 항목](EXECUTION-MODEL-RESULTS.md)을 구분한다. 기존 게시판은 Boot 4.1.2의 MVC/Tomcat을 유지하고 가상 스레드 설정이 없다. 비교 모듈은 별도로 추가했다. Redis의 Lettuce가 Netty를 사용한다는 사실과 HTTP 서버가 Netty라는 판단은 구분한다.

가상 스레드는 스레드 실행 방식이고, Netty는 이벤트루프에서 I/O를 처리한다. 둘은 조합할 수 있다. 비교할 때 HTTP 서버·클라이언트·작업 실행기를 각각 식별하며, Boot 설정 하나가 모든 Kafka·Netty 작업에 일괄 적용된다고 가정하지 않는다. [Boot 작업 실행](https://docs.spring.io/spring-boot/4.1/reference/features/task-execution-and-scheduling.html), [WebFlux 실행 모델](https://docs.spring.io/spring-framework/reference/web/webflux/new-framework.html), [Lettuce의 Netty 사용](https://docs.spring.io/spring-data-redis/reference/4.0/redis/drivers.html)을 기준으로 한다.

이번 Boot 4.1.2 기본 자동구성에서는 가상 스레드를 켠 MVC 비교 모듈의 Kafka listener도 가상 스레드로 실행됐다. 버전·사용자 실행기 설정에 따라 적용 범위를 확인하며, [실제 스레드 표와 고정 버전 원문](EXECUTION-MODEL-RESULTS.md#실제-스레드는-경계마다-확인한다)을 근거로 남긴다.

| 비교 구성 | 확인할 실행 경계 |
| --- | --- |
| MVC/Tomcat + 플랫폼 스레드 | 현재 기준 구성의 요청 처리·JDBC 대기·Kafka 발행/소비 |
| MVC/Tomcat + 가상 스레드 | 실제 설정이 적용된 실행기와 각 작업의 스레드 종류 |
| WebFlux/Netty | 이벤트루프·Reactor 작업 전환과 블로킹 작업을 분리한 실행기. 분리한 실행기의 플랫폼/가상 스레드도 별도 축으로 비교 |

| 경계·장애 입력 | 필요한 관측과 실패 판정 |
| --- | --- |
| 스레드·Reactor 작업 전환 | 같은 요청의 추적 문맥을 유지하고 다른 요청에 섞이지 않는지 검사. 스레드 ID나 작업 전환만으로 호출 인과관계를 만들면 실패 |
| HTTP → outbox → Kafka → 소비자 | 발행 대기 동안 보존할 문맥과 Kafka header 주입·추출을 검증. 메서드 진입·스레드 변경·메시지 처리를 서로 다른 관계로 표현 |
| 재시도·중복·다중 소비·묶음 처리 | 원본 메시지와 각 처리 시도를 구분. 부모 관계와 별도 span 간 연결인 Span Links를 함께 표현하고 문맥 누락은 미확인으로 유지 |
| 느린 JDBC·Redis와 처리량 초과 | 이벤트루프의 블로킹, DB 연결 풀 대기, 동시 처리·큐 상한과 수신 속도 조절을 관측. 가상 스레드 수를 DB나 Kafka 처리 용량으로 해석하지 않음 |
| 타임아웃·취소·오류 | 취소 뒤 남은 작업, 처리 위치(offset) 반영, 재전달과 수집 유실을 구분하고 앱 결과·예외를 보존 |
| JDK별 가상 스레드 정체 | JDK 21과 24 이상을 구분해 가상 스레드가 실제 실행을 담당하는 플랫폼 스레드에서 분리되지 못하는 pinning 근거를 수집. 한 버전의 진단을 다른 버전의 보장으로 확대하지 않음 |

Reactor의 요청 문맥과 스레드별 로그 문맥(MDC)은 등록·복원·정리 범위를 확인한다. [Reactor 문맥 전파](https://projectreactor.io/docs/core/release/reference/advanced-contextPropagation.html)는 자동 전파 설정과 ThreadLocal 연동의 조건을 설명한다. Kafka에서는 [소비 병렬성·poll 조건](https://docs.spring.io/spring-kafka/reference/4.1/kafka/receiving-messages/message-listener-container.html)을 함께 기록한다. 메시지 문맥의 `traceparent` 전파는 이 프로젝트에서 검증할 연동 계약이며 현재 구현된 기능이 아니다.

[OTel 메시징 span 규약](https://opentelemetry.io/docs/specs/semconv/messaging/messaging-spans/)은 2026-11-12 조회 시 1.45.0 Development 상태다. 기본 producer/consumer 상관관계의 Links와 단일 메시지 처리의 부모 선택 조건을 구분하고, 모든 이벤트를 동기 부모·자식 호출로 강제하지 않는다. [JEP 491](https://openjdk.org/jeps/491)은 JDK 24의 synchronized 관련 pinning 개선이며 모든 pinning 제거를 뜻하지 않는다.

각 비교에 Boot/JDK/분석기/계측기/문맥 규약의 정확한 버전, 실행기 설정, artifact·분석 식별과 부하·자원 상한을 남긴다. 동일 입력의 관계 정확성·유실·대기·지연을 비교하며, 기존 [9개 로컬 통합 결과](LOCAL-MSA-TARGET.md)를 이 실행 모델 비교의 통과로 집계하지 않는다.

## 빌드·분석·실행을 연결할 식별

각 결과에는 저장소 식별자·커밋·빌드·산출물의 내용 식별자·모듈을 남긴다. 내용 식별자(digest)는 파일 내용으로 계산한 해시다. 분석 결과에는 분석 실행 식별자, 분석기·스키마 버전, 설정 식별자와 색인의 내용 식별자를 추가한다. 실행 기록에는 요청·호출 인스턴스, 배포와 산출물 참조, 수집 범위·계측 버전·표본 수집(sampling) 조건을 남긴다. 해당 정보가 없거나 충돌하면 연결 미확인 또는 불일치로 반환한다.

메서드는 첫 JVM 입력에서 모듈·클래스·이름·descriptor로 구분한다. descriptor는 인수와 반환 타입을 나타내는 JVM 표기다. 이 형식을 다른 언어의 공통 필수 식별자로 강제하지 않는다. 소스 위치만으로 연결할 때는 생성·변환 코드와 줄 번호 부재의 한계를 별도로 표시한다.

같은 commit이라도 classpath, 컴파일 중 코드를 생성하는 annotation processor의 출력, 빌드 설정이 다르면 별도 입력이다. 각각의 파일 digest와 도구·설정 식별을 남긴다. 외부 저장소에서 같은 버전 문자열의 파일이 바뀌면 입력 충돌로 드러내고 기존 분석을 조용히 재사용하지 않는다.

## 파일 변경을 메서드 영향 범위로 넓히기

Git 파일 차이는 재분석의 시작점이다. 다음 순서는 후속 구현에서 전체 재분석 결과와 대조할 후보 절차다.

1. 변경·삭제한 파일과 이전 분석의 선언 매핑을 찾는다. 새 파일은 새 선언 후보로 분석한다.
2. 바뀐 선언을 참조하는 호출자, 타입 상속·구현 관계, 영향받는 모듈을 다시 계산한다. 직접 바뀐 파일만 갱신하고 끝내지 않는다.
3. classpath·생성 코드·빌드/분석 설정이 바뀌거나 의존 관계를 알 수 없으면 모듈 또는 전체 분석으로 확대한다. 확대 이유와 범위를 기록한다.
4. C11의 삭제·이름 변경과 인터페이스 구현 교체를 적용한다. 선택 범위만 분석한 결과를 같은 입력의 전체 재분석과 비교해 오래된 관계·빠진 후보를 판정한다.
5. 결과를 완성한 뒤 버전별 index를 공개한다. 실패한 부분 분석으로 마지막 성공한 index를 덮어쓰지 않는다.

현재 상태만 재확인하면 조회 사이에 지나간 중간 commit의 분석 결과를 얻지 못할 수 있다. Git 이력에서 소스를 찾더라도 당시 의존성·생성 코드·빌드 환경이 없으면 같은 artifact를 재현했다고 보장할 수 없다. [기존 실험의 중간 이력 공백](HYBRID-RESULTS.md)은 이 문제를 해결한 결과가 아니다.

## 실행 예산과 측정 계획

다음 숫자는 **작은 후속 실험의 예산 제안**이다. 공급자 권장 사양·측정값·제품 운영 기준이 아니다. 실행 전에 실제 환경과 제한 수단을 고정한다.

| 대상 | 제안할 제한·일정 | 남길 관측값과 중단 조건 |
| --- | --- | --- |
| 정적 분석 | 작업당 경과 시간 60초, JVM heap 1GiB, 출력 파일 10MiB | 감독 프로세스가 제한 초과 시 자식 프로세스를 종료. 프로세스 상주 메모리(RSS)의 최대값·CPU·시간·입력 크기·부분 결과를 기록. heap 제한은 전체 프로세스 메모리 상한이 아님 |
| 기능 계측 | 포함 패키지 고정, 요청별 최대 100개 호출 기록, 출력 총 10MiB | 상한 초과·내보내기 실패를 누락 사유로 기록. 수집 실패가 앱의 원래 응답·예외를 바꾸면 실패 |
| 성능 비교 | 같은 정상 조회 입력으로 warmup 100회 후 측정 1,000회, 구성별 5회 반복 | agent 없음·기본·선택 계측의 지연·처리량·RSS·생성/전송/유실 기록 수를 보존. 로컬 반복을 운영 SLO나 독립 장애 표본으로 해석하지 않음 |

JDK 17·21의 정확한 배포판·패치 버전, OS·CPU, classpath와 artifact digest를 기록하고 조합마다 기능 검증을 먼저 수행한다. 첫 기능 비교는 모든 합성 요청을 수집하는 정책으로 sampling을 고정하고 기대 호출 수를 대조한다. 성능 측정에서도 sampling·전송 설정을 고정한다. warmup은 측정 전 반복 실행이며 횟수만으로 JVM 최적화가 안정됐다고 보장하지 않는다. 원시 반복값도 남긴다.

계측한 구성의 지연 중앙값이 같은 조건에서 agent 없이 실행한 기준 지연 중앙값의 1.2배를 넘으면 해당 구성은 **이 실험의 예산 미달**로 분류할 것을 제안한다. 계산식은 `(계측 지연 중앙값 − 무계측 지연 중앙값) / 무계측 지연 중앙값 > 0.20`이다. 기준 지연이 측정 분해능에 가까우면 비율 판정을 보류하고 원시값과 그 이유를 남긴다. 정확성 통과와 비용 미달은 따로 보고하며, 빠른 빈 결과를 성공으로 취급하지 않는다.

## 다음 판정과 남은 일

[후속 최소 재현 T25 #44](https://github.com/DDINGJOO/JJAM-TONG/issues/44)에는 후보·설정·실제 명령·입력 hash, C01~C12의 기대/실제 관계·누락 이유, 시간·메모리·출력량을 함께 남긴다. 도구 선택에는 소유자의 명시적 선택과 ADR이 필요하다. 분석기·계측기 후보의 실제 빌드·계측·호환성·비용 검증은 미실행이다. 수동 문맥을 사용하는 별도 앱의 실행 모델 비교는 [첫 로컬 결과](EXECUTION-MODEL-RESULTS.md)로 구분한다.

관측성·코드·에이전트/SRE·MSA·Kubernetes·인프라·CMDB·SIEM은 모두 구현 대상이다. 이 실험은 그 근거를 정확한 버전으로 연결하기 위한 출발점이며, AWS EKS·ECS·일반 Kubernetes 및 온프레미스·AWS 자원 매핑의 지원 완료나 플랫폼 설치 환경의 결정은 아니다.

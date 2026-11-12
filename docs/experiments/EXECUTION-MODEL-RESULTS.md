# 실행 모델·이벤트 문맥의 첫 로컬 비교

2026-11-12에 Spring Boot 4.1.2의 MVC 일반 스레드·MVC 가상 스레드·WebFlux/Netty를 실행했다. **구성별 7개, 총 21개 검증을 통과했다.** 수동으로 전달한 합성 요청 문맥과 실제 스레드·빌드 정보를 비교한 결과다. 자동 메서드 추적·정적 호출 그래프·OTel span 생성의 완료를 뜻하지 않는다.

[ADR 0003](../decisions/0003-execution-model-comparison.md) · [구조화한 실행 결과](execution-model-results.json) · [비교 실행기](../../experiments/execution_lab/compare.py) · [T25 #44](https://github.com/DDINGJOO/JJAM-TONG/issues/44)

## 대상과 재현 조건

기존 게시판과 같은 로컬 인프라를 쓰는 작은 검증 모듈을 별도 대상 저장소에 추가했다. 테이블 접두어는 `execution_probe_`, 토픽은 `execution.probe.v1`, 소비자 그룹은 실행 모드별로 구분한다. 기존 앱·컨테이너를 유지했고 게시판 업무 소스를 플랫폼 저장소에 복사하지 않았다.

검증 후 비교용 앱 3개만 중지했다. 빌드 산출물·DB 기록·JFR은 로컬에 보존하며 기존 게시판과 인프라는 계속 실행한다.

- 대상 revision: `9f56f1d54c35ced8a5712efaadbe875a4d1aa5c4`, clean. 소스는 로컬에만 있으며 공개 원격 저장소는 없다. 공개 결과에는 파일 55개의 해시와 최종 앱 JAR 2개의 해시를 남겼다. 다른 독자는 실행기만으로 이 대상 전체를 재구성할 수 없다.
- 앱: Boot 4.1.2, Temurin JRE 21.0.13. MVC는 Tomcat 11.0.27, Netty 구성은 Reactor 3.8.8·Reactor Netty 1.3.8·Netty 4.2.19.Final이다. 실제 JAR의 의존성 목록과 진입 스레드도 대조했다. MVC에도 Lettuce 때문에 Netty가 포함되지만 HTTP 서버는 Tomcat이다.
- 인프라: 기존 Kafka 4.3.2·Redis 8.10.3·PostgreSQL 17.11 컨테이너. Kafka 클라이언트는 Boot가 관리하는 4.2.2이며 broker 버전과 구분한다. 실제 RDS·Kubernetes는 사용하지 않았다.
- 각 앱: 메모리 512MiB·CPU 1개, DB 연결 풀의 최대 연결 수 2개, 작업 동시 실행 상한 4개. Netty는 별도 플랫폼 작업 스레드 4개와 대기 작업을 최대 4개 담는 큐를 둔다. 이 큐 차이가 있으므로 허용된 요청 수를 처리량 순위로 읽지 않는다.
- 라이브러리: 기존 Java 빌드 식별 계약 JAR을 그대로 사용했다. 시작 시 최종 앱 JAR의 SHA-256을 sidecar와 비교한다. 분석 인덱스가 없으므로 `UNRESOLVED`를 유지한다.

대상 저장소에서 기존 라이브러리 JAR을 지정해 빌드하고 비교용 앱만 실행한다.

```sh
python3 scripts/build_execution.py --library /path/to/evidence-contract.jar
docker compose -f compose.execution.yaml build
docker compose -f compose.execution.yaml up -d --no-build --pull never
```

JJAM-TONG에서 다음 명령을 실행한다. 앱은 loopback의 28280·28281·28282 포트에 있어야 한다. 실행기는 `delayMillis`·`retryFailures`·`dropHeader`·`failAfterInsert`를 매번 명시하며 합성 UUID로 실행 데이터를 구분한다.

```sh
python3 -m unittest experiments.execution_lab.test_oracles -v
python3 experiments/execution_lab/compare.py \
  --expected-target-revision 9f56f1d54c35ced8a5712efaadbe875a4d1aa5c4 \
  --output results/execution-comparison.json
```

## 실제 스레드는 경계마다 확인한다

각 구성의 표본에서 `Thread.currentThread().isVirtual()`을 읽었다.

| 구성 | 요청 진입 → 작업 | outbox 발행 | Kafka 소비 |
| --- | --- | --- | --- |
| MVC 일반 스레드 | Tomcat 플랫폼 → 같은 요청 스레드 | 플랫폼 | 플랫폼 |
| MVC 가상 스레드 | Tomcat 가상 → 같은 요청 스레드 | 가상 | 가상 |
| WebFlux/Netty | `reactor-http-nio-*` → `probe-blocking-*` 플랫폼 스레드 | 플랫폼 | 플랫폼 |

이번 Boot 4.1.2의 기본 자동구성에서는 가상 스레드 설정이 Kafka listener의 실행기에도 적용됐다. [버전을 고정한 자동구성 원문](https://github.com/spring-projects/spring-boot/blob/634e6fd6bc2e475d745c0bdceb8e775864f7f2ec/module/spring-boot-kafka/src/main/java/org/springframework/boot/kafka/autoconfigure/KafkaAnnotationDrivenConfiguration.java#L116-L153)과 일치한다. 사용자 factory·configurer가 바뀌면 다시 확인해야 하며, Kafka 내부의 모든 스레드나 Netty 이벤트루프까지 바뀐다는 뜻은 아니다.

Netty에서는 Reactor Context에서 요청 문맥을 읽고, JDBC·Redis 작업을 실행하는 스레드 안에서만 ThreadLocal scope를 열었다. 완료·예외 뒤에는 이전 값을 복원한다. 스레드 이름이나 ID로 요청 관계를 추측하지 않는다. 이 명시적 연결과 프레임워크가 자동 전파하는 문맥은 별개다.

## 7개 입력의 기대값과 실제 결과

아래 검증을 세 구성에서 각각 수행했다. 앱 단위 테스트는 기존 3개와 신규 7개를 합쳐 10개, 비교 실행기의 판정 검사는 6개를 통과했다.

효과 행은 소비자가 이벤트 처리 결과를 DB에 기록한 행을 뜻한다.

| 입력 | 판정한 결과 |
| --- | --- |
| 서로 다른 문맥 12개, 동시 요청 3개 | 요청·작업·outbox·Kafka의 문맥과 빌드 ID·artifact가 일치하고 scope 종료 후 다른 요청의 값이 남지 않음 |
| Kafka 처리 두 번 실패 | 같은 eventId의 시도 3개를 구분하고 `실패 → 실패 → 반영` 확인. 효과 행 1개 |
| 같은 이벤트 다시 발행 | 추가 시도는 중복으로 기록하고 효과 행은 1개 유지 |
| Kafka header에서 문맥을 의도적으로 제거 | outbox에는 문맥이 있지만 소비자에는 누락 상태를 유지. 이를 정상 연결로 판정하려는 검사가 실제로 실패함 |
| INSERT 뒤 예외 주입 | HTTP 503, outbox INSERT 롤백, 효과 행 없음, 문맥 정리 확인 |
| DB에서 1초 대기하는 요청 12개 | 실제 실행 4개·DB 사용 2개/대기 2개에서 건강 확인 HTTP 200. MVC 각 4개 허용/8개 429, Netty 8개 허용/4개 429. Netty의 추가 큐 영향이 포함됨 |
| 50ms 뒤 클라이언트 타임아웃 | MVC 두 구성은 이후 outbox·효과 행 각 1개, Netty는 각각 0개 관측. 후속 새 요청의 문맥 정리 확인. 서버 취소의 일반 보장으로 확대하지 않음 |

누락 탐지·타임아웃 관측의 통과는 누락을 복구했거나 서버 취소를 보장했다는 뜻이 아니다. 중복 검증도 이 테이블의 유일 키로 효과 행을 한 개 유지한 결과이며, 분산 트랜잭션의 exactly-once 보장이 아니다. 재시도는 최대 두 번 실패하도록 제한한 합성 입력이다. 재시도 소진 뒤의 복구·DLQ 정책은 검증하지 않았다.

건강 확인 지연은 단회 표본으로 JSON에 남겼다. 반복 부하·최대 처리량·운영 지연의 비교 자료로 사용하지 않는다. 관측값 자체를 DB에 기록하므로 이 실험 코드도 연결 풀을 사용하며 별도 성능 비용이 있다.

## JDK별 pinning은 별도 입력으로 비교했다

[실행 방법과 코드](../../experiments/execution_lab/README.md)는 Java 21로 컴파일한 동일 클래스 파일을 Corretto 21.0.11과 Microsoft OpenJDK 25.0.3에서 실행한다. 가상 스레드 스케줄러의 병렬도·최대 크기는 1로 고정하고, JFR(Java Flight Recorder)의 pinning 이벤트 문턱값은 0으로 설정했다.

| JDK | monitor 없는 대기 | `synchronized` 안의 대기 | 두 입력 각각의 가상 스레드 시작/종료 |
| --- | --- | --- | --- |
| 21.0.11 | pinning 0건 | 해당 메서드의 pinning 4건 | 4/4건 |
| 25.0.3 | pinning 0건 | 해당 메서드의 pinning 0건 | 4/4건 |

독립 재실행에서도 같은 클래스 해시와 결과를 확인했다. [JEP 491](https://openjdk.org/jeps/491)의 monitor 개선과 일치하지만 모든 pinning이 사라졌다는 증거는 아니다. **Spring/Kafka 앱 자체를 JFR로 진단한 결과도 아니다.** 배포판까지 다르므로 두 JDK의 단일 변수 성능 비교로 해석하지 않는다. 원시 JFR은 로컬에 보존하고 공개 JSON에는 요약·설정·해시를 남겼다.

## 남은 검증

자동 메서드 계측·정적 호출 그래프와 실제 실행의 결합, OTel 부모/Span Links, 다중 소비·묶음 처리, Kafka offset·재균형·프로세스 종료 복구, 수집기 유실·sampling과 앱의 실제 pinning은 남아 있다. Netty의 블로킹 실행기를 가상 스레드로 바꾼 조합도 실행하지 않았다.

이번 결과는 [C06~C08 관련 추가 조건](CODE-ANALYSIS-COMPARISON.md#실행-모델과-이벤트-경계도-함께-검증한다)의 일부 근거다. 기존 게시판 9개 통합 검증과 별개이며, C01~C12·47개 Draft BDD·#44 전체의 완료로 집계하지 않는다. 다음 도구 선정에서는 실행 모델·문맥 경계와 빌드 식별을 함께 보존하는지 확인한다.

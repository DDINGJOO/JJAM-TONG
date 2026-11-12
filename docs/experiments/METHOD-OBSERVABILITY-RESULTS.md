# 정적 호출 후보·자동 메서드 계측의 첫 실제 비교

상태: **로컬 비교 실행 완료, 미해결 항목 보존 / T25 진행 중 · 2026-11-12**.

[T25 #44](https://github.com/DDINGJOO/JJAM-TONG/issues/44) · [비교 조건](CODE-ANALYSIS-COMPARISON.md) · [ADR 0004](../decisions/0004-method-evidence-comparison.md) · [구조화한 결과](method-observability-results.json) · [30회 원시 비용](method-observability-costs.json).

## 확인한 결과

별도 로컬 Java 대상에서 정적 메서드 후보와 자동 수집한 실행을 실제 빌드에 연결했다. **기능 실행 124개는 앱 결과와 클래스·메서드 수준의 관계 검사를 통과했다. 정확한 overload 선언의 실행 식별은 미해결**이다. 전체 C01~C12·BDD 통과나 제품 도구 채택으로 해석하지 않는다.

| 구성 | 실제 실행·판정 |
| --- | --- |
| JavaParser·SymbolSolver 3.28.2 | 소스 선언·private 호출·서로 다른 overload descriptor를 구분. 인터페이스 호출은 선언 대상으로 남김 |
| WALA 1.9.0, 클래스 계층 분석(CHA) | 동일 입력에서 private 호출과 구현체 후보 2개를 보존. reflection 대상·native 본문은 미해결 |
| 무계측·OTel 기본 | 각각 40개 시나리오의 앱 결과 보존. 이 순수 Java 입력의 앱 메서드 span은 0개 |
| OTel 2.33.1 선택 메서드 | JDK 17·21 × A/B × 10개, 총 40개. private·비동기 부모 전달·재귀·오류와 호출 수 확인 |
| 수집 원인 대조 | JDK별 `always_off`·executor 계측 해제, 총 4개. 각각 span 없음·비동기 부모 단절을 확인 |

기능 실행에서 읽은 앱 메서드 span은 총 194개다. 정상 선택 계측 40개에서 184개, executor 계측 해제 2개에서 10개다. `always_off`로 span 수집을 끈 대조 실행 2개에서는 0개다. 입력별 독립 기대 관계·호출 수·관측 금지 메서드와 대조했다. OTel에 descriptor가 없어 검증할 수 없는 overload 금지 조건은 `unverifiedForbiddenMethods`에 남겼다.

## 대상과 버전

대상은 플랫폼과 분리한 합성 프로젝트의 `method-fixture`다. DB 이름의 repository 구현체는 이 작은 메서드 입력에서 고정 결과를 반환하며 실제 JDBC·Redis를 호출하지 않는다. 실제 Kafka·Redis·PostgreSQL 대상의 [앞선 수동 검증](EXECUTION-MODEL-RESULTS.md)과 구분한다. 대상 소스는 플랫폼 저장소에 복사하지 않았다. 외부 대상 자체는 로컬에만 있어 아래 전체 행렬을 재현하려면 그 별도 체크아웃이 필요하다. 공개 저장소만으로는 어댑터의 작은 합성 oracle과 근거 계약 검사를 재현할 수 있다.

- 대상 revision: `3e4d1296f2b47b8e26e9d9f6912d387b3ba9d95b`, clean 상태.
- A/B는 같은 revision의 명시적인 소스 overlay로 빌드한다. B는 private `validate`를 `validateV2`로 바꾸며 유효 소스 목록·각 파일 해시를 별도로 남긴다.
- A1/A2는 같은 소스·클래스 파일이며 빌드 manifest의 ID가 다르다. 의존성·생성 코드가 다른 두 빌드의 검증으로 확대하지 않는다.
- 컴파일: Temurin `17.0.19+10`, `--release 17 -Xlint:all -Werror`, 클래스 버전 61. 외부 실행 의존성 없음.
- 실행·분석: Temurin `17.0.19+10`, Corretto `21.0.11+10-LTS`. 정확한 JVM 원문과 JAR 해시는 구조화한 결과에 있다.

| 빌드 | 최종 JAR SHA-256 |
| --- | --- |
| method-a1 | `a549b1f64e0d92aaced4342ad4f5d849c1dc85ba981201498d14e549d8e2a5b4` |
| method-a2 | `542d49f4a14aa2de8c83ee2c8ca7fc672967f23720cb965dcf9406404bb27c12` |
| method-b1 | `ac9faa30a8e4523730e1eb2fa08a86ee6f5adb4cf0e12fd66290cc4cf52af3bf` |

분석 도구의 빌드에는 기존 `maven:3.9.9-eclipse-temurin-21` 이미지를 사용했다. 배포된 WALA 바이너리를 실행했으며 WALA 소스 빌드를 수행하지 않았다. 직접·전이 의존성 16개와 어댑터 JAR의 해시는 결과 JSON에 있다. 분석기의 소스·JAR 입력 확인은 빌드 출처 인증이 아니다.

## C01~C12에 대입한 결과

| 조건 | 실제 대조와 남은 한계 |
| --- | --- |
| C01 정상·거부 | 정상·거부 결과 보존, 선택한 구현체와 private 호출 관측. 실행하지 않은 별도 분기·다른 구현체를 실행으로 반환하지 않음 |
| C02 private self-call | `Service.list → validate`와 B의 `validateV2`를 정적 후보·실제 부모 관계에서 확인 |
| C03 overload | 정적 선언 2개 구분. OTel에는 descriptor가 없어 실제 `find`는 `UNRESOLVED_CODE_SYMBOL`; 정확한 실행 선언 식별 미달 |
| C04 인터페이스 | JavaParser의 선언과 WALA의 구현체 후보 2개를 분리. 실제 실행은 선택한 클래스만 관측 |
| C05 reflection | 정적 미해결을 유지하며 선택 범위의 실제 대상 span을 확인. 정적 호출 불가능으로 해석하지 않음 |
| C06 비동기 | executor 계측 사용 시 실제 부모·같은 trace, 해제 시 별도 trace의 작업을 보존. 부모를 추정해 붙이지 않음 |
| C07 재귀·예외 | 재귀 4개 인스턴스·self 부모 3개, 오류 span과 원래 앱 결과 보존 |
| C08 제외·sampling·native·유실 | 범위 밖과 native 본문을 구분. `always_off` 실행 대조. 저장 후 부모 제거·기록 상한은 부분 수집으로 판정. 실제 SDK/네트워크 장애 주입은 미실행 |
| C09 같은 commit의 다른 build | A1의 기록을 A2·B에 조회하면 `MISMATCH`. A1/A2는 manifest 차이이며 dependency·생성 코드 변경 입력은 미실행 |
| C10 같은 artifact 재분석 | 실제 CachedRepository 제외 설정으로 메서드·후보 감소, 설정·색인 해시 분리. 과거 색인 덮어쓰기 거부. 분석기·스키마 업그레이드는 미실행 |
| C11 이름 변경 | 유효 소스 차이와 삭제·추가 선언 확인. 과거 실행은 A 색인으로 조회. 부분 영향 범위 계산이 없어 전체 재분석으로 전환; 독립 반복 전체 결과와 일치 |
| C12 없는 이력·미지원 | 없는 분석 ID는 `HISTORY_NOT_COLLECTED`. Python 소스 입력은 실제 실패하고 이전 출력 유지. 최신 지도나 성공한 빈 그래프로 채우지 않음 |

C11의 전체 재분석 전환은 안전한 후퇴 경로다. **실제 증분 알고리즘과 전체 분석의 비용·정확성을 비교한 결과는 없다.** 이름 변경을 자동으로 동일 메서드의 별칭으로 추론하지도 않는다. 기존 [관계 BDD](../../specs/features/01-code-relations.feature)·[버전 BDD](../../specs/features/02-version-identity.feature)·[갱신 BDD](../../specs/features/03-graph-refresh.feature)는 Draft 상태를 유지한다.

## 연결·수집에서 지킨 경계

[근거 연결 CLI](../../tools/method_evidence/README.md)는 최종 JAR·유효 소스·manifest를 대조한 색인을 생성한다. 조회 시 분석 실행 ID와 계측 설정 해시를 명시해야 한다. 빌드 다섯 필드가 다르면 불일치, 정보가 없으면 미해결이다. 같은 이름의 overload를 임의로 고르지 않는다. 정적 후보와 실제 span 부모 관계는 별도 근거다.

OTel의 `logging-otlp` exporter가 남긴 JSON에서 허용 항목만 읽는다. 수집 뒤의 도구는 SQL·URL·인수·반환 본문·예외 본문을 버린다. 원시 로그와 실제 명령의 로컬 경로는 무시 디렉터리에 두며 공개하지 않는다. 여기서 OTel resource는 호출자가 넣은 정보이므로 원격 실행의 출처 인증으로 표현하지 않는다.

처음에는 인터페이스와 구현체를 함께 선택해 정상 조회의 repository 본문에 span 2개가 생겼다. 구체 클래스 본문만 선택한 뒤 독립 호출 수와 일치했다. 첫 실패 로그도 로컬에 보존했다. 별도 검토에서 발견한 계측 설정 생략 허용과 검증 없는 캐시 반환은 수정했다. 캐시는 원본 해시를 대조하고 현재 판정기로 다시 검증하며 검증 코드 해시를 결과에 남긴다.

## 비용과 제한

기능 실행은 최대 2개 JVM을 병렬 실행했고 각 JVM의 heap은 256MiB, 제한 시간은 60초였다. 비용 측정은 한 번에 하나씩, JDK별 세 구성 각각 warmup 100회·측정 1,000회를 5번 반복했다. 측정한 호출은 총 30,000개다. warmup의 span도 내보내므로 선택 계측은 매 실행 1,100 trace·4,400 span, 총 44,000 span을 확인했다. 이는 기대 개수와 실제 exporter 출력의 일치이며 SDK 내부 생성량을 직접 측정한 값은 아니다.

| JDK | 구성 | 실행별 중앙값의 중앙값 | 최대 상주 메모리(RSS)의 중앙값 |
| --- | --- | --- | --- |
| 17 | 무계측 / 기본 / 선택 | 83 / 42 / 10,667ns | 45.11 / 205.27 / 211.80MiB |
| 21 | 무계측 / 기본 / 선택 | 84 / 42 / 9,145.5ns | 47.00 / 226.30 / 239.63MiB |

시간은 JVM 시작·종료와 exporter 종료 처리를 제외한 메서드 호출 구간이다. 로그 출력·JIT 최적화·로컬 자원 경쟁의 영향이 있으며 정상 조회가 극히 짧다. 양의 최소 기준 표본이 41ns이고 0ns 표본도 남았다. 이 실험에서는 기준 중앙값이 양의 최소 표본의 10배보다 작으면 비율 판정을 보류하는 보수적 규칙을 적용했다. 이는 시계의 정밀도 교정이 아니다. **20% 비용 예산 통과나 제품 성능 순위로 판정하지 않는다.** 원시값을 버리거나 0ns를 보정하지 않았다.

정적 분석은 원래 실행 6개를 같은 입력으로 독립 반복해 바이트 일치를 확인했다. 반복 실행의 경과 시간은 약 0.88~0.94초, 최대 RSS는 약 873.5~964.4MiB, JSON은 약 56~57KiB였다. JVM heap 1GiB·60초·결과 10MiB 제한은 적용했지만 **프로세스 전체 RSS 상한은 적용하지 않았다.** RSS는 macOS `/usr/bin/time -l`의 bytes 값이며 Python 감독 프로세스까지 감싼 실행의 기록이다. 운영 용량 산정으로 확대하지 않는다.

근거 저장 단계의 trace당 100개·입력 10MiB 제한은 앱의 span 생성 상한이 아니다. SDK 큐의 용량은 span 8,192개이며, 한 번에 내보내는 묶음(batch)은 최대 span 512개로 설정했다. 수집 정책은 기능·비용 실험에서 `always_on`으로 고정했고 sampling 음성 대조만 `always_off`다. 실제 exporter 큐 초과·강제 종료·네트워크 유실은 남은 검증이다.

## 재현 명령

`TARGET_ROOT`는 별도 대상 체크아웃, `JDK_17`·`JDK_21`은 해당 설치 경로다. OTel JAR은 [Maven Central](https://repo.maven.apache.org/maven2/io/opentelemetry/javaagent/opentelemetry-javaagent/2.33.1/opentelemetry-javaagent-2.33.1.jar)의 2.33.1을 사용하며 SHA-256 `e43a270df53c6f423e0ab157be9c27ccc01d5dc3232e162fe54777573db2f149`를 실행 전에 대조한다. 빌드 ID와 색인 ID는 재사용하지 않는다.

```sh
python3 tools/java-call-analysis/build.py
python3 tools/java-call-analysis/verify.py --java-home "$JDK_17"
python3 tools/java-call-analysis/verify.py --java-home "$JDK_21"
python3 -m unittest tools.method_evidence.test_evidence -v

python3 "$TARGET_ROOT/scripts/build_method_fixture.py" --java-home "$JDK_17" --variant A --build-id method-a1 --smoke
python3 "$TARGET_ROOT/scripts/build_method_fixture.py" --java-home "$JDK_17" --variant A --build-id method-a2 --smoke
python3 "$TARGET_ROOT/scripts/build_method_fixture.py" --java-home "$JDK_17" --variant B --build-id method-b1 --smoke
```

각 빌드의 `sources`, `method-fixture.jar`, `identity.json`을 [정적 분석 CLI](../../tools/java-call-analysis/README.md)에 넣고 결과를 [색인 CLI](../../tools/method_evidence/README.md)에 넣는다. A1/B1은 JDK 17·21별 색인을 만들고 A2와 A1의 실제 제외 설정도 별도로 만든다. 이번 실행 ID는 결과 JSON의 `indexes`에 있다.

```sh
python3 experiments/method_observability.py \
  --target "$TARGET_ROOT" --artifacts "$TARGET_ROOT/.local/method-fixture/artifacts" \
  --store "$INDEX_STORE" --agent "$OTEL_AGENT_JAR" \
  --jdk17 "$JDK_17" --jdk21 "$JDK_21" \
  --build-a method-a1 --build-b method-b1 --output "$RUN_OUTPUT" --phase functional
# 같은 인수로 --phase cost --workers 1을 실행한다.
python3 experiments/method_history.py \
  --store "$INDEX_STORE" --artifacts "$TARGET_ROOT/.local/method-fixture/artifacts" \
  --runs "$RUN_OUTPUT" --full-reference "$INDEPENDENT_FULL_ANALYSIS_JSON" \
  --output "$HISTORY_RESULT_JSON"
```

`--full-reference`에는 같은 B 입력을 실제로 다시 전체 분석한 출력을 넣는다. 캐시 재검은 앱을 다시 실행했다는 뜻이 아니며 기존 실행의 원본 로그를 현재 규칙으로 대조한다.

## 실제 Boot·가상 스레드·Netty·Kafka에도 적용했다

앞선 별도 MSA의 세 실행 모델에도 같은 OTel agent를 외부에서 붙였다. Boot 4.1.2·컨테이너 JDK `21.0.13+9-LTS`에서 실제 HTTP 요청, Redis 왕복, JDBC outbox 저장과 Kafka 소비를 실행했다. 이는 위 순수 Java 행렬·비용 측정과 별도의 **기능 흐름 3개**다. Boot 앱을 정적 분석기에 넣어 descriptor까지 연결한 검증은 아니다.

[3개 흐름·첫 실패·수정 빌드의 구조화한 근거](execution-agent-results.json)에 실제 부모·link, 계측 코드·원본 로그 해시와 테스트 범위를 남겼다. 별도 판정기 회귀 검사 13개는 잘못된 header·부모, 관련 없는 JDBC 기록, 누락 메서드·다른 산출물을 성공으로 처리하지 않는지 검사했다.

첫 실행에서는 합성 대상의 파서가 Kafka header의 `traceparent` 끝 플래그 `03`을 거부했다. 실제 broker record에서 그 값을 확인했으며 DB 효과는 0개였다. 테스트 앱이 `00/01`만 허용한 것이 원인이었다. W3C Level 1은 플래그를 두 자리 소문자 16진수의 bitfield로 정의하고 sampled bit를 마스크로 검사한다. 고정 SDK 1.67.0은 sampled `0x01`과 random `0x02`를 사용하므로 실제 `03`과 맞는다. [W3C Recommendation](https://www.w3.org/TR/2021/REC-trace-context-1-20211123/#trace-flags), [고정 SDK의 플래그](https://github.com/open-telemetry/opentelemetry-java/blob/b4b3a1b354425c3f1411173c0e48cb24a1cba224/api/all/src/main/java/io/opentelemetry/api/trace/ImmutableTraceFlags.java).

대상의 version 00 전용 파서를 두 자리 hex 수신으로 좁게 수정했다. ID가 모두 0인 값의 거부와 길이·소문자 검사는 유지했다. 입력 문맥은 문자열 그대로 운반한다. 이 변경으로 일반 W3C 전체 버전 파서를 구현했다고 주장하지 않는다. random flag를 정의한 Level 2 문서는 [Candidate Recommendation Draft](https://www.w3.org/TR/2024/CRD-trace-context-2-20240328/#trace-flags)이며, SDK가 알 수 없는 모든 bit를 새 span의 모든 경유 구간에서 보존한다는 뜻도 아니다.

수정 대상 revision은 `1707e7c9e01e19d52bb90fbf13cb70414d5d7a6d`, 새 build는 `method-agent-b1`이다. MVC JAR 해시는 `93ab80c32ab81a5295e50a2ff239b732f455032d2f7be0600b67c5b6205d33cf`, Netty는 `c5524b816dba85c709c633b460679749cfc419e7a5a0092e2a8d617016e19f76`이다. 기존 수동 비교 빌드와 위 메서드 fixture의 JAR을 덮어쓰지 않았다.

| 실행 모델 | 수정 후 실제 결과 | 남은 문맥 경계 |
| --- | --- | --- |
| MVC 플랫폼 스레드 | HTTP 진입·선택 메서드·JDBC와 Kafka producer→consumer 관계 관측, DB 효과 1개 | 예약 outbox 발행의 SDK trace가 원래 HTTP trace와 다름 |
| MVC 가상 스레드 | 동일 기능 결과. 요청·Kafka 소비자에서 실제 가상 스레드 확인 | 동일하게 HTTP→outbox 발행 연결은 없음 |
| WebFlux/Netty | HTTP 문맥과 별도 블로킹 작업의 선택 메서드를 같은 trace에서 관측, Kafka 처리·DB 효과 1개 | 동일하게 예약 발행의 trace는 별도 |

**수동 문자열을 outbox에 보관하는 것만으로 OTel SDK 문맥은 복원되지 않았다.** 세 모델 모두 SDK가 producer 문맥으로 Kafka header를 바꿨고 consumer는 그 producer의 trace를 받았다. HTTP와 producer 사이의 span 부모·link는 만들지 않았으며 같다고 합치지 않는다. Redis 왕복은 성공했지만 이 실행에서는 Redis 전용 span을 찾지 못했다. 그 원인을 입증하거나 Redis 자동 계측 지원을 완료했다고 판정하지 않는다.

스모크 검사는 계측을 붙여 실제 기능 흐름을 확인하는 작은 검사다. 읽은 전체 span 367/244/117개에는 예약 작업·다른 소비 기록이 포함되므로 요청당 비용·유실률로 비교하지 않는다. 이 별도 수집기의 로그 입력 한도는 앱별 64MiB, 선택 흐름에 보관할 span은 200개로 제한했다. 순수 Java 연결 CLI의 10MiB·100개 제한과 다르다. 사용한 세 앱은 정지·제거했고 기존 실행 컨테이너 11개의 ID가 그대로임을 확인했다.

이 대상의 기존 `/probe/runtime` 응답에 남은 `runtimeMethodTracing=false`는 앞선 수동 비교 단계의 고정 표기다. 외부 agent 부착을 탐지하는 값으로 사용하지 않았다. 실제 span과 그 resource의 agent·SDK 버전, 배포 JAR 해시를 대조했다.

[실행 도구](../../experiments/execution_agent_smoke.py)에 별도 대상·새 빌드·새 무시 출력 디렉터리를 지정한다. 실제 실행 명령은 `python3 experiments/execution_agent_smoke.py --target "$TARGET_ROOT" --build-id method-agent-b1 --agent "$OTEL_AGENT_JAR" --output "$NEW_SMOKE_OUTPUT" --run`이다. 비용 측정과 동시에 실행하지 않는다.

## 공식 근거와 남은 작업

선택 계측의 이름 매칭과 descriptor 부재는 [고정 메서드 계측 코드](https://github.com/open-telemetry/opentelemetry-java-instrumentation/blob/d9045e02e0711837d54f0fd058cd55f77742506d/instrumentation/methods/javaagent/src/main/java/io/opentelemetry/javaagent/instrumentation/methods/MethodInstrumentation.java), [code 속성 추출](https://github.com/open-telemetry/opentelemetry-java-instrumentation/blob/d9045e02e0711837d54f0fd058cd55f77742506d/instrumentation-api-incubator/src/main/java/io/opentelemetry/instrumentation/api/incubator/semconv/code/CodeAttributesExtractor.java)과 대조했다. JSON 형식은 agent에 포함된 SDK 1.67.0의 [logging exporter](https://github.com/open-telemetry/opentelemetry-java/blob/b4b3a1b354425c3f1411173c0e48cb24a1cba224/exporters/logging-otlp/src/main/java/io/opentelemetry/exporter/logging/otlp/OtlpJsonLoggingSpanExporter.java), SQL 설정은 [JDBC metadata](https://github.com/open-telemetry/opentelemetry-java-instrumentation/blob/d9045e02e0711837d54f0fd058cd55f77742506d/instrumentation/jdbc/metadata.yaml)에 근거한다. 분석기 공식 API·라이선스는 [어댑터 원문 목록](../../tools/java-call-analysis/dependency-provenance.json)에 있다.

정확한 overload 계측, 실제 부분 영향 범위와 전체 결과 비교, exporter 장애·버전별 이벤트 문맥, 운영에 가까운 비용 입력을 다음 검증으로 남긴다. 자동 등록·지속 갱신 서비스, 권한·보존 서버, Kubernetes·AWS·CMDB·SIEM의 구현 완료를 뜻하지 않는다. 모두 플랫폼 구현 대상이며 이 실험은 그 근거 연결의 첫 구현이다.

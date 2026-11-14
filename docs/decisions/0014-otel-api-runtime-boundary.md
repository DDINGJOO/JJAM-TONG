# ADR 0014 — 런타임 문맥 연동의 OpenTelemetry API 경계

날짜: 2026-11-14. 상태: **사용자가 선택한 런타임 인터페이스 / 첫 어댑터 검증 범위**.

연결: [런타임 근거 계약 #66](https://github.com/DDINGJOO/JJAM-TONG/issues/66), [입력 계약 실험 #88](https://github.com/DDINGJOO/JJAM-TONG/issues/88), [API 어댑터 #93](https://github.com/DDINGJOO/JJAM-TONG/issues/93), [빌드 식별 계약](../../libraries/evidence-contract-java/README.md).

## 결정과 이유

런타임 연동은 OpenTelemetry API를 기준으로 개발한다. 기존 계측이 전달하는 실행 문맥을 활용하고, JJAM-TONG은 코드 분석·빌드 버전과 근거를 정확히 연결하는 책임을 맡는다. 첫 구현은 [Java API 문맥 어댑터](../../libraries/otel-context-java/README.md)다. 이 선택으로 SDK(소프트웨어 개발 키트)·Exporter(전송 구성 요소)·Collector·저장소·배포 방식을 함께 확정하지 않는다.

API만 사용하는 라이브러리는 애플리케이션의 전역 SDK를 초기화하지 않는다. 호출자가 명시적으로 전달한 Span(예: `Span.current()`)에서 허용한 식별자·플래그만 읽고, 유효하지 않은 문맥은 미해결로 남긴다. API가 모든 메서드·private 호출·접근자를 자동으로 계측한다고 가정하지 않는다. 실제 span 생성과 자동 계측 범위는 별도 입력·검증이 필요하다.

## 문맥과 실행 근거를 구분한다

유효한 `SpanContext`는 전파 식별자이며 메서드 실행·수집·전송의 증명이 아니다. 첫 어댑터의 성공 상태는 `CONTEXT_AVAILABLE`로 표현한다. `sampled`·`recording`·`remote`는 각각 보존하며 어느 하나로 내보내기 성공이나 요청 전체 수집을 판정하지 않는다. `Span.wrap`으로 만든 유효한 비기록 문맥도 이 원칙을 따른다.

선택한 분석·런타임 빌드와 계측 설정 식별자는 호출자가 명시한다. 분석기 설정과 런타임 계측 설정은 서로 다른 식별자다. 빌드·계측 설정이 다르면 선택한 분석본에 연결하지 않으며, 누락되면 최신 버전이나 대체 값을 고르지 않는다. 호출자가 제공한 식별의 일치는 원격 프로세스의 실제 빌드 출처를 인증하지 않는다.

OpenTelemetry API의 `Span`은 기록된 부모·링크 목록을 조회하는 인터페이스를 제공하지 않는다. 첫 어댑터는 이 관계를 만들어 내지 않는다. 후속 수집 경로가 제공하는 부모·링크를 정적 호출 후보와 구분해 보존한다.

## 첫 검증과 후속 경계

실제 API·Context JAR 1.66.0을 고정한 작은 소비자 시험을 수행한다. 최신 버전이나 모든 기존 agent 조합의 호환성을 주장하지 않는다. API와 기존 빌드 계약만 classpath에 넣고 SDK는 설치하지 않는다. 유효하지 않은 문맥, 비샘플링·비기록·원격 문맥, 식별 누락·불일치, Scope 복원과 명시적 Executor·가상 스레드 전달을 판별한다. 합성 문맥 시험은 업무 요청의 실제 Trace 검증과 구분한다.

Reactor의 구독 문맥, Kafka 전파와 배치 링크, 자동 메서드 계측, OTLP(OpenTelemetry Protocol) 지속 수집·저장·유실·재시작·수용량, 화면 자동 갱신은 이어서 검증한다. 이 단계가 지원되지 않는 영역의 완료를 뜻하지 않는다. 전체 플랫폼 범위는 유지하며 각 경계의 구현·검증을 별도 티켓으로 연결한다.

근거: [OpenTelemetry Java API](https://opentelemetry.io/docs/languages/java/api/), [Trace API 명세](https://opentelemetry.io/docs/specs/otel/trace/api/), [문맥 전달](https://opentelemetry.io/docs/languages/java/context/), [메시징 관계 규약](https://opentelemetry.io/docs/specs/semconv/messaging/messaging-spans/).

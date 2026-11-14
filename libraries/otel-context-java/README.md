# OpenTelemetry API context adapter (experimental)

This small Java 17 library reads a caller-supplied [OpenTelemetry Java API](https://opentelemetry.io/docs/languages/java/api/) `Span` (for example, `Span.current()`) and combines only its valid propagation identifiers with explicit JJAM-TONG identities. The adapter does not implicitly capture the current thread's context. It was tested against the cached `opentelemetry-api` and `opentelemetry-context` **1.66.0** artifacts; this is a reproducible baseline, not a claim about the latest OpenTelemetry release.

It is the API-only baseline for [issue #93](https://github.com/DDINGJOO/JJAM-TONG/issues/93). It depends on the existing `evidence-contract` JAR for `AnalysisIdentity`, `BuildIdentity`, and `EvidenceLinker`.

## Contract

`OtelContextAdapter.capture` accepts an explicit `Span`, selected `AnalysisIdentity`, runtime `BuildIdentity`, and separate expected/runtime telemetry configuration SHA-256 values. The analyzer configuration in `AnalysisIdentity` is independent of the telemetry configuration; one is never used as a fallback for the other. Its immutable `ContextCapture` copies only valid `traceId`, `spanId`, `remote`, `sampled`, and `recording` flags plus those explicit identities.

`CONTEXT_AVAILABLE` means a valid supplied propagation context and matching selected/runtime build and configuration identities. It does **not** mean a method ran, that a span was recorded or exported, or that a trace is complete. A valid non-recording or `sampled=false` context remains context evidence. Invalid/no-op context and missing identities are `UNRESOLVED`; mismatched build or configuration identities are `MISMATCH` and do not cross-link to the selected analysis.

The adapter never creates spans, initializes an SDK, exports data, reads baggage or `TraceState`, infers method names from span names, or fabricates parents or links. The API does not expose a span's recorded parent or links, so those are not represented here. See the [OpenTelemetry trace API specification](https://opentelemetry.io/docs/specs/otel/trace/api/) for the distinction between span context, recording, and propagation.

## Build and test

No Maven, Gradle, network fetch, SDK, or exporter is needed. Build the reused contract first, then supply the API/context JAR paths explicitly, plus their cached API runtime dependency:

```sh
python3 libraries/evidence-contract-java/build.py --java-home "$JDK17_HOME"
python3 libraries/otel-context-java/build.py \
  --java-home "$JDK17_HOME" --java21-home "$JDK21_HOME" \
  --evidence-contract libraries/evidence-contract-java/build/evidence-contract.jar \
  --otel-api /path/to/opentelemetry-api-1.66.0.jar \
  --otel-context /path/to/opentelemetry-context-1.66.0.jar \
  --otel-common /path/to/opentelemetry-common-1.66.0.jar
```

The main library and standard tests compile with `--release 17 -Xlint:all -Werror`. The separate virtual-thread test compiles and runs on JDK 21 with `--release 21`; it proves explicit `Context.taskWrapping` propagation and that an unwrapped virtual worker does not inherit the context. `build/verification.json` records the commands' JDK details and JAR hashes.

## Not implemented

This module does not implement a Reactor bridge, Kafka propagation, recorded parent/link retrieval, automatic method instrumentation, OTLP ingestion, storage, or a UI. It provides context semantics only and must never be treated as proof of observed application execution.

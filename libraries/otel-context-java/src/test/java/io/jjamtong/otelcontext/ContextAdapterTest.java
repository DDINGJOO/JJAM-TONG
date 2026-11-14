package io.jjamtong.otelcontext;

import io.jjamtong.evidence.AnalysisIdentity;
import io.jjamtong.evidence.BuildIdentity;
import io.jjamtong.evidence.EvidenceLinker;
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import io.opentelemetry.api.trace.TraceFlags;
import io.opentelemetry.api.trace.TraceState;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.Scope;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** API/context-only checks. Passing them never proves application execution or export. */
public final class ContextAdapterTest {
    private static final String A = "a".repeat(64);
    private static final String B = "b".repeat(64);
    private static final String TRACE = "0123456789abcdef0123456789abcdef";
    private static final String SPAN = "0123456789abcdef";
    private static int checks;

    public static void main(String[] args) throws Exception {
        BuildIdentity build = new BuildIdentity("synthetic/board", "commit-A", "build-A", "api", A);
        AnalysisIdentity analysis = new AnalysisIdentity(build, "run-A", "synthetic", "1", "draft-1", A, B);
        check(!GlobalOpenTelemetry.isSet(), "no SDK global is unset");
        check(Span.current().getSpanContext().isValid() == false, "no SDK current span is invalid");
        ContextCapture noSdk = capture(Span.current(), analysis, build, A);
        check(noSdk.status() == ContextCapture.Status.UNRESOLVED, "no SDK is unresolved");
        check(noSdk.currentSpan().isEmpty() && noSdk.fields().contains("runtimeContext"), "no synthetic IDs");

        Span sampled = Span.wrap(context(false, true));
        ContextCapture available = capture(sampled, analysis, build, A);
        check(available.status() == ContextCapture.Status.CONTEXT_AVAILABLE, "valid context available");
        check(available.currentSpan().orElseThrow().traceId().equals(TRACE), "trace ID copied");
        check(available.currentSpan().orElseThrow().sampled(), "sampled flag copied");
        check(!available.currentSpan().orElseThrow().recording(), "wrapped span is non-recording");
        check(available.linkedAnalysis().orElseThrow().equals(analysis), "only matching analysis linked");

        ContextCapture unsampled = capture(Span.wrap(context(false, false)), analysis, build, A);
        check(unsampled.status() == ContextCapture.Status.CONTEXT_AVAILABLE, "unsampled valid context retained");
        check(!unsampled.currentSpan().orElseThrow().sampled(), "unsampled flag retained");
        ContextCapture remote = capture(Span.wrap(context(true, false)), analysis, build, A);
        check(remote.currentSpan().orElseThrow().remote(), "remote flag retained");

        ContextCapture invalid = capture(Span.wrap(SpanContext.getInvalid()), analysis, build, A);
        check(invalid.status() == ContextCapture.Status.UNRESOLVED && invalid.currentSpan().isEmpty(), "invalid rejected");
        ContextCapture missingBuild = newCapture(sampled, Optional.of(analysis), Optional.empty(), Optional.of(A));
        check(missingBuild.status() == ContextCapture.Status.UNRESOLVED
                && missingBuild.fields().contains("runtime"), "missing build unresolved");
        ContextCapture missingConfig = newCapture(sampled, Optional.of(analysis), Optional.of(build), Optional.empty());
        check(missingConfig.status() == ContextCapture.Status.UNRESOLVED
                && missingConfig.fields().contains("telemetryConfigSha256"), "missing config unresolved");
        ContextCapture missingSelected = newCapture(sampled, Optional.empty(), Optional.of(build), Optional.of(A));
        check(missingSelected.status() == ContextCapture.Status.UNRESOLVED
                && missingSelected.fields().contains("analysis")
                && !missingSelected.fields().contains("telemetryConfigSha256"),
                "missing analysis does not erase independently supplied telemetry config");

        BuildIdentity otherBuild = new BuildIdentity("synthetic/board", "commit-B", "build-A", "api", A);
        ContextCapture buildMismatch = capture(sampled, analysis, otherBuild, A);
        check(buildMismatch.status() == ContextCapture.Status.MISMATCH
                && buildMismatch.buildComparison().status() == EvidenceLinker.Status.MISMATCH
                && buildMismatch.fields().equals(Set.of("revision")), "build mismatch does not link");
        check(buildMismatch.linkedAnalysis().isEmpty(), "build mismatch has no cross-link");
        ContextCapture configMismatch = capture(sampled, analysis, build, B);
        check(configMismatch.status() == ContextCapture.Status.MISMATCH
                && configMismatch.fields().equals(Set.of("telemetryConfigSha256")), "config mismatch does not link");
        check(configMismatch.linkedAnalysis().isEmpty(), "config mismatch has no cross-link");
        String telemetry = "c".repeat(64);
        ContextCapture separateConfig = OtelContextAdapter.capture(new OtelContextAdapter.CaptureInput(
                sampled, Optional.of(analysis), Optional.of(build), Optional.of(telemetry), Optional.of(telemetry)));
        check(separateConfig.status() == ContextCapture.Status.CONTEXT_AVAILABLE,
                "analysis config and telemetry config are independent identities");
        ContextCapture selectedTelemetryMissing = OtelContextAdapter.capture(new OtelContextAdapter.CaptureInput(
                sampled, Optional.of(analysis), Optional.of(build), Optional.empty(), Optional.of(A)));
        check(selectedTelemetryMissing.status() == ContextCapture.Status.UNRESOLVED,
                "missing selected telemetry config cannot fall back to analyzer config");
        rejects(() -> new OtelContextAdapter.CaptureInput(sampled, Optional.of(analysis), Optional.of(build),
                Optional.of(A), Optional.of("not-a-digest")), IllegalArgumentException.class);

        Span prior = Span.current();
        try (Scope scope = sampled.makeCurrent()) {
            check(scope != null, "scope is created");
            check(Span.current().getSpanContext().equals(sampled.getSpanContext()), "scope makes span current");
        }
        check(Span.current() == prior, "scope restores prior current span");
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            check(!executor.submit(() -> Span.current().getSpanContext().isValid()).get(), "unwrapped worker has no context");
            try (Scope scope = sampled.makeCurrent()) {
                check(scope != null, "executor scope is created");
                check(!executor.submit(() -> Span.current().getSpanContext().isValid()).get(),
                        "unwrapped worker does not inherit active submission context");
                check(Context.taskWrapping(executor).submit(
                        () -> Span.current().getSpanContext().getTraceId()).get().equals(TRACE),
                        "wrapped executor restores submission context");
                check(!executor.submit(() -> Span.current().getSpanContext().isValid()).get(),
                        "wrapped worker restores prior context without cross-request leak");
            }
        } finally {
            executor.shutdown();
        }
        System.out.println("PASS " + checks + " API/context checks on " + Runtime.version());
    }

    private static ContextCapture capture(Span span, AnalysisIdentity analysis, BuildIdentity build, String config) {
        return newCapture(span, Optional.of(analysis), Optional.of(build), Optional.of(config));
    }

    private static ContextCapture newCapture(Span span, Optional<AnalysisIdentity> analysis,
                                             Optional<BuildIdentity> build, Optional<String> config) {
        return OtelContextAdapter.capture(new OtelContextAdapter.CaptureInput(span, analysis, build, Optional.of(A), config));
    }

    private static SpanContext context(boolean remote, boolean sampled) {
        TraceFlags flags = sampled ? TraceFlags.getSampled() : TraceFlags.getDefault();
        return remote ? SpanContext.createFromRemoteParent(TRACE, SPAN, flags, TraceState.getDefault())
                : SpanContext.create(TRACE, SPAN, flags, TraceState.getDefault());
    }

    private static void rejects(Runnable action, Class<? extends RuntimeException> expected) {
        try {
            action.run();
        } catch (RuntimeException error) {
            check(expected.isInstance(error), "invalid digest rejected");
            return;
        }
        throw new AssertionError("Expected " + expected.getSimpleName());
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
        checks++;
    }
}

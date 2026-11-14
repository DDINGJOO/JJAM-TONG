package io.jjamtong.otelcontext;

import io.jjamtong.evidence.AnalysisIdentity;
import io.jjamtong.evidence.BuildIdentity;
import io.jjamtong.evidence.EvidenceLinker;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;

/**
 * Reads an existing API span only. This class never creates spans, initializes an SDK, or exports data.
 */
public final class OtelContextAdapter {
    private static final String CONFIG_FIELD = "telemetryConfigSha256";
    private static final String CONTEXT_FIELD = "runtimeContext";

    private OtelContextAdapter() {}

    /** Capture the supplied span as a context candidate; never attests the current thread or execution. */
    public static ContextCapture capture(CaptureInput input) {
        Objects.requireNonNull(input, "input");
        SpanContext spanContext = input.span().getSpanContext();
        Optional<ContextCapture.CurrentSpan> current = spanContext.isValid()
                ? Optional.of(new ContextCapture.CurrentSpan(
                        spanContext.getTraceId(), spanContext.getSpanId(), spanContext.isRemote(),
                        spanContext.isSampled(), input.span().isRecording()))
                : Optional.empty();

        EvidenceLinker.Result comparison = EvidenceLinker.compare(
                input.selectedAnalysis(), input.runtimeBuild());
        Set<String> fields = new LinkedHashSet<>(comparison.fields());
        Optional<String> selectedConfig = input.selectedTelemetryConfigSha256();
        if (selectedConfig.isEmpty() || input.runtimeConfigSha256().isEmpty()) {
            fields.add(CONFIG_FIELD);
        } else if (!selectedConfig.orElseThrow().equals(input.runtimeConfigSha256().orElseThrow())) {
            fields.add(CONFIG_FIELD);
        }
        if (current.isEmpty()) fields.add(CONTEXT_FIELD);

        ContextCapture.Status status;
        if (current.isEmpty() || comparison.status() == EvidenceLinker.Status.UNRESOLVED
                || selectedConfig.isEmpty() || input.runtimeConfigSha256().isEmpty()) {
            status = ContextCapture.Status.UNRESOLVED;
        } else if (comparison.status() == EvidenceLinker.Status.MISMATCH
                || !selectedConfig.orElseThrow().equals(input.runtimeConfigSha256().orElseThrow())) {
            status = ContextCapture.Status.MISMATCH;
        } else {
            status = ContextCapture.Status.CONTEXT_AVAILABLE;
        }
        Optional<AnalysisIdentity> linked = status == ContextCapture.Status.CONTEXT_AVAILABLE
                ? input.selectedAnalysis() : Optional.empty();
        return new ContextCapture(status, fields, current, comparison, selectedConfig,
                input.runtimeConfigSha256(), linked);
    }

    /** Explicit caller-owned inputs; absent identities remain absent rather than receiving synthetic values. */
    public record CaptureInput(Span span, Optional<AnalysisIdentity> selectedAnalysis,
                               Optional<BuildIdentity> runtimeBuild,
                               Optional<String> selectedTelemetryConfigSha256,
                               Optional<String> runtimeConfigSha256) {
        public CaptureInput {
            Objects.requireNonNull(span, "span");
            Objects.requireNonNull(selectedAnalysis, "selectedAnalysis");
            Objects.requireNonNull(runtimeBuild, "runtimeBuild");
            Objects.requireNonNull(selectedTelemetryConfigSha256, "selectedTelemetryConfigSha256");
            Objects.requireNonNull(runtimeConfigSha256, "runtimeConfigSha256");
            selectedTelemetryConfigSha256 = selectedTelemetryConfigSha256.map(OtelContextAdapter::digest);
            runtimeConfigSha256 = runtimeConfigSha256.map(OtelContextAdapter::digest);
        }
    }

    private static String digest(String value) {
        Objects.requireNonNull(value, "runtimeConfigSha256");
        if (!value.matches("[0-9a-fA-F]{64}")) {
            throw new IllegalArgumentException("runtimeConfigSha256 must be a SHA-256 hex digest");
        }
        return value.toLowerCase(Locale.ROOT);
    }
}

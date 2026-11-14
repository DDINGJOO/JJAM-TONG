package io.jjamtong.otelcontext;

import io.jjamtong.evidence.AnalysisIdentity;
import io.jjamtong.evidence.EvidenceLinker;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;

/** Immutable result of reading a supplied OpenTelemetry context, not an execution observation. */
public record ContextCapture(
        Status status,
        Set<String> fields,
        Optional<CurrentSpan> currentSpan,
        EvidenceLinker.Result buildComparison,
        Optional<String> selectedTelemetryConfigSha256,
        Optional<String> runtimeConfigSha256,
        Optional<AnalysisIdentity> linkedAnalysis) {
    public enum Status { CONTEXT_AVAILABLE, UNRESOLVED, MISMATCH }

    public ContextCapture {
        Objects.requireNonNull(status, "status");
        fields = Set.copyOf(fields);
        Objects.requireNonNull(currentSpan, "currentSpan");
        Objects.requireNonNull(buildComparison, "buildComparison");
        Objects.requireNonNull(selectedTelemetryConfigSha256, "selectedTelemetryConfigSha256");
        Objects.requireNonNull(runtimeConfigSha256, "runtimeConfigSha256");
        Objects.requireNonNull(linkedAnalysis, "linkedAnalysis");
        if (status == Status.CONTEXT_AVAILABLE && (currentSpan.isEmpty() || linkedAnalysis.isEmpty())) {
            throw new IllegalArgumentException("available context requires a linked selected analysis");
        }
        if (status != Status.CONTEXT_AVAILABLE && linkedAnalysis.isPresent()) {
            throw new IllegalArgumentException("unresolved or mismatched context must not cross-link analysis");
        }
    }

    /** Only allowlisted propagation identifiers and flags; this is never proof of execution or export. */
    public record CurrentSpan(String traceId, String spanId, boolean remote, boolean sampled,
                              boolean recording) {
        public CurrentSpan {
            Objects.requireNonNull(traceId, "traceId");
            Objects.requireNonNull(spanId, "spanId");
        }
    }
}

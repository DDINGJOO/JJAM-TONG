package io.jjamtong.evidence;

import java.util.LinkedHashSet;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;

/** Compares metadata only. Does not discover analyses, validate schemas, or observe execution. */
public final class EvidenceLinker {
    private EvidenceLinker() {}

    public enum Status { MATCH, MISMATCH, UNRESOLVED }

    /** Fields contains missing sides for UNRESOLVED or differing build fields for MISMATCH. */
    public record Result(Status status, Set<String> fields,
                         Optional<AnalysisIdentity> analysis, Optional<BuildIdentity> runtime) {
        public Result {
            Objects.requireNonNull(status, "status");
            fields = Set.copyOf(fields);
            Objects.requireNonNull(analysis, "analysis");
            Objects.requireNonNull(runtime, "runtime");
        }
    }

    public static Result compare(Optional<AnalysisIdentity> analysis, Optional<BuildIdentity> runtime) {
        Objects.requireNonNull(analysis, "analysis");
        Objects.requireNonNull(runtime, "runtime");
        Set<String> fields = new LinkedHashSet<>();
        if (analysis.isEmpty()) fields.add("analysis");
        if (runtime.isEmpty()) fields.add("runtime");
        if (!fields.isEmpty()) return new Result(Status.UNRESOLVED, fields, analysis, runtime);

        BuildIdentity expected = analysis.orElseThrow().target();
        BuildIdentity actual = runtime.orElseThrow();
        difference(fields, "repository", expected.repository(), actual.repository());
        difference(fields, "revision", expected.revision(), actual.revision());
        difference(fields, "build", expected.build(), actual.build());
        difference(fields, "module", expected.module(), actual.module());
        difference(fields, "artifactSha256", expected.artifactSha256(), actual.artifactSha256());
        return new Result(fields.isEmpty() ? Status.MATCH : Status.MISMATCH, fields, analysis, runtime);
    }

    private static void difference(Set<String> fields, String field, String expected, String actual) {
        if (!expected.equals(actual)) fields.add(field);
    }
}

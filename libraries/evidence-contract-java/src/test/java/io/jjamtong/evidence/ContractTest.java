package io.jjamtong.evidence;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Optional;
import java.util.Set;

public final class ContractTest {
    private static final String A = "a".repeat(64);
    private static final String B = "b".repeat(64);
    private static int checks;

    public static void main(String[] args) throws Exception {
        BuildIdentity build = new BuildIdentity("synthetic/board", "commit-A", "build-A", "api", A);
        AnalysisIdentity analysis = analysis(build, "run-A", A);
        var match = EvidenceLinker.compare(Optional.of(analysis), Optional.of(build));
        check(match.status() == EvidenceLinker.Status.MATCH && match.fields().isEmpty(), "exact match");
        check(match.analysis().orElseThrow().equals(analysis), "selected analysis retained");

        mismatch(analysis, new BuildIdentity("other/board", "commit-A", "build-A", "api", A), "repository");
        mismatch(analysis, new BuildIdentity("synthetic/board", "commit-B", "build-A", "api", A), "revision");
        mismatch(analysis, new BuildIdentity("synthetic/board", "commit-A", "build-B", "api", A), "build");
        mismatch(analysis, new BuildIdentity("synthetic/board", "commit-A", "build-A", "worker", A), "module");
        mismatch(analysis, new BuildIdentity("synthetic/board", "commit-A", "build-A", "api", B), "artifactSha256");
        var multiple = EvidenceLinker.compare(Optional.of(analysis), Optional.of(
                new BuildIdentity("synthetic/board", "commit-A", "build-B", "api", B)));
        check(multiple.fields().equals(Set.of("build", "artifactSha256")), "all differences retained");
        unresolved(Optional.empty(), Optional.of(build), Set.of("analysis"));
        unresolved(Optional.of(analysis), Optional.empty(), Set.of("runtime"));
        unresolved(Optional.empty(), Optional.empty(), Set.of("analysis", "runtime"));

        AnalysisIdentity reanalysis = analysis(build, "run-B", B);
        var reselected = EvidenceLinker.compare(Optional.of(reanalysis), Optional.of(build));
        check(!analysis.equals(reanalysis) && reselected.analysis().orElseThrow().equals(reanalysis)
                && reselected.status() == EvidenceLinker.Status.MATCH, "same build preserves separate analysis");
        check(new BuildIdentity("r", "c", "b", "m", A.toUpperCase()).artifactSha256().equals(A),
                "digest case normalization");
        rejects(() -> new BuildIdentity(" ", "c", "b", "m", A), IllegalArgumentException.class);
        rejects(() -> new BuildIdentity("r", "c", "b", "m", "abc"), IllegalArgumentException.class);
        rejects(() -> new BuildIdentity("r", "c", "b", "m", "z".repeat(64)), IllegalArgumentException.class);
        rejects(() -> new BuildIdentity(null, "c", "b", "m", A), NullPointerException.class);
        rejects(() -> analysis(build, "", A), IllegalArgumentException.class);
        rejects(() -> new AnalysisIdentity(build, "run", "test", "1", "1", "wrong", A),
                IllegalArgumentException.class);
        rejects(() -> match.fields().add("changed"), UnsupportedOperationException.class);
        rejects(() -> EvidenceLinker.compare(null, Optional.of(build)), NullPointerException.class);

        Path artifact = Files.createTempFile("jjamtong-contract-", ".bin");
        try {
            Files.writeString(artifact, "abc");
            check(ArtifactDigests.sha256(artifact).equals(
                    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"), "SHA256 known vector");
            Files.writeString(artifact, "abcd");
            check(!ArtifactDigests.sha256(artifact).equals(
                    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"), "changed artifact changes digest");
        } finally {
            Files.deleteIfExists(artifact);
        }
        System.out.println("PASS " + checks + " contract checks on " + Runtime.version());
    }

    private static AnalysisIdentity analysis(BuildIdentity build, String run, String config) {
        return new AnalysisIdentity(build, run, "synthetic-test-only", "1", "draft-1", config, A);
    }

    private static void mismatch(AnalysisIdentity analysis, BuildIdentity runtime, String field) {
        var result = EvidenceLinker.compare(Optional.of(analysis), Optional.of(runtime));
        check(result.status() == EvidenceLinker.Status.MISMATCH && result.fields().equals(Set.of(field)), field);
    }

    private static void unresolved(Optional<AnalysisIdentity> analysis, Optional<BuildIdentity> runtime,
                                   Set<String> missing) {
        var result = EvidenceLinker.compare(analysis, runtime);
        check(result.status() == EvidenceLinker.Status.UNRESOLVED && result.fields().equals(missing), "missing sides");
    }

    private static void rejects(Runnable action, Class<? extends RuntimeException> expected) {
        try {
            action.run();
        } catch (RuntimeException error) {
            check(expected.isInstance(error), "rejected invalid input: " + expected.getSimpleName());
            return;
        }
        throw new AssertionError("Expected " + expected.getSimpleName());
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
        checks++;
    }
}

package io.jjamtong.evidence;

import java.util.Objects;

/** Identifies an explicitly selected analysis. Different runs/configurations stay distinct. */
public record AnalysisIdentity(
        BuildIdentity target,
        String run,
        String analyzer,
        String analyzerVersion,
        String schemaVersion,
        String configSha256,
        String indexSha256) {
    public AnalysisIdentity {
        Objects.requireNonNull(target, "target");
        run = IdentityChecks.identifier(run, "run");
        analyzer = IdentityChecks.identifier(analyzer, "analyzer");
        analyzerVersion = IdentityChecks.identifier(analyzerVersion, "analyzerVersion");
        schemaVersion = IdentityChecks.identifier(schemaVersion, "schemaVersion");
        configSha256 = IdentityChecks.digest(configSha256, "configSha256");
        indexSha256 = IdentityChecks.digest(indexSha256, "indexSha256");
    }
}

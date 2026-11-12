package io.jjamtong.evidence;

/** Caller-supplied identity of one final artifact; this is not provenance attestation. */
public record BuildIdentity(
        String repository, String revision, String build, String module, String artifactSha256) {
    public BuildIdentity {
        repository = IdentityChecks.identifier(repository, "repository");
        revision = IdentityChecks.identifier(revision, "revision");
        build = IdentityChecks.identifier(build, "build");
        module = IdentityChecks.identifier(module, "module");
        artifactSha256 = IdentityChecks.digest(artifactSha256, "artifactSha256");
    }
}

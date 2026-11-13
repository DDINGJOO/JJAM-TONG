"""Committed immutable v1 agreement for the method-fixture CI artifact."""
from types import MappingProxyType


CONTRACT = MappingProxyType({
    "schema": "jjamtong.github-method-evidence.v1",
    "bundle_files": ("manifest.json", "index.json"),
    "manifest_fields": ("schema", "repository", "repositoryId", "revision", "workflow", "runId",
                        "runAttempt", "analysisRunId", "indexSha256", "indexFileSha256"),
    "artifactName": "jjamtong-method-index-{runId}-{runAttempt}",
    "analysisRunId": "gh-{repositoryId}-{runId}-{runAttempt}",
    "indexRepository": "https://github.com/{repository}",
    "indexBuild": "gh-{runId}-{runAttempt}",
    "module": "method-fixture",
})

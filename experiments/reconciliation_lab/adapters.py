"""Read-only Git ports. No source code is executed or copied to reports."""
import hashlib
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

API_VERSION = "2026-03-10"
ANALYZER = "git-file-index/1"
SCHEMA = "repository-files/1"
OID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class ReadFailure(Exception):
    def __init__(self, code, retry_after=5):
        super().__init__(code)
        self.retry_after = retry_after


def settings(prefixes=("services/",), analyzer=ANALYZER):
    if not prefixes or any(not p or p.startswith("/") or ".." in p.split("/") for p in prefixes):
        raise ValueError("explicit relative inclusion prefixes required")
    return {"prefixes": sorted(set(prefixes)), "analyzer": analyzer, "schema": SCHEMA}


def fingerprint(config):
    return hashlib.sha256(canonical(config).encode()).hexdigest()


def make_index(source, revision, tree, files, source_at, config):
    if not OID.fullmatch(revision) or not OID.fullmatch(tree):
        raise ReadFailure("invalid_git_object_id")
    selected = {}
    for path, blob in files.items():
        if not isinstance(path, str) or path.startswith("/") or ".." in path.split("/"):
            raise ReadFailure("invalid_tree_path")
        if not isinstance(blob, str) or not OID.fullmatch(blob):
            raise ReadFailure("invalid_blob_id")
        if any(path.startswith(p) for p in config["prefixes"]):
            selected[path] = blob
    return {"source": source, "revision": revision, "tree": tree,
            "source_at": source_at, "config": config, "files": dict(sorted(selected.items()))}


class LocalGit:
    def __init__(self, path, source, ref="refs/heads/main", config=None):
        self.path, self.source, self.ref = str(path), "git:" + source + "#" + ref, ref
        self.config = config or settings()
        self.calls = Counter()

    def git(self, *args):
        try:
            return subprocess.run(["git", "-C", self.path, *args], check=True,
                                  capture_output=True, timeout=10).stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            raise ReadFailure("git_read_failed") from None

    def read(self, previous=None):
        self.calls["checks"] += 1
        revision = self.git("rev-parse", "--verify", "--end-of-options", self.ref + "^{commit}").decode().strip()
        if previous and previous["revision"] == revision and previous["config"] == self.config:
            return previous, None
        self.calls["trees"] += 1
        tree = self.git("rev-parse", revision + "^{tree}").decode().strip()
        files = {}
        for entry in self.git("ls-tree", "-r", "-z", revision).split(b"\0"):
            if entry:
                meta, path = entry.split(b"\t", 1)
                mode, kind, oid = meta.decode().split()
                if kind == "blob" and mode in ("100644", "100755"):
                    files[path.decode("utf-8")] = oid
        source_at = self.git("show", "-s", "--format=%cI", revision).decode().strip()
        return make_index(self.source, revision, tree, files, source_at, self.config), None


class GitHub:
    """Public metadata GETs only; redirects cannot send requests to another host.

    The loopback origin option exists solely for HTTP contract/fault tests.
    Responses are bounded. Truncated trees fail closed instead of silently
    removing files from the current index. This adapter has no write method.
    """
    def __init__(self, repository, ref="main", config=None, origin="https://api.github.com", token=None):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ValueError("owner/repository required")
        parsed = urllib.parse.urlsplit(origin)
        local = (parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                 and not parsed.username and not parsed.password and not parsed.path
                 and not parsed.query and not parsed.fragment)
        if origin != "https://api.github.com" and not local:
            raise ValueError("only GitHub or loopback test origins allowed")
        self.repository, self.ref, self.origin = repository, ref, origin.rstrip("/")
        self.source, self.config = "github:" + repository + "#" + ref, config or settings()
        self.token, self.calls = token, Counter()

    def get(self, endpoint, etag=None):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "JJAM-TONG-reconciliation-lab",
                   "X-GitHub-Api-Version": API_VERSION}
        if etag:
            headers["If-None-Match"] = etag
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        self.calls["http"] += 1
        request = urllib.request.Request(self.origin + endpoint, headers=headers)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=10) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise ReadFailure("response_size_limit")
                return json.loads(raw), response.headers.get("ETag")
        except urllib.error.HTTPError as error:
            if error.code == 304:
                self.calls["not_modified"] += 1
                return None, etag
            delay = 5
            if error.code in (403, 429):
                delay = 60
                retry = error.headers.get("Retry-After", "")
                reset = error.headers.get("X-RateLimit-Reset", "")
                if retry.isdigit():
                    delay = max(delay, int(retry))
                if error.headers.get("X-RateLimit-Remaining") == "0" and reset.isdigit():
                    delay = max(delay, float(reset) - time.time())
            raise ReadFailure("http_" + str(error.code), delay) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise ReadFailure("http_read_failed") from None

    def read(self, previous=None, etag=None):
        self.calls["checks"] += 1
        path = "/repos/" + self.repository
        commit, new_etag = self.get(path + "/commits/" + urllib.parse.quote(self.ref, safe=""), etag)
        if commit is None:
            if previous is None:
                raise ReadFailure("304_without_committed_snapshot")
            return previous, new_etag
        try:
            revision, tree = commit["sha"], commit["commit"]["tree"]["sha"]
            if previous and previous["revision"] == revision and previous["config"] == self.config:
                if previous["tree"] != tree:
                    raise ReadFailure("immutable_commit_tree_conflict")
                return previous, new_etag
            if not OID.fullmatch(revision) or not OID.fullmatch(tree):
                raise ReadFailure("invalid_git_object_id")
            self.calls["trees"] += 1
            data, _ = self.get(path + "/git/trees/" + tree + "?recursive=1")
            if data["truncated"] is not False or data["sha"] != tree:
                raise ReadFailure("incomplete_tree")
            files = {f["path"]: f["sha"] for f in data["tree"]
                     if f["type"] == "blob" and f["mode"] in ("100644", "100755")}
            return make_index(self.source, revision, tree, files, commit["commit"]["committer"]["date"],
                              self.config), new_etag
        except (KeyError, TypeError):
            raise ReadFailure("invalid_github_response") from None

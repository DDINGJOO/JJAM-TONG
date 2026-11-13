"""Bounded, fail-closed GitHub Actions artifact collection."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import io
import json
import re
import stat
from typing import Mapping, Optional, Protocol
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile

from tools.evidence_store.contracts import prepare
from tools.method_evidence.evidence import HEX64, validate_index

API_HOST = "api.github.com"
ARCHIVE_LIMIT = 12 * 1024 * 1024
INDEX_LIMIT = 10 * 1024 * 1024
MANIFEST_LIMIT = 16 * 1024
SHA40 = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")
WORKFLOW = re.compile(r"\.github/workflows/[A-Za-z0-9_-][A-Za-z0-9_.-]*\.ya?ml$")


class ImportError(ValueError):
    """A deliberately non-sensitive import rejection."""


class Transport(Protocol):
    def json(self, path: str) -> dict: ...
    def bytes(self, url: str) -> bytes: ...


class Store(Protocol):
    def publish(self, tenant: str, index: dict) -> bool: ...


@dataclass(frozen=True)
class SourceConfig:
    repository: str
    workflow: str
    branch: str
    tenant: str
    pages: int = 3

    def __post_init__(self):
        if not isinstance(self.repository, str) or not REPOSITORY.fullmatch(self.repository) or ".." in self.repository:
            raise ValueError("repository must be one explicit owner/name")
        workflow = self.workflow
        if isinstance(workflow, str) and "/" not in workflow:
            workflow = ".github/workflows/" + workflow
            object.__setattr__(self, "workflow", workflow)
        if not isinstance(workflow, str) or not WORKFLOW.fullmatch(workflow) or ".." in workflow:
            raise ValueError("workflow must be an explicit .github/workflows filename")
        if not isinstance(self.branch, str) or not re.fullmatch(r"[A-Za-z0-9._/-]{1,255}", self.branch) or ".." in self.branch:
            raise ValueError("invalid branch")
        if not isinstance(self.tenant, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", self.tenant):
            raise ValueError("invalid tenant")
        if type(self.pages) is not int or not 1 <= self.pages <= 10:
            raise ValueError("pages must be 1 through 10")

    @property
    def workflow_filename(self):
        return self.workflow.rsplit("/", 1)[1]


@dataclass(frozen=True)
class Receipt:
    run_id: str
    attempt: str
    artifact_id: str
    run_url: str
    artifact_url: str
    archive_sha256: str
    index_sha256: str
    revision: str
    build: str
    analysis_run_id: str
    tenant: str
    status: str

    def json(self):
        return asdict(self)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubTransport:
    """Only authenticates API-host requests; redirects never receive the token."""

    def __init__(self, token: str, timeout: int = 10):
        if not isinstance(token, str) or not token:
            raise ValueError("JJAMTONG_GITHUB_TOKEN is required")
        self._token, self._timeout = token, timeout
        self._opener = build_opener(_NoRedirect())

    def _open(self, url: str, authenticated: bool, unavailable=False):
        try:
            parsed = urlparse(url)
            port = parsed.port
        except (TypeError, ValueError):
            raise ImportError("INVALID_URL") from None
        if parsed.scheme != "https":
            raise ImportError("HTTPS_REQUIRED")
        if parsed.username is not None or parsed.password is not None or port not in (None, 443):
            raise ImportError("INVALID_URL")
        if authenticated and parsed.hostname != API_HOST:
            raise ImportError("API_HOST_REQUIRED")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "jjamtong-evidence-sync",
                   "X-GitHub-Api-Version": "2026-03-10"}
        if authenticated:
            headers["Authorization"] = "Bearer " + self._token
        try:
            return self._opener.open(Request(url, headers=headers), timeout=self._timeout)
        except HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                return exc
            exc.close()
            if unavailable and exc.code in (404, 410):
                raise ImportError("UNAVAILABLE") from None
            raise ImportError("GITHUB_REQUEST_FAILED") from None
        except Exception:
            raise ImportError("GITHUB_REQUEST_FAILED") from None

    def json(self, path: str) -> dict:
        if not isinstance(path, str) or not path.startswith("/"):
            raise ImportError("INVALID_API_PATH")
        response = self._open("https://" + API_HOST + path, True)
        try:
            try:
                payload = response.read(2 * 1024 * 1024 + 1)
            except Exception:
                raise ImportError("GITHUB_REQUEST_FAILED") from None
        finally:
            try:
                response.close()
            except Exception:
                pass
        if not isinstance(payload, bytes) or len(payload) > 2 * 1024 * 1024:
            raise ImportError("API_RESPONSE_TOO_LARGE")
        try:
            value = _json(payload)
        except Exception:
            raise ImportError("INVALID_API_RESPONSE") from None
        if not isinstance(value, dict):
            raise ImportError("INVALID_API_RESPONSE")
        return value

    def bytes(self, url: str) -> bytes:
        current, authenticated = url, True
        for _ in range(4):
            response = self._open(current, authenticated, unavailable=True)
            try:
                code = response.getcode()
                if code in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not isinstance(location, str) or not location:
                        raise ImportError("ARTIFACT_REDIRECT_FAILED")
                    current, authenticated = location, False
                    continue
                try:
                    body = response.read(ARCHIVE_LIMIT + 1)
                except Exception:
                    raise ImportError("GITHUB_REQUEST_FAILED") from None
                if not isinstance(body, bytes) or len(body) > ARCHIVE_LIMIT:
                    raise ImportError("ARCHIVE_TOO_LARGE")
                return body
            finally:
                try:
                    response.close()
                except Exception:
                    pass
        raise ImportError("ARTIFACT_REDIRECT_FAILED")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ImportError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _json(raw: bytes):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)


def _expect(value, name):
    if not isinstance(value, dict):
        raise ImportError("INVALID_" + name)
    return value


class Collector:
    def __init__(self, config: SourceConfig, transport: Transport, store: Store, contract: Mapping):
        self.config, self.transport, self.store, self.contract = config, transport, store, contract
        required = {"schema", "bundle_files", "manifest_fields", "artifactName", "analysisRunId", "indexRepository", "indexBuild", "module"}
        if not isinstance(contract, Mapping) or not required <= set(contract):
            raise ValueError("invalid producer contract")

    def _api(self, path, name):
        try:
            return _expect(self.transport.json(path), name)
        except ImportError:
            raise
        except Exception:
            raise ImportError("GITHUB_REQUEST_FAILED") from None

    def _download(self, url):
        try:
            return self.transport.bytes(url)
        except ImportError:
            raise
        except Exception:
            raise ImportError("GITHUB_REQUEST_FAILED") from None

    def collect(self, run_id: Optional[str] = None, continue_on_error=False, on_error=None) -> list[Receipt]:
        repository = self._api("/repos/" + self.config.repository, "REPOSITORY")
        repo_id = repository.get("id")
        if type(repo_id) is not int or repo_id < 1 or repository.get("full_name") != self.config.repository:
            raise ImportError("REPOSITORY_IDENTITY_MISMATCH")
        runs = [self._run(run_id)] if run_id else self._runs()
        receipts, failure = [], None
        for run in runs:
            try:
                self._verify_run(run, repo_id)
                receipts.append(self._import(run, repo_id))
            except ImportError as exc:
                if continue_on_error:
                    if on_error:
                        on_error(exc)
                else:
                    failure = failure or exc
        if failure:
            raise failure
        return receipts

    def _run(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", run_id):
            raise ValueError("run-id must be a positive numeric GitHub Actions run id")
        run = self._api("/repos/" + self.config.repository + "/actions/runs/" + run_id, "RUN")
        if type(run.get("id")) is not int or str(run["id"]) != run_id:
            raise ImportError("RUN_ID_MISMATCH")
        return run

    def _runs(self):
        found, seen = [], set()
        base = "/repos/" + self.config.repository + "/actions/workflows/" + quote(self.config.workflow_filename, safe="") + "/runs?branch=" + quote(self.config.branch, safe="")
        for event in ("push", "workflow_dispatch"):
            for page in range(1, self.config.pages + 1):
                data = self._api(base + "&event=" + event + "&status=success&per_page=100&page=" + str(page), "RUN_LIST")
                runs = data.get("workflow_runs")
                if not isinstance(runs, list):
                    raise ImportError("INVALID_RUN_LIST")
                for run in runs:
                    if not isinstance(run, dict) or type(run.get("id")) is not int or run["id"] < 1:
                        raise ImportError("INVALID_RUN_LIST")
                    if run["id"] not in seen:
                        found.append(run)
                        seen.add(run["id"])
                if len(runs) < 100:
                    break
            # Discovery is a bounded recent-history window, not an exhaustive
            # inventory. A full final page must not block all newer imports.
        return found

    def _verify_run(self, run, repo_id):
        required = ("id", "run_attempt", "head_sha", "conclusion", "status", "event", "head_branch", "workflow_id", "repository", "head_repository")
        if not isinstance(run, dict) or any(key not in run for key in required):
            raise ImportError("RUN_METADATA_INCOMPLETE")
        if (type(run["id"]) is not int or run["id"] < 1 or type(run["run_attempt"]) is not int or run["run_attempt"] < 1
                or type(run["workflow_id"]) is not int or run["workflow_id"] < 1 or not isinstance(run["head_sha"], str)
                or not SHA40.fullmatch(run["head_sha"]) or run["status"] != "completed" or run["conclusion"] != "success"
                or run["event"] not in ("push", "workflow_dispatch") or run["head_branch"] != self.config.branch):
            raise ImportError("RUN_NOT_ALLOWED")
        if any(not isinstance(run[key], dict) or type(run[key].get("id")) is not int or run[key]["id"] != repo_id for key in ("repository", "head_repository")):
            raise ImportError("RUN_REPOSITORY_MISMATCH")
        workflow = self._api("/repos/" + self.config.repository + "/actions/workflows/" + str(run["workflow_id"]), "WORKFLOW")
        if type(workflow.get("id")) is not int or workflow["id"] != run["workflow_id"] or workflow.get("path") != self.config.workflow:
            raise ImportError("WORKFLOW_MISMATCH")

    def _artifact_url_is_canonical(self, value, artifact_id):
        try:
            parsed = urlparse(value) if isinstance(value, str) else None
            port = parsed.port if parsed else None
        except (TypeError, ValueError):
            return False
        expected = "/repos/" + self.config.repository + "/actions/artifacts/" + str(artifact_id) + "/zip"
        return bool(parsed and parsed.scheme == "https" and parsed.hostname == API_HOST and port in (None, 443) and parsed.username is None and parsed.password is None and parsed.query == "" and parsed.fragment == "" and parsed.path == expected)

    def _artifact_fingerprint(self, artifact):
        return (artifact["id"], artifact["name"], artifact["expired"], artifact["size_in_bytes"], artifact["digest"], artifact["archive_download_url"], tuple(artifact["workflow_run"][key] for key in ("id", "repository_id", "head_repository_id", "head_branch", "head_sha")))

    def _artifact(self, run, repo_id):
        run_id, attempt = str(run["id"]), str(run["run_attempt"])
        name = self.contract["artifactName"].format(runId=run_id, runAttempt=attempt)
        base = "/repos/" + self.config.repository + "/actions/runs/" + run_id + "/artifacts?name=" + quote(name, safe="") + "&per_page=100"
        artifacts, total = [], None
        for page in range(1, self.config.pages + 1):
            data = self._api(base + "&page=" + str(page), "ARTIFACT_LIST")
            if type(data.get("total_count")) is not int or data["total_count"] < 0:
                raise ImportError("INVALID_ARTIFACT_LIST")
            if total is None:
                total = data["total_count"]
                if total > self.config.pages * 100:
                    raise ImportError("ARTIFACT_PAGINATION_INCOMPLETE")
            elif total != data["total_count"]:
                raise ImportError("ARTIFACT_METADATA_CHANGED")
            page_items = data.get("artifacts")
            if not isinstance(page_items, list):
                raise ImportError("INVALID_ARTIFACT_LIST")
            artifacts.extend(page_items)
            if len(artifacts) > total:
                raise ImportError("INVALID_ARTIFACT_LIST")
            if len(artifacts) >= total:
                break
            if len(page_items) < 100:
                raise ImportError("ARTIFACT_PAGINATION_INCOMPLETE")
        else:
            raise ImportError("ARTIFACT_PAGINATION_INCOMPLETE")
        named = [item for item in artifacts if isinstance(item, dict) and item.get("name") == name]
        if not named or all(item.get("expired") is True for item in named):
            raise ImportError("UNAVAILABLE")
        usable = [item for item in named if item.get("expired") is False]
        if len(named) != 1 or len(usable) != 1:
            raise ImportError("ARTIFACT_NOT_UNIQUE")
        artifact, workflow = usable[0], usable[0].get("workflow_run")
        required = ("id", "repository_id", "head_repository_id", "head_branch", "head_sha")
        if (type(artifact.get("id")) is not int or artifact["id"] < 1 or type(artifact.get("size_in_bytes")) is not int or not 0 < artifact["size_in_bytes"] <= ARCHIVE_LIMIT or not isinstance(workflow, dict) or any(key not in workflow for key in required) or not self._artifact_url_is_canonical(artifact.get("archive_download_url"), artifact["id"])):
            raise ImportError("ARTIFACT_METADATA_INCOMPLETE")
        if (type(workflow["id"]) is not int or workflow["id"] != run["id"] or type(workflow["repository_id"]) is not int or workflow["repository_id"] != repo_id or type(workflow["head_repository_id"]) is not int or workflow["head_repository_id"] != repo_id or workflow["head_branch"] != self.config.branch or workflow["head_sha"] != run["head_sha"]):
            raise ImportError("ARTIFACT_RUN_MISMATCH")
        if not isinstance(artifact.get("digest"), str) or not DIGEST.fullmatch(artifact["digest"]):
            raise ImportError("ARTIFACT_METADATA_INCOMPLETE")
        return artifact

    def _import(self, selected_run, repo_id):
        run = self._run(str(selected_run["id"]))
        self._verify_run(run, repo_id)
        artifact = self._artifact(run, repo_id)
        archive = self._download(artifact["archive_download_url"])
        if not isinstance(archive, bytes) or len(archive) > ARCHIVE_LIMIT:
            raise ImportError("ARCHIVE_TOO_LARGE")
        archive_sha = hashlib.sha256(archive).hexdigest()
        if archive_sha != DIGEST.fullmatch(artifact["digest"]).group(1):
            raise ImportError("ARCHIVE_DIGEST_MISMATCH")
        manifest, index, index_bytes = self._bundle(archive)
        self._verify_bundle(manifest, index, index_bytes, run, repo_id)
        fresh_run = self._run(str(run["id"]))
        self._verify_run(fresh_run, repo_id)
        if self._run_fingerprint(fresh_run) != self._run_fingerprint(run):
            raise ImportError("RUN_METADATA_CHANGED")
        fresh_repository = self._api("/repos/" + self.config.repository, "REPOSITORY")
        if type(fresh_repository.get("id")) is not int or fresh_repository["id"] != repo_id or fresh_repository.get("full_name") != self.config.repository:
            raise ImportError("REPOSITORY_IDENTITY_MISMATCH")
        fresh_artifact = self._artifact(fresh_run, repo_id)
        if self._artifact_fingerprint(fresh_artifact) != self._artifact_fingerprint(artifact):
            raise ImportError("ARTIFACT_METADATA_CHANGED")
        try:
            created = self.store.publish(self.config.tenant, index)
        except Exception:
            raise ImportError("PUBLISH_FAILED") from None
        if type(created) is not bool:
            raise ImportError("PUBLISH_FAILED")
        run_id, attempt, identity = str(run["id"]), str(run["run_attempt"]), index["buildIdentity"]
        return Receipt(run_id, attempt, str(artifact["id"]), _run_url(self.config.repository, run_id), _artifact_url(self.config.repository, artifact["id"]), archive_sha, index["indexSha256"], identity["revision"], identity["build"], index["analysisRunId"], self.config.tenant, "created" if created else "replay")

    @staticmethod
    def _run_fingerprint(run):
        return tuple(run[key] for key in ("id", "run_attempt", "head_sha", "conclusion", "status", "event", "head_branch", "workflow_id")) + (run["repository"]["id"], run["head_repository"]["id"])

    def _bundle(self, archive):
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                entries = bundle.infolist()
                if len(entries) != 2 or {entry.filename for entry in entries} != {"manifest.json", "index.json"}:
                    raise ImportError("INVALID_ARCHIVE_CONTENTS")
                values, total = {}, 0
                for entry in entries:
                    limit, mode = (MANIFEST_LIMIT if entry.filename == "manifest.json" else INDEX_LIMIT), entry.external_attr >> 16
                    if (entry.is_dir() or entry.flag_bits & 1 or stat.S_ISLNK(mode) or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) or entry.file_size < 0 or entry.compress_size < 0 or entry.file_size > limit or entry.compress_size > ARCHIVE_LIMIT):
                        raise ImportError("INVALID_ARCHIVE_CONTENTS")
                    total += entry.file_size
                    if total > MANIFEST_LIMIT + INDEX_LIMIT:
                        raise ImportError("ARCHIVE_BUDGET_EXCEEDED")
                    with bundle.open(entry) as stream:
                        raw = stream.read(limit + 1)
                    if len(raw) > limit or len(raw) != entry.file_size:
                        raise ImportError("ARCHIVE_BUDGET_EXCEEDED")
                    values[entry.filename] = (_json(raw), raw)
                return values["manifest.json"][0], values["index.json"][0], values["index.json"][1]
        except ImportError:
            raise
        except Exception:
            raise ImportError("INVALID_ARCHIVE") from None

    def _verify_bundle(self, manifest, index, index_bytes, run, repo_id):
        fields = self.contract["manifest_fields"]
        if not isinstance(manifest, dict) or not isinstance(fields, (list, tuple)) or set(manifest) != set(fields):
            raise ImportError("MANIFEST_FIELDS_MISMATCH")
        required_text = ("schema", "repository", "revision", "workflow", "runId", "runAttempt", "analysisRunId", "indexSha256", "indexFileSha256")
        if any(not isinstance(manifest.get(key), str) for key in required_text) or type(manifest.get("repositoryId")) is not int:
            raise ImportError("MANIFEST_TYPES_MISMATCH")
        run_id, attempt = str(run["id"]), str(run["run_attempt"])
        try:
            expected_run = self.contract["analysisRunId"].format(repositoryId=repo_id, runId=run_id, runAttempt=attempt)
            expected_repository = self.contract["indexRepository"].format(repository=self.config.repository)
            expected_build = self.contract["indexBuild"].format(runId=run_id, runAttempt=attempt)
        except Exception:
            raise ImportError("INVALID_PRODUCER_CONTRACT") from None
        if (manifest["schema"] != self.contract["schema"] or manifest["repository"] != self.config.repository or manifest["repositoryId"] != repo_id or manifest["revision"] != run["head_sha"] or manifest["workflow"] != self.config.workflow or manifest["runId"] != run_id or manifest["runAttempt"] != attempt or manifest["analysisRunId"] != expected_run or not HEX64.fullmatch(manifest["indexSha256"]) or not HEX64.fullmatch(manifest["indexFileSha256"])):
            raise ImportError("MANIFEST_METADATA_MISMATCH")
        if hashlib.sha256(index_bytes).hexdigest() != manifest["indexFileSha256"]:
            raise ImportError("INDEX_FILE_DIGEST_MISMATCH")
        if not isinstance(index, dict):
            raise ImportError("INVALID_INDEX")
        if index.get("analysisRunId") != expected_run or index.get("indexSha256") != manifest["indexSha256"]:
            raise ImportError("INDEX_MANIFEST_MISMATCH")
        identity = index.get("buildIdentity")
        if not isinstance(identity, dict) or identity.get("repository") != expected_repository:
            raise ImportError("BUILD_IDENTITY_MISMATCH")
        if identity.get("revision") != run["head_sha"] or identity.get("build") != expected_build or identity.get("module") != self.contract["module"]:
            raise ImportError("BUILD_IDENTITY_MISMATCH")
        try:
            validate_index(index)
            prepare(index)
        except Exception:
            raise ImportError("INDEX_VALIDATION_FAILED") from None


def _run_url(repository, run_id):
    return "https://github.com/" + repository + "/actions/runs/" + run_id


def _artifact_url(repository, artifact_id):
    return "https://api.github.com/repos/" + repository + "/actions/artifacts/" + str(artifact_id)

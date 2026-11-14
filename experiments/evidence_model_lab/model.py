"""Typed, append-only evidence claims for a deliberately small local experiment.

This is not a storage engine, discovery system, or generic graph API.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
import copy
import hashlib
import json


class EntityKind(str, Enum):
    REPOSITORY = "REPOSITORY"
    SOURCE_REVISION = "SOURCE_REVISION"
    MODULE = "MODULE"
    MODULE_BUILD = "MODULE_BUILD"
    ARTIFACT = "ARTIFACT"
    ANALYSIS_SNAPSHOT = "ANALYSIS_SNAPSHOT"
    SERVICE = "SERVICE"
    DEPLOYMENT = "DEPLOYMENT"
    WORKLOAD = "WORKLOAD"
    POD = "POD"
    RUNTIME = "RUNTIME"
    RESOURCE = "RESOURCE"
    METHOD_VERSION = "METHOD_VERSION"


class EvidenceMode(str, Enum):
    STATIC_CANDIDATE = "STATIC_CANDIDATE"
    DECLARED = "DECLARED"
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"


class RelationKind(str, Enum):
    HAS_REVISION = "HAS_REVISION"
    HAS_MODULE = "HAS_MODULE"
    BUILDS = "BUILDS"
    PRODUCES = "PRODUCES"
    ANALYZED_AS = "ANALYZED_AS"
    DEPLOYS = "DEPLOYS"
    RUNS = "RUNS"
    HAS_POD = "HAS_POD"
    HOSTS_RUNTIME = "HOSTS_RUNTIME"
    RUNTIME_USES_BUILD = "RUNTIME_USES_BUILD"
    RUNTIME_PRIMARY_BUILD = "RUNTIME_PRIMARY_BUILD"
    SERVICE_USES_MODULE = "SERVICE_USES_MODULE"
    USES_RESOURCE = "USES_RESOURCE"
    CATALOG_MAPS = "CATALOG_MAPS"
    STATIC_CALL = "STATIC_CALL"
    EQUIVALENT_TO = "EQUIVALENT_TO"


# relation -> (allowed endpoint pairs, allowed evidence modes, object cardinality per subject)
_RULES = {
    RelationKind.HAS_REVISION: ({(EntityKind.REPOSITORY, EntityKind.SOURCE_REVISION)}, frozenset({EvidenceMode.DECLARED}), "many"),
    RelationKind.HAS_MODULE: ({(EntityKind.SOURCE_REVISION, EntityKind.MODULE)}, frozenset({EvidenceMode.DECLARED}), "many"),
    RelationKind.BUILDS: ({(EntityKind.MODULE, EntityKind.MODULE_BUILD)}, frozenset({EvidenceMode.DECLARED}), "many"),
    RelationKind.PRODUCES: ({(EntityKind.MODULE_BUILD, EntityKind.ARTIFACT)}, frozenset({EvidenceMode.DECLARED}), "many"),
    RelationKind.ANALYZED_AS: ({(EntityKind.ARTIFACT, EntityKind.ANALYSIS_SNAPSHOT)}, frozenset({EvidenceMode.DECLARED}), "many"),
    RelationKind.DEPLOYS: ({(EntityKind.SERVICE, EntityKind.DEPLOYMENT)}, frozenset({EvidenceMode.DECLARED}), "many"),
    RelationKind.RUNS: ({(EntityKind.DEPLOYMENT, EntityKind.WORKLOAD)}, frozenset({EvidenceMode.DECLARED, EvidenceMode.OBSERVED}), "many"),
    RelationKind.HAS_POD: ({(EntityKind.WORKLOAD, EntityKind.POD)}, frozenset({EvidenceMode.OBSERVED}), "many"),
    RelationKind.HOSTS_RUNTIME: ({(EntityKind.POD, EntityKind.RUNTIME)}, frozenset({EvidenceMode.OBSERVED}), "many"),
    RelationKind.RUNTIME_USES_BUILD: ({(EntityKind.RUNTIME, EntityKind.MODULE_BUILD)}, frozenset({EvidenceMode.OBSERVED}), "many"),
    RelationKind.RUNTIME_PRIMARY_BUILD: ({(EntityKind.RUNTIME, EntityKind.MODULE_BUILD)}, frozenset({EvidenceMode.DECLARED, EvidenceMode.OBSERVED}), "single"),
    RelationKind.SERVICE_USES_MODULE: ({(EntityKind.SERVICE, EntityKind.MODULE)}, frozenset({EvidenceMode.DECLARED}), "many"),
    RelationKind.USES_RESOURCE: ({(EntityKind.SERVICE, EntityKind.RESOURCE)}, frozenset({EvidenceMode.DECLARED, EvidenceMode.OBSERVED, EvidenceMode.INFERRED}), "many"),
    RelationKind.CATALOG_MAPS: ({(EntityKind.SERVICE, EntityKind.RESOURCE)}, frozenset({EvidenceMode.DECLARED, EvidenceMode.INFERRED}), "many"),
    RelationKind.STATIC_CALL: ({(EntityKind.METHOD_VERSION, EntityKind.METHOD_VERSION)}, frozenset({EvidenceMode.STATIC_CANDIDATE}), "many"),
    RelationKind.EQUIVALENT_TO: (set(), frozenset({EvidenceMode.DECLARED, EvidenceMode.INFERRED}), "many"),
}


def _text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 512:
        raise ValueError(f"invalid {field}")


def _utc(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
        raise ValueError(f"{field} must be timezone-aware UTC")


@dataclass(frozen=True, order=True)
class EntityRef:
    kind: EntityKind
    tenant: str
    provider: str
    native_id: str
    incarnation: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EntityKind):
            raise ValueError("unknown entity kind")
        for field in ("tenant", "provider", "native_id"):
            _text(getattr(self, field), field)
        if not isinstance(self.incarnation, str) or (self.incarnation and (not self.incarnation.strip() or self.incarnation != self.incarnation.strip())) or len(self.incarnation) > 512:
            raise ValueError("invalid incarnation")

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "tenant": self.tenant, "provider": self.provider,
                "nativeId": self.native_id, "incarnation": self.incarnation}


@dataclass(frozen=True, order=True)
class EvidenceRef:
    tenant: str
    provider: str
    native_id: str
    original_ref: str

    def __post_init__(self) -> None:
        for field in ("tenant", "provider", "native_id", "original_ref"):
            _text(getattr(self, field), field)


@dataclass(frozen=True)
class Claim:
    claim_id: str
    tenant: str
    subject: EntityRef
    relation: RelationKind
    object: EntityRef
    mode: EvidenceMode
    evidence: EvidenceRef
    valid_from: datetime
    known_at: datetime
    valid_to: datetime | None = None
    supersedes: str | None = None
    retracts: str | None = None

    def __post_init__(self) -> None:
        _text(self.claim_id, "claim_id")
        _text(self.tenant, "tenant")
        if not isinstance(self.relation, RelationKind) or not isinstance(self.mode, EvidenceMode):
            raise ValueError("unknown relation or evidence mode")
        if not isinstance(self.subject, EntityRef) or not isinstance(self.object, EntityRef) or not isinstance(self.evidence, EvidenceRef):
            raise ValueError("typed endpoints and evidence are required")
        if self.tenant != self.subject.tenant or self.tenant != self.object.tenant or self.tenant != self.evidence.tenant:
            raise ValueError("cross-tenant claim")
        _utc(self.valid_from, "valid_from")
        _utc(self.known_at, "known_at")
        if self.valid_to is not None:
            _utc(self.valid_to, "valid_to")
            if self.valid_to <= self.valid_from:
                raise ValueError("valid time must be a half-open increasing interval")
        if self.supersedes is not None:
            _text(self.supersedes, "supersedes")
        if self.retracts is not None:
            _text(self.retracts, "retracts")
        if self.supersedes is not None and self.retracts is not None:
            raise ValueError("claim cannot both supersede and retract")
        if self.claim_id in (self.supersedes, self.retracts):
            raise ValueError("claim cannot reference itself")
        pairs, modes, _ = _RULES[self.relation]
        if self.mode not in modes:
            raise ValueError("evidence mode is invalid for relation")
        if self.relation is RelationKind.EQUIVALENT_TO:
            if self.subject.kind is not self.object.kind:
                raise ValueError("equivalence requires equal entity kinds")
        elif (self.subject.kind, self.object.kind) not in pairs:
            raise ValueError("relation endpoint mismatch")

    def to_dict(self) -> dict:
        return {"claimId": self.claim_id, "tenant": self.tenant, "subject": self.subject.to_dict(),
                "relation": self.relation.value, "object": self.object.to_dict(), "mode": self.mode.value,
                "evidence": {"provider": self.evidence.provider, "nativeId": self.evidence.native_id,
                             "originalRef": self.evidence.original_ref}, "validFrom": self.valid_from.isoformat(),
                "validTo": self.valid_to.isoformat() if self.valid_to else None, "knownAt": self.known_at.isoformat(),
                "supersedes": self.supersedes, "retracts": self.retracts}


@dataclass(frozen=True)
class QueryRequest:
    tenant: str
    subject: EntityRef
    relation: RelationKind
    valid_at: datetime
    known_at: datetime
    allowed_refs: frozenset[EntityRef]
    modes: frozenset[EvidenceMode] = frozenset(EvidenceMode)
    limit: int = 20
    visibility_complete: bool = False

    def __post_init__(self) -> None:
        _text(self.tenant, "tenant")
        if not isinstance(self.subject, EntityRef):
            raise ValueError("query subject must be a typed ref")
        if not isinstance(self.relation, RelationKind):
            raise ValueError("query relation must be typed")
        if self.subject.tenant != self.tenant:
            raise ValueError("query tenant or relation mismatch")
        _utc(self.valid_at, "valid_at")
        _utc(self.known_at, "known_at")
        if not isinstance(self.allowed_refs, frozenset) or not all(isinstance(item, EntityRef) for item in self.allowed_refs):
            raise ValueError("allowed_refs must be a frozen set of typed refs")
        if any(item.tenant != self.tenant for item in self.allowed_refs):
            raise ValueError("allowed_refs must belong to query tenant")
        if not isinstance(self.modes, frozenset) or not self.modes or not all(isinstance(mode, EvidenceMode) for mode in self.modes):
            raise ValueError("modes must be a nonempty frozen evidence-mode set")
        if type(self.limit) is not int or not 1 <= self.limit <= 1000:
            raise ValueError("limit must be a bounded integer")
        if type(self.visibility_complete) is not bool:
            raise ValueError("visibility_complete must be bool")


@dataclass(frozen=True)
class QueryResult:
    status: str
    claim_ids: tuple[str, ...]
    object_refs: tuple[EntityRef, ...]
    reasons: tuple[str, ...]
    # Query projections preserve visible provenance but never ledger linkage IDs.
    claims: tuple[Claim, ...] = ()

    def to_dict(self) -> dict:
        return {"status": self.status, "claimIds": list(self.claim_ids),
                "objectRefs": [item.to_dict() for item in self.object_refs],
                "claims": [claim.to_dict() for claim in self.claims], "reasons": list(self.reasons)}


class ClaimLog:
    """Append-only in-memory log; callers only receive immutable claim objects."""
    def __init__(self) -> None:
        self._claims: dict[str, Claim] = {}

    def append(self, claim: Claim) -> None:
        if not isinstance(claim, Claim):
            raise ValueError("claim must be typed")
        existing = self._claims.get(claim.claim_id)
        if existing is not None:
            if existing != claim:
                raise ValueError("immutable claim ID collision")
            raise ValueError("claim replay")
        for target_id, label in ((claim.supersedes, "supersedes"), (claim.retracts, "retracts")):
            if target_id is None:
                continue
            target = self._claims.get(target_id)
            if target is None:
                raise ValueError(f"{label} target is not known")
            if target_id == claim.claim_id:
                raise ValueError(f"{label} cannot reference itself")
            same_source = (target.evidence.tenant, target.evidence.provider, target.evidence.native_id) == (claim.evidence.tenant, claim.evidence.provider, claim.evidence.native_id)
            if target.tenant != claim.tenant or target.subject != claim.subject or target.relation != claim.relation or not same_source or target.mode != claim.mode:
                raise ValueError(f"{label} must preserve tenant, source, subject, relation and evidence mode")
            if claim.known_at < target.known_at:
                raise ValueError(f"{label} cannot predate target knowledge")
            if label == "retracts" and claim.object != target.object:
                raise ValueError("retraction object must match target")
        self._claims[claim.claim_id] = claim

    def query(self, request: QueryRequest) -> QueryResult:
        if not isinstance(request, QueryRequest):
            raise ValueError("query request must be typed")
        if not request.visibility_complete or request.subject not in request.allowed_refs:
            return QueryResult("INCOMPLETE", (), (), ("INCOMPLETE_VISIBILITY",))
        # This caller-declared scope is deliberately applied before all result and
        # conflict construction. Hidden claims cannot affect a visible response.
        scoped = [claim for claim in self._claims.values()
                  if claim.tenant == request.tenant and claim.subject == request.subject
                  and claim.relation == request.relation and claim.mode in request.modes
                  and claim.known_at <= request.known_at and claim.object in request.allowed_refs]
        # A known correction/retraction removes its target regardless of either
        # event's valid interval; otherwise an expired correction resurrects facts.
        removed = {target for claim in scoped for target in (claim.supersedes, claim.retracts) if target}
        visible = [claim for claim in scoped if claim.claim_id not in removed and claim.retracts is None
                   and claim.valid_from <= request.valid_at and (claim.valid_to is None or request.valid_at < claim.valid_to)]
        visible.sort(key=lambda item: item.claim_id)
        if not visible:
            return QueryResult("NO_MATCH_IN_KNOWN_EVIDENCE", (), (), ("NO_MATCH_IN_KNOWN_EVIDENCE",))
        _, _, cardinality = _RULES[request.relation]
        objects = {claim.object for claim in visible}
        shown = visible[:request.limit]
        limited = len(visible) > request.limit
        conflict = cardinality == "single" and len(objects) > 1
        reasons = (() if not limited else ("QUERY_LIMIT",)) + (() if not conflict else ("CONFLICTING_SINGLE_VALUE",))
        status = "PARTIAL" if limited else ("CONFLICT" if conflict else "MATCH")
        # Omit history pointers uniformly, even when both endpoints are allowed.
        # Conditional redaction would disclose whether hidden provenance exists.
        projected = tuple(replace(item, supersedes=None, retracts=None) for item in shown)
        return QueryResult(status, tuple(item.claim_id for item in shown), tuple(item.object for item in shown), reasons, projected)


@dataclass(frozen=True)
class V1Bridge:
    tenant: str
    build_identity: tuple[tuple[str, str], ...]
    analysis_run_id: str
    index_sha256: str
    config_sha256: str
    repository: EntityRef
    source_revision: EntityRef
    module: EntityRef
    module_build: EntityRef
    artifact: EntityRef
    analysis_snapshot: EntityRef

    def to_dict(self) -> dict:
        return {"tenant": self.tenant, "buildIdentity": dict(self.build_identity), "analysisRunId": self.analysis_run_id,
                "indexSha256": self.index_sha256, "configSha256": self.config_sha256,
                "refs": {"repository": self.repository.to_dict(), "sourceRevision": self.source_revision.to_dict(),
                         "module": self.module.to_dict(), "moduleBuild": self.module_build.to_dict(),
                         "artifact": self.artifact.to_dict(), "analysisSnapshot": self.analysis_snapshot.to_dict()},
                "limitations": ["metadata-only bridge", "no method inventory imported", "no service, deployment, workload, pod, runtime, or trace inferred"]}


def import_v1(index: dict, tenant: str, provider: str = "method-index-v1") -> V1Bridge:
    """Strictly validate a v1 index, then map only its immutable identity metadata."""
    from tools.evidence_store.contracts import prepare
    snapshot = copy.deepcopy(index)
    prepare(snapshot)
    _text(tenant, "tenant")
    _text(provider, "provider")
    identity = snapshot["buildIdentity"]
    fields = ("repository", "revision", "build", "module", "artifactSha256")
    bindings = tuple((field, identity[field]) for field in fields)
    def composite_id(*field_names: str) -> str:
        payload = {field: identity[field] for field in field_names}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()
    repository = EntityRef(EntityKind.REPOSITORY, tenant, provider, identity["repository"])
    revision = EntityRef(EntityKind.SOURCE_REVISION, tenant, provider, composite_id("repository", "revision"))
    module = EntityRef(EntityKind.MODULE, tenant, provider, composite_id("repository", "module"))
    build = EntityRef(EntityKind.MODULE_BUILD, tenant, provider, composite_id(*fields))
    artifact = EntityRef(EntityKind.ARTIFACT, tenant, provider, identity["artifactSha256"])
    analysis_snapshot = EntityRef(EntityKind.ANALYSIS_SNAPSHOT, tenant, provider, snapshot["analysisRunId"], snapshot["indexSha256"])
    return V1Bridge(tenant, bindings, snapshot["analysisRunId"], snapshot["indexSha256"], snapshot["configSha256"], repository, revision, module, build, artifact, analysis_snapshot)


def require_exact_bridge(bridge: V1Bridge, build_identity: dict, index_sha256: str, config_sha256: str) -> V1Bridge:
    if tuple((field, build_identity.get(field)) for field, _ in bridge.build_identity) != bridge.build_identity:
        raise ValueError("exact build identity mismatch")
    if bridge.index_sha256 != index_sha256 or bridge.config_sha256 != config_sha256:
        raise ValueError("exact analysis or configuration hash mismatch")
    return bridge

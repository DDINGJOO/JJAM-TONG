"""A deliberately small, synthetic trace append/replay contract.

This is not a collector, persistence layer, OTLP receiver, or an extension of
the local web server.  It defines the fail-closed behaviour that a later
continuous-input design would need to preserve.
"""
from dataclasses import asdict, dataclass
import re
from typing import Optional


HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX = re.compile(r"^[0-9a-f]+$")


def _identifier(value, size):
    if not isinstance(value, str) or len(value) != size or not HEX.fullmatch(value) or int(value, 16) == 0:
        raise ValueError("invalid trace or span identifier")
    return value


@dataclass(frozen=True)
class AnalysisVersion:
    """An explicit static-analysis selection; a stream may not substitute latest."""
    run_id: str
    index_sha256: str
    build_identity: tuple
    telemetry_config_sha256: str

    def __post_init__(self):
        if not self.run_id or not HEX64.fullmatch(self.index_sha256):
            raise ValueError("explicit analysis version required")
        if not isinstance(self.build_identity, tuple) or not self.build_identity:
            raise ValueError("explicit build identity required")
        if not HEX64.fullmatch(self.telemetry_config_sha256):
            raise ValueError("explicit telemetry configuration required")


@dataclass(frozen=True)
class ObservedSpan:
    """Allowlisted synthetic observation; parentage and links remain observations."""
    trace_id: str
    span_id: str
    build_identity: tuple
    telemetry_config_sha256: str
    parent_span_id: Optional[str] = None
    links: tuple = ()
    class_name: Optional[str] = None
    method_name: Optional[str] = None

    def __post_init__(self):
        _identifier(self.trace_id, 32)
        _identifier(self.span_id, 16)
        if self.parent_span_id is not None:
            _identifier(self.parent_span_id, 16)
        if not isinstance(self.links, tuple):
            raise ValueError("links must be an immutable tuple")
        for trace_id, span_id in self.links:
            _identifier(trace_id, 32)
            _identifier(span_id, 16)
        if not HEX64.fullmatch(self.telemetry_config_sha256):
            raise ValueError("invalid telemetry configuration")


class TraceStream:
    """In-memory append contract with idempotent replay and no causal inference."""
    def __init__(self, analysis):
        self.analysis = analysis
        self._spans = {}
        self._partial_reasons = set()
        self._conflicts = {}

    def append(self, span):
        """Append one observation without replacing conflicting prior evidence."""
        if not isinstance(span, ObservedSpan):
            raise ValueError("observed span input required")
        if span.build_identity != self.analysis.build_identity:
            return {"outcome": "REJECTED", "reason": "BUILD_IDENTITY_MISMATCH"}
        if span.telemetry_config_sha256 != self.analysis.telemetry_config_sha256:
            return {"outcome": "REJECTED", "reason": "TELEMETRY_CONFIG_MISMATCH"}
        key = (span.trace_id, span.span_id)
        existing = self._spans.get(key)
        if existing is None:
            self._spans[key] = span
            return {"outcome": "APPENDED"}
        if existing == span:
            return {"outcome": "REPLAYED"}
        self._conflicts.setdefault(span.trace_id, set()).add(span.span_id)
        return {"outcome": "CONFLICT", "reason": "CONFLICTING_SPAN_REPLAY"}

    def append_frame(self, spans, complete):
        """Append an explicitly bounded frame; incomplete input is not success."""
        outcomes = []
        for span in spans:
            try:
                outcomes.append(self.append(span))
            except (TypeError, ValueError):
                outcomes.append({"outcome": "REJECTED", "reason": "PARTIAL_OR_INVALID_INPUT"})
                self._partial_reasons.add("PARTIAL_OR_INVALID_INPUT")
        if not complete:
            self._partial_reasons.add("INPUT_FRAME_NOT_FINAL")
        return outcomes

    def replay(self, trace_id, static_candidates):
        """Project collected observations without turning static candidates into calls.

        ``static_candidates`` is keyed by (class, method).  It is intentionally
        supplied separately: this experiment does not read, merge, or replace a
        static index and never chooses an overloaded JVM descriptor.
        """
        _identifier(trace_id, 32)
        rows = [span for (current_trace, _), span in self._spans.items() if current_trace == trace_id]
        reasons = set(self._partial_reasons)
        conflicts = sorted(self._conflicts.get(trace_id, ()))
        if conflicts:
            reasons.add("CONFLICTING_SPAN_REPLAY")
        present = {span.span_id for span in rows}
        records, parents, links = [], [], []
        for span in rows:
            candidates = tuple(static_candidates.get((span.class_name, span.method_name), ()))
            record = {"spanId": span.span_id, "class": span.class_name, "method": span.method_name,
                      "symbolCandidates": candidates,
                      "symbolStatus": "unique-name-resolved" if len(candidates) == 1 else "UNRESOLVED_CODE_SYMBOL"}
            records.append(record)
            if span.parent_span_id:
                parents.append({"relation": "observed-span-parent", "parentSpanId": span.parent_span_id,
                                "childSpanId": span.span_id,
                                "parentState": "collected" if span.parent_span_id in present else "external-or-not-collected"})
                if span.parent_span_id not in present:
                    reasons.add("PARENT_EXTERNAL_OR_NOT_COLLECTED")
            for linked_trace, linked_span in span.links:
                links.append({"relation": "observed-span-link", "sourceSpanId": span.span_id,
                              "targetTraceId": linked_trace, "targetSpanId": linked_span,
                              "targetState": "collected" if linked_trace == trace_id and linked_span in present
                              else "external-or-not-collected"})
        if not rows:
            reasons.add("NO_MATCHING_SPANS")
        return {"analysisVersion": asdict(self.analysis), "traceId": trace_id, "spans": records,
                "observedParents": parents, "observedLinks": links,
                "status": "OBSERVED" if rows and not reasons else "PARTIAL" if rows else "UNRESOLVED",
                "conflictingSpanIds": conflicts,
                "collectionReasons": sorted(reasons),
                "limitations": ["Observed parentage and links do not prove a synchronous source call.",
                                "Static candidates are not observed calls; overloaded symbols stay unresolved.",
                                "This in-memory experiment does not provide persistent ingestion."]}

# Trace stream contract experiment

Synthetic in-memory contract checks for a possible continuous trace input lane.
It verifies append, idempotent replay, conflicting replay, partial frames, and
explicit analysis/build/configuration boundaries.  It keeps static symbol
candidates separate from observed span parent and link relations; it does not
choose an overloaded descriptor or infer causality.

This is not an OTLP receiver, a persistence design, or a change to the local
startup-file capture.  It neither reads a latest source/index nor claims
persistent ingestion.

Conflicting retransmissions preserve the first observation and mark only the
affected trace as partial on replay, returning the conflicting span IDs. The
conflicting payload itself is not retained or quarantined by this experiment.
The supplied symbol-candidate map must be selected by the caller for the stated
analysis version; this experiment does not load or attest that map. An
`OBSERVED` result describes collected spans, not full request coverage or exact
method-descriptor resolution.

Tracking: [#88](https://github.com/DDINGJOO/JJAM-TONG/issues/88). Transport,
durable checkpoints, rejection/conflict quarantine, per-trace collection
boundaries, retention, load limits, and consumer integration require separate
implementation decisions and verification. `append_frame` assumes a bounded
caller-provided frame; it does not enforce a frame-size budget.

```sh
python3 -m unittest experiments.trace_stream_contract.test_model -v
```

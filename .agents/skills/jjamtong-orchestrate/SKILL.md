---
name: jjamtong-orchestrate
description: Coordinate bounded JJAM-TONG engineering work across agents with issue traceability, resumable evidence, and minimal escalation. Use for multi-lane implementation or investigation that needs explicit ownership and dependencies.
---

# JJAM-TONG orchestration

Coordinate a verified outcome without turning routine work into ceremony. Read the shared runtime contract at
[`docs/engineering/AGENT-ORCHESTRATION.md`](../../../docs/engineering/AGENT-ORCHESTRATION.md)
before coordinating; it is the source for detailed runtime conventions. This skill defines how to apply that
contract to JJAM-TONG work.

## Establish a bounded work graph

Turn the requested outcome into a GitHub issue hierarchy: epic, story, task, then subtask only where it makes
the work independently verifiable. Give each leaf an owner, a bounded deliverable, dependencies, acceptance
criteria, and a parent. An agent may own only one active leaf at a time. Do not create leaves merely to meet a
quota.

The coordinator owns repository documentation, wiki/ADR alignment, issue traceability, integration decisions,
and final verification. For independent work such as Java/static analysis and runtime trace work, establish the
shared input/output contract first, then assign separate bounded leaves (for example, A owns Java/static and B
owns trace evidence). Keep shared-file ownership explicit; wait for a prerequisite rather than silently changing
another owner's boundary.

Use installed specialist roles when they are available and fit the work: `explore` for repository facts,
`researcher` for official references, `executor` for a bounded implementation, and `verifier` or `critic` for
independent validation. Select tools and roles from the active environment; do not hard-code a model and do not
invoke an unsupported `worker` role outside its team runtime.

## Keep work resumable and evidence-linked

For every active leaf, retain a compact ledger containing:

- parent issue, owner, dependency state, acceptance criteria, and next safe action;
- repository and commit, build/artifact, module, analyzer, schema, and configuration versions as applicable;
- commands or scenarios run, input boundaries, outputs, observed result, and remaining unknowns;
- elapsed active time, dependency wait time, and rework count/reason.

Measure latency as elapsed time from a leaf becoming ready to accepted evidence, wait as time blocked on a named
dependency or authority, and rework as a repeated completed step caused by a changed requirement, failed
acceptance criterion, or invalid evidence. Use these measurements to remove a demonstrated bottleneck, not to
rank people or impose issue-volume targets.

Use the local helper with an explicit run manifest. The shared contract documents its schema and bounds:

```sh
python3 tools/agent_workflow.py status
python3 tools/agent_workflow.py check --manifest .local/agent-workflow/run.json
```

`status` reads a saved checkpoint; `check` refreshes it against the owned files. A valid manifest can still
contain pending tasks. Neither output proves that product behavior works.

## Triage before creating work

Before filing a defect or follow-up, search for a parent or duplicate and assess confidence. File only when the
evidence is actionable. A filed item records its parent, priority rationale, minimal reproduction, expected and
actual behavior, user or operational impact, evidence/version references, and a retest condition. Low-confidence
observations remain in the current leaf's evidence as an unknown or follow-up hypothesis until a discriminating
check exists.

Escalate only a meaningful choice that changes scope, authority, an irreversible external action, or a contract
with no evidence-backed default. Respect existing authorization boundaries: never automatically merge, write to
Notion, add dependencies, or make external production changes.

## Evaluate and close

Use scenario-driven actual use, not checklist-only review. For changed behavior, run the smallest affected
regression set continuously and expand to an integration or browser/consumer check when the changed contract
requires it. Do not require a global heavy review for every tiny edit. Record a failure, the corrective change,
and its retest evidence before moving the leaf to review or complete.

Close a leaf only after its acceptance criteria, dependencies, evidence references, and consumer-visible outcome
are verified. The coordinator then checks parent traceability, documentation/wiki/ADR impact, unresolved risks,
and the evidence needed to resume later work.

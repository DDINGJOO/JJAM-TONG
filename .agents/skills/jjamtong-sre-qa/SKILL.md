---
name: jjamtong-sre-qa
description: Evaluate JJAM-TONG evidence workflows for human and agent consumers across platform, SRE, DevOps, security, and infrastructure scenarios. Use when defining or validating evidence-query, operational, or UI behavior.
---

# JJAM-TONG SRE and evidence QA

Validate an evidence workflow as real investigation work for two distinct consumers: a human operator and an
agent. Read the shared runtime contract at
[`docs/engineering/AGENT-ORCHESTRATION.md`](../../../docs/engineering/AGENT-ORCHESTRATION.md)
before planning evaluation. Preserve its version, authorization, and evidence rules rather than replacing them.

## Model both consumers

The human path is progressive: show the selected API and relevant business flow first. Preserve collected
`getId()` accessors, constructors and private methods in the evidence; simplify their presentation with explicit
filters or collapsed groups and provide search, all-items and expand paths to recover them. Java `private` is
a language visibility property, separate from consumer authorization. A visual filter must not change access
permissions or erase the original relationships. Verify normal, empty, error, partial
collection, and conflicting-evidence states in the actual interface when a UI is in scope.

The agent path is complete and retrievable within authorization: return raw evidence references and records needed
to audit the conclusion, together with version/source/time, coverage limits, and query/resource budgets. Preserve
these distinct outcomes:

- `unknown`: the system cannot determine the fact from the available evidence;
- `hidden-by-view`: evidence exists and a display filter or collapsed group hides it;
- `authorization-restricted`: the consumer is not authorized to retrieve that scope;
- `missing`: the requested evidence record was not collected or cannot be found.
- `truncated`: a stated query or collection budget limited the returned records.

Do not collapse these states into an empty result, and do not expose source bodies, secrets, personal data, or real
security events merely to make the agent response complete.

## Drive QA with actual investigation scenarios

Write each scenario as a user question, persona, authorized inputs, version/time boundary, expected conclusion,
expected evidence and limitations, budget, and observable acceptance signal. Exercise at least the relevant
persona(s) among platform engineer, SRE, DevOps engineer, security engineer, and infrastructure engineer. Useful
scenario shapes include deployment regression investigation, partial trace collection, mismatched build evidence,
authorization-limited security correlation, and shared or moved infrastructure resource mapping.

For every scenario, verify that the human can navigate to and understand the conclusion and that the agent can
retrieve the complete authorized evidence without guessing. A request or API response alone does not complete UI
QA; use the available browser interaction path for human workflows. Use synthetic data in public artifacts.

## Regress proportionally and triage findings

On each behavior change, continuously run the smallest affected scenario and contract regression, then add
cross-consumer, integration, load, or browser checks only when the changed boundary needs them. Avoid quotas and
global heavyweight review for a trivial isolated edit. Capture repository/commit, build or artifact, module,
analyzer, schema, configuration, scenario input, observed output, and test-tool versions so the result is
reproducible.

Before filing an issue, deduplicate and confidence-triage the observation. An actionable issue includes parent,
priority rationale, reproduction, expected versus actual behavior, impact, evidence/version links, and a retest
condition. Keep weak signals as explicitly labeled hypotheses or unknowns rather than creating issue spam.

Escalate only choices that materially change consumer authorization, acceptance criteria, product scope, or an
irreversible action. Do not automatically merge, write to Notion, add dependencies, or perform external changes.

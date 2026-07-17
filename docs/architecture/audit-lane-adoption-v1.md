---
doc_type: architecture_decision
status: implemented
task: BUREAU-LENSKIT-AUDIT-LANES-001
---

# Evidence-oriented audit lanes: adoption decision and rollout plan

## Purpose

This decision adopts the useful part of large specialist-lens audit systems without
turning Lenskit into an agent runner or review authority. Lenskit plans a small,
deterministic set of audit lanes from a concrete change surface. External operators
may later execute those lanes in an isolated environment and must return evidence-bound
results through separate contracts.

## Dialectic

### Thesis

Narrow specialist perspectives reduce attention dilution. Concurrency, storage,
authority, deployment, UI, performance and failure semantics should not compete in a
single broad prompt.

### Antithesis

Hundreds of autonomous agent invocations amplify cost, correlated blind spots, prompt
injection and false positives. Repeated self-declared completion is not evidence of
review completeness.

### Decision

Adopt bounded **audit lanes**, not a mass agent runner:

1. Plan at most eight lanes deterministically from changed paths and an optional review
   question.
2. Give concrete path signals more weight than natural-language hints.
3. Require each lane to state the evidence it needs and the checks it merely suggests.
4. Keep the output `navigation_index` / `diagnostic`; it cannot establish a defect,
   correctness, severity or completeness.
5. Do not execute agents, repository commands, issue creation, patches or merges in
   Lenskit core.
6. Measure usefulness against known findings before any default promotion.

## Phases

A phase is a bounded delivery step with its own acceptance gate.

### Phase 1 — deterministic planning contract — implemented in this change

- `plan_audit_lanes()` with a fixed, versioned lane catalog.
- Safe repository-path validation and deterministic tie-breaking.
- Bounded output with explicit negative semantics.
- Draft-07 JSON Schema and unit coverage.

Acceptance gate: stable output, schema-valid examples, no agent or write surface.

### Phase 2 — evidence adapter — registered follow-up

Define a separate result contract that binds every claimed finding to resolvable Lenskit
citations, changed revision identity and the executed lane. It must distinguish
`candidate`, `verified`, `stale`, `wrong` and `unresolved` without converting an LLM
verdict into repository truth.

Acceptance gate: malformed, stale or citation-less findings fail closed.

### Phase 3 — isolated pilot runner — registered follow-up

Run only 5–8 selected lanes in an ephemeral container with read-only source, no user
credentials, local output only, fixed call/time budgets and no automatic issue creation.

Acceptance gate: sandbox evidence, bounded cost and deterministic run manifest.

### Phase 4 — measured comparison — registered follow-up

Compare baseline review against audit-lane-assisted review on closed Lenskit changes with
known true findings and known false positives.

Metrics: precision, expected-finding recall, duplicate rate, validated findings per agent
call, cost and elapsed time. Promotion requires no central category regression and no
security-boundary relaxation.

## Lane catalog v1

- concurrency and TOCTOU
- storage and migration integrity
- cache and publication coherence
- authentication and authority boundaries
- deployment and rollback contracts
- UI, touch and accessibility
- performance and scale
- tests and failure semantics

## Alternative path

A cheaper alternative is to use only the existing review-intent retrieval router and
manual review profiles. This remains valid when cost or attack surface matters more than
incremental breadth. Audit lanes are justified only when the measured pilot finds more
confirmed defects without unacceptable noise.

## Risks and controls

| Risk | Control |
| --- | --- |
| Prompt injection | No execution in Lenskit; later runner must be isolated and credential-free |
| False positives | Separate evidence adapter and independent verification |
| Cost explosion | Maximum eight planned lanes; pilot executes only 5–8 selected lanes with budgets |
| Authority drift | `navigation_index`, `diagnostic`, explicit `does_not_establish` |
| Correlated model errors | Goldset comparison and method diversity, not repeated `DONE` claims |
| Stale findings | Revision binding and freshness validation in Phase 2 |

## Non-goals

- copying external prompt inventories or implementation code
- adding an LLM dependency to Lenskit core
- claiming review completeness
- automatically filing issues or modifying repositories
- making audit lanes the default review path before measurement

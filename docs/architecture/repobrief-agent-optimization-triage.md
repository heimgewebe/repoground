# RepoBrief Agent Optimization Triage v1

## Status

This document closes Bureau task `RBAW-V1-T005` as a deduplicating triage layer.

It maps broad Agent Workbench / RepoBrief optimization axes to existing RepoBrief roadmap tasks, explicit non-goals, or future bounded tasks. It does not start a broad refactor and does not change RepoBrief authority boundaries.

## Scope

The triage covers these axes:

- Agent contracts and answer/reading compliance
- Agent Reading Pack and Agent Entry surfaces
- CLI JSON hygiene
- Graph and relation signals
- Python AST / symbol indexing
- Retrieval v2 promotion
- Doc freshness and documentation drift
- Patch Evaluation Sidecar boundary
- MCP exposure sequencing

## Decision summary

RepoBrief should optimize agent usefulness in this order:

1. **Evidence hygiene first**: finish provenance, availability, freshness, and health/status vocabulary before adding more analysis surfaces.
2. **Consumption hygiene second**: make CLI/read-access outputs predictable enough for agents without adding hidden refresh, shell, Git, PR, or patch authority.
3. **Workbench intelligence third**: add relation, graph, symbol, and retrieval improvements only as deterministic, read-only surfaces with explicit availability and non-claims.
4. **Mutable evaluation last and external**: prototype patch/test execution only in the external Patch Evaluation Sidecar, never inside RepoBrief core.

The alternative axis is important: the goal is not “more tools for agents” in general. The goal is “fewer unjustified agent assumptions per edit.” A smaller tool that reports missing evidence is better than a larger tool that sounds certain.

## Mapping matrix

| Optimization axis | Current surface | Roadmap owner | Triage decision | Boundary / non-claim |
|---|---|---|---|---|
| Agent contracts and required-reading compliance | `docs/architecture/agent-consumption-contract.md`; Required Reading Protocol; Answer Compliance; Agent Consumption Trace | Existing agent-consumption surfaces; continue through `RBV1-T006`, `RBV1-T007`, `RBV1-T008`, `RBV1-T009` when availability/CLI/export behavior touches consumption | No new broad task. Treat as already split into protocol, trace, CLI, and preflight surfaces. Future changes must be narrow contract extensions. | Passing compliance does not prove actual reading, correctness, complete context, or merge readiness. |
| Agent Reading Pack and Agent Entry surfaces | Agent Reading Pack producer, Agent Entry Manifest, bundle registration, profile-aware required-reading | `RBV1-T005` (provenance), `RBV1-T006` (availability/freshness), `RBV1-T009` (export safety/profile alignment) | Do not create “Reading Pack v3” as a broad task. Add only concrete missing fields or status projections as owners require them. | Reading Pack is navigation, not canonical truth. Agent Entry is entry metadata, not proof of context use. |
| CLI JSON hygiene | `repobrief` CLI read/create/preflight commands and contract JSON outputs | `RBV1-T007` (CLI alias), `RBV1-T008` (CLI migration docs), later bounded smoke tests under each owning command | No separate cleanup epic now. Fold command-specific JSON shape checks into the owning CLI PRs. Create a new task only if two or more commands drift in the same envelope invariant. | JSON shape stability helps automation but does not make outputs true, fresh, or sufficient. |
| Health degradation vocabulary | Health/status diagnostics and validation dependency reporting | `RBV1-T004` (verified) plus follow-up use in `RBV1-T005`, `RBV1-T006` | Treat as foundation already started; future slices must reuse explicit `pass`/`warn`/`fail`/`degraded`/`not_applicable` semantics rather than inventing local variants. | A green health check is diagnostic only. It is not forensic readiness unless a profile explicitly requires and proves that level. |
| Git provenance | Snapshot provenance fields and freshness basis | `RBV1-T005` | Next implementation dependency before freshness-sensitive Workbench features. | Missing commit/dirty/branch data must yield unknown or blocked freshness, not invented confidence. |
| Availability and freshness | Artifact availability states; stale/unknown/not-comparable freshness | `RBV1-T006` | Must land before richer Workbench outputs are promoted, otherwise graph/symbol/retrieval results will be overread. | Stale or missing evidence must not trigger automatic refresh on read paths. |
| Export safety / agent-facing profiles | Export Safety Report; profile policies | `RBV1-T009` | Keep profile-specific. Do not make every local snapshot pay public/export safety costs, but never allow agent/public profiles to hide missing export safety. | Export eligibility is not a truth or merge verdict. |
| Graph and relation signals | Relation cards, guard relation goldset, graph source roots, graph availability concepts | `RBV1-T014`, `RBV1-T015` | Sequence relation goldset before graph availability. Measure false positives before agent-facing promotion. | Static relation evidence says “possibly related,” not “tested,” “covered,” or “correct.” |
| Python AST / symbol index | Planned deterministic symbol index | `RBV1-T016` | Keep optional/read-only/opt-in. Use Python AST first; do not introduce Tree-sitter or multi-language scope in v1. | Symbol presence does not prove reachability, behavior, or complete dependency analysis. |
| Retrieval v2 | Review intent router, graph/symbol optional signals, retrieval evaluation | `RBV1-T017` | No default promotion without measured improvement against legacy retrieval and category regressions. | Retrieval ranking is a navigation aid, not evidence truth. Bad or missing hits must be visible as misses. |
| Doc freshness | Doc Freshness Registry and generated freshness report | Existing doc-freshness machinery; targeted updates owned by the specific doc/task whose claim drifts | No new broad doc-refresh task. Add registry entries only for concrete normative claims that can be bound to symbols/tests/proofs/absent text. | A freshness pass proves only that tracked claims did not contradict declared evidence. It does not prove the docs are complete. |
| MCP exposure | MCP boundary docs, read-only resources, explicit `snapshot_create` later | `RBV1-T010`, `RBV1-T011` | Resources first. Read-only tools second. Explicit snapshot creation only after access/freshness/profile safety is stable. | MCP must not smuggle shell, Git, patch, PR, or secret access through RepoBrief resources. |
| Patch Evaluation Sidecar | External artifact contract and read-only consumer; sidecar prototype deferred | `RBAW-V1-T004` after `RBAW-V1-T002`/`RBAW-V1-T003` | Keep later. Do not build sidecar before provenance/freshness and core agent evidence hygiene are settled. | Sidecar evidence is external evaluation evidence, never merge authorization. |

## Recommended execution order after this triage

1. `RBV1-T005` — harden snapshot Git provenance status.
2. `RBV1-T006` — add snapshot availability/freshness model.
3. `RBV1-T007` / `RBV1-T008` — stabilize CLI alias and migration docs using the same JSON/status vocabulary.
4. `RBV1-T009` — align export safety with profiles.
5. `RBV1-T014` / `RBV1-T015` — relation goldset, then graph availability.
6. `RBV1-T016` — Python AST symbol index v1.
7. `RBV1-T017` — retrieval v2 promotion evaluation.
8. `RBAW-V1-T004` — only then prototype external patch/test harness.

This order differs from a tool-first path. It deliberately delays the shiny Workbench pieces until stale/missing/degraded evidence has a stable vocabulary. The less glamorous foundation is the part that prevents agent overconfidence.

## Risks and benefits

Benefits:

- Reduces duplicate roadmap tasks.
- Keeps the Agent Workbench read-only and deterministic.
- Gives agents better future context without granting hidden mutation authority.
- Makes missing and stale evidence visible before advanced graph/symbol/retrieval features can be overread.

Risks:

- Deferring the Sidecar slows mutable patch-evaluation automation.
- Mapping too much to existing tasks can hide under-scoped gaps if owners do not carry the acceptance criteria forward.
- Static analysis surfaces can still be mistaken for correctness unless every output repeats authority and non-claim metadata.

Mitigation:

- Each future implementation PR should name the exact owner task and repeat the relevant non-claims.
- Any newly discovered invariant that spans more than one command or artifact should become a small registered task, not a broad refactor.
- Workbench outputs should fail closed or degrade visibly when required source roots, provenance, indexes, schemas, or freshness bases are missing.

## Explicit non-goals

This triage does not:

- implement the Patch Evaluation Sidecar,
- add AST, graph, relation, or retrieval code,
- rename the Python package or repository,
- promote semantic reranking into the deterministic core,
- add shell, Git, PR, patch, sandbox, or secret capabilities to RepoBrief,
- assert that tests are sufficient,
- assert merge readiness.

## Acceptance mapping

- `rbaw-v1-t005-deduped-map`: satisfied by the mapping matrix above. Each broad axis is mapped to an existing roadmap owner, deferred sidecar owner, or explicit non-goal.
- `rbaw-v1-t005-no-broad-refactor`: satisfied because this slice only adds a triage document and cross-reference. It does not alter runtime, CLI, contracts, schemas, or generated artifacts.

## Does not establish

This document does not establish:

- runtime correctness,
- test sufficiency,
- review completeness,
- merge readiness,
- security correctness,
- roadmap completeness,
- that future task implementations will preserve these boundaries without review.

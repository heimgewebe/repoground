# RepoGround Agent Utility T020 proof

Task: `REPOGROUND-AGENT-UTILITY-V1-T020`

Base commit: `be022b1f40f9955f17001d426a655d4f427531c0`

## Scope

T020 hardens the existing static Python call-graph surface without pretending that a static graph is complete runtime truth.

The current base already resolves the representative direct, imported-alias and module-alias Python cases. T020 therefore leaves the call-graph producer unchanged and hardens the consumer boundary instead:

- one shared coverage/confidence projection reports resolved/candidate/ambiguous/unresolved ratios and unresolved reasons;
- task-profile thresholds expose an explicit completeness caveat when observed static resolution is insufficient for that use;
- skipped Python files force profile confidence to `insufficient` even when every observed edge resolved;
- Config/Schema/Workflow evidence is modeled in the system-relation overlay, not as Python `calls` edges;
- schema/config contract relations are provenance-bound S1 declarations and fail closed when the target endpoint kind is wrong.

## Fixed goldset

`docs/retrieval/repoground_agent_utility_t020_goldset.v1.json` binds T020 to the existing Python call-graph goldset and to fixed structural-relation fixtures.

Required Python cases include:

- direct local helper;
- imported alias;
- module alias / qualified call;
- dynamic higher-order call;
- ambiguous conditional definition.

The machine evaluation of `python_call_graph_goldset.v1.json` on this base reported:

- cases: 13/13 passing;
- S1 precision: `1.0`;
- target recall: `1.0`;
- false positives: `0`;
- false negatives: `0`;
- true positives: `9`;
- unresolved records: `4` (`0.307692` share);
- skipped Python files: `0`.

The T020 structural fixture additionally proves independent `declares_config`, `references_config`, and `validates_schema` relation families. Config relations have `contract_identity.kind=config`, target `config_contract`, S1 declared evidence and never become `calls` or `constructs` relations.

## Coverage and confidence boundary

`call_graph_coverage_confidence()` is deliberately a coverage proxy, not statistical confidence. It exposes:

- `resolved_ratio` and per-status ratios;
- unresolved counts by status and reason;
- `skipped_files_count`;
- task-profile assessments for basic questions, review, change impact, relevant-test search and grounding;
- explicit caveats when a threshold is not met.

Compatibility is retained for existing navigation consumers (`scope=observed_call_edges`; all observed edges resolved may still report `completeness=complete`). The stronger `model_scope=observed_static_python_call_edges` and nonclaims make clear what that word does not mean.

The projection explicitly does **not** establish complete call graphs, caller/callee completeness, irrelevance of unresolved edges, runtime reachability or behaviour, statistical confidence, test sufficiency, change impact outside the model, review completeness or merge readiness.

## Scale regression

The existing fixed call-navigation benchmark was run with 50,000 synthetic calls and byte-equivalence enabled.

Observed on the Heim-PC (CPython 3.10.12, x86_64, 32 logical CPUs):

- status: `PASS`;
- linear vs indexed response byte-equivalence: `true`;
- process-local index build: `308.438 ms`;
- indexed warm query-batch median: `53.131 ms`;
- linear warm query-batch median: `811.245 ms`;
- warm speedup: `15.2688x`;
- persisted-sidecar warm median: `55.895 ms`.

This benchmark does not establish performance on every machine/repository, runtime call-graph completeness or dynamic-dispatch coverage.

## Regression checks

Final focused regression selection before commit:

- `211 passed, 10 skipped` across T020 goldset, system relations, impact context, call navigation, Python call graph and Python call-graph goldset;
- targeted Ruff checks: pass;
- `git diff --check`: pass.

A repository-wide local pytest run progressed without reported failures through 44% but was cancelled after an unrelated long-running test stopped progress for several minutes. It is therefore **not** counted as passing evidence; pull-request CI remains the repository-wide authority.

## Remaining boundary

`system_relation_overlay` consumes already-collected, digest-bound relation evidence. It does not itself scan repositories for Config/Workflow relations. T020 establishes the typed, provenance-bound truth model and validation boundary; automatic collection is a separate producer concern and must not be inferred from this proof.

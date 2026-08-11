# RepoGround Agent Utility V1 — T022 Proof Contract

Task: `REPOGROUND-AGENT-UTILITY-V1-T022`

## What this change establishes

T022 adds a bounded, offline producer for selected repository-level structural
relations and a fail-closed consumer path into Agent Impact Context.

The producer supports only these static sources:

- root `pyproject.toml` first-level `[tool.NAME]` tables → `declares_config`;
- tracked `*.schema.json` files with exactly one literal top-level `$id` →
  `declares_schema`;
- direct job-level `.github/workflows/*.yml|*.yaml` static local
  `uses: ./.github/workflows/...` references whose target exists in the same Git
  commit → `references_workflow`.

Workflow relations come from parsed YAML mapping structure rather than raw-line
matching, so text inside block scalars such as `run: |` cannot become a
relation. Duplicate top-level schema `$id` keys are ambiguous and therefore
omitted. Dynamic, generated, ambiguous, missing-target, invalid, oversized,
sensitive, non-regular and unsupported cases are likewise omitted or reported
with a reason. They are not inferred.

## Revision binding

`collect_system_relation_evidence()` accepts an exact repository commit and
verifies that it names a local Git commit object. Candidate metadata and file
bytes are then read from the Git object database for that commit. The mutable
working tree is not a producer input.

The Git tree index is read with a hard streaming byte cap: the producer
terminates the child process as soon as the configured candidate-index budget
would be exceeded instead of buffering unbounded output first. Blob bytes that
were actually read count against the total byte budget even when decoding or
later parsing fails.

The result includes an explicit `revision_binding` receipt. The context adapter
rejects the evidence unless all of these are coherent:

1. expected repository commit;
2. producer repository commit;
3. producer `revision_binding` with `mode=git_commit_object` and `verified=true`;
4. SHA-256 of the raw evidence object;
5. a fresh normalization of that evidence through `system_relation_overlay`.

A mismatch produces a visible `blocked` or `missing` structural-evidence state
and projects zero structural records.

## Relation separation and shared record bound

System relations remain a separate structure lane. They do not become Python
`calls` or `constructs` edges. Agent Impact Context exposes them under optional
`structural_relations`; existing relation behavior remains unchanged when the
new evidence input is absent.

Producer, overlay normalizer and context consumer share the same hard maximum of
4096 evidence records. The producer truncates deterministically at that bound
and reports `record_budget_exhausted`; externally supplied evidence above the
same bound is rejected rather than partly trusted.

`references_workflow` is deliberately S0/reference evidence. Config and schema
declarations are S1/declaration evidence. This keeps the S1 lane limited to
facts that are explicitly declared in static source structure.

## Goldset gate

The fixed goldset is:

`docs/retrieval/repoground_agent_utility_t022_goldset.v1.json`

It contains positive, ambiguous and true-null cases and is evaluated by:

`merger/repoground/tests/test_agent_utility_t022_goldset.py`

The checked gate requires:

- precision: `1.0`;
- recall: `1.0`;
- source-range accuracy: `1.0`;
- S1 false positives: `0`;
- exact omission reasons for ambiguous cases.

Each synthetic case is materialized as a real Git repository and evaluated
against its exact committed fixture HEAD.

## Regression and safety checks

Focused tests cover:

- commit-object reads remaining stable when the working tree is dirty;
- malformed and missing commit rejection;
- deterministic output;
- bounded file, byte, candidate-index and record budgets;
- candidate-index termination while Git output is being read;
- invalid UTF-8 blobs still consuming the bytes actually read;
- dynamic and missing workflow targets;
- YAML block-scalar text not masquerading as a `uses` mapping key;
- duplicate, nested and missing top-level schema `$id` handling;
- shared producer/consumer record-limit compatibility;
- optional Python 3.10 TOML-parser absence failing closed;
- raw-evidence digest tampering;
- producer revision-binding tampering;
- overlay tampering;
- Agent Impact Context commit mismatch without false target activation;
- schema validation of the extended Agent Impact Context.

The existing T020 overlay and Agent Impact Context suites are run together with
the new T022 tests to guard backward compatibility.

## Revision-bound scale gate

The reproducible benchmark is:

`merger/repoground/scripts/bench_system_relation_producer.py`

It must be run against the exact candidate Git HEAD, for example:

```text
python -m merger.repoground.scripts.bench_system_relation_producer \
  --repo . \
  --commit "$(git rev-parse HEAD)" \
  --identity heimgewebe/repoground \
  --repetitions 3
```

The default practical gates are:

- p95 producer runtime ≤ 5000 ms;
- Python allocation peak ≤ 64 MiB;
- canonical result artifact ≤ 2 MiB;
- one deterministic result digest across repetitions.

The benchmark reports candidate count, scanned bytes, candidate-index bytes,
record count, omission count, relation kinds, runtime, memory and artifact size.
The exact final-HEAD benchmark receipt belongs in the PR/closeout evidence so it
can be bound to the immutable reviewed revision without creating a
self-referential commit.

## Explicit non-claims

This change does **not** establish:

- runtime config effect;
- schema conformance or validation execution;
- workflow execution or workflow validity;
- complete repository relation coverage;
- runtime behavior or correctness;
- merge readiness by itself;
- agent-utility benefit sufficient for default activation.

The producer is local and network-disabled by construction, does not read
secret-file contents, and reads only supported tracked candidates from Git
objects. Broader or default agent-context activation remains gated on a separate
paired agent-utility benefit proof.

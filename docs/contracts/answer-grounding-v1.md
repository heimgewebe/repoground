# RepoBrief Answer Grounding v1

Status: contract_design
Initiative: `REPOBRIEF-FRONTDOOR-GROUNDING-V1`
Task: `RBGV-V1-T001`

## Purpose

Answer Grounding v1 defines the contract boundary between an answer that declares its
RepoBrief evidence and a later deterministic verifier that checks the declared evidence.

The contract has two JSON surfaces:

- `answer-grounding-declaration.v1.schema.json`: what an answer declares it used;
- `answer-grounding-verdict.v1.schema.json`: what a deterministic verifier can report
  after checking that declaration against existing snapshot artifacts.

## Boundary

This is not a truth detector. A grounding `pass` means only that the checked citation,
range and required-reading mechanics satisfied the v1 grounding contract in the checked
scope.

It does not establish:

- actual reading by an agent;
- answer correctness;
- repository understanding;
- complete context use;
- claim truth;
- test sufficiency;
- regression absence;
- runtime behavior;
- forensic readiness;
- merge readiness;
- security correctness.

## Declaration surface

A declaration identifies:

- the answer and its hashes;
- the snapshot stem and manifest path;
- the task profile;
- used citation IDs;
- used ranges;
- optional strong-claim markers;
- declared non-claims and freshness caveats.

The declaration remains a declaration. It does not prove that the model actually read the
cited material or used all relevant context.

## Verdict surface

A verdict identifies:

- the checked declaration;
- the checked snapshot;
- citation checks;
- range checks;
- required-reading checks;
- diagnostics;
- freshness and availability caveats;
- mandatory non-claims.

Allowed top-level statuses are:

| Status | Meaning | Non-claim |
| --- | --- | --- |
| `pass` | Declared grounding resolved in the checked scope. | Not answer truth. |
| `warn` | Grounding resolved, but caveats or recommended gaps remain. | Not completeness. |
| `fail` | Required evidence, citation, range or non-claim check failed. | Not a semantic falsehood verdict. |
| `degraded` | The verifier could not complete all required checks. | Not safe to smooth into pass. |
| `not_applicable` | The task/profile does not require grounding verification. | Not approval. |

## Example outcomes

### Pass

A pass verdict may be emitted when all declared required citations and ranges resolve
against the selected snapshot and required-reading checks are satisfied. It still carries
all mandatory `does_not_establish` values.

### Warn

A warn verdict may be emitted when required grounding resolves but recommended artifacts
are missing, freshness is stale or non-blocking availability caveats exist.

### Fail

A fail verdict may be emitted when a required citation is unknown, a range cannot resolve,
a range hash drifts, a required artifact is missing, or mandatory non-claims are absent.

### Degraded

A degraded verdict may be emitted when the verifier cannot complete required checks because
a dependency, schema validator or required artifact loader is unavailable. Degraded is
visible; it is not normalized to warning or pass.

## Relationship to existing contracts

- `answer-compliance.v1.schema.json` records what an answer declares about artifact use.
- `agent-consumption-trace.v1.schema.json` compares required-reading expectations with
  answer-compliance declarations.
- Answer Grounding v1 narrows the next step: citation/range mechanics and grounding caveats.
- It does not replace Required Reading, Agent Consumption Trace, Citation Map, Range-Ref or
  the read-only access boundary.

## Implementation posture

This task defines contracts only. A later task implements the minimal read-only verifier.

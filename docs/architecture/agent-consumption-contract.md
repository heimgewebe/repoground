# Agent Consumption Contract

## Status

Required Reading Protocol Core implemented.
Answer Compliance Contract v1 implemented.
Agent Consumption Trace v1 implemented.
The Agent Entry Manifest core is implemented with a contract, producer and
focused tests.
A dedicated CLI command, automatic bundle emission, bundle-manifest
registration and stable consumer integration are not yet implemented.
Export Safety Report, Lens Cards, and Relation Cards exist as scoped contract/core surfaces. Agent Reading Pack v2 card indexes and any promoted Retrieval v2 default remain unimplemented.

---

## Required Reading Protocol

### Purpose

The Required Reading Protocol formalises the `REQUIRED_READING_BY_TASK` matrix from the Agent Reading Pack as a machine-readable, deterministic contract.

An agent or test can use it to check — before answering — whether the artifacts required for a given task are present in the available bundle context.

### Files

| File | Role |
|------|------|
| `merger/lenskit/contracts/required-reading-protocol.v1.schema.json` | JSON Schema (Draft-07) for the protocol contract |
| `merger/lenskit/core/required_reading.py` | Resolver: `default_required_reading_protocol()`, `resolve_required_reading()` |
| `merger/lenskit/tests/test_required_reading_protocol.py` | Schema validation and resolver tests |

---

### Relationship to Agent Reading Pack

The Agent Reading Pack (`agent_reading_pack.py`) renders `REQUIRED_READING_BY_TASK` as a Markdown table inside the pack.  The Required Reading Protocol is a direct translation of that table into a JSON contract and a Python resolver.

- The Agent Reading Pack remains the **navigation layer** — it is what an agent reads to orient itself.
- The Required Reading Protocol is the **protocol/navigation layer** — it is what a tool or test uses to check compliance programmatically.
- Neither establishes content truth.

### Relationship to canonical_md

`canonical_md` is the sole content truth.  The Required Reading Protocol does not change this.

The protocol tells an agent *which artifacts to read* for a task; it does not authorise any artifact to replace `canonical_md` as the source of content claims.

---

### Task Profiles

| task_profile | required | recommended |
|---|---|---|
| `basic_repo_question` | `agent_reading_pack`, `canonical_md` | `citation_map_jsonl` |
| `pr_review` | `agent_reading_pack`, `canonical_md`, `citation_map_jsonl`, `post_emit_health` | `bundle_surface_validation`, `claim_evidence_map_json` |
| `roadmap_status_claim` | `agent_reading_pack`, `canonical_md`, `claim_evidence_map_json` | `citation_map_jsonl` |
| `artifact_surface_review` | `bundle_manifest`, `bundle_surface_validation`, `canonical_md`, `post_emit_health` | `output_health` |
| `retrieval_quality_review` | `canonical_md`, `chunk_index_jsonl`, `retrieval_eval_json`, `sqlite_index` | `docs/retrieval/*` |

Note: `post_emit_health`, `bundle_surface_validation`, `bundle_manifest`, and `docs/retrieval/*` are protocol/surface aliases — they are not `ArtifactRole` enum values and the enum is not extended for PR 1.

For basic_repo_question, citation_required is false by default; citation_map_jsonl is recommended when the answer makes specific cited claims.

---

### Resolver Status Values

`resolve_required_reading(protocol, available_roles, task_profile)` returns one of:

| status | meaning |
|--------|---------|
| `pass` | All required and all recommended roles present |
| `warn` | All required roles present; at least one recommended role missing |
| `fail` | At least one required role missing |
| `not_applicable` | task_profile not found in protocol |

Resolver results preserve `citation_required`, `answer_checklist_required`, and `does_not_establish`.

### Example: pr_review

```python
from merger.lenskit.core.required_reading import (
    default_required_reading_protocol,
    resolve_required_reading,
)

protocol = default_required_reading_protocol()
result = resolve_required_reading(
    protocol,
    available_roles={"agent_reading_pack", "canonical_md", "citation_map_jsonl", "post_emit_health"},
    task_profile="pr_review",
)
# result["status"] == "warn"
# result["missing_recommended"] == ["bundle_surface_validation", "claim_evidence_map_json"]
```

---

### does_not_establish

Each task profile carries a `does_not_establish` list.  These are invariants that are **not** established even when all required roles are present:

- `repo_understood`
- `answer_safe_without_citations`
- `claims_true`
- `all_relevant_context_used`
- `forensic_ready`

The protocol-level `does_not_establish` field repeats these for the contract as a whole.

does_not_establish must include the five protocol invariants on both protocol and task-profile level.

---

### Invariants

- `canonical_md` is the sole content truth.
- The Required Reading Protocol is protocol/navigation, not truth.
- Satisfying a profile does not mean claims are correct.
- No LLMs, no embeddings, no review judgements, no patch automation.
- No new Primary Lens IDs introduced.

---

## Answer Compliance

The Answer Compliance Contract records what an answer declares it used.
It is a declaration layer only. It does not prove actual reading, answer correctness, complete context use, runtime behavior, test sufficiency, regression absence, forensic readiness, or repo understanding.

The Agent Consumption Trace validator compares Required Reading Protocol expectations against Answer Compliance declarations (see below).

---

## Agent Consumption CLI

The `agent-consumption` CLI exposes the existing Required Reading Protocol resolver
and Agent Consumption Trace validator.

Commands:

- `agent-consumption required`
- `agent-consumption validate-trace`

The CLI is a thin execution layer. It does not create an Agent Entry Manifest,
mutate Bundle Manifest, update Output Health/Post-Emit Health, enforce Export
Safety, or prove actual reading.

## Agent Consumption Trace

The Agent Consumption Trace compares Required Reading expectations against Answer Compliance declarations.
It may report:

- pass: required artifacts are declared and no warning/failure condition was found.
- warn: required artifacts are declared, but recommended artifacts are missing/unread or unknown declared artifacts were observed.
- fail: required artifacts are missing/unread, task profiles mismatch, or required negative semantics are missing or invalid.
- not_applicable: no applicable task profile could be resolved and no failing contract invariant was detected.

The trace is a declaration-comparison artifact only. It does not prove actual reading, answer correctness, complete context use, runtime behavior, test sufficiency, regression absence, forensic readiness, or repo understanding.

### Files

| File | Role |
|------|------|
| `merger/lenskit/contracts/agent-consumption-trace.v1.schema.json` | JSON Schema (Draft-07) for the trace contract |
| `merger/lenskit/core/agent_consumption_validate.py` | Pure validator: `validate_agent_consumption(required_reading_result, answer_compliance, *, available_roles=None)` |
| `merger/lenskit/tests/test_agent_consumption_trace.py` | Schema validation and validator behaviour tests |

### Scope

Implemented:
- Agent Consumption Trace Contract
- Core validator
- strict-mode validation
- deterministic exit-code policy
- CLI commands for Required Reading resolution and trace validation
- focused contract, validator and CLI tests

Deferred:
- automatic bundle emission
- mutation of the bundle manifest
- Output Health or Post-Emit Health integration
- export-safety wiring
- mandatory adoption by external agent wrappers

The validator performs no I/O, holds no global state, and reuses the existing Required Reading resolution rather than re-deriving it.

`available_roles` is supplied explicitly. When omitted, only required and recommended roles are treated as known, and any other declared role is conservatively warned. The trace does not infer roles from the Bundle Manifest. Bundle-aware CLI integration or Agent Entry Manifest consumption remains deferred, and the `ArtifactRole` enum is not extended here.

# Agent Consumption Contract

## Status

Required Reading Protocol Core implemented.
Answer Compliance Contract v1 implemented.
Agent Consumption Trace v1 implemented.
Agent Tool-Read Receipts and Consumption Evidence Comparison v1 implemented
(optional, declaration-vs-observation layer; no runtime interception).
The Agent Entry Manifest core is implemented with a contract, producer and
focused tests.
The dedicated Agent Consumption CLI is implemented. Automatic bundle emission,
bundle-manifest registration and stable external consumer adoption are not yet
implemented.
Export Safety Report, Lens Cards, and Relation Cards exist as scoped contract/core surfaces. Agent Reading Pack v2 card indexes and any promoted Retrieval v2 default remain unimplemented.

---

## Required Reading Protocol

### Purpose

The Required Reading Protocol formalises the `REQUIRED_READING_BY_TASK` matrix from the Agent Reading Pack as a machine-readable, deterministic contract.

An agent or test can use it to check — before answering — whether the artifacts required for a given task are present in the available bundle context.

### Files

| File | Role |
|------|------|
| `merger/repoground/contracts/required-reading-protocol.v1.schema.json` | JSON Schema (Draft-07) for the protocol contract |
| `merger/repoground/core/required_reading.py` | Resolver: `default_required_reading_protocol()`, `resolve_required_reading()` |
| `merger/repoground/tests/test_required_reading_protocol.py` | Schema validation and resolver tests |

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
from merger.repoground.core.required_reading import (
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
- `agent-consumption preflight`
- `agent-consumption validate-trace`
- `agent-consumption compare-evidence`

`preflight` resolves required reading, can derive available roles from a Bundle Manifest, emits an Answer Compliance template, and optionally validates a supplied Answer Compliance file into an Agent Consumption Trace.

`compare-evidence` compares Answer Compliance declarations with trusted
tool-read receipts for one `task_id` and `repo_commit`. It reports
`declared-only`, `observed-only`, `declared-and-observed`, or `unavailable`
per artifact role. It does not prove semantic reading, relevance, correctness,
or truth.

The CLI is a thin execution layer. It does not create an Agent Entry Manifest,
mutate Bundle Manifest, update Output Health/Post-Emit Health, enforce Export
Safety, intercept runtime tool calls, require wrapper adoption, or prove actual
semantic reading.

## Agent Consumption Trace

The Agent Consumption Trace compares Required Reading expectations against Answer Compliance declarations.
It may report:

- pass: required artifacts are declared and no warning/failure condition was found.
- warn: required artifacts are declared, but recommended artifacts are missing/unread or unknown declared artifacts were observed.
- fail: required artifacts are missing/unread, task profiles mismatch, input fields cannot be safely normalised, declarations contradict themselves, unread roles are assigned to the wrong expectation class, or required negative semantics are missing or invalid.
- not_applicable: no applicable task profile could be resolved and no failing input or declaration invariant was detected.

The trace is a declaration-comparison artifact only. It does not prove actual reading, answer correctness, complete context use, runtime behavior, test sufficiency, regression absence, forensic readiness, or repo understanding.

### Consistency boundary

The validator is not a replacement for full JSON Schema validation of Required Reading or Answer Compliance. It does enforce the minimum boundary needed for a deterministic, schema-shaped trace:

- missing or malformed comparison fields (`task_profile`, Required Reading `status`, `required`, `recommended`, and Answer Compliance `declared_artifacts`) become `invalid_input_field` failures instead of being silently treated as empty;
- a scalar string remains a compatibility shorthand for one role, while other scalar role values and mappings fail closed instead of being coerced;
- one artifact cannot consistently be declared both read and unread;
- one artifact cannot consistently be classified as both required-unread and recommended-unread;
- unread declarations must match the required or recommended class of the resolved profile;
- citation, range and epistemic-gap objects are deep-copied so later consumer mutation cannot rewrite the original declaration.

These checks establish formal self-consistency only. They do not turn declarations into observed evidence.

### Files

| File | Role |
|------|------|
| `merger/repoground/contracts/agent-consumption-trace.v1.schema.json` | JSON Schema (Draft-07) for the trace contract |
| `merger/repoground/core/agent_consumption_validate.py` | Pure validator: `validate_agent_consumption(required_reading_result, answer_compliance, *, available_roles=None)` |
| `merger/repoground/tests/test_agent_consumption_trace.py` | Base schema validation and validator behaviour tests |
| `merger/repoground/tests/test_agent_consumption_consistency.py` | Contradiction, malformed-input and mutable-identity regression tests |

### Scope

Implemented:
- Agent Consumption Trace Contract
- Core validator split into bounded comparison helpers
- fail-closed declaration consistency checks
- schema-shaped malformed-input handling
- deep-copy isolation for pass-through declaration objects
- strict-mode validation
- deterministic exit-code policy
- CLI commands for Required Reading resolution, preflight, and trace validation
- focused contract, validator and CLI tests

Deferred:
- automatic bundle emission
- mutation of the bundle manifest
- Output Health or Post-Emit Health integration
- export-safety wiring
- mandatory adoption by external agent wrappers
- runtime interception of arbitrary tool calls
- cryptographic signing of receipts beyond deterministic SHA-256 binding

The validator performs no I/O, holds no global state, and reuses the existing Required Reading resolution rather than re-deriving it.

`available_roles` is supplied explicitly. When omitted, only required and recommended roles are treated as known, and any other declared role is conservatively warned. The trace does not infer roles from the Bundle Manifest. The `preflight` CLI can derive roles from a Bundle Manifest as operator convenience, but it still does not mutate or certify the bundle. Agent Entry Manifest consumption remains deferred, and the `ArtifactRole` enum is not extended here.

---

## Tool-Read Receipts and Consumption Evidence

### Purpose

The evidence layer is a **separate, optional** comparison surface that sits
beside the declaration-only Agent Consumption Trace:

1. Answer Compliance still declares what an answer claims it used.
2. A **trusted wrapper or tool gateway** may mint a tool-read receipt when it
   observes access to one artifact identity.
3. `compare_agent_consumption_evidence` compares declarations and receipts for
   **exactly the same** `task_id`, `repo_commit`, `artifact_role`, and immutable
   artifact identity (`path` + `sha256` + `bytes`).

The layer is deliberately data-sparing:

- no artifact body/content is stored on the receipt;
- secrets and content-bearing fields fail closed;
- metadata size and character shapes are strictly bounded;
- SHA-256 binding uses deterministic JSON serialization (`sort_keys`, compact
  separators, UTF-8).

### Trust boundary

Only allowlisted issuers may produce observed evidence:

| issuer.kind | issuer.id |
|-------------|-----------|
| `trusted_wrapper` | `repoground.agent_consumption.tool_read_wrapper` |
| `tool_gateway` | `repoground.agent_consumption.tool_gateway` |

Answer text, free-form self-declarations, and unknown issuer ids never mint
observed evidence. The comparison rejects untrusted and invalid receipts
without elevating any role to `declared-and-observed`.

### Comparison states

| state | meaning |
|-------|---------|
| `declared-only` | Role is declared in Answer Compliance; no accepted trusted receipt |
| `observed-only` | Accepted trusted receipt exists; role was not declared |
| `declared-and-observed` | Declaration and accepted trusted receipt for the same role (and matching identity when provided) |
| `unavailable` | Role is expected but has neither declaration nor accepted observation |

Rejected receipts are diagnosed and listed; they never raise the evidence state.

### Rejection diagnostics that never elevate evidence

| reason | meaning |
|--------|---------|
| `missing` | No usable declaration/observation material for the comparison set |
| `stale` | Receipt age exceeds `max_age_seconds` relative to `as_of` |
| `task_mismatch` | Receipt `task_id` differs from the bound task |
| `commit_mismatch` | Receipt `repo_commit` differs from the bound commit |
| `replay` | Duplicate `access_event_id` |
| `artifact_mismatch` | Role identity conflicts with declared or previously accepted identity |
| `untrusted_issuer` | Issuer not on the allowlist |
| `privacy_violation` | Content/secret-bearing fields present |
| `binding_mismatch` | `binding_sha256` / `receipt_sha256` does not recompute |
| `invalid_receipt` | Structural or shape failure |

### Retention, redaction, deletion

Every receipt and evidence report carries:

```text
policy = ephemeral_comparison_input
content_retained = false
redaction = metadata_only
deletion = safe_at_any_time
```

Operators may discard receipts at any time. Deletion never mutates repository
content; absence becomes `missing` / `unavailable` rather than a stronger claim.

### Files

| File | Role |
|------|------|
| `merger/repoground/contracts/agent-tool-read-receipt.v1.schema.json` | Receipt JSON Schema |
| `merger/repoground/contracts/agent-consumption-evidence.v1.schema.json` | Evidence comparison JSON Schema |
| `merger/repoground/core/agent_consumption_receipts.py` | Mint/validate + `TrustedToolReadWrapper` |
| `merger/repoground/core/agent_consumption_evidence.py` | Pure comparison: `compare_agent_consumption_evidence(...)` |
| `merger/repoground/tests/test_agent_consumption_evidence.py` | Schema, determinism, negative, replay, freshness, mismatch, E2E tests |
| `docs/contracts/agent-consumption-evidence-v1.md` | Contract surface notes |
| `docs/proofs/agent-consumption-evidence-v1-proof.md` | Implementation proof |

### Non-claims

Evidence comparison does **not** establish:

- semantic reading or understanding;
- relevance of observed files to an answer;
- answer correctness or claim truth;
- complete context use;
- test sufficiency, regression absence, or runtime behavior;
- forensic readiness;
- runtime interception or mandatory wrapper adoption;
- that every wrapper emits trusted receipts.

The existing Trace `does_not_establish` set remains intact for declaration
comparison. Evidence comparison includes those nine boundaries and adds
observation-specific non-claims.

# Validation Check Shape Consistency Audit

Status: implemented audit / no producer migration.

Task: `TASK-VALIDATION-DIAG-003`.

## Purpose

Three Lenskit validation producers expose a `checks` surface, but they do not
share one container shape:

- `output_health["checks"]` is a **mapping** (dict keyed by check name);
- `post_emit_health["checks"]` is a **list** of check objects;
- `bundle_surface_validation["checks"]` is a **list** of check objects.

This audit answers the core question — *why* the surfaces differ, and *what
follows for consumers, tests, and later structured error objects* — and records a
deliberate decision for this slice. It changes no producer, schema, contract, or
CLI. It adds a small regression test that pins the currently accepted shapes so
the divergence cannot drift silently.

It builds on, and does not duplicate, the vocabulary inventory in
[validation-diagnostics-schema-alignment-proof.md](validation-diagnostics-schema-alignment-proof.md),
whose "Shape differences" section first recorded this divergence and explicitly
deferred unification to `TASK-VALIDATION-DIAG-003`.

Language note: claims below are grounded in read-only inspection of the searched
paths. "Observed" means observed in producer code, schema, or a test assertion on
the audited revision. No claim of consumer completeness is made beyond the
searched paths, and no producer migration is performed in this slice.

## Scope

This audit covers the `checks` container shape of:

- `output_health["checks"]`
- `post_emit_health["checks"]`
- `bundle_surface_validation["checks"]`

Out of scope (hard non-goals for this slice): producer migration, schema
migration, contract versioning, unifying any of the three `checks` shapes,
structured `ValidationError` objects, a central `safe_load_yaml`/`safe_load_json`
loader, a global validation service, forensic-strict gating, CLI/agent-pack
rework, and any new dependency.

## Current shapes

### output_health

Shape: **mapping / dict**, keyed by check name.

Producer: `merger/lenskit/core/output_health.py` — `compute_output_health()`
builds `checks: Dict[str, Any]` and returns it under `"checks"`.

Schema: `merger/lenskit/contracts/output-health.v1.schema.json` declares
`checks` as `type: object` with `additionalProperties: true` and ~20 required
keys.

Observed properties:

- summary-style, self-test of the pre-/emit artifact chain;
- mixed scalar and object values under one mapping:
  - booleans (e.g. `manifest_present`, `canonical_md_hash_ok`, `sqlite_present`);
  - counters (e.g. `chunk_count`, `chunk_invalid_json_line_count`,
    `fts_empty_row_count`);
  - nested diagnostic records (e.g. `range_ref_resolution`,
    `sample_query_content_hit`, `agent_pack_present`, `excluded_noise`,
    `noise_hygiene`);
- `range_ref_resolution` carries the check-local validation metadata at
  `checks["range_ref_resolution"]["validation"]` with `{mode, engine, reason}`;
- it reads as a *pre-/emit self-test summary object*, not an ordered check log.

### post_emit_health

Shape: **list of check objects**.

Producer: `merger/lenskit/core/post_emit_health.py` — `compute_post_emit_health()`
appends `_check(name, status, detail=None, validation=None)` entries to
`checks: List[Dict[str, Any]]`.

Schema: `merger/lenskit/contracts/post-emit-health.v1.schema.json` declares
`checks` as `type: array`; each item requires `name` and `status`, with optional
`detail` and optional `validation`.

Observed properties:

- each check has `name` and `status`;
- `detail` is optional;
- `validation` is optional; schema-bound checks (e.g. `manifest_schema_valid`,
  `range_ref_resolution`, `claim_evidence_map_schema_valid`) carry
  `validation.{mode, engine, reason}`;
- it reads as an *ordered, appended check log* of the final emitted surface.

### bundle_surface_validation

Shape: **list of check objects**.

Producer: `merger/lenskit/core/bundle_surface_validate.py` —
`validate_bundle_surface()` appends `_surface_check(...)` entries to
`checks: List[Check]`.

Schema: `merger/lenskit/contracts/bundle-surface-validation.v1.schema.json`
declares `checks` as `type: array`; each item requires `name` and `status`, with
optional `detail` and optional `validation` (its `engine` is an unconstrained
string).

Observed properties:

- each check has `name` and `status`;
- in current code every `_surface_check` carries `validation`, with
  `mode = structural_precheck`, `engine = bundle_surface_validate`, and a
  `reason` of `surface_coherence_check` or `check_not_applicable` (the schema
  still keeps `validation` optional for backward compatibility);
- it is surface/coherence-oriented, not a claim verdict; the report's own
  `does_not_mean` lists `forensic_ready`, so a pass does not establish
  forensic-readiness.

## Consumer inventory

Paths searched (read-only). Classification: **dict-consumer** reads
`output_health["checks"]` by key; **list-consumer** iterates a PEH/BSV checks
list; **shape-agnostic** does not depend on the `checks` container shape;
**unrelated** uses a different `checks` namespace.

### Producers and schemas

| Path | Role |
|------|------|
| `merger/lenskit/core/output_health.py` | Producer (OH dict). Builds and returns `checks`; does not consume any other surface. |
| `merger/lenskit/core/post_emit_health.py` | Producer (PEH list). Also a **dict-consumer** of OH: reads a declared `output_health` sidecar's `checks` (guarded `isinstance(..., dict)`) for sqlite/noise signals. |
| `merger/lenskit/core/bundle_surface_validate.py` | Producer (BSV list). `_rollup` iterates its own checks list. |
| `merger/lenskit/contracts/output-health.v1.schema.json` | Schema: `checks` = object. |
| `merger/lenskit/contracts/post-emit-health.v1.schema.json` | Schema: `checks` = array. |
| `merger/lenskit/contracts/bundle-surface-validation.v1.schema.json` | Schema: `checks` = array. |

### Runtime consumers

| Path | Surface | Classification |
|------|---------|----------------|
| `merger/lenskit/core/merge.py` | BSV | **list-consumer**: filters surface checks by `name`/`status` to find invariant `fail`s before emission. |
| `merger/lenskit/core/agent_reading_pack.py` | OH | **dict-consumer** (guarded `isinstance(..., dict)`): reads `chunk_count`, `sqlite_row_count`, `fts_content_non_empty`, `range_ref_resolution_status`. |
| `merger/lenskit/core/context_quality.py` | OH | **dict-consumer** (guarded): projects `canonical_md_hash_ok`, `chunk_index_hash_ok`, `sqlite_row_count_matches_chunk_count`, `fts_content_non_empty`, `range_ref_resolution_status`, redaction flags. (Beyond the task's listed paths; included for honesty.) |
| `merger/lenskit/core/parity_state.py` | OH | **dict-consumer** (guarded): `checks.get(key) is True` over OH check keys. (Beyond the task's listed paths.) |
| `merger/lenskit/cli/cmd_bundle_surface.py` | BSV | **list-consumer**: human printer iterates `checks` printing `status`/`name`/`detail`. |
| `merger/lenskit/cli/cmd_bundle_health.py` | PEH | **shape-agnostic**: human printer reads top-level fields only; checks pass through `json.dumps`. |
| `scripts/rlens-post-merge-surface-smoke.sh` | OH | **dict-consumer** (guarded): reads `checks.excluded_noise` / `checks.noise_hygiene`. |

### Tests

| Path | Classification |
|------|----------------|
| `merger/lenskit/tests/test_output_health.py` | dict access (`result["checks"]["..."]`). |
| `merger/lenskit/tests/test_post_emit_health.py` | list access (`{c["name"]: c for c in report["checks"]}`). |
| `merger/lenskit/tests/test_bundle_surface_validate.py` | list access + `_assert_all_checks_have_structural_precheck`. |
| `merger/lenskit/tests/test_cli_bundle_health.py` | shape-agnostic (fixtures set `"checks": []`). |
| `merger/lenskit/tests/test_cli_bundle_surface.py` | list access (`c["name"] for c in out["checks"]`). |
| `merger/lenskit/tests/test_rlens_post_merge_surface_smoke.py` | dict access on OH `checks` via mutators. |
| `merger/lenskit/tests/test_validation_check_shapes.py` | **new** — pins all three shapes (this slice). |

### Docs

| Path | Note |
|------|------|
| `docs/proofs/validation-diagnostics-schema-alignment-proof.md` | Prior proof; "Shape differences" records the divergence and defers unification to `TASK-VALIDATION-DIAG-003`. Inspected in full. |
| `docs/proofs/portable-validation-diagnostics-proof.md` | Present; related diagnostics proof. Not modified. |
| `docs/proofs/post-emit-health-implementation-proof.md` | Present; documents the PEH list surface. Not modified. |
| `docs/proofs/real-dump-surface-self-check-proof.md` | Present; documents the BSV surface. Not modified. |
| `docs/tasks/board.md`, `docs/tasks/index.json` | Task registration (this slice). |

### Unrelated / not applicable

- `merger/lenskit/adapters/diagnostics.py` — uses a different `checks`
  namespace (wgx-profile checks with a `code` field); not one of the three
  surfaces.
- `merger/lenskit/core/forensic_preflight.py` — a *fourth* validator that
  independently emits its own **list-of-checks** shape. It does not consume the
  three surfaces' `checks`, but it is worth noting (see Assessment) that it, too,
  chose the list shape.

## Assessment

The difference is best read as **intentional, role-driven shape**, not accidental
drift:

- `output_health` is a compact pre-/emit *self-test summary*. A mapping keyed by
  check name fits direct key lookups (`checks["fts_content_non_empty"]`) and lets
  unrelated consumers (`agent_reading_pack`, `context_quality`, `parity_state`,
  `post_emit_health`, the smoke gate) pull individual signals by name without
  scanning a list.
- `post_emit_health` and `bundle_surface_validation` are *ordered check logs* of
  the final emitted surface, appended in evaluation order, where the natural unit
  is a `{name, status, detail?, validation?}` record and consumers iterate or
  roll up by precedence.

Two facts support "intentional, tolerated" over "drift":

1. The divergence is in the *container* only. The nested `validation` object is
   uniform across all three schemas (`mode`, `engine`, `reason` required where
   present), so the diagnostic vocabulary is already consistent; only the
   surrounding container differs.
2. A fourth, independent validator (`forensic_preflight`) also chose the list
   shape. Among the four, `output_health`'s mapping is the single outlier — which
   is consistent with its different role (summary vs. log), not with random
   drift.

It is therefore classified as a **tolerated, role-justified shape difference**.
It is not asserted to be *optimal*; only that changing it now would be a
schema/consumer migration, not a cleanup.

### Consumer risk (the load-bearing finding)

Every dict-consumer of `output_health["checks"]` guards with
`isinstance(checks, dict)` and falls back to `{}` on mismatch — observed in
`post_emit_health.py`, `agent_reading_pack.py`, `context_quality.py`,
`parity_state.py`, and `scripts/rlens-post-merge-surface-smoke.sh` (five guarded
sites).

This is good defensive hygiene, but it has a sharp consequence for any *future*
migration: if `output_health["checks"]` were changed to a list, none of these
consumers would raise. They would silently degrade to the empty-mapping branch
and quietly drop the extracted booleans/counters (chunk/sqlite/FTS/noise/range
signals). The smoke gate would fail its explicit assertions, but
`agent_reading_pack`, `context_quality`, and `parity_state` would lose signal
*silently*. Any later normalization must treat this as a contract change with a
compatibility plan, not a drop-in shape swap.

The list-shape (PEH/BSV) consumers are narrower: `merge.py` and
`cmd_bundle_surface.py` iterate and filter by `name`/`status`, and the
`cmd_bundle_health` printer is shape-agnostic.

## Decision

For this slice: **keep all three producer shapes unchanged.**

Rationale:

- `output_health` is a compact pre-/emit diagnostic summary; a mapping fits
  by-name signal lookup used by five consumers.
- `post_emit_health` and `bundle_surface_validation` are ordered check logs; a
  list fits append-order and precedence roll-up.
- Changing any producer shape would be a schema + consumer migration (with the
  silent-degradation risk above), not a local refactor.
- Later structured error objects need a clarified, agreed surface first; this
  audit clarifies it without committing to a migration.

What this slice does instead: documents the shapes and consumers, classifies the
difference as tolerated/role-justified, names the consumer risk, and adds
`merger/lenskit/tests/test_validation_check_shapes.py` to pin the currently
accepted shapes so the divergence cannot drift unnoticed.

## Follow-up options

If/when a unification is pursued (each is a separate, explicit decision — none is
started here):

1. **Additive read-only normalization helper.** A consumer-side helper that
   presents any of the three as a common iterable/lookup *view*, without changing
   producers or schemas. Lowest risk; additive only.
2. **Define a common `CheckView` for consumers.** A typed read model the five
   dict-consumers and the list-consumers can share, decoupling consumers from the
   raw container shape before any producer change.
3. **Migrate schemas later, only with an explicit compatibility plan.** Any
   producer shape change must version the contract and address the
   `isinstance(..., dict)` silent-degradation path in all five OH consumers.
4. **Keep all three shapes, documented as distinct roles.** Accept the
   divergence permanently as summary (OH) vs. ordered log (PEH/BSV), with this
   audit as the rationale of record.

Recommended next step is option 1 or 2 (additive, consumer-side) *if* a single
read surface is wanted; option 3 must not be bundled with normalization work.

## Non-claims

This audit does not prove:

- forensic readiness;
- claim truth;
- schema-migration safety;
- consumer completeness beyond the searched paths;
- that the current shapes are optimal.

It performs no producer migration, no schema/contract change, no CLI change, and
adds no dependency in this slice.

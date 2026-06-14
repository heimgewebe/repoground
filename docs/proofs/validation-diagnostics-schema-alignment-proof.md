# Validation Diagnostics Schema Alignment Proof

Status: diagnostic alignment / decision record.

## Purpose

This proof inventories the current validation diagnostic vocabulary across schemas, producers, tests, docs, and optionally emitted local sidecars.
It does not change producer behavior.
It does not change schemas.
It does not introduce a new contract version.

It exists to label the fuse box before anyone throws the "architecture" main switch: it separates what is *schema-valid* from what is *producer-emitted today*, from *reserved* vocabulary, from *obsolete/invalid* planning residue, so the next stabilization slice (PR 3B) does not blindly inherit stale planning values.

## Scope

Covered:

- `merger/lenskit/contracts/output-health.v1.schema.json`
- `merger/lenskit/contracts/post-emit-health.v1.schema.json`
- `merger/lenskit/contracts/bundle-surface-validation.v1.schema.json`
- `merger/lenskit/core/output_health.py`
- `merger/lenskit/core/post_emit_health.py`
- `merger/lenskit/core/bundle_surface_validate.py`
- existing validation diagnostics docs and tests

Out of scope:

- schema migration
- producer refactor
- dependency inventory
- loader consolidation
- structured validation error objects
- forensic strict calibration

Throughout this proof three short labels are used for the three surfaces:

- **OH** = `output-health.v1` schema, produced by `output_health.py`
- **PEH** = `post-emit-health.v1` schema, produced by `post_emit_health.py`
- **BSV** = `bundle-surface-validation.v1` schema, produced by `bundle_surface_validate.py`

## Method

The inventory was produced by read-only inspection:

- **schema enum inventory** — a JSON walker over the three contract files, printing every `validation.mode` / `validation.engine` / `validation.reason` `enum`.
- **schema vocabulary search** — `rg` for the diagnostic terms across the three schema files.
- **producer vocabulary search** — `rg` over the three producer modules, then reading each `validation`-building helper (`_range_ref_validation`, `_validation`, `_surface_validation`) and tracing the literal arguments actually passed at emit sites.
- **tests/docs vocabulary search** — `rg` over `merger/lenskit/tests` and `docs`, focusing on the exact-match assertions in `test_output_health.py`, `test_post_emit_health.py`, and `test_bundle_surface_validate.py`.
- **optional local sidecar inspection** — a `find` for emitted `*.output_health.json` / `*.post_emit_health.json` / `*.bundle_surface_validation.json` in the working tree.

A value is treated as **producer-emitted today** only where a producer literally sets it at an emit site (and, where available, a test asserts it). A value present only in an `enum`, a `Literal` type, or a doc is treated as **reserved** (or **obsolete/invalid** if it appears in none of schema, producer, type, test).

No local sidecars were available in the working tree, so no emitted-sidecar evidence is claimed here; the producer-emitted column is grounded in producer code plus test assertions.

## Current diagnostic object shape

Where present, the diagnostic is an additive nested object:

```json
{
  "validation": {
    "mode": "...",
    "engine": "...",
    "reason": "..."
  }
}
```

- Where `validation` appears, it is an additive diagnostic object; it is not a truth or forensic verdict.
- Older reports may omit `validation` where the schema allows it (it is not in any `required` list at the report root; in OH/PEH/BSV it lives inside per-check objects and is optional there).
- Making `validation` required would need an explicit versioning or migration decision, not a silent tightening.

## Mode inventory

| mode | schema-valid where | producer-emitted today | status | notes |
|------|--------------------|------------------------|--------|-------|
| `jsonschema` | OH, PEH, BSV | `output_health.py`, `post_emit_health.py` | emitted (OH+PEH); reserved (BSV) | full schema validation ran. BSV lists it in its `mode` enum but `bundle_surface_validate` never emits it. |
| `skipped_unavailable` | OH, PEH | `output_health.py`, `post_emit_health.py` | emitted | validation was not performed; `reason` explains why. **Not** in the BSV `mode` enum. |
| `structural_precheck` | OH, PEH, BSV | `output_health.py`, `post_emit_health.py`, `bundle_surface_validate.py` | emitted | surface / coherence / malformed-input precheck, not full schema validation. |
| `minimal_fallback` | OH, PEH, BSV | none | reserved unless producer proves otherwise | part of the shared diagnostic vocabulary and also present as a `Literal` in `bundle_surface_validate.py`, but no producer sets it. Do not claim observed emission without producer evidence. |

Rules applied:

- `minimal_fallback` is **not** marked as producer-emitted: the producer search found no emit site for it in any of the three modules.
- `range_ref_minimal` is **not** used as a mode example (see Engine inventory and Findings).
- `skipped_unavailable` is schema-valid in OH and PEH only; BSV's `mode` enum deliberately omits it.

## Reason inventory

| reason | schema-valid where | producer-emitted today | meaning | notes |
|--------|--------------------|------------------------|---------|-------|
| `available` | OH, PEH, BSV | `output_health.py`, `post_emit_health.py` | validation ran | reserved in BSV (never emitted there). |
| `dependency_unavailable` | OH, PEH, BSV | `output_health.py`, `post_emit_health.py` | a validation dependency (`jsonschema`) was absent | reserved in BSV. Producers use this for the jsonschema-missing case. |
| `dependency_missing` | BSV | none | dependency absent (BSV-local vocabulary) | reserved; BSV emits only `surface_coherence_check` / `check_not_applicable`. **Not** in OH/PEH enums. |
| `jsonschema_unavailable` | OH, PEH | none | the `jsonschema` dependency is absent | reserved; for this exact case the producers emit `dependency_unavailable`, not `jsonschema_unavailable`. |
| `schema_missing` | OH, PEH | `output_health.py`, `post_emit_health.py` | schema file unavailable/missing | **not** in the BSV `reason` enum. |
| `check_not_applicable` | OH, PEH, BSV | `output_health.py`, `post_emit_health.py`, `bundle_surface_validate.py` | check not applicable to the emitted inputs | emitted by all three surfaces. |
| `unsupported_runtime` | OH, PEH | `post_emit_health.py` | runtime cannot run the check (neither dependency-missing nor schema-missing) | emitted by PEH via `_schema_skip_reason`; OH does not emit it today. |
| `malformed_range_ref` | OH, PEH | `output_health.py`, `post_emit_health.py` | a range reference was structurally invalid | paired with `mode=structural_precheck`. |
| `surface_coherence_check` | BSV | `bundle_surface_validate.py` | default surface-coherence classification | BSV-only; the default `reason` for `_surface_check`. |

Stated clearly:

- `skipped_unavailable` (a **mode**) is **not** equivalent to `dependency_unavailable` (a **reason**). A `skipped_unavailable` mode can carry `reason` ∈ {`dependency_unavailable`, `schema_missing`, `check_not_applicable`, `unsupported_runtime`} depending on *why* the check did not run.
- `reason` classifies the cause of non-execution or the validation provenance; it must be inspected before classifying a skip as a dependency failure.

## Engine inventory

| engine | schema-valid where | producer-emitted today | status | notes |
|--------|--------------------|------------------------|--------|-------|
| `jsonschema` | OH, PEH (enum); BSV (free string) | `post_emit_health.py` | emitted (PEH); reserved (OH) | OH lists it in its `engine` enum, but `output_health.py` emits only `range_resolver`. |
| `range_resolver` | OH, PEH (enum); BSV (free string) | `output_health.py`, `post_emit_health.py` | emitted | engine for the range-ref checks. |
| `doc_freshness_minimal` | OH, PEH (enum); BSV (free string) | none | schema-valid but reserved | a schema-valid `engine` value in OH and PEH; no producer emits it. |
| `bundle_surface_validate` | BSV (free string `engine`) | `bundle_surface_validate.py` | emitted | BSV's `engine` is an unconstrained string, not an enum; the OH/PEH `engine` enums do **not** include this value. |
| `range_ref_minimal` | no | no | obsolete/invalid unless proven | not present in any schema, producer, `Literal` type, test, or doc. Do not use as example. |

Note on BSV `engine`: in `bundle-surface-validation.v1` the `engine` field is `{"type": "string"}` with no `enum`, so any string is schema-valid there; the "schema-valid where" column above reflects explicit enum membership (OH/PEH) versus the unconstrained BSV field.

`range_ref_minimal` is **not** schema-valid as an explicit value in any of the three schemas and is emitted by no producer; the only reason it is listed at all is to record it as obsolete planning residue.

## Shape differences

The three surfaces do not share a single `checks` shape:

- `output_health["checks"]` is **dict-like** (keyed by check name); the diagnostic lives at `output_health["checks"]["range_ref_resolution"]["validation"]`.
- `post_emit_health["checks"]` is a **list of check objects**, each `{name, status, detail?, validation?}`.
- `bundle_surface_validation["checks"]` is a **list of check objects**, each `{name, status, detail, validation}`.

This is documented here, not migrated. Unifying the OH dict-shape with the PEH/BSV list-shape is a follow-up candidate tracked as **TASK-VALIDATION-DIAG-003** and must not be bundled into PR 3B.

## Compatibility decision

Current decision (unchanged by this proof):

- `validation` remains an **additive, optional** diagnostic object.
- Legacy fields (e.g. `range_ref_resolution_ok`, `range_ref_resolution_status`) remain valid.
- Older reports may omit `validation` where the schemas allow it.
- Making `validation` required belongs in a future, explicit versioning decision — not this slice.

## Findings

Currently emitted values (producer evidence + test assertions):

- `mode`: `jsonschema`, `skipped_unavailable`, `structural_precheck`.
- `engine`: `jsonschema` (PEH), `range_resolver` (OH/PEH), `bundle_surface_validate` (BSV).
- `reason`: `available`, `dependency_unavailable`, `schema_missing`, `check_not_applicable`, `unsupported_runtime` (PEH), `malformed_range_ref`, `surface_coherence_check` (BSV).

Schema-valid but not emitted today:

- `engine=doc_freshness_minimal` (OH/PEH enum, no producer).
- `engine=jsonschema` in OH specifically (enum member, but `output_health.py` emits only `range_resolver`).
- `reason=jsonschema_unavailable` (OH/PEH enum, but producers emit `dependency_unavailable` for that case).
- `reason=dependency_missing` (BSV enum, no producer).
- `reason=available` / `dependency_unavailable` in BSV specifically (enum members, never emitted by `bundle_surface_validate`).

Reserved vocabulary:

- `mode=minimal_fallback` across OH/PEH/BSV — shared vocabulary, no producer.
- `engine=doc_freshness_minimal` — shared vocabulary, no producer.

Obsolete/invalid planning residue:

- `range_ref_minimal` — absent from every schema, producer, type, test, and doc.

Mandatory findings:

- `range_ref_minimal` must not be used as an example unless future schemas and producers explicitly support it.
- `minimal_fallback` must not be described as a value any producer emits today; producer evidence does not exist, so it stays reserved.
- `skipped_unavailable` means validation was **not performed**; the `reason` field explains whether the cause is a missing dependency, a missing schema, non-applicability, or another allowed cause — it is not, on its own, a dependency-outage signal.

## Recommendation for PR 3B

A safe next implementation slice (no new vocabulary, no version bump):

- Add or adjust **Golden tests** that pin the currently schema-valid, currently emitted `validation` objects for OH and PEH (PEH already validates emitted reports against its schema; OH validates emitted `result` objects against its schema — keep and extend those positive anchors).
- Add **Golden negative tests** proving invalid `validation.mode` / `validation.engine` / `validation.reason` values are rejected. BSV already does this (`test_bundle_surface_validation_schema_rejects_bad_validation_mode`, `..._bad_validation_reason`, `..._incomplete_validation`); replicate the same negative pattern for OH and PEH, which currently have positive golden coverage but no enum-rejection negatives.
- Keep `validation` optional for v1 unless an explicit version bump is chosen.
- Do not introduce new `engine` values before schema and producer agreement; treat `doc_freshness_minimal` as reserved until a real producer emits it.
- Treat `minimal_fallback` as reserved until there is a real producer for it.
- Keep `checks` shape unification (OH dict vs PEH/BSV list) as the separate **TASK-VALIDATION-DIAG-003**.
- Do not introduce `range_ref_minimal`; it must remain absent until schema and producer evidence exists.

## Related docs

- [portable-validation-diagnostics-proof.md](portable-validation-diagnostics-proof.md)
- [post-emit-health-implementation-proof.md](post-emit-health-implementation-proof.md)
- [real-dump-surface-self-check-proof.md](real-dump-surface-self-check-proof.md)
- [../architecture/artifact-capability-matrix.md](../architecture/artifact-capability-matrix.md)

## Non-claims

- This proof does not prove claim truth.
- This proof does not prove forensic readiness.
- This proof does not change contracts.
- This proof does not make reserved vocabulary emitted.
- This proof does not migrate the `checks` shape difference.

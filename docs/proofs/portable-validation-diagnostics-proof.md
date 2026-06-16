# Portable Validation Diagnostics Proof

Status: implemented / diagnostic semantics proof.

## Purpose

This proof documents portable validation diagnostics emitted by Lenskit sidecars.
It does not prove claim truth.
It does not prove forensic readiness.
It documents how full validation, degraded validation, fallback checks, and structural prechecks are represented.

## Scope

Covered sidecars:

- `output_health`
- `post_emit_health`
- `bundle_surface_validation`

Out of scope:

- dependency inventory reports
- structured validation error objects
- YAML/JSON loader consolidation
- forensic strict gate calibration

## Evidence baseline

This proof is based on the post-merge diagnostic surfaces emitted after portable validation diagnostics landed.
Observed diagnostic surfaces:

- `output_health.checks.range_ref_resolution.validation`
- `post_emit_health.checks[].validation` for schema/range validation checks
- `bundle_surface_validation.checks[].validation`
This proof documents emitted diagnostic semantics. It does not change producer code, schemas, or runtime dependency behavior.
The evidence baseline covers currently emitted diagnostics. Reserved vocabulary such as `minimal_fallback` is documented separately and must not be read as observed emission unless a producer emits it.

## Diagnostic object shape

```json
{
  "validation": {
    "mode": "...",
    "engine": "...",
    "reason": "..."
  }
}
```

* `mode`: how the validation/check was performed or why it was degraded.
* `engine`: component or validation engine.
* `reason`: cause or classification.
* The object is additive.
* Legacy fields remain valid.
* Older reports may omit `validation` where schemas keep it optional.

## Modes

### jsonschema

Meaning:
Full JSON Schema validation ran with the `jsonschema` dependency available.

Example:
```json
{
  "validation": {
    "mode": "jsonschema",
    "engine": "jsonschema",
    "reason": "available"
  }
}
```

Limit:
Schema validity proves structure, not claim truth.

### skipped_unavailable

Meaning:
A relevant validation was not performed. The `reason` field identifies why it was skipped, for example because a dependency was unavailable, the schema was missing, or the check was not applicable to the emitted inputs.

Example:
```json
{
  "validation": {
    "mode": "skipped_unavailable",
    "engine": "jsonschema",
    "reason": "dependency_unavailable"
  }
}
```

Range-ref example:
```json
{
  "validation": {
    "mode": "skipped_unavailable",
    "engine": "range_resolver",
    "reason": "dependency_unavailable"
  }
}
```

Non-applicable example:
```json
{
  "validation": {
    "mode": "skipped_unavailable",
    "engine": "range_resolver",
    "reason": "check_not_applicable"
  }
}
```

Missing-schema example:
```json
{
  "validation": {
    "mode": "skipped_unavailable",
    "engine": "jsonschema",
    "reason": "schema_missing"
  }
}
```

Limits:
This is not a successful validation.
It is a machine-readable non-execution/degradation signal.
Consumers must inspect `reason` before classifying the cause.
Portable/degraded runtimes may still emit sidecars.

### minimal_fallback

Meaning:
When emitted, this mode indicates that a limited structural fallback check ran instead of full schema validation.

Current emission status:
This mode is part of the shared diagnostic vocabulary, but this proof does not claim a currently emitted `minimal_fallback` example for the checked sidecars.

Limit:
This is not full JSON Schema validation.
Do not infer this mode from `skipped_unavailable`; they are separate diagnostic modes.

### structural_precheck

Meaning:
A coherence or surface precheck ran. This is not full schema validation.

Example:
```json
{
  "validation": {
    "mode": "structural_precheck",
    "engine": "bundle_surface_validate",
    "reason": "surface_coherence_check"
  }
}
```

Not-applicable example:
```json
{
  "validation": {
    "mode": "structural_precheck",
    "engine": "bundle_surface_validate",
    "reason": "check_not_applicable"
  }
}
```

Limits:
This does not prove claim truth.
This does not prove forensic readiness.

## Current emitted sidecars

### output_health

* `checks.range_ref_resolution.validation` records range-ref validation or degradation.
* Legacy fields such as `range_ref_resolution_ok` and `range_ref_resolution_status` remain.
* `output_health.verdict` is not a forensic verdict.

### post_emit_health

* Checks such as `manifest_schema_valid`, `range_ref_resolution`, and `claim_evidence_map_schema_valid` carry check-local validation where validation provenance is available or skipped.
* `post_emit_health.status` is separate from `output_health.verdict`.
* A degraded validation check must not be silently read as full validation.

### bundle_surface_validation

* Surface checks use `structural_precheck`.
* `output_health_not_forensic_ready` uses `check_not_applicable`.
* A surface pass does not mean `claims_true`.
* A surface pass does not mean `forensic_ready`.

## Runtime interpretation

### Normal runtime

* `jsonschema` is available.
* Full schema validation can emit `mode=jsonschema`.

### Non-execution and degraded runtime

* A validation dependency, schema, or input prerequisite is unavailable or not applicable.
* Sidecars remain portable.
* The non-execution/degradation must be visible as `skipped_unavailable`.
* Reserved fallback vocabulary such as `minimal_fallback` must only be read as emitted where a producer actually emits it.
* Degraded runtime must not be normalized into a silent pass.
* (Pythonista/iPad environments are examples of a degraded runtime, not a special contract.)

### Pythonista / iPad degraded runtime

Pythonista/iPad environments may lack optional validation dependencies such as
`jsonschema`. In that case Lenskit must not silently treat full schema validation as
successful. The runtime is degraded, not necessarily broken.

Expected machine-readable signals:
- `dependencies.jsonschema.available=false`
- `dependencies.jsonschema.effect=validation_degraded`
- schema-bound checks use `validation.mode=skipped_unavailable` or a documented
  `minimal_fallback`
- `skipped_unavailable` is not a pass for schema validation
- degraded validation does not establish `forensic_ready`

Core distinctions:
- degraded runtime != corrupted artifact
- skipped_unavailable != schema valid
- minimal_fallback != full validation
- warn != claim truth
- output_health pass/warn != forensic ready

## Non-claims

Explicitly state:

* `validation.mode=jsonschema` proves schema structure, not claim truth.
* `validation.mode=skipped_unavailable` is not a pass.
* `validation.mode=minimal_fallback` is not full schema validation.
* `validation.mode=structural_precheck` is not full schema validation.
* `output_health.verdict=pass` does not mean `forensic_ready`.
* `post_emit_health.status=pass` does not replace `output_health.verdict`.
* `bundle_surface_validation.status=pass` does not mean `claims_true`.
* `bundle_surface_validation.status=pass` does not mean `forensic_ready`.

## Related files

* [docs/proofs/post-emit-health-implementation-proof.md](post-emit-health-implementation-proof.md)
* [docs/proofs/real-dump-surface-self-check-proof.md](real-dump-surface-self-check-proof.md)
* [docs/architecture/artifact-capability-matrix.md](../architecture/artifact-capability-matrix.md)

## Acceptance proof

* real emitted `output_health` carries nested validation diagnostics where validation provenance is available or degraded
* real emitted `post_emit_health` carries check-local validation diagnostics for schema/range validation checks
* real emitted `bundle_surface_validation` carries structural precheck diagnostics
* legacy compatibility is preserved by additive fields
* degraded runtime is visible and not silently normalized

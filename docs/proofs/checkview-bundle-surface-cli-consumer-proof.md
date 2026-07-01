---
doc_type: proof
status: active
task: TASK-CHECKVIEW-BUNDLE-SURFACE-CLI-CONSUMER-001
---

# Proof: CheckView Bundle-Surface CLI Consumer

## Purpose

`compact_check_projection(report)` existed after the CheckView compatibility slice, but no runtime consumer used it yet. This slice connects one low-risk, read-only consumer: the human output path of `lenskit bundle-surface validate`.

The selected consumer is intentionally conservative. It prints diagnostics for humans; it does not alter bundle emission, JSON output, producer reports, schemas, contracts, or exit-code semantics.

## Implementation

`merger/lenskit/cli/cmd_bundle_surface.py` now formats human `checks` output from `compact_check_projection(report)` instead of iterating the raw producer-specific list shape directly.

The formatter preserves current list-shaped bundle-surface output and can also render mapping-shaped check summaries:

- list-shaped checks print as `[status] name: detail`;
- mapping nested checks with `status` and `reason` print as `[status] name: reason`;
- mapping scalar checks print as `name: value`.

## Verification

Tests added in `merger/lenskit/tests/test_cli_bundle_surface.py` prove that the human printer is no longer hardwired to list-shaped producer output. Existing CLI JSON tests remain unchanged, so machine-readable output is not migrated.

Focused local test:

```text
python3 -m pytest -q merger/lenskit/tests/test_cli_bundle_surface.py merger/lenskit/tests/test_validation_check_view.py
37 passed
```

## Negative semantics

This does not establish truth, correctness, completeness, runtime behavior, test sufficiency, regression absence, repo understanding, or forensic readiness. It is only the first read-only consumer use of the CheckView projection.

## Non-goals

No producer normalization, no schema or contract migration, no JSON-output migration, no broad migration of output_health consumers, no new artifact, no default promotion gate, and no mirror of all raw check fields.

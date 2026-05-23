# Agent Export Gate Proof (A5)

- Date: 2026-05-23
- Scope: Minimal export gate for agent-facing profiles

## Why output_health is insufficient

`output_health` is pre-emit and observational. The gate does not treat `output_health.verdict` as sufficient evidence for export permission.

## Why post_emit_health is required

Agent-facing export requires a readable `post_emit_health` report with `status=pass`. Missing or unreadable post-emit health blocks agent-facing export.

The gate additionally requires `post_emit_health` shape/binding validity before trust:
- `kind == lenskit.post_emit_health`
- `version == 1.0`
- valid status enum
- schema-valid when `jsonschema` is available
- `bundle_manifest_path` must be present, non-empty, and match the evaluated bundle manifest path
- for `status=pass`, `bundle_run_id` must match the evaluated manifest `run_id`

Invalid or mismatched post-emit reports block agent-facing export.

## Why redaction false blocks agent-facing export

For agent-facing profiles with required redaction, `capabilities.redaction` must be `true`. If not, gate result is fail.

## What this gate does not mean

A gate pass does not mean:
- `repo_understood`
- `answer_safe_without_citations`
- `claims_true`

The gate is export eligibility logic, not a truth verdict.

Profile policy is fail-closed:
- missing profile => blocked
- unknown profile => blocked
- only known non-agent profiles are treated as non-agent-facing

## Manifest mutation

The gate reads manifest and optional health files only. It does not write to or mutate the bundle manifest.

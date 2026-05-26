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

## A5 verified/closed

Verified acceptance criteria:
- agent-facing export is blocked without a valid post_emit_health report
- agent-facing export is blocked when capabilities.redaction is false
- canonical agent-portable / agent-safe profiles are treated as agent-facing export profiles
- internal local-search / debug-full / max-private / forensic-strict profiles are blocked from agent export
- non-agent-facing profiles do not claim agent-surface certification
- output_health.verdict=pass is observation only and does not certify agent-safe export
- the gate does not mutate the manifest
- the gate validates against agent-export-gate.v1.schema.json through its test coverage

Test evidence:
- `python -m pytest merger/lenskit/tests/test_agent_export_gate.py merger/lenskit/tests/test_agent_profiles.py merger/lenskit/tests/test_post_emit_health.py merger/lenskit/tests/test_cli_bundle_health.py` -> 75 passed
- `python -m pytest merger/lenskit/tests/test_context_quality.py merger/lenskit/tests/test_cli_context_quality.py` -> 28 passed

Closure notes:
- output_health pass means pre-emit or diagnostic health only; it is not agent-safe proof
- post_emit_health is the final bundle-surface certification layer for agent-facing export
- the gate is a diagnostic_signal, not a truth verdict

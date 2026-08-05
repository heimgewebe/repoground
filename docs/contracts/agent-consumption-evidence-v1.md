# Agent Consumption Evidence v1

Status: implemented contract surface (optional observation layer)

Initiative: `REPOGROUND-AGENT-UTILITY-V1`
Task: `REPOGROUND-AGENT-UTILITY-V1-T005`

## Purpose

Bind declared Agent Consumption statements to trusted tool-read receipts for the
same task, repository commit, artifact role and immutable artifact identity —
without storing source content and without claiming understanding, relevance,
correctness or truth.

## Surfaces

| Contract | Kind | Module |
|----------|------|--------|
| `agent-tool-read-receipt.v1.schema.json` | `lenskit.agent_tool_read_receipt` | `agent_consumption_receipts.py` |
| `agent-consumption-evidence.v1.schema.json` | `lenskit.agent_consumption_evidence` | `agent_consumption_evidence.py` |

## Mint path

Only:

- `TrustedToolReadWrapper.observe_artifact_access(...)`
- `mint_tool_read_receipt(...)` with an allowlisted issuer

may create observed evidence. Answer Compliance remains declaration-only.

## Comparison CLI

```bash
python3 -m merger.repoground.cli.main agent-consumption compare-evidence \
  --answer-compliance path/to/answer-compliance.json \
  --receipts path/to/receipts.json \
  --task-id REPOGROUND-AGENT-UTILITY-V1-T005 \
  --repo-commit <40-hex> \
  [--expected-roles role_a,role_b] \
  [--declared-identities path/to/identities.json] \
  [--as-of 2026-08-05T22:00:00Z] \
  [--max-age-seconds 3600] \
  [--strict] \
  [--out evidence.json]
```

## Retention

Receipts are ephemeral comparison inputs:

- no content retention
- metadata-only redaction
- safe deletion at any time

## Non-claims

A `declared-and-observed` state means only that a declaration and an accepted
trusted receipt matched the bound task/commit/role/identity. It does not prove
semantic reading, relevance, answer correctness, or truth.

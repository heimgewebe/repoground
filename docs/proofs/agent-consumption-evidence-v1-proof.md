# Agent Consumption Evidence v1 proof

Task: `REPOGROUND-AGENT-UTILITY-V1-T005`

Status: implementation proof for the optional declaration-vs-observation evidence layer.

## Problem

Answer Compliance and the Agent Consumption Trace compare declarations with
required-reading expectations. That is formal self-consistency only. It does
not record whether a trusted tool wrapper observed access to the declared
artifact identity for the same task and repository commit.

Without a separate observation layer, operators cannot distinguish:

- declared-only claims;
- trusted observations without declaration;
- matching declaration and observation;
- unavailable expected roles.

Any observation layer that stored source content or treated answer text as
evidence would over-claim privacy and truth.

## Implemented surface

This slice adds:

- `agent-tool-read-receipt.v1.schema.json`
- `agent-consumption-evidence.v1.schema.json`
- `merger/repoground/core/agent_consumption_receipts.py`
- `merger/repoground/core/agent_consumption_evidence.py`
- CLI `agent-consumption compare-evidence`
- focused schema, determinism, negative, replay, freshness, mismatch and E2E tests
- architecture and contract documentation

## Binding

Each receipt deterministically binds:

- `task_id`
- `repo_commit` (40-hex SHA-1)
- `artifact_role`
- immutable `artifact_identity` (`path`, `sha256`, `bytes`)
- `access_event_id`
- allowlisted `issuer`

via `binding_sha256` and full-document `receipt_sha256` over canonical JSON.
Content is hashed for identity and discarded.

## Trust and privacy

- Only `trusted_wrapper` / `tool_gateway` allowlisted issuer ids elevate evidence.
- Answer text and self-declarations have no mint path.
- Forbidden content/secret keys fail closed.
- Secret-like path or event-id material fails closed.
- Receipt JSON size is bounded.

## Comparison states

Exactly:

- `declared-only`
- `observed-only`
- `declared-and-observed`
- `unavailable`

Missing, stale, task-mismatch, commit-mismatch, replay and artifact-mismatch
receipts are diagnosed and never produce a stronger evidence state.

## Verification command

```bash
python3 -m pytest merger/repoground/tests/test_agent_consumption_evidence.py \
  merger/repoground/tests/test_agent_consumption_trace.py \
  merger/repoground/tests/test_cli_agent_consumption.py -q
```

## Non-claims / STOP

This slice does not establish:

- semantic reading;
- relevance of observed files to later answers;
- answer correctness or claim truth;
- complete context use;
- runtime interception of all tools;
- mandatory adoption by external wrappers;
- deployment or merge readiness;
- cryptographic hardware-backed attestation.

STOP: no runtime agent hook is installed; no deployment; no second initiative task.

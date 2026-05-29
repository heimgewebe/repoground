# Authority/Risk-Class C2.3 Inference-Boundary Proof

## 1. Scope

C2.3 is implemented as a **contract-only / test-only** slice for selected, already
boundary-adjacent diagnostic contracts:

- `merger/lenskit/contracts/post-emit-health.v1.schema.json`
- `merger/lenskit/contracts/agent-export-gate.v1.schema.json`
- `merger/lenskit/contracts/retrieval-eval.v1.schema.json`
- `merger/lenskit/contracts/context-quality.v1.schema.json`

The patch adds exactly two optional top-level fields to each selected contract:

```json
{
  "allowed_inferences": ["..."],
  "forbidden_inferences": ["..."]
}
```

Both fields are arrays of strings. They are **not** required and do not change the
contract major version.

## 2. Naming Decision

The C2.3 field names are plural:

- `allowed_inferences`
- `forbidden_inferences`

Rationale:

1. The values are arrays, so plural names match the shape.
2. Only one naming family is introduced; singular names (`allowed_inference`,
   `forbidden_inference`) remain invalid because the contracts keep
   `additionalProperties: false`.
3. The plural names avoid schema drift before later lint/export-gate work defines any
   closed policy vocabulary.

## 3. Semantics

`forbidden_inferences` is a machine-readable companion to existing local boundaries
such as `does_not_mean` or `claim_boundaries.does_not_prove`, depending on the
selected contract. It does not replace those fields and it is not a claim-verdict field.

`allowed_inferences` describes permitted use of the artifact as a diagnostic signal.
It is not a truth judgment. It must not be read as `supported`, `unsupported`,
`proven`, or `safe`.

This slice intentionally adds no runtime logic, no producer emission, no CLI behavior,
no lint rule, and no export gate.

## 4. Free-String Decision

No enum/const vocabulary is introduced in C2.3. The fields are free `array[string]`
for now because:

1. C2.3 is preparation for future lint/export-gate work, not the policy vocabulary
   itself.
2. The selected contracts already have surface-local boundary phrases; forcing a
   closed cross-contract enum now would either invent policy terms or prematurely
   normalize local wording.
3. Later C2.4/C2.5 work can define a validated vocabulary once the contract shape has
   proven stable.

## 5. Non-Changes

Explicitly unchanged:

- `merger/lenskit/contracts/output-health.v1.schema.json`
- Federation contracts
- `agent-query-session.v2.schema.json`
- `bundle-manifest.v1.schema.json`
- no new `authority-matrix.v1` contract
- no new `inference-boundary.v1` contract
- no runtime annotations, lints, producer emission, or export gates

C2.4, C2.5, C4, and C5 remain open.

## 6. Test Coverage

`merger/lenskit/tests/test_contract_inference_boundaries.py` covers all four selected
contracts:

1. Legacy/minimal documents without `allowed_inferences` and `forbidden_inferences`
   continue to validate.
2. Documents with plural `allowed_inferences` and `forbidden_inferences` string arrays
   validate.
3. Scalar values such as `allowed_inferences: "text"` and
   `forbidden_inferences: "text"` are rejected.
4. Arrays containing non-strings are rejected.
5. Singular field names remain invalid under `additionalProperties: false`.

## 7. Verification Commands

Targeted schema tests:

```bash
python -m pytest -q merger/lenskit/tests/test_contract_inference_boundaries.py
```

Required C2.3 regression commands:

```bash
python -m pytest -q \
  merger/lenskit/tests/test_contract_version_guards.py \
  merger/lenskit/tests/test_jsonschema_degradation.py \
  merger/lenskit/tests/test_contract_inference_boundaries.py \
  merger/lenskit/tests/test_post_emit_health.py \
  merger/lenskit/tests/test_agent_export_gate.py \
  merger/lenskit/tests/test_retrieval_eval.py \
  merger/lenskit/tests/test_context_quality.py

python -m ruff check \
  merger/lenskit/tests/test_contract_inference_boundaries.py \
  --select=F401,F811,F841,E711,E712

git diff --check
```

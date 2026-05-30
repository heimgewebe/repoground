# Authority/Risk-Class C2.6 — retrieval-eval-diagnostics.v1 Root Boundary Proof

## 1. Scope

C2.6 resolves the single deferral that C2.4
(`docs/proofs/authority-risk-class-c2-4-lint-proof.md` §4) tracked but
deliberately did not fix: `retrieval-eval-diagnostics.v1.schema.json`
self-declared `authority: diagnostic_signal` (a boundary-requiring authority
under C1 / L3) but carried **no** machine-readable inference boundary. C2.4
surfaced this honestly as a non-blocking `deferred` lint finding and named the
fix as a separate C2.6 boundary-normalizing follow-up. This slice is that follow-up.

It is **boundary-normalizing, producer-compatible, and intentionally
tightening**: it gives the diagnostics report a required root `does_not_prove`
boundary, emits it from the existing producer, and empties the lint's deferral
registry so the contract is governed as a clean (blocking) L3 case instead of a
tracked deferral. The `required` field is formally stricter for historical
instances—old reports lacking `does_not_prove` would fail validation—but this is
locally defensible: the consumer/fixture audit (§3a) found no persisted corpus and
no external schema-validation consumer, the producer is updated in the same
change, and the artifact is ephemeral (not a bundle-manifest role).

New / changed files:

- `merger/lenskit/contracts/retrieval-eval-diagnostics.v1.schema.json` (required
  root `does_not_prove` array with `contains` constraints)
- `merger/lenskit/retrieval/eval_diagnostics.py` (`DOES_NOT_PROVE` constant +
  producer emission)
- `merger/lenskit/core/anti_hallucination_lint.py` (`DEFERRED_BOUNDARY_CONTRACTS`
  is now empty; mechanism retained)
- `merger/lenskit/tests/test_anti_hallucination_lint.py`
- `merger/lenskit/tests/test_retrieval_eval_diagnostics.py`
- `docs/proofs/authority-risk-class-c2-6-diagnostics-boundary-proof.md` (this file)
- `docs/roadmap/lenskit-master-roadmap.md`, `docs/testing/test-matrix.md`,
  `docs/diagnostics/retrieval-eval-diagnostics.md` (status alignment)

## 2. The Boundary

`does_not_prove` is a **required** root `array[string]` with `minItems: 1` and an
`allOf` of `contains` constraints requiring these canonical entries (mirroring the
sibling `retrieval-eval.v1` `miss_taxonomy.does_not_prove` discipline, adapted to
the per-miss *diagnosis* vocabulary of this contract):

- `absence_of_retrieval_hit_does_not_prove_absence_in_repository`
- `miss_diagnosis_does_not_prove_claim_truth_or_falsehood`
- `primary_diagnosis_does_not_prove_root_cause_certainty`
- `retrieval_eval_does_not_prove_retrieval_completeness`
- `diagnosis_is_diagnostic_not_authoritative`

The producer (`RetrievalEvalDiagnosticsCalibrator.generate_report`) emits exactly
this list from the module-level `DOES_NOT_PROVE` constant, so every generated
report carries the boundary and validates against the contract. `additionalProperties:
false` remains; additional disclaimer strings are permitted by the schema but the
five canonical entries are mandatory.

## 3. Why Required (not optional)

C2.1–C2.3 added *optional* fields and explicitly avoided producer changes. C2.6 is
the deliberately-scoped boundary normalization that those steps deferred, so it
takes the stronger and more consistent route:

- The sibling diagnostics contract `retrieval-eval.v1` already makes
  `miss_taxonomy.does_not_prove` **required with `contains`**; this contract is the
  per-miss analogue and now matches that discipline.
- The producer is fully under our control and is updated in the same change, so
  there is never a window where it emits an artifact that fails validation
  (locked by `test_schema_validation` + `test_report_carries_does_not_prove_boundary`).
- The artifact is an ephemeral analysis output: it is **not** a bundle-manifest
  role, has **no** committed example fixtures, and no consumer loads historical
  copies — so a required field breaks no persisted corpus.
- An *optional* boundary would be boundary-theater: the L3 rule exists precisely so
  diagnostic artifacts carry their epistemic limits, not merely *may* carry them.

## 3a. Consumer & Fixture Audit (Breaking-Change Evidence)

The claim that `required` is safe requires positive evidence. The following
searches were executed on the full repository tree:

```bash
# 1. Schema references outside the implementation and test files
grep -rn "retrieval-eval-diagnostics" \
  --include="*.py" --include="*.json" --include="*.yaml" --include="*.yml" \
  . | grep -v "merger/lenskit/contracts/" \
      | grep -v "merger/lenskit/retrieval/eval_diagnostics" \
      | grep -v "merger/lenskit/tests/" \
      | grep -v "merger/lenskit/core/anti_hallucination" \
      | grep -v "docs/"
# Result: (empty) — no external Python/config consumer references the schema path.

# 2. External callers of generate_report / RetrievalEvalDiagnosticsCalibrator
grep -rn "generate_report\|eval_diagnostics\|RetrievalEvalDiagnosticsCalibrator" \
  --include="*.py" . \
  | grep -v "__pycache__" \
  | grep -v "test_retrieval_eval_diagnostics.py" \
  | grep -v "eval_diagnostics.py"
# Result: merger/lenskit/retrieval/eval_diagnostics_integration.py — the only
#   non-test caller. It calls calibrator.generate_report() but does NOT load the
#   schema and does NOT call jsonschema.validate; it passes the result through.

# 3. Stored fixtures / golden files containing diagnostic report keys
find . -name "*.json" | xargs grep -l \
  "diagnostic_breakdowns\|does_not_prove\|primary_diagnosis" 2>/dev/null \
  | grep -v "__pycache__" | grep -v ".git"
# Result: only merger/lenskit/contracts/retrieval-eval-diagnostics.v1.schema.json
#   (the schema itself, not a stored report).

# 4. jsonschema.validate calls targeting the diagnostics schema (outside our tests)
grep -rn "jsonschema.validate" --include="*.py" . \
  | grep -v "__pycache__" \
  | grep -v "test_retrieval_eval_diagnostics.py" \
  | grep -v "test_anti_hallucination_lint.py" \
  | grep -v "anti_hallucination_lint.py" \
  | xargs grep -l "retrieval-eval-diagnostics" 2>/dev/null
# Result: (empty) — no other file both calls jsonschema.validate and references the
#   diagnostics schema.
```

**Findings:**

| Check | Result |
|-------|--------|
| External Python/config consumers of the schema path | None found |
| Callers of `generate_report` outside test files | One: `eval_diagnostics_integration.py` — does not validate against the schema |
| Committed JSON fixtures / golden files with diagnostics report keys | None found |
| Non-test `jsonschema.validate` calls targeting this schema | None found |

**Conclusion:** The artifact is confirmed ephemeral with no committed corpus and no
external schema-validation consumer. Making `does_not_prove` required breaks no
existing usage. If a stored fixture or external consumer were found, the correct
response would be to revert to `optional` and document a separate migration path.

## 4. Lint Effect

`DEFERRED_BOUNDARY_CONTRACTS` is now `{}`. The deferral *mechanism* in `_check_l3`
and `audit_deferral_registry` is unchanged and still downgrades any future
registered contract to a non-blocking `deferred` finding (exercised by
`test_l3_deferral_mechanism_downgrades_registered_contract` via a synthetic entry).

Result of `lenskit governance lint`:

- before: `PASS` — 38 scanned, 0 errors, **1 deferred** (`retrieval-eval-diagnostics.v1`)
- after:  `PASS` — 38 scanned, 0 errors, **0 deferred**

## 5. Non-Changes (out of scope)

- **No** new contract, **no** schema other than the single `does_not_prove`
  addition, **no** change to `metadata`/`diagnostics`/the diagnosis vocabulary.
- **No** truth/claim evaluation, **no** repository-absence claim, **no** ranking or
  retrieval-behavior change, **no** manifest mutation/registration.
- **No** change to the C2.4 lint rules (L3/L5), the out-of-scope L1/L2/L4/L6
  framing, or the export gate (C5). C4 (runtime annotation) and the broader C5
  framework remain **open**.

## 6. Verification Commands

```bash
# Lint the real contracts (blocking gate; exit 0, 0 deferred)
python3 -m merger.lenskit.cli.main governance lint
python3 -m merger.lenskit.cli.main governance lint --json

# Targeted suites
python3 -m pytest -q \
  merger/lenskit/tests/test_anti_hallucination_lint.py \
  merger/lenskit/tests/test_retrieval_eval_diagnostics.py

# Regression (contracts / health / quality / eval / export-gate / cli)
python3 -m pytest -q \
  merger/lenskit/tests/test_contract_inference_boundaries.py \
  merger/lenskit/tests/test_contract_version_guards.py \
  merger/lenskit/tests/test_post_emit_health.py \
  merger/lenskit/tests/test_context_quality.py \
  merger/lenskit/tests/test_retrieval_eval.py \
  merger/lenskit/tests/test_agent_export_gate.py \
  merger/lenskit/tests/test_cli_bundle_health.py

# Import hygiene (repo CI gate selection)
python3 -m ruff check --select=F401,F811,F841,E711,E712 --exclude='**/fixtures/**' \
  merger/lenskit/core/anti_hallucination_lint.py \
  merger/lenskit/retrieval/eval_diagnostics.py \
  merger/lenskit/tests/test_anti_hallucination_lint.py \
  merger/lenskit/tests/test_retrieval_eval_diagnostics.py
```

## 7. Results (local run)

- `governance lint`: `PASS` — 38 scanned, 0 errors, 0 deferred, exit 0.
- `test_anti_hallucination_lint.py` + `test_retrieval_eval_diagnostics.py`: 59 passed.
- Regression (contracts/health/quality/eval/export-gate/cli): 173 passed, no regressions.
- Schema meta-validation: `Draft7Validator.check_schema` OK.
- `ruff --select=F401,F811,F841,E711,E712`: clean.
- Python: 3.11.15 (local). CI runs 3.12.

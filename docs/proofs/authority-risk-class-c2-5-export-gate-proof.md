# Authority/Risk-Class C2.5 / C5 Export-Gate Inference-Boundary Proof

## 1. Scope

C2.5 is the **minimal** slice of Governance Track **C5** — the export-gate side of
the C1 anti-hallucination matrix rule **L6** (export-risk), which C2.4 explicitly
deferred (`docs/proofs/authority-risk-class-c2-4-lint-proof.md` §3;
`merger/lenskit/core/anti_hallucination_lint.py` `OUT_OF_SCOPE_RULES["L6"]`).

The existing `agent_export_gate` (roadmap A5) is **minimally hardened**, not
replaced: it now reads the optional C2.3 `forbidden_inferences` field from the
bundle's diagnostic artifacts and refuses to certify an **agent-facing** export
when a diagnostic explicitly forbids a high-risk inference.

Changed files:

- `merger/lenskit/core/agent_export_gate.py` (additive read + gate condition)
- `merger/lenskit/tests/test_agent_export_gate.py` (C2.5 coverage)
- `docs/proofs/authority-risk-class-c2-5-export-gate-proof.md` (this file)
- `docs/roadmap/lenskit-master-roadmap.md` (C2.5 / C5 status)

This slice adds **no new contract**, **no runtime annotation**, **no producer
emission**, **no claim-truth evaluation**, and **no change to `canonical_md` or
retrieval**.

## 2. The Rule (blocking, agent-facing only)

For an **agent-facing** export profile, if any in-bundle diagnostic artifact
machine-readably forbids an inference from the export-risk vocabulary (§3), the
gate result is downgraded to `fail` (or stays `blocked` if already blocked) and
an error names the offending inference(s).

The rule exists only so that an agent-facing export does **not appear safe**
while a diagnostic in the same bundle explicitly says that exact inference is
forbidden. It is export-eligibility logic, not a truth verdict — consistent with
the gate's pre-existing `does_not_mean` disclaimers
(`repo_understood`, `answer_safe_without_citations`, `claims_true`).

Non-agent-facing profiles are **not** export-risk gated: they are evaluated on
the existing separate path and never certify the agent surface in the first
place.

## 3. Export-Risk Vocabulary (minimal, closed)

`_EXPORT_RISK_FORBIDDEN_INFERENCES` in `agent_export_gate.py`:

- `claims_true`
- `repo_understood`
- `answer_safe_without_citations`
- `retrieval_complete`

This is a deliberately small, closed set that mirrors the existing
`context_quality.DOES_NOT_MEAN` vocabulary
(`merger/lenskit/core/context_quality.py`). Matching is **exact** on the strings
declared in `forbidden_inferences`; any other (free-string) forbidden inference
is honored as a C2.3 boundary note but does **not** block export. C2.3 keeps the
field as a free `array[string]`, so this closed vocabulary lives in the gate, not
in the contract.

## 4. Read Surface

`forbidden_inferences` is read from:

1. **Manifest diagnostic artifacts** that self-declare `authority ==
   diagnostic_signal`, resolved with `resolve_secure_path` so a path escaping the
   bundle directory is rejected (same posture as the existing `output_health`
   observation). Artifacts that are not diagnostic, are unreadable, or are not
   JSON objects are silently skipped.
2. The already-loaded **`post_emit_health`** document.

Both `agent-export-gate.v1`, `post-emit-health.v1`, `retrieval-eval.v1`, and
`context-quality.v1` carry the optional C2.3 `forbidden_inferences` field; the
gate only reads it where a diagnostic artifact is actually reachable in the
bundle. The gate does **not** mutate the manifest or any artifact (asserted by
`test_agent_export_gate_does_not_mutate_manifest`).

## 5. Fail vs Blocked Semantics

The downgrade reuses the gate's existing semantics:

- `blocked` = certification could not complete (missing/unknown/non-exportable
  profile, missing/invalid `post_emit_health`, missing `run_id`). A forbidden
  inference does **not** override an existing `blocked`.
- `fail` = certification completed but a defect was found. An export-risk
  inference is exactly such a defect, so it maps to `fail` — identical to the
  redaction-disabled branch.

The report shape is unchanged: the reason is surfaced in the existing `errors`
array, so the report still validates against `agent-export-gate.v1`
(no schema change).

## 6. Non-Changes

Explicitly unchanged:

- No contract schema file was modified (the C2.3 `forbidden_inferences` field
  already existed; no new contract, no new field, no version bump).
- No producer/runtime emission of `forbidden_inferences` — the gate **reads**
  boundaries, it does not write them.
- No claim-truth evaluation; no `supported`/`unsupported`/`proven`/`safe`
  semantics introduced.
- `evaluate_agent_export_gate` keeps its signature, so the
  `lenskit bundle-health export-gate` CLI (`cmd_bundle_health.py`) is unaffected;
  the `fail` status already maps to its existing exit code.
- No change to `canonical_md`, retrieval, or any other artifact.
- C4 (runtime annotation) and the broader C5 governance framework remain open;
  this is only the L6 export-risk inference lever.

## 7. Test Coverage

`merger/lenskit/tests/test_agent_export_gate.py` (C2.5 block):

1. Legacy `post_emit_health` without `forbidden_inferences` stays `pass`.
2. A harmless free-string `forbidden_inferences` does not block.
3. Each of the four export-risk inferences in `post_emit_health` fails an
   agent-facing export (parametrized).
4. A `forbidden_inferences` on an in-bundle diagnostic manifest artifact also
   fails the export.
5. A non-agent-facing profile (`human_review`) is **not** blocked by a forbidden
   inference.
6. `forbidden_inferences` on a non-`diagnostic_signal` artifact is ignored
   (no overreach).
7. A diagnostic path escaping the bundle is rejected and its boundary is not
   read (security posture).
8. A diagnostic artifact with invalid UTF-8 is skipped and does not abort
   export-gate certification.
9. The export-risk `fail` report still validates against `agent-export-gate.v1`.

Existing A5 / C2.1 / C2.3 gate tests remain green.

## 8. Verification Commands

```bash
python -m pytest -q \
  merger/lenskit/tests/test_agent_export_gate.py \
  merger/lenskit/tests/test_contract_inference_boundaries.py \
  merger/lenskit/tests/test_anti_hallucination_lint.py

python -m ruff check \
  merger/lenskit/core/agent_export_gate.py \
  merger/lenskit/tests/test_agent_export_gate.py \
  --select=F401,F811,F841,E711,E712

git diff --check
```

## 9. Results (local run)

- Targeted trio: **107 passed**
  (`test_agent_export_gate.py` 47, including 12 new C2.5 pytest cases).
- `ruff --select=F401,F811,F841,E711,E712`: clean.
- `git diff --check`: clean.
- Regression (`test_post_emit_health.py`, `test_context_quality.py`,
  `test_retrieval_eval.py`, `test_contract_version_guards.py`,
  `test_jsonschema_degradation.py`, `test_cli_bundle_health.py`): **97 passed**,
  no regressions.
- Python: 3.11.15 (local). CI runs 3.12.

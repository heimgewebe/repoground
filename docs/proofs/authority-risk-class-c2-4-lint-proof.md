# Authority/Risk-Class C2.4 Anti-Hallucination Contract Lint Proof

## 1. Scope

C2.4 implements the **contract-static subset** of the C1 anti-hallucination lint
rules (`docs/blueprints/lenskit-authority-risk-matrix.md` §6). It is the
"Vorbereitung der Lint-Regeln (C1 §6 L1–L6) als spätere CI-Stufe" called out by
the C2a gap audit (`docs/proofs/authority-contract-gap-audit.md` §8) — the rules
that are **mechanically decidable from contract schemas alone** and that are
already clean on the current contract set, so the lint ships as a green,
drift-catching CI gate **without forcing premature contract migration**.

New / changed files:

- `merger/lenskit/core/anti_hallucination_lint.py` (lint engine, pure functions)
- `merger/lenskit/cli/cmd_governance.py` (`lenskit governance lint`)
- `merger/lenskit/cli/main.py` (dispatch wiring)
- `merger/lenskit/tests/test_anti_hallucination_lint.py`
- `.github/workflows/anti-hallucination-lint.yml` (path-scoped blocking gate)
- `docs/proofs/authority-risk-class-c2-4-lint-proof.md` (this file)
- `docs/roadmap/lenskit-master-roadmap.md` (Governance Track C status)

This slice adds **no** runtime annotation, **no** producer emission, **no**
contract mutation, and **no** claim-truth evaluation.

## 2. Rules Implemented (blocking)

### L3 — Missing Inference Boundary

A contract whose **root** object self-declares a boundary-requiring authority via
an `authority` / `session_authority` `const` in
`{diagnostic_signal, runtime_observation, agent_context_projection}` MUST declare
a machine-readable boundary information at the root: a `does_not_prove` / `does_not_mean`
array, or a `claim_boundaries` object.

- Only the **root** declaration is governed. `bundle-manifest.v1` assigns
  authority to *other* artifacts per-role (nested enum), so it is correctly
  excluded — it is a registry, not a self-declaring diagnostic artifact.
- A non-compliant contract is a **blocking error**, *unless* it is registered in
  `DEFERRED_BOUNDARY_CONTRACTS` (see §4), in which case it is reported as a
  non-blocking `deferred` finding.

### L5 — Unsupported Truth Language

- **Property names:** no forbidden truth-asserting *property key* may appear
  anywhere in a schema (recursively, including `$defs`):
  `understanding_health`, `understanding_score`, `context_score`, `agent_safe`,
  `agent_ready`, `proven`, `supported`, `unsupported`, `verified`, `correct`.
- **Verdict values:** no forbidden truth token may appear as an `enum` or `const` value of a
  verdict-like field (`verdict`, `status`, `*_verdict`):
  `proven`, `supported`, `unsupported`, `verified`, `safe`, `unsafe`,
  `green`, `yellow`, `red`.

Matching is **exact** — never substring. Status tokens such as `complete`,
`true`, `false`, `green/yellow/red` are deliberately **not** forbidden as
*property names* or *generic values*; only the verdict-value rule constrains the
verdict-like fields. Disclaimer-array *values* (`does_not_prove`,
`does_not_mean`, `forbidden_inferences`, `allowed_inferences`,
`agent_use_constraints`) are **never** scanned, because they legitimately *name*
the forbidden inferences as negatives (blueprint §6 L5 "Mögliche False
Positives").

## 3. Rules Out Of Scope (documented, not implemented)

- **L1 / L2 / L4** — forbidden semantic upgrades, authority-escalation detection,
  and derived-artifact misuse require Python **AST / code-path** static analysis
  (high false-positive surface per blueprint §6). Deferred to a later AST lint
  stage.
- **L6** — export-risk violations are export-gate integration = Governance Track
  **C5**.

These are recorded machine-readably in the lint report under
`rules_out_of_scope`.

## 4. Deferral Registry (tracked, non-blocking)

Exactly one current contract self-declares a boundary-requiring authority without
a boundary array:

- `retrieval-eval-diagnostics.v1.schema.json` — declares `authority:
  diagnostic_signal` (required const) but carries no
  `does_not_prove`/`does_not_mean`/`claim_boundaries`. It is **not** in the C2a
  gap-audit Contract Inventory table (which audited the distinct
  `retrieval-eval.v1`). C2.4 surfaces this gap honestly as a `deferred` finding
  rather than (a) silently ignoring it or (b) force-migrating the contract, which
  the gap audit (§8: "erst nachdem die Contracts stabil normiert sind"; §5.D;
  §7) explicitly defers. Adding the boundary is a separate additive C2.x
  follow-up.

`audit_deferral_registry()` guards against registry rot: a deferral is flagged
stale if its contract is absent, no longer self-declares a governed authority, or
has since gained a boundary. A test asserts the registry is currently non-stale.

> **Update (resolved by C2.6):** this deferral has since been closed. The C2.6
> follow-up gave `retrieval-eval-diagnostics.v1` a required root `does_not_prove`
> boundary (with producer emission), so `DEFERRED_BOUNDARY_CONTRACTS` is now empty
> and the lint reports **0 deferred**. The deferral *mechanism* (and its rot guard)
> is retained for any future contract. See
> `docs/proofs/authority-risk-class-c2-6-diagnostics-boundary-proof.md`. The §5/§8
> figures below describe the original C2.4 state (1 deferred) and are kept as the
> historical record.

## 5. Why The Gate Is Green Today

Ground-truth scan of `merger/lenskit/contracts/*.schema.json`:

- **L5 property names / verdict values:** none present in any contract (matches
  gap audit §5.E: "C1-L5-Verbotsliste ist derzeit eingehalten").
- **L3 self-declaring contracts (8):** `agent-export-gate.v1`,
  `agent-query-session.v2` (`session_authority`), `context-lookup.v1`,
  `context-quality.v1`, `post-emit-health.v1`, `retrieval-eval.v1`,
  `trace-lookup.v1` all carry a root boundary; only
  `retrieval-eval-diagnostics.v1` does not (deferred, §4).

Result: `status=pass`, `error_count=0`, `deferred_count=1`, 38 contracts scanned.

## 6. Non-Changes

Explicitly unchanged:

- No contract schema files were modified (no boundary added to
  `retrieval-eval-diagnostics.v1`, no field added anywhere).
- `output-health.v1`, the federation contracts, `diagnostics-lookup.v1`,
  `agent-query-session.v2`, and `bundle-manifest.v1` are untouched.
- No producer/runtime/CLI emission of lint annotations; the lint reads contracts
  and reports, it does not write into artifacts or the manifest.
- C4 (runtime annotation) and C5 (export-gate) remain open.

## 7. Verification Commands

```bash
# Lint the real contracts (blocking gate; exit 0 today)
python -m merger.lenskit.cli.main governance lint
python -m merger.lenskit.cli.main governance lint --json

# Targeted test suite
python -m pytest -q merger/lenskit/tests/test_anti_hallucination_lint.py

# Regression (contracts / health / quality / eval / cli)
python -m pytest -q \
  merger/lenskit/tests/test_contract_inference_boundaries.py \
  merger/lenskit/tests/test_contract_version_guards.py \
  merger/lenskit/tests/test_post_emit_health.py \
  merger/lenskit/tests/test_context_quality.py \
  merger/lenskit/tests/test_retrieval_eval.py \
  merger/lenskit/tests/test_cli_citation.py \
  merger/lenskit/tests/test_cli_context_quality.py \
  merger/lenskit/tests/test_cli_parity_compare.py \
  merger/lenskit/tests/test_cli_bundle_health.py

# Import hygiene (repo CI gate selection + extras)
python -m ruff check --select=F401,F811,F841,E711,E712 --exclude='**/fixtures/**' \
  merger/lenskit/core/anti_hallucination_lint.py \
  merger/lenskit/cli/cmd_governance.py \
  merger/lenskit/cli/main.py \
  merger/lenskit/tests/test_anti_hallucination_lint.py
```

## 8. Results (local run)

- `governance lint`: `PASS` — 38 scanned, 0 errors, 1 deferred
  (`retrieval-eval-diagnostics.v1`), exit 0.
- `test_anti_hallucination_lint.py`: 32 passed.
- Regression (contracts/health/quality/eval/cli): no regressions.
- `ruff --select=F401,F811,F841,E711,E712`: clean.
- Python: 3.11.15 (local). CI runs 3.12.

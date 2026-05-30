# Authority/Risk-Class C2.7 — Experimental Marker-Gated AST Lint Proof (L1/L2/L4 Vorbau)

## 1. Scope

C2.7 is a deliberately small, **conservative groundwork (Vorbau)** for the
AST/code-path subset of the C1 anti-hallucination lint rules **L1 / L2 / L4**
(`docs/blueprints/lenskit-authority-risk-matrix.md` §6) that the contract-static
C2.4 stage (`docs/proofs/authority-risk-class-c2-4-lint-proof.md` §3) explicitly
deferred because they require Python AST analysis with a high false-positive
surface.

It adds a **separate, clearly delimited** lint mechanism that is **experimental,
non-blocking, and marker-gated**. It does **not** complete L1/L2/L4 as full
inference-based rules; it lays the smallest sound foundation and proves it cannot
mass-false-positive on real code.

New / changed files:

- `merger/lenskit/core/anti_hallucination_ast_lint.py` (new lint engine, pure functions)
- `merger/lenskit/cli/cmd_governance.py` (`lenskit governance ast-lint`, experimental)
- `merger/lenskit/cli/main.py` (dispatch wiring for the new subcommand)
- `merger/lenskit/tests/test_anti_hallucination_ast_lint.py` (25 tests)
- `docs/proofs/authority-risk-class-c2-7-ast-lint-proof.md` (this file)
- `docs/roadmap/lenskit-master-roadmap.md`, `docs/testing/test-matrix.md` (status)

This slice adds **no** runtime annotation (C4 stays open), **no** producer
emission, **no** contract mutation, **no** new blocking CI gate, and **no** change
to `canonical_md`, retrieval, the export gate (C5), or the bundle manifest.

## 2. Negative Finding — L1/L2/L4 Were Open, No AST Analysis Existed

Verified by doc + code inspection before writing any code:

| Claim | Evidence |
|-------|----------|
| L1/L2/L4 documented as **open / out-of-scope** | Roadmap C2.4 line "Die AST-/codepfadbasierten Regeln L1/L2/L4 bleiben **offen**"; roadmap §C2.4 STOP/Out-of-Scope; C2.4 proof §3; C2.6 proof §5; test-matrix Anti-Hallucination row "Offen: AST-/codepfadbasierte Regeln L1/L2/L4". |
| The rules were tracked machine-readably as out-of-scope | `anti_hallucination_lint.OUT_OF_SCOPE_RULES` = {L1, L2, L4, L6}; surfaced in the lint report under `rules_out_of_scope`. |
| **No existing AST/code-path analysis** governs these rules | `anti_hallucination_lint.py` operates purely on JSON contract schemas (no `ast`). The only Python-AST code in `merger/` is `architecture/import_graph.py` (static import graph), `architecture/entrypoints.py` (entrypoint discovery), and the frontend/backend parity guard (`cmd_parity` / `docs/PARITY_GUARD.md`, argparse↔JobRequest feature parity). None reference `authority` / `inference` / `diagnostic_signal` / `canonical_content` — confirmed by `rg`. |
| **C4 runtime annotation** remains open | Roadmap C2.1 follow-ups list "C4: Runtime-Annotation — **offen**"; C2.6 proof §5. Untouched here. |

Conclusion: there was no duplication risk (Stop-Kriterium satisfied) and the gap
was real.

## 3. Why Marker-Gated (Operationalizability + FP Avoidance)

The blueprint §6 flags a high false-positive surface for each rule, and the
prerequisites for inference-based detection do not exist in the tree:

- There is **no** `authority: T` interface annotation in the codebase (the
  blueprint's own anticipated L2 integration), **no** registry mapping function
  names to required authority, and **no** type information.
- A purely structural scan (e.g. flag every `if x.status == "...": f()`) would
  mass-false-positive: the parity gates, `output_health` consumers, and many CI
  paths legitimately branch on `verdict`/`status`. This is exactly the "aggressive
  Real-Code-Blockade" the task forbids.

Therefore L1/L2/L4 are **not** cleanly operationalizable as a blocking real-code
lint today. Per the Stop-Kriterien, this slice does **not** build a pseudo-lint.
Instead it uses an **opt-in marker convention** — directly aligned with the
blueprint's own anticipated L2 integration ("`authority: T` annotation with static
checking"):

- The lint fires **only** on code carrying explicit, lint-only governance markers.
- Because the markers are **not adopted anywhere** in the runtime code (C2.7 baseline), the lint
  produces **zero findings on the real tree** (§6/7) — it is safe to run, cannot
  block CI, and is not wired into any GitHub Actions gate.
- Synthetic fixtures (annotated source strings) prove the detector fires correctly
  for each rule.

**Crucial honesty:** because detection is marker-gated, a clean run does **not**
prove the code is authority-safe. It only proves that no *declared* low-authority
value flows into a *declared* canonical sink. The report self-declares this
(`authority: diagnostic_signal`, `does_not_mean` array, `experimental: true`).

## 4. The Rules (Marker Convention)

Markers are **lint-only static-analysis hints** parsed from comment tokens via
`tokenize` (so marker text inside string literals is never matched). They are
**not** runtime annotations, are never emitted into any artifact, and change no
contract.

| Marker | Meaning |
|--------|---------|
| `# lenskit:authority=<class>` on an assignment | the assigned name(s) carry authority `<class>` |
| `# lenskit:requires-authority=canonical_content` on a call line | that call site is a canonical-authority **sink** |
| `# lenskit:requires-authority=canonical_content` on a `def` line | the function is a canonical sink |
| `@lenskit_requires_canonical` decorator | the function is a canonical sink |

Detection (file-scoped; single-statement, no cross-function flow):

- **L1 — Forbidden semantic upgrade.** A `diagnostic_signal`-declared value gates
  an `if` whose body invokes a canonical sink.
  ```python
  cq = compute_quality()  # lenskit:authority=diagnostic_signal
  if cq.projection_status == "complete":
      trust_content()  # lenskit:requires-authority=canonical_content   → L1
  ```
- **L2 — Authority escalation.** A value declared with a runtime/agent/diagnostic/
  external authority (`runtime_observation`, `agent_context_projection`,
  `agent_generated`, `diagnostic_signal`, `external_unverified`) is passed to a
  canonical sink.
  ```python
  @lenskit_requires_canonical
  def generate_canonical_report(x): ...
  agent_input = load_session()  # lenskit:authority=runtime_observation
  generate_canonical_report(agent_input)                                → L2
  ```
- **L4 — Derived-artifact misuse.** A value declared with a navigation/derived/
  cache authority (`navigation_index`, `derived_projection`, `retrieval_index`,
  `runtime_cache`, `cache`) is passed to a canonical sink.
  ```python
  content = reading_pack_top_chunks()  # lenskit:authority=navigation_index
  verify_as_canonical(content)  # lenskit:requires-authority=canonical_content → L4
  ```

Negative cases proven by tests: unmarked code of identical shape, a
`canonical_content`-declared value into a canonical sink, a low-authority value
into an *undeclared* sink, and marker text inside a string literal all produce
**no** finding. Unparseable sources are skipped, not failed.

## 5. Non-Changes (out of scope)

- **No** runtime annotation; **C4 remains open and untouched.** The markers are
  static-analysis-only and never become artifact fields.
- **No** producer emission, **no** contract / schema change, **no** manifest
  mutation, **no** change to `canonical_md`, retrieval/ranking, or the export gate
  (C5).
- **No** modification of the C2.4 contract lint (`anti_hallucination_lint.py`): the
  AST mechanism is kept in its own module to stay "separat, klar abgegrenzt".
- **No** new blocking CI workflow. The existing `Anti-Hallucination Contract Lint`
  gate is unchanged.
- L3/L5 stay contract-static (C2.4); L6 stays export-gate (C5). They are recorded
  in `rules_out_of_scope` alongside C4.

## 6. Verification Commands

```bash
# Existing contract lint (unchanged; min-test requirement)
python3 -m merger.lenskit.cli.main governance lint

# C2.7 baseline: experimental, non-blocking AST lint (before C2.8 adoption: real tree → 0 findings, exit 0)
python3 -m merger.lenskit.cli.main governance ast-lint
python3 -m merger.lenskit.cli.main governance ast-lint --json

# Targeted suites
python3 -m pytest -q \
  merger/lenskit/tests/test_anti_hallucination_lint.py \
  merger/lenskit/tests/test_anti_hallucination_ast_lint.py

# Regression (contracts / eval-diagnostics / cli)
python3 -m pytest -q \
  merger/lenskit/tests/test_contract_inference_boundaries.py \
  merger/lenskit/tests/test_contract_version_guards.py \
  merger/lenskit/tests/test_retrieval_eval_diagnostics.py \
  merger/lenskit/tests/test_cli_bundle_health.py \
  merger/lenskit/tests/test_cli_context_quality.py

# Import hygiene (repo CI gate selection)
python3 -m ruff check --select=F401,F811,F841,E711,E712 --exclude='**/fixtures/**' \
  merger/lenskit/core \
  merger/lenskit/tests/test_anti_hallucination_lint.py \
  merger/lenskit/tests/test_anti_hallucination_ast_lint.py

git diff --check
```

## 7. Results — C2.7 Baseline (before C2.8 adoption)

- `governance lint`: `PASS` — 38 scanned, 0 errors, 0 deferred, exit 0 (unchanged).
- `governance ast-lint`: `PASS` — 91 files scanned, 0 skipped, **0 findings**, exit 0 (C2.7 baseline; markers not yet adopted in production code).
- `test_anti_hallucination_lint.py` (33) + `test_anti_hallucination_ast_lint.py` (25): **58 passed**.
- Regression (contracts/version-guards/eval-diagnostics/cli): 71 passed, no regressions.
- `ruff --select=F401,F811,F841,E711,E712`: clean. `git diff --check`: clean.
- Python: 3.11.15 (local). CI runs 3.12.

## 8. Precise Next Slice (C2.8+)

The marker-gated Vorbau is intentionally inert until markers are adopted. The next
slices, in increasing risk order:

1. **Adoption pilot:** annotate a small set of genuinely high-risk authority sinks
   (e.g. the agent export path, citation/canonical resolvers) with the markers and
   observe findings on a real, bounded subset — still non-blocking.
2. **Lift from marker-gated to inference-based:** introduce a real
   authority registry (or `authority: T` parameter annotations per blueprint L2) so
   the lint no longer depends on per-call-site opt-in. This is where the
   false-positive calibration (blueprint §6, Phase-3 stop-criterion "FP-Rate > 10% →
   Regel zurückziehen") must be measured before any CI promotion.
3. **CI promotion:** only after a measured low FP rate, wire a path-scoped blocking
   gate analogous to `anti-hallucination-lint.yml`.
4. **C4 (runtime annotation)** remains a separate, still-open track and is **not**
   a prerequisite for the above.

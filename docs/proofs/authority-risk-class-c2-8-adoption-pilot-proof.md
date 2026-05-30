# Authority/Risk-Class C2.8 — Adoption Pilot: Real-Tree Sink Annotation

## 1. Scope

C2.8 is the **adoption pilot** for the C2.7 marker-gated AST lint
(`docs/proofs/authority-risk-class-c2-7-ast-lint-proof.md`). C2.7 was
deliberately inert: no runtime code carried markers, so the default scan
produced zero findings. This slice adopts the markers on a small, bounded set
of genuinely high-risk canonical-content sinks and runs the lint for the first
time against real production paths — still non-blocking.

New / changed files:

- `merger/lenskit/core/merge.py` (sink + authority markers)
- `merger/lenskit/core/citation_map.py` (sink marker)
- `merger/lenskit/core/agent_reading_pack.py` (sink + authority markers)
- `merger/lenskit/tests/test_anti_hallucination_ast_lint.py` (updated real-tree test)
- `docs/proofs/authority-risk-class-c2-8-adoption-pilot-proof.md` (this file)
- `docs/roadmap/lenskit-master-roadmap.md`, `docs/testing/test-matrix.md` (status)

This slice adds **no** new lint rules, **no** type inference, **no** runtime
annotation (C4 stays open), **no** producer emission, **no** contract mutation,
**no** new blocking CI gate.

## 2. Annotated Sinks

Three canonical-content sinks annotated with `# lenskit:requires-authority=canonical_content`
on their `def` lines:

| Sink | File | Line | Rationale |
|------|------|------|-----------|
| `resolve_canonical_md()` | `core/merge.py` | 402 | Selects which generated MD path becomes the canonical source of truth; the highest-stakes authority selection in the bundle pipeline. |
| `produce_citation_map()` | `core/citation_map.py` | 713 | Produces the citation_map_jsonl from SHA-verified canonical inputs; any non-canonical data here corrupts stable citation identifiers. |
| `produce_agent_reading_pack()` | `core/agent_reading_pack.py` | 645 | Produces the agent reading pack (navigation index derived from canonical bundle); governs what agents use as their entry point into the bundle. |

Two **authority markers** (`# lenskit:authority=<class>`) on variables whose
data comes from a clearly lower-authority source:

| Variable | File | Line | Authority class | Rationale |
|----------|------|------|-----------------|-----------|
| `md_parts` | `core/merge.py` | 5689 | `derived_projection` | List of generated markdown paths; output of the generation pipeline, not yet verified as canonical content. |
| `health` | `core/agent_reading_pack.py` | 780 | `diagnostic_signal` | Loaded from the `output_health` artifact; a diagnostic observation about bundle state, not canonical content itself. |

## 3. Findings

```
governance ast-lint --json
status: warn  |  files_scanned: 91  |  files_skipped: 0  |  finding_count: 4
```

All four findings are L4 in `core/merge.py`:

| Rule | File | Line | Symbol | Description |
|------|------|------|--------|-------------|
| L4 | `merge.py` | 5699 | `md_parts` | `derived_projection` value passed to canonical sink `resolve_canonical_md` |
| L4 | `merge.py` | 5714 | `md_parts` | same |
| L4 | `merge.py` | 5824 | `md_parts` | same |
| L4 | `merge.py` | 5843 | `md_parts` | same |

Zero findings in `citation_map.py` or `agent_reading_pack.py`.

## 4. Analysis per Candidate

### 4.1 `resolve_canonical_md()` (merge.py) — 4 L4 findings

**Pattern:** `md_parts = [p for p in generated_paths if ...]` (derived_projection)
is passed to `resolve_canonical_md(md_parts)` at four call sites in
`write_reports_v2()`. The file-scoped over-approximation propagates the
`derived_projection` authority from the one annotated assignment (line 5689) to
all occurrences of `md_parts` in the file, producing a finding at each
`resolve_canonical_md(md_parts)` call.

**True positive or false positive?** This is a **known-intentional design
crossing**: `resolve_canonical_md()` is specifically designed to *select* the
canonical MD from generated paths — it IS the function that upgrades a derived
path to canonical status. The crossing is intentional. However, the lint
correctly identifies it as an L4 pattern (navigation/derived value → canonical
sink). The finding is technically accurate; it is not a bug, but it documents
the exact line where authority is deliberately upgraded.

**Implication:** An authority registry (C2.9 / inference-based lift) would need
an explicit *exception* or *upgrade declaration* for this call site, rather than
suppressing the lint. This is the expected design gap: the marker-gated approach
cannot distinguish "intentional upgrade" from "accidental upgrade" without
additional metadata.

**False-positive rate for L4 in merge.py:** 4 / 4 findings are
known-intentional. FP rate = 100% — consistent with the blueprint's prediction
that marker-gated detection without an upgrade registry produces false positives
at intentional canonical-selection sites.

### 4.2 `produce_citation_map()` (citation_map.py) — 0 findings

**Pattern:** No low-authority variable annotations exist in `citation_map.py`.
All inputs to `produce_citation_map()` are either:
- Plain strings (`manifest_path_str`, `output_path_str`) — unclassified
- Loaded from the manifest after SHA verification (canonical authority)

**Finding:** Clean. The citation producer does not have in-file authority
violations. The absence of findings does **not** prove the function is
authority-safe (cross-file flows — e.g., the caller's authority context — are
invisible to the file-scoped engine). It confirms no intra-file violation is
detectable at the current marker adoption level.

### 4.3 `produce_agent_reading_pack()` (agent_reading_pack.py) — 0 findings

**Pattern:** `health` (diagnostic_signal) is declared at line 780, but it flows
into the canonical pack via an intermediary: `PackModel(health=health, ...)` at
line 881, then `render_agent_reading_pack(model)` at line 894. The C2.7
file-scoped engine detects direct argument flow into canonical sinks but does
**not** track authority through object construction intermediaries.

**Finding:** 0 findings — **indirect-flow gap revealed.** The lint does not fire
even though `health` (diagnostic_signal) is ultimately embedded in the rendered
pack. This is an **intentional design** (the pack explicitly self-declares as
`authority=navigation_index, canonicality=derived` and the health section is
clearly labelled diagnostic context for the agent), but the lint cannot
distinguish this from an accidental case.

**Implication:** Detection of indirect flows (authority class A → field of
intermediate object → canonical sink) requires either:
1. Dataflow / alias analysis (significantly higher complexity)
2. Marking the intermediate object constructor as a canonical sink (which would
   be incorrect here since PackModel is not canonical)
3. An authority registry that explicitly tracks which object fields are allowed
   to carry diagnostic authority into a canonical-neighbouring context

This gap motivates the "authority registry" step in the inference-based lift
(C2.9+).

## 5. Key Findings from the Pilot

| Finding | Observation | Implication |
|---------|-------------|-------------|
| L4 at `resolve_canonical_md` | Lint correctly identifies the canonical-selection boundary crossing | Authority registry needs an "upgrade declaration" mechanism |
| 0 findings in citation_map.py | Clean producer; file-scoped approach confirms no intra-file violations | Cross-file flows remain invisible |
| 0 findings in agent_reading_pack.py | Indirect diagnostic→pack flow goes undetected | Object-intermediary tracking not supported by file-scoped engine |
| FP rate for L4 in merge.py | 4/4 findings are known-intentional | Confirms blueprint's predicted high FP rate before upgrade declarations are possible |

**Honest summary:** the pilot confirms the C2.7 design decision was correct. A
fully structural scan would generate false positives at exactly the known
canonical-selection points (merge.py). The marker-gated approach generates
findings only where both the sink and the input are explicitly annotated —
which is better than noise, but insufficient to catch the indirect health→pack
flow without dataflow analysis.

## 6. Non-Changes (out of scope)

- **No** new lint rules; L1/L2/L4 remain marker-gated.
- **No** runtime annotation; **C4 remains open and untouched.** The markers are
  static-analysis-only comments.
- **No** producer emission, **no** contract / schema change, **no** manifest
  mutation, **no** change to `canonical_md`, retrieval/ranking, or the export gate
  (C5).
- **No** modification of the C2.4 contract lint (`anti_hallucination_lint.py`).
- **No** new blocking CI workflow. The existing `Anti-Hallucination Contract
  Lint` gate is unchanged; `governance ast-lint` is still not wired into CI.

## 7. Verification Commands

```bash
# Existing contract lint (unchanged; min-test requirement)
python3 -m merger.lenskit.cli.main governance lint

# AST lint (now warns with 4 C2.8 pilot findings, exit 1 — still non-blocking)
python3 -m merger.lenskit.cli.main governance ast-lint
python3 -m merger.lenskit.cli.main governance ast-lint --json

# Targeted suites
python3 -m pytest -q \
  merger/lenskit/tests/test_anti_hallucination_lint.py \
  merger/lenskit/tests/test_anti_hallucination_ast_lint.py

# Regression
python3 -m pytest -q \
  merger/lenskit/tests/test_contract_inference_boundaries.py \
  merger/lenskit/tests/test_contract_version_guards.py \
  merger/lenskit/tests/test_cli_bundle_health.py \
  merger/lenskit/tests/test_cli_context_quality.py

# Import hygiene
python3 -m ruff check --select=F401,F811,F841,E711,E712 --exclude='**/fixtures/**' \
  merger/lenskit/core/merge.py \
  merger/lenskit/core/citation_map.py \
  merger/lenskit/core/agent_reading_pack.py \
  merger/lenskit/tests/test_anti_hallucination_ast_lint.py

git diff --check
```

## 8. Results (local run)

- `governance lint`: `PASS` — 38 scanned, 0 errors, 0 deferred, exit 0 (unchanged).
- `governance ast-lint`: `WARN` — 91 files scanned, 0 skipped, **4 findings**
  (all L4 in merge.py), exit 1. Non-blocking (`blocking: false`).
- `test_anti_hallucination_lint.py` (33) + `test_anti_hallucination_ast_lint.py` (25): **58 passed**.
- Regression (contracts/version-guards/cli): 45 passed, no regressions.
- `ruff --select=F401,F811,F841,E711,E712`: clean. `git diff --check`: clean.
- Python: 3.11.15 (local). CI runs 3.12.

## 9. Precise Next Slice (C2.9+)

The pilot confirms the two key gaps for the inference-based lift:

1. **Authority upgrade declarations.** `resolve_canonical_md()` is a legitimate
   canonical-selection upgrade point. The next step needs a mechanism to declare
   "this call site intentionally upgrades authority from derived_projection to
   canonical_content" — analogous to a `@suppress_lint(L4, reason=...)` or an
   explicit entry in an authority registry. Without this, the inference-based
   lint will have an irremovable L4 false positive at every canonical-selection
   call.

2. **Object-intermediary / dataflow tracking.** The indirect
   `health (diagnostic_signal) → PackModel → render_agent_reading_pack` flow is
   invisible to the file-scoped engine. Detection requires either (a) annotating
   the PackModel constructor fields with per-field authority, or (b) a proper
   dataflow analysis that tracks authority class through object construction.
   This is the key open work for the inference-based lift.

3. **Authority registry (prerequisite for both).** Before either gap can be
   closed, a machine-readable registry mapping function names / call sites to
   their authority requirements is needed — the blueprint's anticipated
   "authority: T parameter annotation" system (blueprint §6, L2 integration).

4. **C4 (runtime annotation)** remains a separate, still-open track and is
   **not** a prerequisite for the above.

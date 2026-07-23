# Python Call Graph Goldset and Promotion Gate v1

Bureau task: `RPU-V1-T024`

## Scope

This slice evaluates the existing conservative Python call graph. It does not
change producer resolution rules or promote call-graph context into the default
agent route.

The fixed goldset covers 13 scored categories:

- direct calls;
- imported-name aliases and module aliases;
- direct recursion;
- same-class methods;
- lexical shadowing and callback parameters;
- decorator and default-argument calls;
- higher-order dynamic dispatch;
- an ambiguous negative control;
- a German Unicode identifier and UTF-8 literal;
- local constructor relations.

Python is the scored producer. The Unicode case checks encoding and identifier
handling; it is not evidence for a multilingual call-graph implementation.

## Metrics and gate

The evaluator reports these dimensions separately:

- S1 precision and target recall;
- false-positive classes, false negatives and unresolved share;
- serialized call-record bytes and measured build time;
- baseline versus graph context paths;
- baseline versus graph tool calls;
- deterministic fixed navigation-task outcomes.

The registered promotion checks are:

- S1 precision at least `0.97`;
- target recall `1.0` on the fixed goldset;
- at least `0.40` aggregate context-path reduction at equal or better recall;
- no scored case or navigation-task regression.

A wrong S1 target counts as both a false positive and a false negative. This
prevents a confidently resolved but incorrect edge from preserving either
precision or recall.

## Navigation-usefulness boundary

The navigation cases reuse the existing `agent_impact_eval` contract. They are
deterministic fixed navigation tasks, not an LLM quality experiment. The report
therefore records task outcomes and compression while explicitly refusing to
claim general agent-quality improvement or answer correctness.

The fixed path surface reduces aggregate context paths from `11` to `5` and tool
calls from `9` to `3`, with unchanged target recall. CI generates the full JSON
report so byte count and wall-clock build time remain observable without turning
machine-dependent timing into a committed exact baseline.

## Promotion semantics

Passing thresholds yields only `eligible_for_review=true`.
`default_promoted` remains `false` and the separate decision authority is the
Bureau. The report also preserves the nonclaims for completeness, runtime
reachability, dynamic dispatch, test sufficiency, review completeness and merge
readiness.

## Fail-closed promotion inputs

The promotion decision is computed only from measured inputs. The gate lists
any absent, non-numeric or empty required input under
`decision.insufficient_evidence` and, when that list is non-empty, forces
`thresholds_met=false` and `eligible_for_review=false` instead of inheriting a
vacuous `all([])` pass. Missing scored cases, missing agent-task outcomes, a
missing navigation signal, or any missing quality metric therefore block
promotion rather than self-attesting one. This hardening changes no measured
value: the goldset, fixture and call-record digests below are unchanged and the
happy-path decision simply reports `insufficient_evidence: []`.

The gate additionally fails closed on inputs that are present but not usable as
measured evidence. A non-finite metric or navigation ratio (`NaN`, `+inf` or
`-inf`) is classified as `insufficient_evidence` rather than being allowed to
pass or fail a threshold by chance. A missing or non-numeric promotion
threshold is surfaced under `insufficient_evidence` (as `thresholds.<field>`)
instead of raising, so a malformed `decide_promotion` call fails closed rather
than crashing. Threshold comparisons are inclusive at the exact boundary and a
malformed, non-empty case or navigation-outcome record can never self-attest a
`no_case_regression` pass. This robustness is exercised by focused tests for
non-finite metrics, non-finite navigation ratios, absent and invalid
thresholds, malformed case records, and the inclusive/just-below boundary of
each numeric premise.

## Commit-bound CI evidence

The canonical pull-request run is bound to:

- head SHA: `a91aacf22e86bb4bdfb1afbbabd14f5788f4bbdb`;
- workflow run: `29733013149`;
- Actions artifact: `8457081289`;
- artifact digest: `sha256:d53ceda0c82691ed4ac40f7d5af92a2916c85684126eb4064157b17ca7a392f4`;
- goldset SHA-256: `beab71b88895dd173d2622a9ad5bf3aae36b5cf37b2a430a8b26348e9533c681`;
- fixture SHA-256: `5b123139486b03b2f188c58f5b78dce8ee857abeb82947833e520894808459ac`;
- call-record SHA-256: `6a26b3a4f0e2ba55d0e1a59c53b7980cc9204e9e7d6718103eab80b4100220e2`.

Observed report values on the GitHub-hosted Python 3.12 runner:

- `13` scored cases across `13` categories and `16` call records;
- S1 precision `1.0`, target recall `1.0`;
- `0` false positives and `0` false negatives;
- unresolved share `0.307692` (`4/13`);
- serialized call records: `9305` bytes;
- measured build time: `2.854 ms`;
- aggregate context-path reduction: `0.5454545454545454` (`11` to `5`);
- tool-call reduction: `0.666667` (`9` to `3`);
- all three deterministic navigation tasks passed;
- `40` focused tests passed in `2.14 s`;
- all four registered threshold checks passed;
- `default_promoted=false`.

The timing value is evidence for this exact runner and commit, not a portable
performance guarantee.

The bound run above predates the non-finite, threshold-validation and
malformed-record hardening. Its digests and observed values remain valid
evidence for the unchanged happy-path fixture — the goldset, fixture and
call-record digests and the serialized byte count are byte-identical after the
hardening, and the happy-path decision is unchanged. It does not, however,
exercise the fail-closed paths added here. Those paths are covered by the
focused tests listed above and were re-confirmed by the hardening pull request's
successful `Python Call Graph Goldset` run:

- hardening head SHA: `bc6eb0b65f9069a5caa7c54448783deebec166a3`;
- workflow run: `30039206495`;
- Actions artifact: `8576522234`;
- artifact digest: `sha256:c70e5dccba0bf89b38c8774799d13b31819ebdf20c19f975c17318f1ed100785`.

The historical bound run is therefore not restated as covering the newer code;
the newer hardening has its own commit-bound CI evidence.

## Reproduction

```bash
python -m merger.repoground.architecture.call_graph_quality_eval \
  --goldset docs/retrieval/python_call_graph_goldset.v1.json \
  --out python-call-graph-quality-report.json
python -m pytest -q \
  merger/repoground/tests/test_python_call_graph_goldset.py \
  merger/repoground/tests/test_python_call_graph.py \
  merger/repoground/tests/test_agent_impact_refinement.py
```

The dedicated `Python Call Graph Goldset` workflow validates JSON, emits the
reviewable report, runs focused producer and impact-evaluator regressions,
checks Ruff and rejects structural diff errors.
